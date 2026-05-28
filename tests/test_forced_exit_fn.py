"""
Tests for portfolio_backtest forced_exit_fn hook (Sprint 1.4).

Verifies that:
1. forced_exit_fn is called for each open position
2. When forced_exit_fn returns True, the position is closed
3. The exit reason from forced_exit_fn is recorded in trades
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_backtest import (
    AllocationMode,
    portfolio_backtest,
    _PositionState,
)


def _series(daily_vol: float, rows: int = 300, seed: int = 0, start: float = 100.0) -> pd.DataFrame:
    """A Close-only OHLCV frame whose realised vol scales with ``daily_vol``."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, daily_vol, rows)
    close = start * np.exp(np.cumsum(rets))
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="B")
    return pd.DataFrame({"Close": close}, index=idx)


def _always_buy(df_slice: pd.DataFrame) -> str:
    """Constant BUY signal."""
    return "BUY"


def test_forced_exit_fn_called_for_open_positions():
    """Verify that forced_exit_fn is invoked for each open position."""
    data = {
        "AAPL": _series(0.015, rows=300, seed=1),
        "MSFT": _series(0.012, rows=300, seed=2),
    }

    call_log = []

    def _hook(ticker: str, df_slice: pd.DataFrame, pos_state: _PositionState) -> tuple[bool, str]:
        call_log.append((ticker, pos_state.is_open))
        return False, "logged"

    result = portfolio_backtest(
        _always_buy,
        tickers=["AAPL", "MSFT"],
        data=data,
        allocation_mode=AllocationMode.EQUAL_WEIGHT,
        max_positions=2,
        initial_capital=50_000.0,
        commission=0.001,
        slippage=0.0005,
        warmup=50,
        step=5,
        forced_exit_fn=_hook,
        verbose=False,
    )

    assert result is not None
    assert len(call_log) > 0
    assert any(is_open for _, is_open in call_log)


def test_forced_exit_fn_closes_position():
    """Returning True from forced_exit_fn must close an open position."""
    data = {
        "AAPL": _series(0.015, rows=300, seed=3),
    }

    state = {"fired": False}

    def _hook(ticker: str, df_slice: pd.DataFrame, pos_state: _PositionState) -> tuple[bool, str]:
        # Force exit on the very first time we see an open position.
        if pos_state.is_open and not state["fired"]:
            state["fired"] = True
            return True, "test_forced_close"
        return False, "ok"

    result_with_hook = portfolio_backtest(
        _always_buy,
        tickers=["AAPL"],
        data=data,
        allocation_mode=AllocationMode.EQUAL_WEIGHT,
        max_positions=1,
        initial_capital=50_000.0,
        commission=0.001,
        slippage=0.0005,
        warmup=50,
        step=5,
        forced_exit_fn=_hook,
        verbose=False,
    )

    assert result_with_hook is not None
    assert state["fired"], "Hook should have fired at least once"
    # The forced exit should have produced at least one round trip with the test reason
    matching = [t for t in result_with_hook.trades if t.exit_reason == "test_forced_close"]
    assert len(matching) >= 1, (
        f"Expected exit_reason=='test_forced_close', got {[t.exit_reason for t in result_with_hook.trades]}"
    )


def test_forced_exit_reason_recorded():
    """Custom exit_reason from forced_exit_fn must end up on PortfolioTrade.exit_reason."""
    data = {
        "AAPL": _series(0.015, rows=300, seed=4),
    }

    def _hook(ticker: str, df_slice: pd.DataFrame, pos_state: _PositionState) -> tuple[bool, str]:
        # Exit after holding for 50 days
        if pos_state.entry_date is not None:
            current = df_slice.index[-1]
            holding_days = (current - pos_state.entry_date).days
            if holding_days >= 50:
                return True, f"forced_exit @ {holding_days}d"
        return False, "not ready"

    result = portfolio_backtest(
        _always_buy,
        tickers=["AAPL"],
        data=data,
        allocation_mode=AllocationMode.EQUAL_WEIGHT,
        max_positions=1,
        initial_capital=50_000.0,
        commission=0.001,
        slippage=0.0005,
        warmup=50,
        step=5,
        forced_exit_fn=_hook,
        verbose=False,
    )

    assert result is not None
    assert result.n_trades >= 1, "Backtest should produce at least one round-trip"

    # At least one trade must carry the custom 'forced_exit' reason — anything
    # weaker is just re-asserting that trades exist.
    forced_exits = [t for t in result.trades if "forced_exit" in t.exit_reason]
    assert len(forced_exits) > 0, (
        f"Expected at least one trade with 'forced_exit' in exit_reason, got "
        f"reasons: {[t.exit_reason for t in result.trades]}"
    )

    for trade in result.trades:
        assert isinstance(trade.exit_reason, str)
        assert len(trade.exit_reason) > 0


def test_forced_exit_fn_exception_handling():
    """Exceptions raised inside forced_exit_fn must be swallowed (logged), not propagated."""
    data = {
        "AAPL": _series(0.015, rows=300, seed=5),
    }

    call_count = [0]

    def _buggy_hook(ticker: str, df_slice: pd.DataFrame, pos_state: _PositionState) -> tuple[bool, str]:
        call_count[0] += 1
        if call_count[0] == 5:
            raise ValueError("Hook error for testing")
        return False, "ok"

    result = portfolio_backtest(
        _always_buy,
        tickers=["AAPL"],
        data=data,
        allocation_mode=AllocationMode.EQUAL_WEIGHT,
        max_positions=1,
        initial_capital=50_000.0,
        commission=0.001,
        slippage=0.0005,
        warmup=50,
        step=5,
        forced_exit_fn=_buggy_hook,
        verbose=True,
    )

    assert result is not None
    assert call_count[0] >= 5, "Hook should have been called multiple times before and after raising"
