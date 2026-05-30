"""
Metrics computation for harness runs.

Computes 8 core metrics from backtest results:
1. period_return (%)
2. cagr (%)
3. sharpe_annual
4. max_drawdown (%)
5. turnover (round trips per year)
6. win_rate (%)
7. profit_factor
8. expectancy ($ per trade)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ComputedMetrics:
    """8 core metrics from a backtest run."""
    period_return: float  # %
    cagr: float  # % annualized
    sharpe_annual: float  # dimensionless
    max_drawdown: float  # %
    turnover: float  # round trips per year
    win_rate: float  # %
    profit_factor: float  # dimensionless (gross_profit / gross_loss)
    expectancy: float  # $ per trade
    holding_days_avg: Optional[float] = None  # avg days per trade

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "period_return": round(self.period_return, 4),
            "cagr": round(self.cagr, 4),
            "sharpe_annual": round(self.sharpe_annual, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "turnover": round(self.turnover, 4),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "expectancy": round(self.expectancy, 2),
            "holding_days_avg": round(self.holding_days_avg, 1) if self.holding_days_avg else None,
        }


def compute_metrics(
    backtest_result,
    initial_capital: float,
    trading_days_per_year: int = 252,
) -> ComputedMetrics:
    """
    Compute 8 core metrics from portfolio_backtest result.

    Args:
        backtest_result: Result object from portfolio_backtest() with .equity_curve, .trades, etc.
        initial_capital: Starting capital (for return computation)
        trading_days_per_year: Days to use for annualization (default 252)

    Returns:
        ComputedMetrics dataclass with 8 metrics filled in.
    """
    if backtest_result is None or not hasattr(backtest_result, 'equity_curve'):
        raise ValueError("Invalid backtest_result: missing equity_curve")

    # Normalize equity to a plain numpy array. PortfolioBacktestResult ships a
    # datetime-indexed pd.Series, mocks ship a numpy array — under pandas 2.x
    # Series[-1] with a datetime index is a KeyError (not just a deprecation
    # warning as in 1.x). Coerce once here so the rest of the function can
    # use positional access uniformly.
    equity_raw = backtest_result.equity_curve
    if hasattr(equity_raw, "to_numpy"):
        equity = np.asarray(equity_raw.to_numpy(), dtype=float)
    else:
        equity = np.asarray(equity_raw, dtype=float)
    # Drop NaN/inf that can sneak in when the backtest force-fills warmup bars
    equity = equity[np.isfinite(equity)]
    trades = backtest_result.trades

    # 1. Period Return (%)
    final_equity = float(equity[-1]) if len(equity) > 0 else initial_capital
    period_return = 100.0 * (final_equity - initial_capital) / initial_capital

    # 2. CAGR (%) — only if we have >=1 year of data
    n_days = len(equity)
    if n_days >= trading_days_per_year:
        years = n_days / trading_days_per_year
        cagr = 100.0 * (pow(final_equity / initial_capital, 1.0 / years) - 1.0)
    else:
        cagr = period_return  # fallback to period return for short periods

    # 3. Sharpe Annual — compute daily returns, then annualize
    if len(equity) > 1:
        daily_returns = np.diff(equity) / equity[:-1]
        std = float(np.std(daily_returns))
        daily_sharpe = float(np.mean(daily_returns)) / std if std > 0 else 0.0
        sharpe_annual = daily_sharpe * np.sqrt(trading_days_per_year)
    else:
        sharpe_annual = 0.0

    # 4. Max Drawdown (%)
    max_dd = 0.0
    if len(equity) > 0:
        running_max = np.maximum.accumulate(equity)
        drawdown = (equity - running_max) / running_max
        max_dd = 100.0 * float(np.min(drawdown)) if len(drawdown) > 0 else 0.0

    # 5. Turnover — annualised round-trip count proxy.
    # PortfolioBacktestResult doesn't carry dollar-volume turnover; use round trips
    # per year (n_trades / years). Comparable across ablations at the same horizon.
    # Mocks that inject a `turnover` attribute take precedence.
    if hasattr(backtest_result, 'turnover'):
        turnover = float(backtest_result.turnover)
    else:
        years = (n_days / trading_days_per_year) if n_days > 0 else 0.0
        turnover = (len(trades) / years) if years > 0 else float(len(trades))

    # 6. Win Rate (%)
    if len(trades) > 0:
        wins = sum(1 for t in trades if hasattr(t, 'pnl') and t.pnl > 0)
        win_rate = 100.0 * wins / len(trades)
    else:
        win_rate = 0.0

    # 7. Profit Factor (gross profit / gross loss)
    gross_profit = 0.0
    gross_loss = 0.0
    for t in trades:
        if hasattr(t, 'pnl'):
            if t.pnl > 0:
                gross_profit += t.pnl
            else:
                gross_loss += abs(t.pnl)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    # 8. Expectancy ($ per trade)
    total_pnl = sum(t.pnl for t in trades if hasattr(t, 'pnl'))
    expectancy = total_pnl / len(trades) if len(trades) > 0 else 0.0

    # Bonus: Holding Days Average
    holding_days_avg = None
    if len(trades) > 0:
        holding_days = []
        for t in trades:
            if hasattr(t, 'exit_date') and hasattr(t, 'entry_date'):
                holding = (t.exit_date - t.entry_date).days
                if holding >= 0:
                    holding_days.append(holding)
        if holding_days:
            holding_days_avg = float(np.mean(holding_days))

    return ComputedMetrics(
        period_return=period_return,
        cagr=cagr,
        sharpe_annual=sharpe_annual,
        max_drawdown=max_dd,
        turnover=turnover,
        win_rate=win_rate,
        profit_factor=profit_factor,
        expectancy=expectancy,
        holding_days_avg=holding_days_avg,
    )
