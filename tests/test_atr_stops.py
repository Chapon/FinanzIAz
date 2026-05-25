"""
Tests for the ATR-stop gate (T01 of the engine roadmap).

The gate runs *before* the strategy and forces a SELL when an open position
crosses one of three thresholds, sized in ATR units off the current entry
or the post-entry high water mark:

    atr_stop    price ≤ avg_cost − stop_mult × ATR
    atr_trail   price ≤ high_water_mark − stop_mult × ATR    (HWM > entry + ATR)
    atr_tp      price ≥ avg_cost + tp_mult × ATR

Default state is OFF (``atr_stops_enabled=False``). Forced SELLs use
``signal_score=1.0`` and bypass Gate 2 (min-holding). When an ATR exit
fires for a ticker, any strategy-emitted SELL for the same ticker is
discarded — the ATR trigger wins.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.engine import (
    _compute_atr_forced_exits,
    _is_atr_forced_exit,
    _update_high_water_marks,
)
from paper_trading.models import PaperPosition, PaperWatchlistItem

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(
    closes: list[float],
    *,
    high_pad: float = 0.5,
    low_pad: float = 0.5,
) -> pd.DataFrame:
    """Build an OHLCV frame from a list of closes. High/Low are ``close ±
    pad`` so True Range stays small and ATR is roughly the pad sum.

    Using fixed pads (rather than random) makes ATR predictable for tests:
    on a steady close series, TR ≈ high_pad + low_pad per bar and ATR
    converges to that same value.
    """
    closes_a = np.asarray(closes, dtype=float)
    highs = closes_a + high_pad
    lows = closes_a - low_pad
    opens = np.r_[closes_a[0], closes_a[:-1]]
    vols = np.full(len(closes_a), 1_000_000.0)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=len(closes_a), freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes_a, "Volume": vols},
        index=idx,
    )


# ── ATR helper itself ─────────────────────────────────────────────────────────


def test_compute_atr_basic():
    """On a steady close, TR per bar = high_pad + low_pad ≈ 1.0 → ATR≈1.0."""
    from analysis.atr import compute_atr

    df = _make_ohlcv([100.0] * 60, high_pad=0.5, low_pad=0.5)
    atr = compute_atr(df, period=14)
    assert atr is not None
    # ATR should be ~ 1.0 (the per-bar range), within tolerance.
    assert 0.8 <= atr <= 1.2


def test_compute_atr_too_short_returns_none():
    """Fewer than period+1 bars → None."""
    from analysis.atr import compute_atr

    df = _make_ohlcv([100.0] * 5)
    assert compute_atr(df, period=14) is None


def test_compute_atr_handles_missing_columns():
    from analysis.atr import compute_atr

    df = pd.DataFrame({"Close": [100.0] * 60})
    assert compute_atr(df, period=14) is None


# ── Gate semantics (unit) ─────────────────────────────────────────────────────


def test_is_atr_forced_exit_classifier():
    assert _is_atr_forced_exit("atr_stop @ 90 ≤ 95")
    assert _is_atr_forced_exit("atr_trail @ ...")
    assert _is_atr_forced_exit("atr_tp @ ...")
    assert not _is_atr_forced_exit("analyze SELL (0.36)")
    assert not _is_atr_forced_exit(None)
    assert not _is_atr_forced_exit("")


def test_gate_disabled_by_default(test_db):
    """With the master switch off, no exits are produced even on a crash."""
    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="AAPL",
                shares=10.0,
                avg_cost=100.0,
                high_water_mark=100.0,
            )
        )
    df = _make_ohlcv([100.0] * 60)

    with session_scope() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.account_id == a.id).all()
        exits = _compute_atr_forced_exits(positions, prices={"AAPL": 50.0}, history_provider=lambda _t: df)
    assert exits == []


def test_gate_stop_loss_fires(test_db):
    """Price below entry − stop_mult × ATR triggers atr_stop."""
    settings.set("atr_stops_enabled", True)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 2.0)
    settings.set("atr_tp_mult", 100.0)  # huge, so TP doesn't accidentally fire
    settings.set("atr_trail_enabled", False)  # isolate stop-loss

    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="AAPL",
                shares=10.0,
                avg_cost=100.0,
                high_water_mark=100.0,
            )
        )
    df = _make_ohlcv([100.0] * 60)  # ATR ≈ 1.0
    # Stop level = 100 - 2*1 = 98. Use 95 → trigger.
    with session_scope() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.account_id == a.id).all()
        exits = _compute_atr_forced_exits(positions, prices={"AAPL": 95.0}, history_provider=lambda _t: df)
    assert len(exits) == 1
    e = exits[0]
    assert e.side == "SELL"
    assert e.ticker == "AAPL"
    assert e.target_shares == 10.0
    assert e.reason is not None and e.reason.startswith("atr_stop")
    assert e.signal_score == 1.0
    assert e.source == "atr_stop_gate"


def test_gate_take_profit_fires(test_db):
    settings.set("atr_stops_enabled", True)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 100.0)  # huge → stop won't fire
    settings.set("atr_tp_mult", 2.0)
    settings.set("atr_trail_enabled", False)

    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="MSFT",
                shares=5.0,
                avg_cost=100.0,
                high_water_mark=100.0,
            )
        )
    df = _make_ohlcv([100.0] * 60)
    # TP level = 100 + 2*1 = 102. Use 105.
    with session_scope() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.account_id == a.id).all()
        exits = _compute_atr_forced_exits(positions, prices={"MSFT": 105.0}, history_provider=lambda _t: df)
    assert len(exits) == 1
    assert exits[0].reason is not None and exits[0].reason.startswith("atr_tp")
    assert exits[0].signal_score == 1.0


def test_gate_trailing_fires(test_db):
    """Trailing requires HWM > entry + ATR. Set HWM way above entry, then a
    price below HWM − 2×ATR triggers atr_trail."""
    settings.set("atr_stops_enabled", True)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 2.0)
    settings.set("atr_tp_mult", 100.0)  # don't accidentally take profit
    settings.set("atr_trail_enabled", True)

    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="NVDA",
                shares=2.0,
                avg_cost=100.0,
                high_water_mark=120.0,  # HWM well above entry
            )
        )
    df = _make_ohlcv([100.0] * 60)  # ATR ≈ 1.0
    # Trail level = 120 - 2*1 = 118. Stop level = 100 - 2 = 98.
    # Use price 117 → trail fires, stop doesn't.
    with session_scope() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.account_id == a.id).all()
        exits = _compute_atr_forced_exits(positions, prices={"NVDA": 117.0}, history_provider=lambda _t: df)
    assert len(exits) == 1
    assert exits[0].reason is not None and exits[0].reason.startswith("atr_trail")


def test_gate_no_trigger_inside_band(test_db):
    settings.set("atr_stops_enabled", True)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 2.0)
    settings.set("atr_tp_mult", 4.0)
    settings.set("atr_trail_enabled", True)

    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="X",
                shares=1.0,
                avg_cost=100.0,
                high_water_mark=100.5,
            )
        )
    df = _make_ohlcv([100.0] * 60)
    # Price right at entry: inside [98, 104] band, HWM not high enough for trail.
    with session_scope() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.account_id == a.id).all()
        exits = _compute_atr_forced_exits(positions, prices={"X": 100.0}, history_provider=lambda _t: df)
    assert exits == []


def test_gate_priority_stop_over_tp(test_db):
    """If both stop and TP would fire (pathological large ATR / weird state),
    the stop wins — capital preservation first."""
    settings.set("atr_stops_enabled", True)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 0.5)
    settings.set("atr_tp_mult", 0.5)
    settings.set("atr_trail_enabled", False)

    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="Y",
                shares=1.0,
                avg_cost=100.0,
                high_water_mark=100.0,
            )
        )
    df = _make_ohlcv([100.0] * 60)  # ATR ≈ 1.0
    # With mult=0.5 the band is [99.5, 100.5]. Price 95 hits stop, also < TP
    # threshold but stop is checked first.
    with session_scope() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.account_id == a.id).all()
        exits = _compute_atr_forced_exits(positions, prices={"Y": 95.0}, history_provider=lambda _t: df)
    assert len(exits) == 1
    assert exits[0].reason is not None and exits[0].reason.startswith("atr_stop")


# ── HWM seeding / advancing ───────────────────────────────────────────────────


def test_hwm_seeds_null(test_db):
    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="HW",
                shares=1.0,
                avg_cost=100.0,
                high_water_mark=None,
            )
        )
    with session_scope() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.account_id == a.id).all()
        _update_high_water_marks(positions, prices={"HW": 105.0})
        assert positions[0].high_water_mark == 105.0


def test_hwm_seeds_to_avg_cost_when_price_lower(test_db):
    """If current price is below entry, the seed is avg_cost — protects
    against the trailing stop firing on day 1 from a low seed."""
    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="HW",
                shares=1.0,
                avg_cost=100.0,
                high_water_mark=None,
            )
        )
    with session_scope() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.account_id == a.id).all()
        _update_high_water_marks(positions, prices={"HW": 90.0})
        assert positions[0].high_water_mark == 100.0


def test_hwm_advances_only_upward(test_db):
    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="HW",
                shares=1.0,
                avg_cost=100.0,
                high_water_mark=110.0,
            )
        )
    with session_scope() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.account_id == a.id).all()
        # Price below HWM — HWM should stay.
        _update_high_water_marks(positions, prices={"HW": 105.0})
        assert positions[0].high_water_mark == 110.0
        # Price above HWM — HWM advances.
        _update_high_water_marks(positions, prices={"HW": 115.0})
        assert positions[0].high_water_mark == 115.0


# ── Integration with run_scan ─────────────────────────────────────────────────


def test_run_scan_fires_stop_and_bypasses_min_holding(test_db, monkeypatch):
    """End-to-end: an ATR stop fires even on a fresh position whose age is
    below min_holding_minutes, and the resulting SELL is filled."""
    from paper_trading import engine

    settings.set("atr_stops_enabled", True)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 2.0)
    settings.set("atr_tp_mult", 100.0)
    settings.set("atr_trail_enabled", False)
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_min_holding_minutes", 60)  # 1h min holding
    settings.set("paper_anti_flap_minutes", 0)

    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        # Position opened 5 minutes ago — would normally be blocked by Gate 2
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="AAPL",
                shares=10.0,
                avg_cost=100.0,
                opened_at=utcnow_naive() - timedelta(minutes=5),
                high_water_mark=100.0,
            )
        )
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    df = _make_ohlcv([100.0] * 60)  # ATR ≈ 1.0

    # Strategy emits nothing — exit comes purely from the ATR gate.
    monkeypatch.setattr(
        engine,
        "get_strategy_fn",
        lambda _: lambda *a, **kw: [],
    )

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 90.0},  # below stop (98)
        history_provider=lambda _t: df,
    )

    assert result is not None
    assert result.filled == 1
    # Position should be closed now.
    with session_scope() as s:
        remaining = (
            s.query(PaperPosition)
            .filter(PaperPosition.account_id == a.id)
            .filter(PaperPosition.ticker == "AAPL")
            .first()
        )
        assert remaining is None or remaining.shares <= 1e-9


def test_run_scan_atr_exit_overrides_strategy_sell(test_db, monkeypatch):
    """If the strategy also emits a SELL for the same ticker, the ATR
    exit replaces it (we only see one SELL, with reason starting atr_)."""
    from paper_trading import engine
    from paper_trading.models import PaperOrder
    from paper_trading.strategies import TargetTrade

    settings.set("atr_stops_enabled", True)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 2.0)
    settings.set("atr_tp_mult", 100.0)
    settings.set("atr_trail_enabled", False)
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_min_holding_minutes", 0)
    settings.set("paper_anti_flap_minutes", 0)

    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="AAPL",
                shares=10.0,
                avg_cost=100.0,
                opened_at=utcnow_naive() - timedelta(days=2),
                high_water_mark=100.0,
            )
        )

    df = _make_ohlcv([100.0] * 60)

    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker="AAPL",
                side="SELL",
                target_shares=10.0,
                target_dollars=None,
                reason="analyze SELL (0.30)",
                source="analyze_single",
            )
        ]

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: strat)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 90.0},  # below stop
        history_provider=lambda _t: df,
    )

    assert result is not None
    assert result.filled == 1

    with session_scope() as s:
        orders = (
            s.query(PaperOrder)
            .filter(PaperOrder.account_id == a.id)
            .filter(PaperOrder.status == "filled")
            .filter(PaperOrder.side == "SELL")
            .all()
        )
        assert len(orders) == 1
        o = orders[0]
        assert o.reason is not None and o.reason.startswith("atr_stop")
        assert o.signal_score == 1.0


def test_run_scan_disabled_no_exit(test_db, monkeypatch):
    """Master switch off + no strategy SELL → no fills, position remains."""
    from paper_trading import engine

    settings.set("atr_stops_enabled", False)
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_min_holding_minutes", 0)

    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="AAPL",
                shares=10.0,
                avg_cost=100.0,
                opened_at=utcnow_naive() - timedelta(days=2),
                high_water_mark=100.0,
            )
        )

    df = _make_ohlcv([100.0] * 60)
    monkeypatch.setattr(
        engine,
        "get_strategy_fn",
        lambda _: lambda *a, **kw: [],
    )

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 50.0},  # huge drop, would trigger if enabled
        history_provider=lambda _t: df,
    )
    assert result is not None
    assert result.filled == 0
    with session_scope() as s:
        pos = (
            s.query(PaperPosition)
            .filter(PaperPosition.account_id == a.id)
            .filter(PaperPosition.ticker == "AAPL")
            .first()
        )
        assert pos is not None
        assert pos.shares == 10.0


def test_run_scan_seeds_hwm_for_legacy_position(test_db, monkeypatch):
    """A legacy position with HWM=NULL gets it seeded on first scan."""
    from paper_trading import engine

    settings.set("atr_stops_enabled", False)  # gate doesn't matter here
    settings.set("paper_enforce_market_hours", False)

    a = create_account(name="A", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="LEGACY",
                shares=3.0,
                avg_cost=200.0,
                high_water_mark=None,
            )
        )
    df = _make_ohlcv([100.0] * 60)
    monkeypatch.setattr(
        engine,
        "get_strategy_fn",
        lambda _: lambda *a, **kw: [],
    )

    engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"LEGACY": 250.0},
        history_provider=lambda _t: df,
    )

    with session_scope() as s:
        pos = (
            s.query(PaperPosition)
            .filter(PaperPosition.account_id == a.id)
            .filter(PaperPosition.ticker == "LEGACY")
            .first()
        )
        assert pos is not None
        assert pos.high_water_mark == 250.0
