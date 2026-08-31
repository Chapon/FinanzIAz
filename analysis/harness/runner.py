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
from typing import Any, Protocol

import pandas as pd

from analysis.portfolio_backtest import AllocationMode, portfolio_backtest
from config.settings_manager import settings as _settings_singleton
from paper_trading.gates import (
    compute_vol_overlay as _gate_compute_vol_overlay,
)


class VolOverlayPolicy(Protocol):
    """Lo único que el runner le pide a la política de overlay inyectada.

    Reemplaza a ``RegimeFeaturePolicy``, un nombre que la anotación citaba y que
    **no existe en el proyecto** — nunca falló porque `from __future__ import
    annotations` no la evalúa, así que era documentación que mentía. Misma familia
    que el `list[_Trade]` de `tests/test_harness.py`.
    """

    def effective(self, regime: str) -> dict: ...


from .config import ExperimentConfig
from .metrics import ComputedMetrics, compute_metrics

# Settings keys the harness writes to. Keep in sync with ExperimentConfig.as_settings_dict().
# ``correlation_gate_enabled`` was removed in Sprint 3 (see docs/sprint2_kill_criteria.md).
# ``cross_sectional_enabled`` added in Sprint 4 / T05 (2026-06-03).
_HARNESS_TOGGLE_KEYS = (
    "hmm_enabled",
    "stacking_enabled",
    "xgb_signal_enabled",
    "vol_overlay_enabled",
    "cross_sectional_enabled",
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
        data: dict[str, pd.DataFrame] | None = None,
        period: str = "2y",
        initial_capital: float = 50_000.0,
        commission: float = 0.001,
        slippage: float = 0.0005,
        warmup: int = 50,
        step: int = 5,
        max_positions: int | None = None,
        verbose: bool = False,
        regime_series: pd.Series | None = None,
        vol_overlay_policy: VolOverlayPolicy | None = None,
    ):
        self.data = data
        self.tickers = tickers
        self.period = period
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.warmup = warmup
        self.step = step
        self.max_positions = max_positions
        self.verbose = verbose
        self.regime_series = regime_series
        self.vol_overlay_policy = vol_overlay_policy
        self.settings_manager = _settings_singleton
        self.results: dict[str, tuple[ComputedMetrics, Any, ExperimentConfig]] = {}

    def snapshot_toggles(self) -> dict[str, Any]:
        return {k: self.settings_manager.get(k) for k in _HARNESS_TOGGLE_KEYS}

    def restore_toggles(self, snapshot: dict[str, Any]) -> None:
        for k, v in snapshot.items():
            self.settings_manager.set(k, v)

    def run_experiment(
        self,
        config: ExperimentConfig,
        signal_fn,
    ) -> ComputedMetrics:
        settings_dict = config.as_settings_dict()
        for key, value in settings_dict.items():
            success = self.settings_manager.set(key, value)
            if not success:
                raise ValueError(f"Failed to set setting {key}={value}")

        if self.verbose:
            print(f"Running experiment: {config.name}")
            print(f"  Config: {config.as_settings_dict()}")

        vol_overlay_fn = self._build_vol_overlay()

        backtest_kwargs = {
            "signal_fn": signal_fn,
            "tickers": self.tickers,
            "allocation_mode": AllocationMode.EQUAL_WEIGHT,
            "max_positions": self.max_positions or len(self.tickers),
            "initial_capital": self.initial_capital,
            "commission": self.commission,
            "slippage": self.slippage,
            "warmup": self.warmup,
            "step": self.step,
            "forced_exit_fn": None,
            "vol_overlay_fn": vol_overlay_fn,
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

    def _build_vol_overlay(self):
        # Locales y no `self.…` dentro del closure: el predicado es EL MISMO, pero
        # así la comprobación de None se ve desde adentro (mypy no puede arrastrar
        # una narrowing a través de un bool intermedio).
        series = self.regime_series
        policy = self.vol_overlay_policy

        def overlay_fn(target_weights, returns_by_ticker):
            if series is not None and policy is not None:
                current_ts = None
                for s in returns_by_ticker.values():
                    if s is not None and not s.empty and (current_ts is None or s.index.max() > current_ts):
                        current_ts = s.index.max()
                if current_ts is None:
                    return 1.0
                matches = series.index <= current_ts
                if not matches.any():
                    from analysis.regime_detector import REGIME_WARMUP

                    regime_at_bar = REGIME_WARMUP
                else:
                    regime_at_bar = str(series.loc[matches].iloc[-1])
                effective = policy.effective(regime_at_bar)
                if not bool(effective.get("vol_overlay_enabled", True)):
                    return 1.0
            else:
                if not bool(self.settings_manager.get("vol_overlay_enabled", True)):
                    return 1.0

            target = float(self.settings_manager.get("vol_target_portfolio_annual", 0.20))
            if target <= 0 or not target_weights:
                return 1.0

            usable = {
                t: returns_by_ticker[t]
                for t in target_weights
                if t in returns_by_ticker
                and returns_by_ticker[t] is not None
                and not returns_by_ticker[t].empty
            }
            if not usable:
                return 1.0
            ret_df = pd.DataFrame(usable).dropna(how="all")
            if ret_df.empty:
                return 1.0

            result = _gate_compute_vol_overlay(target_weights, ret_df, target)
            f = float(result.factor)
            if not (f > 0):
                return 1.0
            return f

        return overlay_fn

    def run_suite(
        self,
        signal_fn,
        experiments: list[ExperimentConfig],
        output_dir: Path | None = None,
    ) -> dict[str, ComputedMetrics]:
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
                print("Settings restored to original snapshot")

        return results_dict

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

            equity = getattr(backtest_result, "equity_curve", None)
            if equity is not None and len(equity) > 0:
                eq_file = results_dir / f"{exp_name}.equity.csv"
                eq_df = pd.DataFrame({"equity": equity.values}, index=equity.index)
                eq_df.index.name = "date"
                eq_df.to_csv(eq_file)

            bh_equity = getattr(backtest_result, "bh_equity_curve", None)
            if bh_equity is not None and len(bh_equity) > 0:
                bh_file = results_dir / f"{exp_name}.bh_equity.csv"
                bh_df = pd.DataFrame({"bh_equity": bh_equity.values}, index=bh_equity.index)
                bh_df.index.name = "date"
                bh_df.to_csv(bh_file)

        csv_file = output_dir / "index.csv"
        rows = []
        for _exp_name, (metrics, backtest_result, config) in self.results.items():
            rows.append(
                {
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
                }
            )

        df_index = pd.DataFrame(rows)
        df_index.to_csv(csv_file, index=False)

        if self.verbose:
            print(f"Results saved to {output_dir}")
            print(f"  JSON results in {results_dir}/")
            print(f"  CSV index at {csv_file}")

    def validate_fidelity(
        self,
        baseline_metrics: ComputedMetrics,
        tolerance: float = 0.02,
    ) -> bool | None:
        if "baseline" not in self.results:
            print("SKIP Fidelity: no baseline experiment in this suite")
            return None

        measured, _, _ = self.results["baseline"]

        pct_diff = abs(measured.period_return - baseline_metrics.period_return) / abs(
            baseline_metrics.period_return
        )
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
        all_pass = True
        for exp_name, (metrics, _, _) in self.results.items():
            checks = [
                (-50 <= metrics.period_return <= 100, f"period_return {metrics.period_return}%"),
                (-2 <= metrics.sharpe_annual <= 5, f"sharpe_annual {metrics.sharpe_annual}"),
                (20 <= metrics.win_rate <= 80, f"win_rate {metrics.win_rate}%"),
                (
                    metrics.max_drawdown >= 0 or metrics.max_drawdown <= 50,
                    f"max_drawdown {metrics.max_drawdown}%",
                ),
            ]
            for check, label in checks:
                if not check:
                    print(f"FAIL Structural {exp_name}: {label}")
                    all_pass = False

        if all_pass:
            print("OK Structural checks passed for all experiments")
        return all_pass
