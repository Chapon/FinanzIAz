"""
Tooltip helper for ticker columns.

Shows a rich popup (name, sector, exchange, P/E, etc.) when hovering over
any ticker cell in the app. Info is sourced from:

  1. In-memory cache (instant)
  2. The Position table (fast, already-stored company_name + sector)
  3. yfinance via a background QThreadPool worker (lazy, only on first hover)

When new info arrives in the background, the global signal
`ticker_cache.info_updated(ticker: str)` is emitted, and tables that called
`install_ticker_tooltips(table, col)` will refresh the tooltip for that
ticker without rebuilding the whole table.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem


# ── Background fetch ──────────────────────────────────────────────────────────


class _FetchSignals(QObject):
    """Bridge from a QRunnable (worker thread) to Qt signals on the main thread."""
    fetched = pyqtSignal(str, dict)   # ticker, info_dict


class _FetchRunnable(QRunnable):
    """Fetches company info for a single ticker via yfinance."""

    def __init__(self, ticker: str, signals: _FetchSignals):
        super().__init__()
        self.ticker = ticker
        self.signals = signals
        # Run-and-forget; do not auto-delete so signals fire reliably
        self.setAutoDelete(True)

    def run(self):
        info: dict = {}
        try:
            # Imported inside run() so that import-time errors in yfinance
            # never break the UI on startup.
            from data.yahoo_finance import get_company_info
            info = get_company_info(self.ticker) or {}
        except Exception as e:
            print(f"[ticker_tooltip] fetch failed for {self.ticker}: {e}")
            info = {}
        info.setdefault("name", self.ticker)
        info["source"] = "yfinance"
        self.signals.fetched.emit(self.ticker, info)


# ── Cache ─────────────────────────────────────────────────────────────────────


class _TickerInfoCache(QObject):
    """
    Global, lazy-loaded cache of company info per ticker.
    Singleton — use the module-level `ticker_cache` instance.
    """
    info_updated = pyqtSignal(str)   # emitted on the main thread when new info arrives

    def __init__(self):
        super().__init__()
        self._cache: dict[str, dict] = {}
        self._pending: set[str] = set()
        self._db_loaded = False

        # Limit how many parallel yfinance calls we run.
        self._pool = QThreadPool.globalInstance()
        # No more than 2 concurrent ticker info fetches — yfinance can be slow
        # and we don't want to compete with price/historical fetches.
        try:
            self._pool.setMaxThreadCount(max(self._pool.maxThreadCount(), 4))
        except Exception:
            pass

        # Persistent signal bridge — keeps refs alive.
        self._signals = _FetchSignals()
        self._signals.fetched.connect(self._on_fetched)

    # ── DB warm-up ───────────────────────────────────────────────────────────

    def _ensure_db_loaded(self):
        """One-shot read of all known Position records → populate cache."""
        if self._db_loaded:
            return
        self._db_loaded = True
        try:
            from database.models import get_session, Position
            session = get_session()
            try:
                rows = session.query(
                    Position.ticker, Position.company_name, Position.sector
                ).all()
                for ticker, name, sector in rows:
                    if not ticker:
                        continue
                    key = ticker.upper()
                    if key in self._cache:
                        continue
                    self._cache[key] = {
                        "ticker": key,
                        "name": name or key,
                        "sector": sector or None,
                        "source": "db",
                    }
            finally:
                session.close()
        except Exception as e:
            print(f"[ticker_tooltip] DB pre-load failed: {e}")

    # ── Public API ───────────────────────────────────────────────────────────

    def get(self, ticker: str) -> dict:
        """
        Return whatever we currently know about `ticker` (always non-None).
        Triggers a background fetch if we have nothing — the cache will be
        populated and `info_updated(ticker)` emitted when ready.
        """
        if not ticker:
            return {"ticker": "—", "name": "—"}
        key = ticker.strip().upper()
        if not key:
            return {"ticker": "—", "name": "—"}

        self._ensure_db_loaded()
        cached = self._cache.get(key)

        # If we only have minimal DB info (name, sector), still kick off a
        # full yfinance fetch once to enrich it (exchange, P/E, etc.).
        if cached is None or cached.get("source") == "db":
            self._schedule_fetch(key)

        if cached is not None:
            return cached
        return {"ticker": key, "name": key, "source": "pending"}

    def _schedule_fetch(self, ticker: str):
        if ticker in self._pending:
            return
        self._pending.add(ticker)
        runnable = _FetchRunnable(ticker, self._signals)
        self._pool.start(runnable)

    def _on_fetched(self, ticker: str, info: dict):
        self._pending.discard(ticker)
        # Don't lose name/sector if yfinance returned an empty payload.
        merged = dict(self._cache.get(ticker, {}))
        merged.update({k: v for k, v in info.items() if v not in (None, "", "N/A")})
        merged["ticker"] = ticker
        if not merged.get("name"):
            merged["name"] = ticker
        self._cache[ticker] = merged
        self.info_updated.emit(ticker)


# Module-level singleton
ticker_cache = _TickerInfoCache()


# ── Tooltip formatting ────────────────────────────────────────────────────────


def _fmt_pct(value, decimals: int = 2) -> Optional[str]:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    # yfinance dividend_yield arrives as a fraction (0.0123) sometimes and
    # as a percentage (1.23) other times. Heuristic: <= 1 → fraction.
    if abs(v) <= 1:
        v = v * 100.0
    return f"{v:.{decimals}f}%"


def _fmt_number(value, decimals: int = 2) -> Optional[str]:
    if value is None:
        return None
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return None


def format_tooltip(ticker: str) -> str:
    """Return rich-text HTML to use as a QToolTip for the given ticker."""
    if not ticker:
        return ""
    key = ticker.strip().upper()
    info = ticker_cache.get(key)

    name = (info.get("name") or key).strip()
    sector = info.get("sector")
    industry = info.get("industry")
    exchange = info.get("exchange")
    country = info.get("country")
    currency = info.get("currency")
    pe = _fmt_number(info.get("pe_ratio"))
    eps = _fmt_number(info.get("eps"))
    div_yield = _fmt_pct(info.get("dividend_yield"))
    beta = _fmt_number(info.get("beta"))

    # Header
    parts: list[str] = []
    parts.append(
        f"<div style='font-size:13px;'><b>{key}</b>"
    )
    if name and name.upper() != key:
        parts.append(f" &nbsp;<span style='color:#9ca3af;'>{name}</span>")
    parts.append("</div>")

    # Body fields
    fields: list[tuple[str, Optional[str]]] = [
        ("Sector", sector if sector and sector != "N/A" else None),
        ("Industria", industry if industry and industry != "N/A" else None),
        ("Mercado", exchange if exchange and exchange != "N/A" else None),
        ("País", country if country and country != "N/A" else None),
        ("Moneda", currency if currency and currency != "N/A" else None),
        ("P/E", pe),
        ("EPS", eps),
        ("Div. Yield", div_yield),
        ("Beta", beta),
    ]
    rows = [
        f"<tr><td style='color:#9ca3af;padding-right:10px;'>{label}</td>"
        f"<td style='color:#e6edf3;'><b>{value}</b></td></tr>"
        for label, value in fields if value
    ]

    if rows:
        parts.append(
            "<table cellspacing='0' cellpadding='1' "
            "style='font-size:11px;margin-top:4px;'>"
            + "".join(rows)
            + "</table>"
        )
    else:
        parts.append(
            "<div style='color:#9ca3af;font-size:11px;margin-top:4px;'>"
            "<i>Cargando información…</i></div>"
        )

    return "".join(parts)


# ── Helpers to wire tables ────────────────────────────────────────────────────


def apply_ticker_tooltip(item: Optional[QTableWidgetItem], ticker: str) -> None:
    """Set a rich tooltip on `item` for the given ticker. Safe with None."""
    if item is None or not ticker:
        return
    item.setToolTip(format_tooltip(ticker))


def install_ticker_tooltips(table: QTableWidget, ticker_col: int) -> None:
    """
    Install ticker tooltips on `table` for the column at index `ticker_col`.
    Refreshes the tooltip of the relevant row whenever new info for a ticker
    arrives in the background. Call this once, after the table is created.
    """
    if table is None:
        return

    def _refresh_for(ticker: str):
        if not ticker:
            return
        target = ticker.strip().upper()
        if not target:
            return
        for r in range(table.rowCount()):
            item = table.item(r, ticker_col)
            if item is None:
                continue
            cell_text = (item.text() or "").strip().upper()
            if cell_text == target:
                item.setToolTip(format_tooltip(target))

    ticker_cache.info_updated.connect(_refresh_for, Qt.ConnectionType.QueuedConnection)
