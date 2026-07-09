"""Telemetría de timing por fase en run_scan (OPS1(c)).

Sin timing no se puede decidir si bajar el intervalo de 15 min es viable ni
detectar degradación de Yahoo antes de que muerda. ``run_scan`` mide fetch
(warm-up + precios), analyze (ATR exits + strategy) y process (gates+fill, van
interleaveados en el mismo loop) y las expone en ``ScanResult``.
"""

from __future__ import annotations

import pandas as pd

from config.settings_manager import settings
from database.models import session_scope
from paper_trading.account import create_account
from paper_trading.models import PaperWatchlistItem


def _isolate_gates() -> None:
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("earnings_blackout_days", 0)


def _no_trades_strategy(account, watchlist, positions, prices, history_provider):
    return []


def _history(n: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": [100.0] * n, "High": [100.0] * n, "Low": [100.0] * n,
         "Close": [100.0] * n, "Volume": [10_000.0] * n},
        index=idx,
    )


def _run(account_id: int):
    from paper_trading import engine

    return engine.run_scan(
        account_id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: _history(),
        earnings_provider=lambda _t: None,
    )


def test_scan_reports_phase_timings(test_db, monkeypatch):
    """El scan expone fetch/analyze/process >= 0 y suman el total wall-clock."""
    from paper_trading import engine

    a = create_account(name="TEL", initial_capital=100_000.0, mode="manual")
    _isolate_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _no_trades_strategy)
    result = _run(a.id)

    assert result is not None
    assert set(result.phase_seconds) == {"fetch", "analyze", "process"}
    assert all(v >= 0.0 for v in result.phase_seconds.values())
    assert result.scan_seconds > 0.0
    # fetch + analyze + process == scan_seconds (por construcción; tolerancia de
    # redondeo a 4 decimales sobre 3 fases).
    assert abs(sum(result.phase_seconds.values()) - result.scan_seconds) < 1e-3


def test_summary_includes_timing_when_measured(test_db, monkeypatch):
    """summary() incluye el total y el desglose por fase cuando hubo medición."""
    from paper_trading import engine

    a = create_account(name="TEL2", initial_capital=100_000.0, mode="manual")
    _isolate_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _no_trades_strategy)
    result = _run(a.id)

    line = result.summary()
    assert "fetch" in line and "analyze" in line and "process" in line
    assert "s (" in line  # el bloque de timing "<total>s (fetch …)"


def test_summary_omits_timing_when_unmeasured():
    """Un ScanResult crudo (sin timing) no ensucia el summary con 0.00s."""
    from datetime import datetime

    from paper_trading.engine import ScanResult

    r = ScanResult(
        account_id=1,
        scan_at=datetime(2026, 7, 9, 15, 0),
        mode="manual",
        strategy="analyze_single",
        prices={},
    )
    assert r.scan_seconds == 0.0
    assert "fetch" not in r.summary()  # sin medición → sin bloque de timing
