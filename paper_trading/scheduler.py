"""
Background scheduler for paper-trading scans.

Independent triggers, all gated by user settings:

1. **Startup** (``paper_scan_on_startup``) — a single scan of every active
   account a few seconds after the app launches.

2. **Interval** (``paper_scheduler_enabled`` + ``paper_scan_interval_minutes``)
   — a QTimer ticks every N minutes; each tick scans every active account
   unless ``paper_market_hours_only`` is on and the market is closed.

3. **Daily cron** (``paper_daily_scan_enabled`` + ``paper_daily_scan_time_et``)
   — once the clock in US/Eastern passes a configured HH:MM (default
   ~5 min after NYSE close) we run a final scan of the day. Re-armed every
   calendar day.

4. **Weekly surprise rebuild** (``surprise_build_enabled``, default on;
   ``surprise_build_interval_days``, default 7) — T-CAT-5a. Rides the
   once-a-minute daily timer (and a one-shot just after launch): when
   ``build_due`` says the interval has elapsed since ``surprise_last_build``,
   a background worker regenerates ``data/catalyst/surprise_profiles.json``
   from yfinance. Only runs while the app is open; the timestamp is stamped on
   success so a missed week catches up on the next launch. This is the in-app
   alternative to a Task Scheduler job — see docs/roadmap_v3_2026-06-09.md.

5. **Daily catalyst refresh** (``catalyst_refresh_on_open``, default on) —
   harvest (T-CAT-1) + classify (T-CAT-2) in-process, primera vez que la app
   abre en el día. El Task Scheduler nocturno (18:30 ART) sigue existiendo,
   pero las noticias dan ventaja DURANTE el día: este trigger garantiza datos
   frescos a la mañana sin depender de aquel. Idempotente (content_hash +
   UPDATE solo de filas NULL) y gated: corre a lo sumo una vez por día
   calendario y solo si ``refresh_due`` (sin harvest hoy, o backlog sin
   clasificar). Emite ``catalyst_refresh_completed`` para que la UI refresque
   la pestaña Noticias.

6. **Hourly catalyst harvest** (``catalyst_hourly_harvest_enabled``, default
   on; ``catalyst_hourly_harvest_minutes``, default 60, piso 15) — tarea 10,
   decisión de Chapa 2026-07-07: el harvest intradía es responsabilidad de la
   app (solo corre con la app abierta), Windows Task Scheduler corre solo el
   pipeline completo de las 15:00. Rides el tick por minuto del daily timer:
   durante RTH lanza un harvest-only (sin classify → sin GPU) cada N minutos.
   Caso motivador: TSLA 2026-07-06, noticia publicada 14:45 ET ingresada
   19:05 por el run único diario.

7. **Daily dashboard refresh** (``dashboard_refresh_enabled``, default on) —
   regenera el snapshot del artifact del dashboard vía
   ``scripts/refresh_dashboard.refresh_dashboard`` (lee ``finanzias.db`` e
   inyecta el ``const DATA`` del index.html). Decisión de Chapa 2026-07-12
   ("Ambos"): corre 1×/día calendario al abrir la app (gate por fecha) **y**
   además tras cada scan de la cuenta del dashboard mientras la app está
   abierta. Reemplaza la tarea del Windows Task Scheduler que lo corría a las
   8:00 — ahora solo con la app abierta. Puramente local (sin red); no-op
   silencioso si la DB o el artifact no existen en la máquina.

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
from database.models import utcnow_naive

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
        return utcnow_naive()


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


class SurpriseBuildWorker(QThread):
    """Rebuild the T-CAT-5a surprise profiles JSON on a background thread.

    Network-bound (yfinance ``get_earnings_dates`` per ticker), so it runs off
    the UI thread. Read-only on the DB (only resolves the account universe).
    Emits ``build_completed(result_dict)`` on success or ``build_failed(error)``.
    """

    build_completed = pyqtSignal(object)  # result dict from run_build
    build_failed = pyqtSignal(str)

    def __init__(self, account_id: int, limit: int = 16, parent=None):
        super().__init__(parent)
        self.account_id = int(account_id)
        self.limit = int(limit)

    def run(self):
        try:
            from scripts.build_surprise_profiles import run_build

            res = run_build(account_id=self.account_id, limit=self.limit)
            self.build_completed.emit(res)
        except Exception as e:
            self.build_failed.emit(f"{type(e).__name__}: {e}")


class CatalystRefreshWorker(QThread):
    """Run the daily news pipeline (harvest + classify) off the UI thread.

    Network + LLM bound (yfinance/EDGAR fetch, luego qwen via Ollama por cada
    headline nueva), puede tardar varios minutos — por eso QThread. Escrituras
    DB idempotentes (las mismas de los scripts del .bat nocturno).
    Emits ``refresh_completed(result_dict)`` or ``refresh_failed(error)``.
    """

    refresh_completed = pyqtSignal(object)  # {"harvest_rc": int, "classify_rc": int}
    refresh_failed = pyqtSignal(str)

    def run(self):
        try:
            from analysis.news_digest import run_catalyst_refresh

            res = run_catalyst_refresh()
            self.refresh_completed.emit(res)
        except Exception as e:
            self.refresh_failed.emit(f"{type(e).__name__}: {e}")


def hourly_harvest_due(
    *,
    enabled: bool,
    now: datetime,
    last: datetime | None,
    interval_min: int,
    hourly_worker_running: bool,
    daily_worker_running: bool,
    market_open: bool,
) -> bool:
    """Decisión pura del harvest horario (tarea 10) — testeable offline.

    Gates: flag → intervalo transcurrido → sin worker horario vivo → sin
    refresh diario vivo (mismo pipeline; dos harvesters concurrentes solo
    suman contención de SQLite) → mercado abierto.
    """
    if not enabled:
        return False
    interval_min = max(15, int(interval_min))
    if last is not None and (now - last).total_seconds() < interval_min * 60:
        return False
    if hourly_worker_running or daily_worker_running:
        return False
    return bool(market_open)


class CatalystHarvestWorker(QThread):
    """Run the harvest-only news pipeline off the UI thread (tarea 10).

    Network-bound (yfinance/EDGAR/finnhub), sin classify → sin GPU. Escrituras
    DB idempotentes (dedup por canonical URL en el harvester). Emits
    ``harvest_completed(result_dict)`` or ``harvest_failed(error)``.
    """

    harvest_completed = pyqtSignal(object)  # {"harvest_rc": int}
    harvest_failed = pyqtSignal(str)

    def run(self):
        try:
            from analysis.news_digest import run_catalyst_harvest_only

            res = run_catalyst_harvest_only()
            self.harvest_completed.emit(res)
        except Exception as e:
            self.harvest_failed.emit(f"{type(e).__name__}: {e}")


class DashboardRefreshWorker(QThread):
    """Regenera el snapshot del dashboard fuera del UI thread (trigger 7).

    Puramente local: lee ``finanzias.db`` e inyecta ``const DATA`` en el
    index.html del artifact (sin red). Va en ``QThread`` igual para no bloquear
    la UI mientras ``build_payload`` arma el snapshot. ``refresh_dashboard`` no
    lanza por condiciones esperables (devuelve ``{"ok": False, ...}``). Emits
    ``refresh_completed(result_dict)`` or ``refresh_failed(error)``.
    """

    refresh_completed = pyqtSignal(object)  # dict de refresh_dashboard
    refresh_failed = pyqtSignal(str)

    def __init__(self, account_id: int, parent=None):
        super().__init__(parent)
        self.account_id = int(account_id)

    def run(self):
        try:
            from scripts.refresh_dashboard import refresh_dashboard

            res = refresh_dashboard(account_id=self.account_id)
            self.refresh_completed.emit(res)
        except Exception as e:
            self.refresh_failed.emit(f"{type(e).__name__}: {e}")


# ── Scheduler ─────────────────────────────────────────────────────────────────


class PaperScheduler(QObject):
    """Orchestrates the three scan triggers and dispatches worker threads."""

    scan_started = pyqtSignal(int)  # account_id
    scan_completed = pyqtSignal(object)  # ScanResult
    scan_failed = pyqtSignal(int, str)  # account_id, error

    # Daily catalyst refresh (trigger 5)
    catalyst_refresh_started = pyqtSignal()
    catalyst_refresh_completed = pyqtSignal(object)  # result dict
    catalyst_refresh_failed = pyqtSignal(str)

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

        # T-CAT-5a weekly surprise-profile rebuild (in-app, single worker).
        self._surprise_worker: SurpriseBuildWorker | None = None

        # Daily catalyst refresh (in-app, single worker, once per calendar day).
        self._catalyst_worker: CatalystRefreshWorker | None = None
        self._last_catalyst_refresh: date | None = None

        # Hourly harvest-only refresh durante RTH (tarea 10) — solo con la app
        # abierta, por decisión de Chapa 2026-07-07 (Windows corre únicamente
        # el pipeline completo de las 15:00).
        self._hourly_harvest_worker: CatalystHarvestWorker | None = None
        self._last_hourly_harvest: datetime | None = None

        # Daily dashboard refresh (trigger 7) — in-app, single worker. "Ambos"
        # (Chapa 2026-07-12): 1×/día al abrir (gate por fecha) + tras cada scan
        # de la cuenta del dashboard. Reemplaza la tarea del Task Scheduler.
        self._dashboard_worker: DashboardRefreshWorker | None = None
        self._last_dashboard_refresh: date | None = None

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

        # T-CAT-5a weekly surprise rebuild — check shortly after launch so the
        # UI has painted; the daily tick re-checks once a day thereafter.
        QTimer.singleShot(self._STARTUP_DELAY_MS, self._maybe_build_surprise)

        # Daily catalyst refresh — primera apertura del día; el tick diario
        # re-chequea por si la app queda abierta pasada la medianoche.
        QTimer.singleShot(self._STARTUP_DELAY_MS, self._maybe_refresh_catalysts)

        # Daily dashboard refresh — snapshot fresco del artifact al abrir; el
        # tick diario re-chequea pasada la medianoche y cada scan lo re-dispara.
        QTimer.singleShot(self._STARTUP_DELAY_MS, self._maybe_refresh_dashboard)

    def stop(self) -> None:
        """Stop all timers and wait briefly for any running worker."""
        self._interval_timer.stop()
        self._daily_timer.stop()
        for w in list(self._workers.values()):
            w.wait(2_000)  # wait up to 2s per worker
        self._workers.clear()
        if self._surprise_worker is not None:
            self._surprise_worker.wait(2_000)
            self._surprise_worker = None
        if self._catalyst_worker is not None:
            self._catalyst_worker.wait(2_000)
            self._catalyst_worker = None
        if self._hourly_harvest_worker is not None:
            self._hourly_harvest_worker.wait(2_000)
            self._hourly_harvest_worker = None
        if self._dashboard_worker is not None:
            self._dashboard_worker.wait(2_000)
            self._dashboard_worker = None
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
        # Weekly surprise rebuild rides the once-a-minute daily timer; build_due
        # short-circuits cheaply until the interval has elapsed.
        self._maybe_build_surprise()

        # Catalyst refresh: cubre el caso "app abierta pasada la medianoche".
        # El gate por día calendario hace que esto sea un no-op el resto del día.
        self._maybe_refresh_catalysts()

        # Harvest horario durante RTH (tarea 10): no-op fuera de mercado o si
        # todavía no pasó el intervalo.
        self._maybe_hourly_harvest()

        # Dashboard: garantiza el refresh 1×/día aunque la app quede abierta
        # pasada la medianoche (no-op el resto del día por el gate por fecha).
        self._maybe_refresh_dashboard()

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
        """Stamp heartbeat, refresh the dashboard, then forward the result."""
        aid = 0
        try:
            aid = int(getattr(result, "account_id", 0)) or 0
            if aid:
                self._last_scan_at[aid] = utcnow_naive()
        except Exception:
            pass
        # Dashboard "Ambos": tras cada scan de la cuenta del dashboard re-genera
        # el snapshot (ungated; el path 1×/día vive en _maybe_refresh_dashboard).
        if aid and aid == self._dashboard_account_id():
            try:
                self._refresh_dashboard_now()
            except Exception:
                log.exception("post-scan dashboard refresh failed")
        self.scan_completed.emit(result)

    def _reap_worker(self, account_id: int) -> None:
        w = self._workers.pop(account_id, None)
        if w is not None:
            w.deleteLater()

    # ── T-CAT-5a weekly surprise rebuild ───────────────────────────────────────

    def _maybe_build_surprise(self) -> None:
        """Launch a surprise-profile rebuild iff enabled and the weekly interval
        has elapsed. Cheap and idempotent: ``build_due`` short-circuits until due,
        and a still-running worker blocks a second launch."""
        if not settings.get("surprise_build_enabled", True):
            return
        if self._surprise_worker is not None and self._surprise_worker.isRunning():
            return
        try:
            from analysis.surprise_score import DEFAULT_BUILD_INTERVAL_DAYS, build_due

            interval = int(settings.get("surprise_build_interval_days", DEFAULT_BUILD_INTERVAL_DAYS))
            if not build_due(settings.get("surprise_last_build", None), utcnow_naive(), interval):
                return
        except Exception:
            log.exception("surprise build_due check failed")
            return
        self._launch_surprise_build()

    def _launch_surprise_build(self) -> None:
        account_id = int(settings.get("surprise_build_account_id", 1) or 1)
        worker = SurpriseBuildWorker(account_id, parent=self)
        worker.build_completed.connect(self._on_surprise_completed)
        worker.build_failed.connect(self._on_surprise_failed)
        worker.finished.connect(self._reap_surprise_worker)
        self._surprise_worker = worker
        log.info("surprise rebuild starting (account %s)", account_id)
        worker.start()

    def _on_surprise_completed(self, res) -> None:
        # Stamp only on success so a failed run retries on the next daily tick.
        try:
            settings.set("surprise_last_build", utcnow_naive().isoformat())
            log.info(
                "surprise rebuild done: %s (%s/%s usable quarters≥min)",
                res.get("out"),
                res.get("n_usable"),
                res.get("n_tickers"),
            )
        except Exception:
            log.exception("stamping surprise_last_build failed")

    def _on_surprise_failed(self, err: str) -> None:
        log.warning("surprise rebuild failed (will retry next tick): %s", err)

    def _reap_surprise_worker(self) -> None:
        w = self._surprise_worker
        self._surprise_worker = None
        if w is not None:
            w.deleteLater()

    # ── Daily catalyst refresh (trigger 5) ─────────────────────────────────────

    def _maybe_refresh_catalysts(self) -> None:
        """Launch harvest+classify iff enabled, not yet run today, and due.

        Gates en orden de costo: flag → once-per-day → worker vivo → refresh_due
        (2 queries chicas e indexadas). Se estampa el día aunque falle, para no
        loopear contra un backend roto; el próximo arranque de la app reintenta.
        """
        if not settings.get("catalyst_refresh_on_open", True):
            return
        today = utcnow_naive().date()
        if self._last_catalyst_refresh == today:
            return
        if self._catalyst_worker is not None and self._catalyst_worker.isRunning():
            return
        try:
            from analysis.news_digest import refresh_due

            if not refresh_due():
                # Nada que hacer (ya cosechado hoy y sin backlog) — estampar
                # para que el tick por minuto no re-consulte el resto del día.
                self._last_catalyst_refresh = today
                return
        except Exception:
            log.exception("catalyst refresh_due check failed")
            return
        self._last_catalyst_refresh = today
        self._launch_catalyst_refresh()

    def _launch_catalyst_refresh(self) -> None:
        worker = CatalystRefreshWorker(parent=self)
        worker.refresh_completed.connect(self._on_catalyst_completed)
        worker.refresh_failed.connect(self._on_catalyst_failed)
        worker.finished.connect(self._reap_catalyst_worker)
        self._catalyst_worker = worker
        log.info("daily catalyst refresh starting (harvest + classify)")
        self.catalyst_refresh_started.emit()
        worker.start()

    def _on_catalyst_completed(self, res) -> None:
        log.info(
            "daily catalyst refresh done: harvest_rc=%s classify_rc=%s",
            res.get("harvest_rc"),
            res.get("classify_rc"),
        )
        self.catalyst_refresh_completed.emit(res)

    def _on_catalyst_failed(self, err: str) -> None:
        log.warning("daily catalyst refresh failed (reintenta al próximo arranque): %s", err)
        self.catalyst_refresh_failed.emit(err)

    def _reap_catalyst_worker(self) -> None:
        w = self._catalyst_worker
        self._catalyst_worker = None
        if w is not None:
            w.deleteLater()

    # ── Hourly catalyst harvest durante RTH (tarea 10) ─────────────────────────

    def _maybe_hourly_harvest(self) -> None:
        """Launch harvest-only iff enabled, market open, interval elapsed.

        Gates en orden de costo: flag → intervalo → workers vivos → mercado
        abierto (puede pegar a Yahoo; por eso va último). Corre SOLO con la app
        abierta (rides el tick por minuto del daily timer). Se estampa el
        timestamp al lanzar, aunque el harvest falle: el reintento natural es
        el próximo intervalo, no el próximo tick.
        """
        now = utcnow_naive()
        if not hourly_harvest_due(
            enabled=bool(settings.get("catalyst_hourly_harvest_enabled", True)),
            now=now,
            last=self._last_hourly_harvest,
            interval_min=int(settings.get("catalyst_hourly_harvest_minutes", 60)),
            hourly_worker_running=(
                self._hourly_harvest_worker is not None and self._hourly_harvest_worker.isRunning()
            ),
            daily_worker_running=(self._catalyst_worker is not None and self._catalyst_worker.isRunning()),
            market_open=_is_market_open_now(),
        ):
            return
        self._last_hourly_harvest = now
        worker = CatalystHarvestWorker(parent=self)
        worker.harvest_completed.connect(self._on_hourly_harvest_completed)
        worker.harvest_failed.connect(self._on_hourly_harvest_failed)
        worker.finished.connect(self._reap_hourly_harvest_worker)
        self._hourly_harvest_worker = worker
        log.info("hourly catalyst harvest starting (harvest-only, RTH)")
        worker.start()

    def _on_hourly_harvest_completed(self, res) -> None:
        log.info("hourly catalyst harvest done: harvest_rc=%s", res.get("harvest_rc"))

    def _on_hourly_harvest_failed(self, err: str) -> None:
        log.warning("hourly catalyst harvest failed (reintenta al próximo intervalo): %s", err)

    def _reap_hourly_harvest_worker(self) -> None:
        w = self._hourly_harvest_worker
        self._hourly_harvest_worker = None
        if w is not None:
            w.deleteLater()

    # ── Daily dashboard refresh (trigger 7) ────────────────────────────────────

    def _dashboard_account_id(self) -> int:
        return int(settings.get("dashboard_refresh_account_id", 1) or 1)

    def _maybe_refresh_dashboard(self) -> None:
        """Refresca el dashboard 1×/día (al abrir / tick diario). Gate por día
        calendario. El path post-scan ("Ambos") llama ``_refresh_dashboard_now``
        directo, sin este gate. Se estampa el día antes de lanzar para no
        re-chequear en cada tick por minuto; los reintentos los cubre el
        post-scan."""
        if not settings.get("dashboard_refresh_enabled", True):
            return
        today = utcnow_naive().date()
        if self._last_dashboard_refresh == today:
            return
        self._last_dashboard_refresh = today
        self._refresh_dashboard_now()

    def _refresh_dashboard_now(self) -> None:
        """Lanza el worker si está habilitado, hay targets (DB + artifact) y no
        hay otro corriendo. ``targets_ready`` evita spawnear un ``QThread`` inútil
        en una máquina sin el artifact del dashboard descargado."""
        if not settings.get("dashboard_refresh_enabled", True):
            return
        if self._dashboard_worker is not None and self._dashboard_worker.isRunning():
            return
        try:
            from scripts.refresh_dashboard import targets_ready

            if not targets_ready():
                return
        except Exception:
            log.exception("dashboard targets_ready check failed")
            return
        worker = DashboardRefreshWorker(self._dashboard_account_id(), parent=self)
        worker.refresh_completed.connect(self._on_dashboard_completed)
        worker.refresh_failed.connect(self._on_dashboard_failed)
        worker.finished.connect(self._reap_dashboard_worker)
        self._dashboard_worker = worker
        worker.start()

    def _on_dashboard_completed(self, res) -> None:
        if isinstance(res, dict) and res.get("ok"):
            log.info(
                "dashboard refresh done: %s posiciones · %s", res.get("positions"), res.get("generated_at")
            )
        else:
            reason = res.get("reason") if isinstance(res, dict) else res
            log.debug("dashboard refresh sin cambios: %s", reason)

    def _on_dashboard_failed(self, err: str) -> None:
        log.warning("dashboard refresh failed: %s", err)

    def _reap_dashboard_worker(self) -> None:
        w = self._dashboard_worker
        self._dashboard_worker = None
        if w is not None:
            w.deleteLater()

    # ── Status / health ───────────────────────────────────────────────────────

    def status(self) -> dict:
        """
        Return a snapshot suitable for the UI status bar / debugging:
        active workers, last-scan timestamps, and stale accounts (no scan
        in over 2× the configured interval).
        """
        now = utcnow_naive()
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
