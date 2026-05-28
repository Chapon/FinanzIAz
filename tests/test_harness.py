"""
Tests for T-harness infrastructure.

Covers:
- ExperimentConfig creation and serialization
- HarnessRunner initialization
- Metrics computation from backtest results
- Fidelity and structural validation
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.harness import ExperimentConfig, HarnessRunner
from analysis.harness.metrics import ComputedMetrics, compute_metrics
from analysis.portfolio_backtest import PortfolioTrade


def _mock_trade(
    ticker: str = "AAPL",
    entry_price: float = 100.0,
    exit_price: float = 101.0,
    shares: int = 10,
    pnl: float = 10.0,
    entry_date=None,
    exit_date=None,
) -> PortfolioTrade:
    """Create a mock trade for testing."""
    if entry_date is None:
        entry_date = pd.Timestamp("2026-01-01")
    if exit_date is None:
        exit_date = pd.Timestamp("2026-01-05")

    cost = entry_price * shares
    return_pct = (pnl / cost) if cost > 0 else 0.0
    return PortfolioTrade(
        ticker=ticker,
        entry_date=entry_date,
        exit_date=exit_date,
        entry_price=entry_price,
        exit_price=exit_price,
        shares=float(shares),
        return_pct=float(return_pct),
        pnl=float(pnl),
        holding_days=int((exit_date - entry_date).days),
        entry_reason="BUY",
        exit_reason="SELL",
    )


class MockBacktestResult:
    """Mock backtest result for testing."""
    def __init__(
        self,
        equity_curve: list[float],
        trades: list[_Trade],
        turnover: float = 0.0,
    ):
        self.equity_curve = np.array(equity_curve)
        self.trades = trades
        self.turnover = turnover


def test_experiment_config_baseline():
    """Verify baseline config has all features enabled."""
    cfg = ExperimentConfig.baseline()
    assert cfg.name == "baseline"
    assert cfg.hmm_enabled is True
    assert cfg.stacking_enabled is True
    assert cfg.xgb_signal_enabled is True
    assert cfg.correlation_gate_enabled is True
    assert cfg.vol_overlay_enabled is True


def test_experiment_config_ablation_variants():
    """Verify ablation variants disable one feature each."""
    variants = ExperimentConfig.ablation_variants()
    assert len(variants) == 5

    # Each variant should have exactly one feature disabled
    for variant in variants:
        enabled_count = sum([
            variant.hmm_enabled,
            variant.stacking_enabled,
            variant.xgb_signal_enabled,
            variant.correlation_gate_enabled,
            variant.vol_overlay_enabled,
        ])
        assert enabled_count == 4, f"Variant {variant.name} should have 4/5 features"


def test_experiment_config_serialization():
    """Verify ExperimentConfig can be serialized to dict."""
    cfg = ExperimentConfig(
        name="test",
        hmm_enabled=False,
        stacking_enabled=True,
        xgb_signal_enabled=False,
        correlation_gate_enabled=True,
        vol_overlay_enabled=False,
        description="Test config",
    )
    d = cfg.to_dict()
    assert d["name"] == "test"
    assert d["hmm_enabled"] is False
    assert d["description"] == "Test config"


def test_experiment_config_as_settings_dict():
    """Verify ExperimentConfig converts to settings dict correctly."""
    cfg = ExperimentConfig(
        name="test",
        hmm_enabled=False,
        stacking_enabled=True,
        xgb_signal_enabled=False,
        correlation_gate_enabled=True,
        vol_overlay_enabled=False,
    )
    settings = cfg.as_settings_dict()
    assert settings == {
        "hmm_enabled": False,
        "stacking_enabled": True,
        "xgb_signal_enabled": False,
        "correlation_gate_enabled": True,
        "vol_overlay_enabled": False,
    }


def test_computed_metrics_serialization():
    """Verify ComputedMetrics can be serialized to dict."""
    metrics = ComputedMetrics(
        period_return=4.68,
        cagr=4.68,
        sharpe_annual=2.16,
        max_drawdown=5.95,
        turnover=12.3,
        win_rate=60.0,
        profit_factor=1.38,
        expectancy=50.25,
        holding_days_avg=5.2,
    )
    d = metrics.to_dict()
    assert d["period_return"] == 4.68
    assert d["sharpe_annual"] == 2.16
    assert d["holding_days_avg"] == 5.2


def test_compute_metrics_period_return():
    """Verify period_return is computed correctly."""
    equity = np.array([50_000.0, 51_000.0, 52_340.0])  # +$2,340 = 4.68%
    backtest = MockBacktestResult(equity, [])
    metrics = compute_metrics(backtest, initial_capital=50_000.0)
    assert abs(metrics.period_return - 4.68) < 0.01


def test_compute_metrics_sharpe():
    """Verify Sharpe ratio is computed (finite, sign matches return direction)."""
    # Noisy returns around a small positive mean — Sharpe should be finite and positive.
    rng = np.random.default_rng(seed=42)
    daily_rets = rng.normal(loc=0.0005, scale=0.01, size=252)
    equity = 50_000.0 * np.cumprod(1.0 + daily_rets)
    equity = np.concatenate([[50_000.0], equity])
    backtest = MockBacktestResult(equity, [])
    metrics = compute_metrics(backtest, initial_capital=50_000.0)
    # Sharpe must be finite and roughly aligned with the positive drift
    assert np.isfinite(metrics.sharpe_annual)
    assert metrics.sharpe_annual > 0  # positive drift → positive Sharpe


def test_compute_metrics_max_drawdown():
    """Verify max drawdown is computed from running peak (not initial capital)."""
    # Peak $51k, trough $47.5k → dd = (47500-51000)/51000 = -6.862...%
    equity = np.array([50_000.0, 51_000.0, 47_500.0, 49_000.0])
    backtest = MockBacktestResult(equity, [])
    metrics = compute_metrics(backtest, initial_capital=50_000.0)
    assert abs(metrics.max_drawdown - (-6.8627)) < 0.01


def test_compute_metrics_win_rate():
    """Verify win_rate is computed from trades."""
    trades = [
        _mock_trade(pnl=100.0),  # win
        _mock_trade(pnl=-50.0),  # loss
        _mock_trade(pnl=75.0),   # win
        _mock_trade(pnl=-25.0),  # loss
        _mock_trade(pnl=200.0),  # win
    ]
    backtest = MockBacktestResult([50_000.0], trades)
    metrics = compute_metrics(backtest, initial_capital=50_000.0)
    # 3 wins out of 5 = 60%
    assert abs(metrics.win_rate - 60.0) < 0.1


def test_compute_metrics_profit_factor():
    """Verify profit_factor is computed correctly."""
    trades = [
        _mock_trade(pnl=100.0),
        _mock_trade(pnl=50.0),
        _mock_trade(pnl=-40.0),
        _mock_trade(pnl=-10.0),
    ]
    backtest = MockBacktestResult([50_000.0], trades)
    metrics = compute_metrics(backtest, initial_capital=50_000.0)
    # gross_profit = 150, gross_loss = 50 → PF = 3.0
    assert abs(metrics.profit_factor - 3.0) < 0.01


def test_compute_metrics_expectancy():
    """Verify expectancy (avg P&L per trade) is computed."""
    trades = [
        _mock_trade(pnl=100.0),
        _mock_trade(pnl=50.0),
        _mock_trade(pnl=-20.0),
    ]
    backtest = MockBacktestResult([50_000.0], trades)
    metrics = compute_metrics(backtest, initial_capital=50_000.0)
    # (100 + 50 - 20) / 3 = 43.33
    assert abs(metrics.expectancy - 43.33) < 0.1


def test_compute_metrics_holding_days_avg():
    """Verify holding_days_avg is computed."""
    entry = pd.Timestamp("2026-01-01")
    exit = pd.Timestamp("2026-01-06")  # 5 days
    trades = [
        _mock_trade(entry_date=entry, exit_date=exit, pnl=100.0),
        _mock_trade(entry_date=entry, exit_date=exit, pnl=50.0),
    ]
    backtest = MockBacktestResult([50_000.0], trades)
    metrics = compute_metrics(backtest, initial_capital=50_000.0)
    assert abs(metrics.holding_days_avg - 5.0) < 0.1


def test_harness_runner_initialization():
    """Verify HarnessRunner can be initialized."""
    data = {
        "AAPL": pd.DataFrame({"Close": [100, 101, 102]}),
        "MSFT": pd.DataFrame({"Close": [200, 201, 202]}),
    }
    runner = HarnessRunner(
        data=data,
        tickers=["AAPL", "MSFT"],
        initial_capital=50_000.0,
    )
    assert runner.initial_capital == 50_000.0
    assert len(runner.results) == 0


def test_validate_fidelity_pass():
    """Verify validate_fidelity returns True when baseline matches."""
    runner = HarnessRunner(
        data={"AAPL": pd.DataFrame({"Close": [100]})},
        tickers=["AAPL"],
    )
    baseline_metrics = ComputedMetrics(
        period_return=4.68,
        cagr=4.68,
        sharpe_annual=2.16,
        max_drawdown=5.95,
        turnover=0.0,
        win_rate=60.0,
        profit_factor=1.38,
        expectancy=0.0,
    )
    measured_metrics = ComputedMetrics(
        period_return=4.70,  # Within ±2%
        cagr=4.70,
        sharpe_annual=2.15,  # Within ±0.5 Sharpe
        max_drawdown=5.93,
        turnover=0.0,
        win_rate=60.0,
        profit_factor=1.38,
        expectancy=0.0,
    )
    backtest_result = MockBacktestResult([50_000.0], [])
    runner.results["baseline"] = (measured_metrics, backtest_result, ExperimentConfig.baseline())

    assert runner.validate_fidelity(baseline_metrics, tolerance=0.02) is True


def test_validate_fidelity_fail():
    """Verify validate_fidelity returns False when baseline diverges."""
    runner = HarnessRunner(
        data={"AAPL": pd.DataFrame({"Close": [100]})},
        tickers=["AAPL"],
    )
    baseline_metrics = ComputedMetrics(
        period_return=4.68,
        cagr=4.68,
        sharpe_annual=2.16,
        max_drawdown=5.95,
        turnover=0.0,
        win_rate=60.0,
        profit_factor=1.38,
        expectancy=0.0,
    )
    measured_metrics = ComputedMetrics(
        period_return=6.0,  # >2% deviation
        cagr=6.0,
        sharpe_annual=2.16,
        max_drawdown=5.95,
        turnover=0.0,
        win_rate=60.0,
        profit_factor=1.38,
        expectancy=0.0,
    )
    backtest_result = MockBacktestResult([50_000.0], [])
    runner.results["baseline"] = (measured_metrics, backtest_result, ExperimentConfig.baseline())

    assert runner.validate_fidelity(baseline_metrics, tolerance=0.02) is False


def test_validate_structure_pass():
    """Verify validate_structure passes with plausible metrics."""
    runner = HarnessRunner(
        data={"AAPL": pd.DataFrame({"Close": [100]})},
        tickers=["AAPL"],
    )
    metrics = ComputedMetrics(
        period_return=10.0,
        cagr=10.0,
        sharpe_annual=1.5,
        max_drawdown=15.0,
        turnover=50.0,
        win_rate=55.0,
        profit_factor=1.2,
        expectancy=100.0,
    )
    backtest_result = MockBacktestResult([50_000.0], [])
    runner.results["test"] = (metrics, backtest_result, ExperimentConfig.baseline())

    assert runner.validate_structure() is True


def test_validate_structure_fail_return_out_of_range():
    """Verify validate_structure fails with out-of-range return."""
    runner = HarnessRunner(
        data={"AAPL": pd.DataFrame({"Close": [100]})},
        tickers=["AAPL"],
    )
    metrics = ComputedMetrics(
        period_return=150.0,  # > 100%
        cagr=150.0,
        sharpe_annual=1.5,
        max_drawdown=15.0,
        turnover=50.0,
        win_rate=55.0,
        profit_factor=1.2,
        expectancy=100.0,
    )
    backtest_result = MockBacktestResult([50_000.0], [])
    runner.results["test"] = (metrics, backtest_result, ExperimentConfig.baseline())

    assert runner.validate_structure() is False
