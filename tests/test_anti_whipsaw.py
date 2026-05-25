"""
Tests for Gate 5 (anti-whipsaw) in paper_trading.engine.

The gate blocks a fresh BUY when the most recent closed cycle for the same
ticker ended at a loss within the configured lookback window. The threshold
``paper_whipsaw_min_loss_pct`` lets the user demand a worse-than-X% loss
before blocking; the default 0.0 blocks any loss.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.engine import _last_closed_cycle_pnl_pct
from paper_trading.models import PaperOrder


def _add_order(session, account_id, ticker, side, fill_price, fill_shares, hours_ago):
    when = utcnow_naive() - timedelta(hours=hours_ago)
    session.add(
        PaperOrder(
            account_id=account_id,
            ticker=ticker,
            side=side,
            target_shares=fill_shares if side == "SELL" else None,
            target_dollars=fill_price * fill_shares if side == "BUY" else None,
            reason=f"test {side}",
            source="analyze_single",
            status="filled",
            created_at=when,
            decided_at=when,
            filled_at=when,
            fill_price=fill_price,
            fill_shares=fill_shares,
            commission_paid=0.0,
            slippage_cost=0.0,
        )
    )


def test_last_cycle_pnl_loss(test_db):
    """BUY @100 then SELL @90 → -10% over the cycle."""
    a = create_account(name="W", initial_capital=10_000.0)
    with session_scope() as s:
        _add_order(s, a.id, "AAPL", "BUY", 100.0, 10.0, hours_ago=48)
        _add_order(s, a.id, "AAPL", "SELL", 90.0, 10.0, hours_ago=24)

    with session_scope() as s:
        pnl = _last_closed_cycle_pnl_pct(s, a.id, "AAPL", within_days=7)

    assert pnl is not None
    assert abs(pnl - (-10.0)) < 1e-6


def test_last_cycle_pnl_gain(test_db):
    """BUY @100 then SELL @110 → +10%."""
    a = create_account(name="W", initial_capital=10_000.0)
    with session_scope() as s:
        _add_order(s, a.id, "MSFT", "BUY", 100.0, 5.0, hours_ago=48)
        _add_order(s, a.id, "MSFT", "SELL", 110.0, 5.0, hours_ago=24)

    with session_scope() as s:
        pnl = _last_closed_cycle_pnl_pct(s, a.id, "MSFT", within_days=7)

    assert pnl is not None
    assert abs(pnl - 10.0) < 1e-6


def test_last_cycle_outside_window_returns_none(test_db):
    """If the SELL was 30 days ago and window=7, the gate sees nothing."""
    a = create_account(name="W", initial_capital=10_000.0)
    with session_scope() as s:
        _add_order(s, a.id, "NVDA", "BUY", 100.0, 5.0, hours_ago=24 * 31)
        _add_order(s, a.id, "NVDA", "SELL", 80.0, 5.0, hours_ago=24 * 30)

    with session_scope() as s:
        pnl = _last_closed_cycle_pnl_pct(s, a.id, "NVDA", within_days=7)

    assert pnl is None


def test_last_cycle_weighted_average_basis(test_db):
    """Multiple BUYs in one cycle should be weighted by share count."""
    a = create_account(name="W", initial_capital=10_000.0)
    with session_scope() as s:
        # 10 shares @ 100, 10 shares @ 120 → avg basis 110
        _add_order(s, a.id, "GM", "BUY", 100.0, 10.0, hours_ago=72)
        _add_order(s, a.id, "GM", "BUY", 120.0, 10.0, hours_ago=60)
        _add_order(s, a.id, "GM", "SELL", 99.0, 20.0, hours_ago=24)

    with session_scope() as s:
        pnl = _last_closed_cycle_pnl_pct(s, a.id, "GM", within_days=7)

    # (99 - 110)/110 ≈ -10.0%
    assert pnl is not None
    assert abs(pnl - (-10.0)) < 1e-6


def test_last_cycle_ignores_prior_cycle(test_db):
    """Only the BUYs *between* the previous SELL and the current SELL count.

    Setup:
        BUY 100 / SELL 110  (cycle 1, gain)
        BUY  90 / SELL  85  (cycle 2, loss — this is what we care about)
    """
    a = create_account(name="W", initial_capital=10_000.0)
    with session_scope() as s:
        _add_order(s, a.id, "WMT", "BUY", 100.0, 5.0, hours_ago=200)
        _add_order(s, a.id, "WMT", "SELL", 110.0, 5.0, hours_ago=180)
        _add_order(s, a.id, "WMT", "BUY", 90.0, 5.0, hours_ago=72)
        _add_order(s, a.id, "WMT", "SELL", 85.0, 5.0, hours_ago=24)

    with session_scope() as s:
        pnl = _last_closed_cycle_pnl_pct(s, a.id, "WMT", within_days=14)

    # (85-90)/90 ≈ -5.56%, NOT the prior gain.
    assert pnl is not None
    assert pnl < 0
    assert abs(pnl - (-5.555555)) < 1e-3


def test_last_cycle_no_sell_returns_none(test_db):
    """A ticker that's only been bought (no SELL yet) has no closed cycle."""
    a = create_account(name="W", initial_capital=10_000.0)
    with session_scope() as s:
        _add_order(s, a.id, "TSLA", "BUY", 300.0, 1.0, hours_ago=24)

    with session_scope() as s:
        pnl = _last_closed_cycle_pnl_pct(s, a.id, "TSLA", within_days=7)

    assert pnl is None


def test_gate_blocks_buy_after_loss(test_db, monkeypatch):
    """Full integration: run_scan should skip a BUY that would re-enter a
    ticker we just sold at a loss inside the lookback window."""
    from paper_trading import engine
    from paper_trading.models import PaperWatchlistItem
    from paper_trading.strategies import TargetTrade

    a = create_account(name="W", initial_capital=10_000.0)
    settings.set("paper_whipsaw_lookback_days", 7)
    settings.set("paper_whipsaw_min_loss_pct", 0.0)
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)  # isolate Gate 5 from Gate 3

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))
        # Simulate a closed losing cycle: BUY @100 → SELL @90 a day ago
        _add_order(s, a.id, "AAPL", "BUY", 100.0, 10.0, hours_ago=72)
        _add_order(s, a.id, "AAPL", "SELL", 90.0, 10.0, hours_ago=24)

    # Strategy proposes a fresh BUY for AAPL.
    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker="AAPL",
                side="BUY",
                target_shares=None,
                target_dollars=1_000.0,
                reason="analyze BUY",
                source="analyze_single",
            )
        ]

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: strat)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"AAPL": 95.0},
        history_provider=lambda _t: None,
    )

    assert result is not None
    assert result.filled == 0
    assert result.queued == 0
    assert result.skipped >= 1
    # The warning message should mention anti-whipsaw so users can see why.
    assert any("anti-whipsaw" in w for w in result.warnings)


def test_gate_allows_buy_after_winning_cycle(test_db, monkeypatch):
    """Same setup, but the prior cycle was a gain → BUY should proceed."""
    from paper_trading import engine
    from paper_trading.models import PaperWatchlistItem
    from paper_trading.strategies import TargetTrade

    a = create_account(
        name="W",
        initial_capital=10_000.0,
        mode="manual",  # easier to assert: queued instead of filled
    )
    settings.set("paper_whipsaw_lookback_days", 7)
    settings.set("paper_whipsaw_min_loss_pct", 0.0)
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="MSFT"))
        # Winning closed cycle
        _add_order(s, a.id, "MSFT", "BUY", 100.0, 5.0, hours_ago=72)
        _add_order(s, a.id, "MSFT", "SELL", 115.0, 5.0, hours_ago=24)

    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker="MSFT",
                side="BUY",
                target_shares=None,
                target_dollars=1_000.0,
                reason="analyze BUY",
                source="analyze_single",
            )
        ]

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: strat)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"MSFT": 118.0},
        history_provider=lambda _t: None,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("anti-whipsaw" in w for w in result.warnings)
