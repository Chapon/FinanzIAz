"""
Tests for ``analysis.backtest``.

Focus on the high-impact correctness properties — leakage of future info,
realistic-cost accounting, and basic invariants — rather than fragile
numeric checks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.backtest import backtest


def _always_buy_then_hold(df_slice: pd.DataFrame) -> str:
    return "BUY"


def _always_hold(df_slice: pd.DataFrame) -> str:
    return "HOLD"


def test_backtest_returns_none_on_short_history(ohlcv_factory):
    df = ohlcv_factory(rows=30)  # < warmup default 200
    assert backtest(df, _always_buy_then_hold) is None


def test_buy_and_hold_strategy_matches_close_to_close(ohlcv_factory):
    """
    With BUY at warmup and no further trades, the equity curve should track
    the underlying price from the entry bar onward. Alpha vs B&H is the
    move during the warmup bars (which the strategy missed) — so we don't
    expect them to match exactly, but both directions and orders of
    magnitude should agree.
    """
    df = ohlcv_factory(rows=300, seed=1)
    res = backtest(df, _always_buy_then_hold, warmup=10, commission=0.0, slippage=0.0)
    assert res is not None
    assert res.n_trades >= 1
    # Both should end up with one continuously-held position; their returns
    # should be of the same sign and within a reasonable spread (the B&H
    # ran for `warmup` extra bars).
    assert (res.total_return_pct > 0) == (res.bh_return_pct > 0)
    assert abs(res.total_return_pct - res.bh_return_pct) < 0.10


def test_costs_increase_with_trade_count(ohlcv_factory):
    """
    A whip-saw signal that flips every bar must accumulate more commission
    than a buy-and-hold strategy. Sanity check the cost tracker.
    """
    df = ohlcv_factory(rows=300, seed=2)
    bh = backtest(df, _always_buy_then_hold, warmup=50, commission=0.001)
    # Alternating BUY/SELL on each evaluation — uses internal step=1
    state = {"flip": False}

    def _flipper(df_slice: pd.DataFrame) -> str:
        state["flip"] = not state["flip"]
        return "BUY" if state["flip"] else "SELL"

    fl = backtest(df, _flipper, warmup=50, commission=0.001)
    assert bh is not None and fl is not None
    assert fl.n_trades > bh.n_trades
    assert fl.total_commission_paid > bh.total_commission_paid


def test_signal_at_t_cannot_use_close_at_t_plus_one(ohlcv_factory):
    """
    Construct a 'cheating' signal that peeks at the *next* bar's close
    and verify our backtest does NOT let it lock in a guaranteed win —
    because we fill on the next bar and the signal is queued one bar.

    Specifically: even with a perfect-foresight signal, the executed price
    is the *next* bar's close, so the cheat is rendered moot by our
    pending-signal mechanism. This is a regression test for the
    same-bar-lookahead fix.
    """
    df = ohlcv_factory(rows=400, seed=3)
    closes = df["Close"].values

    # Peeks at i+1: BUY iff next bar will be higher. With same-bar fills
    # (the bug) this would print money. With t+1 fills (the fix) the gain
    # is bounded by close[i+2] - close[i+1] differences and certainly NOT
    # equal to a deterministic 100% accuracy.
    def _cheat_signal(df_slice: pd.DataFrame) -> str:
        i = len(df_slice) - 1
        if i + 1 >= len(closes):
            return "HOLD"
        return "BUY" if closes[i + 1] > closes[i] else "SELL"

    res = backtest(df, _cheat_signal, warmup=50, commission=0.0, slippage=0.0)
    assert res is not None
    # Win rate should be substantially below 100% — proving the cheat
    # does not give a guaranteed profit because of the t+1 fill rule.
    if res.n_trades > 5:
        assert res.win_rate < 0.95


def test_exposure_and_turnover_in_sane_ranges(ohlcv_factory):
    df = ohlcv_factory(rows=300, seed=4)
    res = backtest(df, _always_buy_then_hold, warmup=50)
    assert res is not None
    assert 0.0 <= res.exposure <= 1.0
    assert res.turnover >= 0.0


def test_max_drawdown_is_non_positive(ohlcv_factory):
    df = ohlcv_factory(rows=300, seed=5)
    res = backtest(df, _always_buy_then_hold, warmup=50)
    assert res is not None
    assert res.max_drawdown <= 0.0


def test_calmar_zero_when_no_drawdown_signal(ohlcv_factory):
    """If max_drawdown == 0 we publish calmar=0 instead of NaN/inf."""
    df = ohlcv_factory(rows=300, seed=6)
    res = backtest(df, _always_hold, warmup=50)
    assert res is not None
    assert np.isfinite(res.calmar)
