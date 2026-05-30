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
from analysis.backtest import signal_from_analyze_stacked


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
    max_positions: Optional[int] = None,
    verbose: bool = True,
):
    """
    Run harness suite.

    Args:
        suite: One of "baseline", "ablations", "all", "stacking_test"
               (baseline + no_stacking only), or "corr_test"
               (baseline + no_correlation_gate only).
        period: Period for auto-loading data ("1y", "2y", etc.)
        tickers: List of tickers to backtest. If None, use default watchlist.
        output_dir: Directory to save results (default: data/harness_results/{timestamp}/)
        max_positions: Slot cap. Default ``None`` → uses ``len(tickers)`` so
                       there is no competition for slots (every BUY can fill).
                       Set to a small value (e.g. 3) to force the
                       correlation_gate / signal-strength ranking to actually
                       have to discriminate.
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
        max_positions=max_positions,
        verbose=verbose,
    )

    # Determine which experiments to run. Focused suites run only baseline +
    # the one ablation of interest — cheaper iterations when chasing a single
    # toggle (no need to re-train HMM/XGB on the other 4 ablations).
    experiments = []
    if suite in ("baseline", "all"):
        experiments.append(ExperimentConfig.baseline())
    if suite in ("ablations", "all"):
        experiments.extend(ExperimentConfig.ablation_variants())
    if suite == "stacking_test":
        experiments = [
            ExperimentConfig.baseline(),
            next(v for v in ExperimentConfig.ablation_variants() if v.name == "no_stacking"),
        ]
    if suite == "corr_test":
        experiments = [
            ExperimentConfig.baseline(),
            next(v for v in ExperimentConfig.ablation_variants() if v.name == "no_correlation_gate"),
        ]

    if not experiments:
        print(f"Unknown suite: {suite}")
        return 1

    print(f"\nRunning {len(experiments)} experiment(s)...")
    print("-" * 60)

    # Sprint 1 wiring: stacked-analyze signal so hmm/xgb/stacking toggles
    # actually transit the code path. RSI-only bypassed them (see
    # sprint_1_completion_2026-05-28 in memory). SLOW: trains models on each
    # step, expect minutes per experiment over 1y of daily bars.
    signal_fn = signal_from_analyze_stacked(enable_xgboost=True)

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
    if fidelity_ok is None:
        print("Fidelity check: SKIPPED (no baseline in this suite)")
    else:
        print(f"Fidelity check: {'PASS' if fidelity_ok else 'FAIL'}")
    print(f"Structure check: {'PASS' if structure_ok else 'FAIL'}")

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

    # fidelity_ok is None when baseline was not in the suite (e.g. `ablations`)
    fidelity_pass = fidelity_ok in (None, True)
    return 0 if (fidelity_pass and structure_ok) else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run T-harness experiment suite")
    parser.add_argument(
        "suite",
        nargs="?",
        default="all",
        choices=["baseline", "ablations", "all", "stacking_test", "corr_test"],
        help=(
            "Which suite to run. Focused options run only 2 experiments "
            "(baseline + one ablation) for fast iteration: "
            "'stacking_test' = baseline + no_stacking; "
            "'corr_test' = baseline + no_correlation_gate."
        ),
    )
    parser.add_argument(
        "-m", "--max-positions",
        type=int,
        default=None,
        help=(
            "Cap on simultaneous portfolio positions. Default ``None`` uses "
            "len(tickers) (no slot competition — correlation_gate never has "
            "to reject anything). Set a small value (e.g. 3) to force the "
            "gate to be exercised."
        ),
    )
    parser.add_argument(
        "-p", "--period",
        default="1y",
        help="Data period to backtest ('1y', '2y', etc.)",
    )
    def _parse_tickers(s: str) -> list[str]:
        """Accept either ``AAPL,MSFT,...`` or ``@path/to/file.txt``.

        File form: one ticker per line, ``#`` introduces a comment (inline or
        full-line). Commas inside a non-comment line are still allowed as
        separators. We parse per-line so commas in comments don't bleed into
        ticker tokens.
        """
        def _parse_text(text: str) -> list[str]:
            out: list[str] = []
            for line in text.splitlines():
                if "#" in line:
                    line = line.split("#", 1)[0]
                line = line.strip()
                if not line:
                    continue
                for tok in line.split(","):
                    t = tok.strip().upper()
                    if t:
                        out.append(t)
            # De-dup preserving order
            seen, deduped = set(), []
            for t in out:
                if t not in seen:
                    seen.add(t)
                    deduped.append(t)
            return deduped

        if s.startswith("@"):
            path = Path(s[1:])
            return _parse_text(path.read_text(encoding="utf-8"))
        return _parse_text(s)

    parser.add_argument(
        "-t", "--tickers",
        type=_parse_tickers,
        help=(
            "Tickers to backtest. Either comma-separated (AAPL,MSFT,...) or "
            "@path/to/file.txt with one ticker per line. "
            "Default: AAPL,MSFT,GOOGL,AMZN,TSLA,META,NVDA,JPM"
        ),
    )
    parser.add_argument(
        "--account-id",
        type=int,
        help=(
            "Read the watchlist from finanzias.db for this paper account id "
            "(overrides --tickers). Use 1 for Sim Principal."
        ),
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

    tickers = args.tickers
    if args.account_id is not None:
        import sqlite3
        db_path = repo_root / "finanzias.db"
        if not db_path.exists():
            print(f"Error: {db_path} not found")
            sys.exit(2)
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT ticker FROM paper_watchlist WHERE account_id = ? ORDER BY ticker",
                (args.account_id,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            print(f"Error: no watchlist tickers for account_id={args.account_id}")
            sys.exit(2)
        tickers = [r[0] for r in rows]
        print(f"Loaded {len(tickers)} tickers from account_id={args.account_id} watchlist")

    exit_code = main(
        suite=args.suite,
        period=args.period,
        tickers=tickers,
        output_dir=args.output,
        max_positions=args.max_positions,
        verbose=not args.quiet,
    )
    sys.exit(exit_code)
