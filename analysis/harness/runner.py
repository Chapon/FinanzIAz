"""
HarnessRunner: orchestrates backtest execution with different feature configurations.

IMPORTANT: To run an ablation we need to flip toggles in the global settings
manager (single source of truth). To avoid polluting the user's production
settings.json, ``run_suite`` snapshots every toggle the suite will touch
before mutating it, and restores the originals in a ``finally`` block — even
if a backtest raises. ``run_experiment`` on its own does NOT restore; call
``snapshot_toggles`` / ``restore_toggles`` explicitly if you use it directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
import pandas as pd

from analysis.portfolio_backtest import portfolio_backtest, AllocationMode
from config.settings_manager import _SettingsManager
from .config import ExperimentConfig
from .metrics import compute_metrics, ComputedMetrics


# Settings keys the harness writes to. Keep in sync with ExperimentConfig.as_settings_dict().
_HARNESS_TOGGLE_KEYS = (
    "hmm_enabled",
    "stacking_enabled",
    "xgb_signal_enabled",
    "correlation_gate_enabled",
    "vol_overlay_enabled",
)


class HarnessRunner:
    """
    Runs experiments with different feature configurations.

    Orchestrates:
    1. Load historical data
    2. For each ExperimentConfig: set features -> run backtest -> compute metrics
    3. Save results to JSON + CSV index
    4. Validate fidelity (31d baseline +/- 2%) and structure (2y plausibility)
    """

    def __init__(
        self,
        tickers: list[str],
        data: Optional[dict[str, pd.DataFrame]] = None,
        period: str = "2y",
        initial_capital: float = 50_000.0,
        commission: float = 0.001,
        slippage: float = 0.0005,
        warmup: int = 50,
        step: int = 5,
        verbose: bool = False,
    ):
        self.data = data
        self.tickers = tickers
        self.period = period
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.warmup = warmup
        self.step = step
        self.verbose = verbose
        self.settings_manager = _SettingsManager()
        self.results: dict[str, tuple[ComputedMetrics, Any, ExperimentConfig]] = {}

    # ── Settings snapshot / restore ──────────────────────────────────────────

    def snapshot_toggles(self) -> dict[str, Any]:
        """Capture current values of every harness toggle so we can restore them."""
        return {k: self.settings_manager.get(k) for k in _HARNESS_TOGGLE_KEYS}

    def restore_toggles(self, snapshot: dict[str, Any]) -> None:
        """Write the snapshotted values back to the settings store."""
        for k, v in snapshot.items():
            self.settings_manager.set(k, v)

    # ── Experiment orchestration ─────────────────────────────────────────────

    def run_experiment(
        self,
        config: ExperimentConfig,
        signal_fn,
    ) -> ComputedMetrics:
        """
        Run a single experiment with the given configuration.

        WARNING: this mutates global settings. Use ``run_suite`` (or wrap your
        own calls in ``snapshot_toggles`` / ``restore_toggles``) to avoid
        leaving production settings in an unintended state.
        """
        # Apply feature toggles to settings
        settings_dict = config.as_settings_dict()
        for key, value in settings_dict.items():
            success = self.settings_manager.set(key, value)
            if not success:
                raise ValueError(f"Failed to set setting {key}={value}")

        if self.verbose:
            print(f"Running experiment: {config.name}")
            print(f"  Config: {config.as_settings_dict()}")

        backtest_kwargs = {
            "signal_fn": signal_fn,
            "tickers": self.tickers,
            "allocation_mode": AllocationMode.EQUAL_WEIGHT,
            "max_positions": len(self.tickers),
            "initial_capital": self.initial_capital,
            "commission": self.commission,
            "slippage": self.slippage,
            "warmup": self.warmup,
            "step": self.step,
            "forced_exit_fn": None,
            "verbose": self.verbose,
        }
        if self.data is not None:
            backtest_kwargs["data"] = self.data
        else:
            backtest_kwargs["period"] = self.period

        backtest_result = portfolio_backtest(**backtest_kwargs)

        if backtest_result is None:
            raise RuntimeError(f"Backtest failed for experiment {config.name}")

        metrics = compute_metrics(backtest_result, self.initial_capital)
        self.results[config.name] = (metrics, backtest_result, config)

        if self.verbose:
            print(f"  Metrics: {metrics.to_dict()}")

        return metrics

    def run_suite(
        self,
        signal_fn,
        experiments: list[ExperimentConfig],
        output_dir: Optional[Path] = None,
    ) -> dict[str, ComputedMetrics]:
        """
        Run a suite of experiments. Settings are snapshotted before the first
        experiment and restored after the last (even on exceptions), so the
        user's production settings.json is left exactly as it was found.
        """
        snapshot = self.snapshot_toggles()
        if self.verbose:
            print(f"Settings snapshot taken: {snapshot}")

        results_dict: dict[str, ComputedMetrics] = {}
        try:
            for config in experiments:
                metrics = self.run_experiment(config, signal_fn)
                results_dict[config.name] = metrics

            if output_dir:
                self.save_results(output_dir)
        finally:
            self.restore_toggles(snapshot)
            if self.verbose:
                print(f"Settings restored to original snapshot")

        return results_dict

    # ── Output ───────────────────────────────────────────────────────────────

    def save_results(self, output_dir: Path):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        results_dir = output_dir / "results"
        results_dir.mkdir(exist_ok=True)

        for exp_name, (metrics, backtest_result, config) in self.results.items():
            result_file = results_dir / f"{exp_name}.json"
            result_dict = {
                "config": config.to_dict(),
                "metrics": metrics.to_dict(),
                "n_trades": len(backtest_result.trades) if backtest_result.trades else 0,
            }
            with open(result_file, "w") as f:
                json.dump(result_dict, f, indent=2, default=str)

        csv_file = output_dir / "index.csv"
        rows = []
        for exp_name, (metrics, backtest_result, config) in self.results.items():
            rows.append({
                "name": config.name,
                "period_return": metrics.period_return,
                "cagr": metrics.cagr,
                "sharpe_annual": metrics.sharpe_annual,
                "max_drawdown": metrics.max_drawdown,
                "turnover": metrics.turnover,
                "win_rate": metrics.win_rate,
                "profit_factor": metrics.profit_factor,
                "expectancy": metrics.expectancy,
                "n_trades": len(backtest_result.trades) if backtest_result.trades else 0,
            })

        df_index = pd.DataFrame(rows)
        df_index.to_csv(csv_file, index=False)

        if self.verbose:
            print(f"Results saved to {output_dir}")
            print(f"  JSON results in {results_dir}/")
            print(f"  CSV index at {csv_file}")

    # ── Validation ───────────────────────────────────────────────────────────

    def validate_fidelity(
        self,
        baseline_metrics: ComputedMetrics,
        tolerance: float = 0.02,
    ) -> bool:
        """Baseline experiment must match frozen baseline within tolerance."""
        if "baseline" not in self.results:
            raise ValueError("Baseline experiment not in results. Run baseline first.")

        measured, _, _ = self.results["baseline"]

        pct_diff = abs(measured.period_return - baseline_metrics.period_return) / abs(baseline_metrics.period_return)
        if pct_diff > tolerance:
            print(f"FAIL Fidelity: period_return diff {pct_diff:.2%}")
            return False

        abs_sharpe_diff = abs(measured.sharpe_annual - baseline_metrics.sharpe_annual)
        if abs_sharpe_diff > 0.5:
            print(f"FAIL Fidelity: Sharpe diff {abs_sharpe_diff:.4f}")
            return False

        print("OK Fidelity check passed")
        return True

    def validate_structure(self) -> bool:
        """Plausibility checks on every experiment's metrics."""
        all_pass = True
        for exp_name, (metrics, _, _) in self.results.items():
            checks = [
                (-50 <= metrics.period_return <= 100, f"period_return {metrics.period_return}%"),
                (-2 <= metrics.sharpe_annual <= 5, f"sharpe_annual {metrics.sharpe_annual}"),
                (20 <= metrics.win_rate <= 80, f"win_rate {metrics.win_rate}%"),
                (0 <= metrics.max_drawdown <= 50, f"max_drawdown {metrics.max_drawdown}%"),
            ]
            for check, label in checks:
                if not check:
                    print(f"FAIL Structural {exp_name}: {label}")
                    all_pass = False

        if all_pass:
            print("OK Structural checks passed for all experiments")
        return all_pass
