"""
Walk-forward harness sobre 2 ventanas no-overlapping del cache de 2y.

Diseño
------
El run full-2y mostró ΔSharpe positivo (= "sacar mejora") para HMM, XGBoost y
vol_overlay. Antes de hardcodear esa poda en Sprint 3, este script confirma
si el patrón es estable a través del tiempo o si depende del régimen del window.

Implementación
--------------
1. Carga 2y de OHLCV para cada ticker del universe file (vía cache).
2. Alinea las series sobre el índice común.
3. Parte el rango en dos mitades: ``early_12m`` y ``late_12m``.
4. Para cada mitad, corre los 6 experimentos (baseline + 5 ablations) sobre
   un dict ``{ticker: df.iloc[i_start:i_end]}`` pasado directo al runner.
5. Imprime una tabla consolidada con ``ΔSharpe = sharpe(ablation) - sharpe(baseline)``
   en ambas ventanas, y un veredicto por feature.

Uso:
    python scripts/harness_walkforward.py data/harness_universe_42.txt

Output:
    data/harness_walkforward/{timestamp}/
        early_12m/  (output del HarnessRunner)
        late_12m/
        summary.json
        summary.txt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


def parse_universe_file(path: Path) -> list[str]:
    """Same parser as scripts/harness.py — per-line, # is a comment, commas allowed inside non-comment lines."""
    raw = path.read_text(encoding="utf-8")
    tickers: list[str] = []
    for line in raw.splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        line = line.strip()
        if not line:
            continue
        for tok in line.split(","):
            t = tok.strip().upper()
            if t:
                tickers.append(t)
    seen, out = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("universe_file", type=Path)
    parser.add_argument("-p", "--period", default="2y", help="Period to load from cache (default 2y)")
    parser.add_argument(
        "--n-windows", type=int, default=2,
        help="Number of non-overlapping windows to split the data into (default 2)",
    )
    args = parser.parse_args()

    # Imports here so --help works without yfinance available
    from data.yahoo_finance import get_historical_data
    from analysis.harness import ExperimentConfig, HarnessRunner
    from analysis.backtest import signal_from_analyze_stacked

    tickers = parse_universe_file(args.universe_file)
    print(f"Loading {args.period} of OHLCV for {len(tickers)} tickers from cache...")
    full_data: dict = {}
    failed: list[str] = []
    for t in tickers:
        df = get_historical_data(t, period=args.period)
        if df is None or df.empty or "Close" not in df.columns:
            failed.append(t)
        else:
            full_data[t] = df
    if failed:
        print(f"  WARNING: skipping {len(failed)} tickers without data: {', '.join(failed)}")
    print(f"  Loaded {len(full_data)}/{len(tickers)} tickers")

    if len(full_data) < 5:
        print("Error: not enough tickers loaded to run a meaningful backtest.")
        sys.exit(2)

    # Common index (intersection across all tickers)
    common_idx = None
    for df in full_data.values():
        common_idx = df.index if common_idx is None else common_idx.intersection(df.index)
    common_idx = common_idx.sort_values()
    n_bars = len(common_idx)
    print(f"  Common index: {n_bars} bars  ({common_idx[0].date()} -> {common_idx[-1].date()})")

    # Build N non-overlapping windows
    windows: dict[str, tuple[int, int]] = {}
    edges = [int(round(i * n_bars / args.n_windows)) for i in range(args.n_windows + 1)]
    for i in range(args.n_windows):
        lo, hi = edges[i], edges[i + 1]
        if args.n_windows == 2:
            name = "early_12m" if i == 0 else "late_12m"
        else:
            name = f"w{i+1}"
        windows[name] = (lo, hi)
        print(f"  Window {name}: bars [{lo}:{hi}]  ({common_idx[lo].date()} -> {common_idx[hi-1].date()})")

    # Prepare output directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = repo_root / "data" / "harness_walkforward" / ts
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput root: {out_root}")

    signal_fn = signal_from_analyze_stacked(enable_xgboost=True)
    experiments = [ExperimentConfig.baseline()] + ExperimentConfig.ablation_variants()

    all_sharpe: dict[str, dict[str, float]] = {}
    all_return: dict[str, dict[str, float]] = {}
    all_maxdd: dict[str, dict[str, float]] = {}

    for w_name, (i0, i1) in windows.items():
        print(f"\n{'=' * 60}\nWindow: {w_name}  ({i1 - i0} bars)\n{'=' * 60}")
        t_start = time.time()
        # Slice each ticker to this window — align to common index first
        window_data = {
            t: df.loc[common_idx[i0:i1]].copy()
            for t, df in full_data.items()
        }
        runner = HarnessRunner(
            data=window_data,
            tickers=list(window_data.keys()),
            initial_capital=50_000.0,
            warmup=50,
            step=5,
            verbose=False,
        )
        runner.run_suite(signal_fn, experiments, output_dir=out_root / w_name)
        elapsed = time.time() - t_start
        print(f"Window {w_name} done in {elapsed/60:.1f} min")

        all_sharpe[w_name] = {
            name: float(m.sharpe_annual) for name, (m, _, _) in runner.results.items()
        }
        all_return[w_name] = {
            name: float(m.period_return) for name, (m, _, _) in runner.results.items()
        }
        all_maxdd[w_name] = {
            name: float(m.max_drawdown) for name, (m, _, _) in runner.results.items()
        }

    # ── Consolidated summary ──────────────────────────────────────────────
    exp_order = ["baseline", "no_hmm", "no_stacking", "no_xgb", "no_correlation_gate", "no_vol_overlay"]
    w_names = list(windows.keys())

    print(f"\n{'=' * 76}\nWALK-FORWARD SUMMARY — Sharpe per window\n{'=' * 76}")
    header = f"{'Experiment':<24} | " + " | ".join(f"{w:>12}" for w in w_names)
    print(header)
    print("-" * len(header))
    for exp in exp_order:
        cells = " | ".join(f"{all_sharpe[w].get(exp, float('nan')):>12.3f}" for w in w_names)
        print(f"{exp:<24} | {cells}")

    print(f"\n{'=' * 76}\nΔSharpe vs baseline per window  (positive = ablation BETTER, kill candidate)\n{'=' * 76}")
    header = f"{'Ablation':<24} | " + " | ".join(f"{w:>12}" for w in w_names) + " | Verdict"
    print(header)
    print("-" * len(header))

    verdicts: dict[str, str] = {}
    for exp in exp_order[1:]:  # skip baseline
        deltas = [all_sharpe[w].get(exp, 0.0) - all_sharpe[w].get("baseline", 0.0) for w in w_names]
        cells = " | ".join(f"{d:>+12.3f}" for d in deltas)

        # Verdict heuristic: stable kill if all deltas positive AND >= +0.05
        if all(d > 0.05 for d in deltas):
            v = "STABLE KILL"
        elif all(d < -0.05 for d in deltas):
            v = "STABLE KEEP"
        elif all(abs(d) < 0.05 for d in deltas):
            v = "NO IMPACT (not evaluable)"
        else:
            v = "UNSTABLE — needs more windows"

        verdicts[exp] = v
        print(f"{exp:<24} | {cells} | {v}")

    # Save JSON summary
    summary = {
        "timestamp": ts,
        "n_windows": args.n_windows,
        "tickers_used": list(full_data.keys()),
        "windows": {w: list(windows[w]) for w in w_names},
        "sharpe": all_sharpe,
        "period_return": all_return,
        "max_drawdown": all_maxdd,
        "verdicts": verdicts,
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2))

    # Save text summary
    txt = [f"Walk-forward summary  ({args.n_windows} windows × {len(exp_order)} experiments)\n"]
    txt.append(f"Output: {out_root}\n")
    txt.append(f"Tickers used: {len(full_data)} of {len(tickers)}\n")
    txt.append("\nSharpe per window:\n")
    txt.append(header.replace(" | Verdict", "") + "\n")
    for exp in exp_order:
        cells = " | ".join(f"{all_sharpe[w].get(exp, float('nan')):>12.3f}" for w in w_names)
        txt.append(f"{exp:<24} | {cells}\n")
    txt.append("\nΔSharpe vs baseline:\n")
    for exp in exp_order[1:]:
        deltas = [all_sharpe[w].get(exp, 0.0) - all_sharpe[w].get("baseline", 0.0) for w in w_names]
        cells = " | ".join(f"{d:>+12.3f}" for d in deltas)
        txt.append(f"{exp:<24} | {cells} | {verdicts[exp]}\n")
    (out_root / "summary.txt").write_text("".join(txt))

    print(f"\nSummary saved to {out_root}/summary.json and summary.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
