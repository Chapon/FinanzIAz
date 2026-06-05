"""
Integration tests for the T10 ADV (average daily volume) liquidity cap in
``paper_trading.engine.run_scan``.

The cap trims a BUY whose notional exceeds ``paper_adv_cap_pct`` of the
ticker's recent average daily *dollar* volume, so the engine never assumes it
can absorb more than a small slice of a name's liquidity. The cap *modifies*
the order (it does not skip it) and then falls through to the min-trade gate,
so a trim that lands below the dust floor is skipped there instead.

These tests drive the full ``run_scan`` path with injected providers; the pure
math is unit-tested in ``test_paper_gates.py``.
"""

from __future__ import annotations

import pandas as pd

from config.settings_manager import settings
from database.models import session_scope
from paper_trading.account import create_account
from paper_trading.models import PaperOrder, PaperWatchlistItem


def _history(ticker_price: float, volume: float, n: int = 30) -> pd.DataFrame:
    """OHLCV frame with constant close/volume → ADV$ = price × volume."""
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [ticker_price] * n,
            "High": [ticker_price] * n,
            "Low": [ticker_price] * n,
            "Close": [ticker_price] * n,
            "Volume": [volume] * n,
        },
        index=idx,
    )


def _isolate_other_gates() -> None:
    """Turn off the gates that would otherwise interfere with these tests."""
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("earnings_blackout_days", 0)


def _make_buy_strategy(ticker: str, dollars: float):
    from paper_trading.strategies import TargetTrade

    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker=ticker,
                side="BUY",
                target_shares=None,
                target_dollars=dollars,
                reason="analyze BUY",
                source="analyze_single",
            )
        ]

    return strat


def _run(monkeypatch, account, *, ticker, price, volume, buy_dollars):
    from paper_trading import engine

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _make_buy_strategy(ticker, buy_dollars))
    return engine.run_scan(
        account.id,
        prices_provider=lambda _tickers: {ticker: price},
        history_provider=lambda _t: _history(price, volume),
        earnings_provider=lambda _t: None,
    )


def _queued_order(result) -> PaperOrder:
    assert result.pending_orders, "expected a queued order"
    with session_scope() as s:
        return s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()


def test_buy_trimmed_when_over_adv_cap(test_db, monkeypatch):
    """ADV$ = 100 × 10_000 = 1_000_000. cap 5% → ceiling 50_000.
    A 200_000 BUY should be trimmed down to 50_000."""
    a = create_account(name="ADV", initial_capital=1_000_000.0, mode="manual")
    _isolate_other_gates()
    settings.set("paper_adv_cap_pct", 0.05)
    settings.set("paper_adv_lookback_days", 20)
    settings.set("paper_min_trade_dollars", 250.0)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    result = _run(monkeypatch, a, ticker="AAPL", price=100.0, volume=10_000.0, buy_dollars=200_000.0)

    assert result is not None
    assert result.queued == 1
    order = _queued_order(result)
    assert order.target_dollars == 50_000.0
    assert any("recortado por ADV" in w for w in result.warnings)


def test_buy_not_trimmed_when_under_cap(test_db, monkeypatch):
    """A small BUY that fits under the ADV ceiling passes untouched."""
    a = create_account(name="ADV", initial_capital=1_000_000.0, mode="manual")
    _isolate_other_gates()
    settings.set("paper_adv_cap_pct", 0.05)  # ceiling 50_000
    settings.set("paper_adv_lookback_days", 20)
    settings.set("paper_min_trade_dollars", 250.0)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="MSFT"))

    result = _run(monkeypatch, a, ticker="MSFT", price=100.0, volume=10_000.0, buy_dollars=10_000.0)

    assert result is not None
    assert result.queued == 1
    order = _queued_order(result)
    assert order.target_dollars == 10_000.0
    assert not any("recortado por ADV" in w for w in result.warnings)


def test_cap_disabled_leaves_order_untouched(test_db, monkeypatch):
    """cap_pct = 0.0 (default) → the gate is a no-op even for a huge BUY."""
    a = create_account(name="ADV", initial_capital=10_000_000.0, mode="manual")
    _isolate_other_gates()
    settings.set("paper_adv_cap_pct", 0.0)
    settings.set("paper_min_trade_dollars", 250.0)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="NVDA"))

    result = _run(monkeypatch, a, ticker="NVDA", price=100.0, volume=10_000.0, buy_dollars=5_000_000.0)

    assert result is not None
    assert result.queued == 1
    order = _queued_order(result)
    assert order.target_dollars == 5_000_000.0
    assert not any("recortado por ADV" in w for w in result.warnings)


def test_failopen_when_history_missing(test_db, monkeypatch):
    """No history → ADV unknown → fail open, order untouched."""
    from paper_trading import engine

    a = create_account(name="ADV", initial_capital=1_000_000.0, mode="manual")
    _isolate_other_gates()
    settings.set("paper_adv_cap_pct", 0.05)
    settings.set("paper_min_trade_dollars", 250.0)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="TSLA"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _make_buy_strategy("TSLA", 200_000.0))
    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"TSLA": 100.0},
        history_provider=lambda _t: None,  # ADV cannot be estimated
        earnings_provider=lambda _t: None,
    )

    assert result is not None
    assert result.queued == 1
    order = _queued_order(result)
    assert order.target_dollars == 200_000.0
    assert not any("recortado por ADV" in w for w in result.warnings)


def test_trim_below_min_trade_is_then_skipped(test_db, monkeypatch):
    """If the ADV trim lands below paper_min_trade_dollars, Gate 4 skips it.

    ADV$ = 100 × 100 = 10_000. cap 1% → ceiling 100. With min-trade 250 the
    trimmed 100 order is dust and must be dropped, not queued."""
    a = create_account(name="ADV", initial_capital=1_000_000.0, mode="manual")
    _isolate_other_gates()
    settings.set("paper_adv_cap_pct", 0.01)  # ceiling 100
    settings.set("paper_adv_lookback_days", 20)
    settings.set("paper_min_trade_dollars", 250.0)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="GM"))

    result = _run(monkeypatch, a, ticker="GM", price=100.0, volume=100.0, buy_dollars=5_000.0)

    assert result is not None
    assert result.queued == 0
    assert result.skipped >= 1
    assert any("recortado por ADV" in w for w in result.warnings)
    assert any("mínimo" in w for w in result.warnings)
