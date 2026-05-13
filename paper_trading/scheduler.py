"""
Background scheduler for paper-trading scans.

Three independent triggers, all gated by user settings:

1. **Startup** (``paper_scan_on_startup``) — a single scan of every active
   account a few seconds after the app launches.

2. **Interval** (``paper_scheduler_enabled`` + ``paper_scan_interval_minutes``)
   — a QTimer ticks every N minutes; each tick scans every active account
   unless ``paper_market_hours_only`` is on and the market is closed.

3. **Daily cron** (``paper_daily_scan_enabled`` + ``paper_daily_scan_time_et``)
   — once the clock in US/Eastern passes a configured HH:MM (default
   ~5 min after NYSE close) we run a final scan of the day. Re-armed every
   calendar day.

Each scan runs on its own ``QThread`` so the UI stays responsive. Workers
are tracked per-account: if a previous scan for account X hasn't finished
yet, the scheduler skips a new one for X instead of piling them up.

Public interface
----------------
``PaperScheduler(parent)``
    Instantiate inside ``MainWindow``. Call ``start()`` once the rest of
    the UI is constructed and ``stop()`` from ``closeEvent``.

Signals
    ``scan_started(account_id: int)``
    ``scan_completed(result: ScanResult)``
    ``scan_failed(account_id: int, error: str)``

Methods
    ``scan_now(account_id: int | None = None)``  — manual trigger; ``None``
    scans all active accounts.
    ``reload_settings()``                         — re-read the interval and
    restart the timer (call when the user saves a new interval value).
"""

from __future__ import annotations

from datetime import date, datetime
from datetime import time as dtime

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from config.logging_config import get_logger
from config.settings_manager import settings

log = get_logger(__name__)


# ── Time-zone helpers (reuse the same logic as yahoo_finance.is_market_open) ─


def _now_et() -> datetime:
    try:
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo("America/New_York")
        except ImportError:
            import pytz

            tz = pytz.timezone("America/New_York")
        return datetime.now(tz)
    except Exception:
        return datetime.utcnow()


def _parse_hhmm(raw: str, default: tuple[int, int] = (16, 5)) -> tuple[int, int]:
    """Parse HH:MM. Returns defaults on any parse error."""
    try:
        h_str, m_str = raw.strip().split(":")
        h = max(0, min(23, int(h_str)))
        m = max(0, min(59, int(m_str)))
        return h, m
    except Exception:
        return default


def _is_market_open_now() -> bool:
    """Thin wrapper that never raises."""
    try:
        from data.yahoo_finance import is_market_open

        open_, _ = is_market_open()
        return bool(open_)
    except Exception:
        return False


# ── Worker thread ─────────────────────────────────────────────────────────────


class PaperScanWorker(QThread):
    """Runs a single ``run_scan(account_id)`` on a background thread."""

    scan_completed = pyqtSignal(object)  # ScanResult
    scan_failed = pyqtSignal(int, str)  # (account_id, error message)

    def __init__(self, account_id: int, parent=None):
        super().__init__(parent)
        self.account_id = int(account_id)

    def run(self):
        try:
            from paper_trading.engine import run_scan

            result = run_scan(self.account_id)
            if result is None:
                self.scan_failed.emit(self.account_id, "Cuenta inactiva o no encontrada.")
            else:
                self.scan_completed.emit(result)
        except Exception as e:
            self.scan_failed.emit(self.account_id, f"{type(e).__name__}: {e}")


# ── Scheduler ─────────────────────────────────────────────────────────────────


class PaperScheduler(QObject):
    """Orchestrates the three scan triggers and dispatches worker threads."""

    scan_started = pyqtSignal(int)  # account_id
    scan_completed = pyqtSignal(object)  # ScanResult
    scan_failed = pyqtSignal(int, str)  # account_id, error

    # How often the daily-cron timer ticks to check the wall clock (ms).
    _DAILY_CHECK_MS = 60_000  # every minute
    # Delay between app start and the startup scan, to let the UI finish loading.
    _STARTUP_DELAY_MS = 3_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: dict[int, PaperScanWorker] = {}

        self._interval_timer = QTimer(self)
        self._interval_timer.timeout.connect(self._on_interval_tick)

        self._daily_timer = QTimer(self)
        self._daily_timer.setInterval(self._DAILY_CHECK_MS)
        self._daily_timer.timeout.connect(self._on_daily_tick)

        self._last_daily_run: date | None = None
        self._started: bool = False

        # Heartbeat: per-account timestamps of the most recent scan so the
        # UI / status bar can flag accounts that haven't been scanned in a
        # suspiciously long time (scheduler stalled or worker thread died).
        self._last_scan_at: dict[int, datetime] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start all enabled triggers. Safe to call twice."""
        if self._started:
            return
        self._started = True

        # Reconciliation: expire any pending orders that survived a previous
        # crash / unclean shutdown. Fast (a single SQL update per account)
        # so it's safe to do synchronously before starting the timers.
        self._reconcile_all_active()

        # Startup scan — delayed so the UI has time to paint.
        if settings.get("paper_scan_on_startup", True):
            QTimer.singleShot(self._STARTUP_DELAY_MS, self._scan_all_active)

        # Interval trigger.
        if settings.get("paper_scheduler_enabled", True):
            self._interval_timer.start(self._interval_ms())

        # Daily cron trigger.
        if settings.get("paper_daily_scan_enabled", True):
            self._daily_timer.start()

    def stop(self) -> None:
        """Stop all timers and wait briefly for any running worker."""
        self._interval_timer.stop()
        self._daily_timer.stop()
        for w in list(self._workers.values()):
            w.wait(2_000)  # wait up to 2s per worker
        self._workers.clear()
        self._started = False

    def reload_settings(self) -> None:
        """Call this from SettingsTab after the user changes interval/enable flags."""
        was_running = self._interval_timer.isActive()
        self._interval_timer.stop()
        if settings.get("paper_scheduler_enabled", True):
            self._interval_timer.start(self._interval_ms())
        elif was_running:
            pass  # already stopped above

        if settings.get("paper_daily_scan_enabled", True):
            if not self._daily_timer.isActive():
                self._daily_timer.start()
        else:
            self._daily_timer.stop()

    # ── Manual trigger ────────────────────────────────────────────────────────

    def scan_now(self, account_id: int | None = None) -> None:
        """Fire a scan immediately. ``None`` scans every active account."""
        if account_id is None:
            self._scan_all_active()
        else:
            self._launch_scan(int(account_id))

    # ── Trigger handlers ──────────────────────────────────────────────────────

    def _on_interval_tick(self) -> None:
        if not settings.get("paper_scheduler_enabled", True):
            return
        if settings.get("paper_market_hours_only", True) and not _is_market_open_now():
            return
        self._scan_all_active()

    def _on_daily_tick(self) -> None:
        if not settings.get("paper_daily_scan_enabled", True):
            return
        now_et = _now_et()
        # Skip weekends entirely.
        if now_et.weekday() >= 5:
            return

        h, m = _parse_hhmm(settings.get("paper_daily_scan_time_et", "16:05"))
        target = dtime(hour=h, minute=m)
        current = dtime(hour=now_et.hour, minute=now_et.minute)
        if current < target:
            return
        today = now_et.date()
        if self._last_daily_run == today:
            return
        self._last_daily_run = today
        self._scan_all_active()

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def _scan_all_active(self) -> None:
        try:
            from paper_trading.account import list_accounts

            accts = list_accounts(active_only=True)
        except Exception:
            # DB not ready, or sqlalchemy error — stay quiet.
            log.exception("list_accounts failed")
            return
        for a in accts:
            self._launch_scan(int(a.id))

    def _reconcile_all_active(self) -> None:
        """
        Expire orphaned ``pending`` orders for every active account at
        startup. Without this, a crash between order generation and the
        next scan leaves pending orders dangling forever.
        """
        try:
            from paper_trading.account import list_accounts
            from paper_trading.engine import reconcile_account

            for a in list_accounts(active_only=True):
                try:
                    n = reconcile_account(int(a.id))
                    if n:
                        log.info("reconciled %d stale pending orders for account %s", n, a.id)
                except Exception:
                    log.exception("reconcile failed for account %s", a.id)
        except Exception:
            log.exception("reconcile_all_active failed")

    def _launch_scan(self, account_id: int) -> None:
        existing = self._workers.get(account_id)
        if existing is not None and existing.isRunning():
            return  # previous scan for this account still in flight
        worker = PaperScanWorker(account_id, parent=self)
        worker.scan_completed.connect(self._on_scan_completed)
        worker.scan_failed.connect(self.scan_failed.emit)
        worker.finished.connect(lambda aid=account_id: self._reap_worker(aid))
        self._workers[account_id] = worker
        self.scan_started.emit(account_id)
        worker.start()

    def _on_scan_completed(self, result) -> None:
        """Stamp heartbeat then forward the result to listeners."""
        try:
            aid = int(getattr(result, "account_id", 0)) or 0
            if aid:
                self._last_scan_at[aid] = datetime.utcnow()
        except Exception:
            pass
        self.scan_completed.emit(result)

    def _reap_worker(self, account_id: int) -> None:
        w = self._workers.pop(account_id, None)
        if w is not None:
            w.deleteLater()

    # ── Status / health ───────────────────────────────────────────────────────

    def status(self) -> dict:
        """
        Return a snapshot suitable for the UI status bar / debugging:
        active workers, last-scan timestamps, and stale accounts (no scan
        in over 2× the configured interval).
        """
        now = datetime.utcnow()
        interval_min = max(1, int(settings.get("paper_scan_interval_minutes", 15)))
        stale_threshold = 2 * interval_min * 60  # seconds

        stale = []
        for aid, ts in self._last_scan_at.items():
            if (now - ts).total_seconds() > stale_threshold:
                stale.append(aid)
        return {
            "started": self._started,
            "active_workers": list(self._workers.keys()),
            "last_scans": {a: ts.isoformat() for a, ts in self._last_scan_at.items()},
            "stale_accounts": stale,
            "interval_min": interval_min,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _interval_ms(self) -> int:
        minutes = int(settings.get("paper_scan_interval_minutes", 15))
        minutes = max(1, minutes)  # never under 1 minute
        return minutes * 60 * 1_000
