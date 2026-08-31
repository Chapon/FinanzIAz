"""Telemetría de cobertura de precios en run_scan (bug B3).

Cuando Yahoo throttlea, varios tickers vuelven sin precio. El scan NO debe
operar a ciegas: ATR exits y la strategy ya saltean los tickers sin precio, y
ahora el resultado del scan reporta cuántos quedaron sin precio (``prices_missing``)
y avisa fuerte si una POSICIÓN abierta quedó sin evaluar (stop no corrido).
"""

from __future__ import annotations

import logging

import pandas as pd

from config.settings_manager import settings
from database.models import session_scope
from paper_trading.account import create_account
from paper_trading.models import PaperPosition, PaperWatchlistItem


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
        {
            "Open": [100.0] * n,
            "High": [100.0] * n,
            "Low": [100.0] * n,
            "Close": [100.0] * n,
            "Volume": [10_000.0] * n,
        },
        index=idx,
    )


def test_scan_reports_missing_prices_and_warns_on_held(test_db, monkeypatch, caplog):
    """Una posición sin precio (throttle) → prices_missing>0 + warning con el ticker."""
    from paper_trading import engine

    a = create_account(name="COV", initial_capital=100_000.0, mode="manual")
    _isolate_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))
        s.add(PaperWatchlistItem(account_id=a.id, ticker="JPM"))
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="JPM",  # posición abierta que quedará sin precio
                shares=10.0,
                avg_cost=140.0,
                high_water_mark=140.0,
            )
        )

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _no_trades_strategy)

    with caplog.at_level(logging.WARNING, logger="paper_trading.engine"):
        result = engine.run_scan(
            a.id,
            # JPM ausente del dict → sin precio (simula throttle de Yahoo)
            prices_provider=lambda _t: {"AAPL": 100.0},
            history_provider=lambda _t: _history(),
            earnings_provider=lambda _t: None,
        )

    assert result is not None
    assert result.prices_requested == 2
    assert result.prices_missing == 1
    # La posición sin precio quedó registrada en los warnings del scan…
    assert any("JPM" in w for w in result.warnings)
    # …y se logueó fuerte (stop no corrido sobre una posición abierta).
    assert any("JPM" in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)


def test_scan_no_warning_when_all_priced(test_db, monkeypatch):
    """Universo completo con precio → prices_missing=0 y sin warnings de cobertura."""
    from paper_trading import engine

    a = create_account(name="COV2", initial_capital=100_000.0, mode="manual")
    _isolate_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _no_trades_strategy)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: _history(),
        earnings_provider=lambda _t: None,
    )

    assert result is not None
    assert result.prices_missing == 0
    assert not any("sin precio" in w for w in result.warnings)
