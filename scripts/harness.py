"""
T-harness CLI: Run experiment suite with different feature configurations.

Usage:
    python3 scripts/harness.py baseline              # Run just baseline
    python3 scripts/harness.py ablations             # Run baseline + 5 ablations
    python3 scripts/harness.py all                   # Run all (baseline + ablations)

Results:
    data/harness_results/{timestamp}/
        index.csv                  # Summary of all experiments
        results/
            baseline.json          # Individual experiment results
            no_hmm.json
            ...
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from analysis.harness import ExperimentConfig, HarnessRunner
from analysis.harness.metrics import ComputedMetrics
from analysis.backtest import signal_from_indicator


def _load_baseline_metrics() -> ComputedMetrics:
    """
    Load the frozen baseline from Sprint 0.

    Baseline (2026-05-26, Sim Principal, 31 days):
    - period_return: 4.68%
    - CAGR: not applicable for 31d
    - sharpe_annual: 2.16
    - max_dd: 5.95%
    - turnover: (computed from data)
    - win_rate: 60%
    - profit_factor: 1.38
    - expectancy: (computed from data)
    """
    return ComputedMetrics(
        period_return=4.68,
        cagr=4.68,  # 31d, so no annualization
        sharpe_annual=2.16,
        max_drawdown=5.95,
        turnover=0.0,  # Not measured in Sprint 0
        win_rate=60.0,
        profit_factor=1.38,
        expectancy=0.0,  # Not measured in Sprint 0
        holding_days_avg=None,
    )


def main(
    suite: str = "all",
    period: str = "1y",
    tickers: Optional[list[str]] = None,
    output_dir: Optional[Path] = None,
    verbose: bool = True,
):
    """
    Run harness suite.

    Args:
        suite: One of "baseline", "ablations", or "all"
        period: Period for auto-loading data ("1y", "2y", etc.)
        tickers: List of tickers to backtest. If None, use default watchlist.
        output_dir: Directory to save results (default: data/harness_results/{timestamp}/)
        verbose: Verbose logging
    """
    # Default watchlist (can be expanded or customized)
    if tickers is None:
        tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "JPM"]

    print(f"Running harness with {len(tickers)} tickers over {period}...")
    print(f"Tickers: {', '.join(tickers)}")

    # Determine output directory
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = repo_root / "data" / "harness_results" / timestamp
    output_dir = Path(output_dir)

    # Create runner (will auto-load data via portfolio_backtest)
    runner = HarnessRunner(
        tickers=tickers,
        period=period,
        initial_capital=50_000.0,
        commission=0.001,
        slippage=0.0005,
        warmup=50,
        step=5,
        verbose=verbose,
    )

    # Determine which experiments to run
    experiments = []
    if suite in ("baseline", "all"):
        experiments.append(ExperimentConfig.baseline())
    if suite in ("ablations", "all"):
        experiments.extend(ExperimentConfig.ablation_variants())

    if not experiments:
        print(f"❌ Unknown suite: {suite}")
        return 1

    print(f"\nRunning {len(experiments)} experiment(s)...")
    print("-" * 60)

    # Create signal function (use RSI as baseline indicator)
    signal_fn = signal_from_indicator("RSI")

    # Run experiments
    try:
        runner.run_suite(
            signal_fn=signal_fn,
            experiments=experiments,
            output_dir=output_dir,
        )
    except Exception as e:
        print(f"❌ Error during harness run: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return 1

    # Validation
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)

    baseline_metrics = _load_baseline_metrics()
    fidelity_ok = runner.validate_fidelity(baseline_metrics, tolerance=0.02)
    structure_ok = runner.validate_structure()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Output directory: {output_dir}")
    print(f"Experiments run: {len(runner.results)}")
    print(f"Fidelity check: {'PASS ✅' if fidelity_ok else 'FAIL ❌'}")
    print(f"Structure check: {'PASS ✅' if structure_ok else 'FAIL ❌'}")

    # Print summary table
    if runner.results:
        rows = []
        for exp_name, (metrics, backtest_result, _) in runner.results.items():
            rows.append({
                "experiment": exp_name,
                "return": f"{metrics.period_return:.2f}%",
                "sharpe": f"{metrics.sharpe_annual:.2f}",
                "max_dd": f"{metrics.max_drawdown:.2f}%",
                "win_rate": f"{metrics.win_rate:.1f}%",
                "n_trades": len(backtest_result.trades) if backtest_result.trades else 0,
            })
        df = pd.DataFrame(rows)
        print("\n" + df.to_string(index=False))

    return 0 if (fidelity_ok and structure_ok) else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run T-harness experiment suite")
    parser.add_argument(
        "suite",
        nargs="?",
        default="all",
        choices=["baseline", "ablations", "all"],
        help="Which suite to run",
    )
    parser.add_argument(
        "-p", "--period",
        default="1y",
        help="Data period to backtest ('1y', '2y', etc.)",
    )
    parser.add_argument(
        "-t", "--tickers",
        type=lambda s: s.split(","),
        help="Comma-separated tickers (default: AAPL,MSFT,GOOGL,AMZN,TSLA,META,NVDA,JPM)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output directory for results",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress verbose output",
    )

    args = parser.parse_args()
    exit_code = main(
        suite=args.suite,
        period=args.period,
        tickers=args.tickers,
        output_dir=args.output,
        verbose=not args.quiet,
    )
    sys.exit(exit_code)
