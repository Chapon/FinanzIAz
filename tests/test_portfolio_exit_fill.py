"""Test del fill realista (exit_fill_prices) en _execute_rebalance del backtest."""
from __future__ import annotations

import pandas as pd
import pytest

from analysis.portfolio_backtest import _PositionState, _execute_rebalance


def _make_position(shares=100.0, avg_cost=100.0):
    return _PositionState(
        shares=shares, avg_cost=avg_cost,
        entry_date=pd.Timestamp("2026-05-01"), entry_reason="BUY signal",
    )


def _close_position(*, exit_fill_prices):
    """Cierra una posición (target 0) y devuelve el trade registrado."""
    positions = {"AAA": _make_position()}
    trades: list = []
    date = pd.Timestamp("2026-05-21")
    # close del día = 85; el stop modeló fill en 90 (touch del nivel).
    _execute_rebalance(
        date=date,
        prices={"AAA": 85.0},
        positions=positions,
        target_dollars={"AAA": 0.0},  # full close
        cash=0.0,
        commission=0.0,
        slippage=0.0,
        reason="atr_stop",
        trades_log=trades,
        forced_exit_reasons={"AAA": "atr_stop @ ..."},
        exit_fill_prices=exit_fill_prices,
    )
    assert len(trades) == 1
    return trades[0]


def test_exit_fill_override_used_for_atr_exit():
    # Con override (fill modelado 90) el SELL ejecuta a 90, no al close 85.
    tr = _close_position(exit_fill_prices={"AAA": 90.0})
    assert tr.exit_price == pytest.approx(90.0)
    # P&L = (90 - 100) * 100 = -1000 (no el peor -1500 del close).
    assert tr.pnl == pytest.approx(-1000.0)


def test_without_override_fills_at_close():
    # Sin override (default), comportamiento histórico: fill al close 85.
    tr = _close_position(exit_fill_prices=None)
    assert tr.exit_price == pytest.approx(85.0)
    assert tr.pnl == pytest.approx(-1500.0)


def test_override_respects_slippage():
    positions = {"AAA": _make_position()}
    trades: list = []
    _execute_rebalance(
        date=pd.Timestamp("2026-05-21"),
        prices={"AAA": 85.0},
        positions=positions,
        target_dollars={"AAA": 0.0},
        cash=0.0,
        commission=0.0,
        slippage=0.01,  # 1%
        reason="atr_stop",
        trades_log=trades,
        forced_exit_reasons={"AAA": "atr_stop"},
        exit_fill_prices={"AAA": 90.0},
    )
    # fill = 90 * (1 - 0.01) = 89.1
    assert trades[0].exit_price == pytest.approx(89.1)
