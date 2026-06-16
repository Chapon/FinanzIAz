"""
Validate Sprint 4 / T05 cross-sectional ranking against the kill_only baseline.

Runs two variants over the same walk-forward windows, persists equity curves,
and prints a Sharpe / return / max-DD comparison.

  1. **kill_only** — current production: HMM off, Stacking off, XGB on,
     vol_overlay on, **cross_sectional_enabled=False**. Frozen baseline as of
     2026-06-02.
  2. **cross_sectional** — same as kill_only but cross_sectional_enabled=True
     with the SCHEMA defaults (lookback=120, weight=0.5).

Verdict per docs/sprint4_t05_cross_sectional_spec.md:

  * ΔSharpe overall ≥ +0.15  AND  P(Δ≤0) < 15%  →  SHIP
  * +0.05 to +0.15           AND  P(Δ≤0) < 25%  →  TUNE-GRID
  * < +0.05 OR P(Δ≤0) ≥ 25%                      →  KILL
  * < 0 in ≥ 3/4 windows                         →  KILL FIRME
  * turnover up >50% relative                    →  penalize Sharpe by 0.05
  * max DD up >2pp absolute                      →  KILL (risk regression)

Usage
-----

  python scripts/run_cross_sectional_validation.py data/harness_universe_41_10y.txt \\
      -p 10y --n-windows 4

Cost: 2 variants × N windows ≈ ⅔ of switcher_validation runtime — expect
~1.5-2 hours with the default args.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


def parse_universe_file(path: Path) -> list[str]:
    """Same parser as scripts/harness_walkforward.py and run_switcher_validation.py."""
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


def bootstrap_p_delta_le_zero(
    deltas_per_window: list[float],
    n_boot: int = 5000,
    rng_seed: int = 20260603,
) -> float:
    """Bootstrap P(Δ overall ≤ 0) over the per-window ΔSharpe values.

    Treats each window-Δ as an independent draw — same convention as
    docs/sprint2_kill_criteria.md Enmienda 1. Returns the fraction of
    bootstrap resamples whose mean is ≤ 0.
    """
    rng = np.random.default_rng(rng_seed)
    arr = np.array(deltas_per_window, dtype=float)
    n = len(arr)
    if n == 0:
        return 1.0
    idx = rng.integers(0, n, size=(n_boot, n))
    means = arr[idx].mean(axis=1)
    return float((means <= 0).mean())


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("universe_file", type=Path)
    parser.add_argument(
        "-p", "--period", default="10y",
        help="Cache period to load (default: 10y).",
    )
    parser.add_argument(
        "--n-windows", type=int, default=4,
        help="Number of non-overlapping windows (default: 4).",
    )
    parser.add_argument(
        "--lookback", type=int, default=None,
        help="Override cross_sectional_lookback (default: SCHEMA default 120).",
    )
    parser.add_argument(
        "--weight", type=float, default=None,
        help="Override cross_sectional_weight (default: SCHEMA default 0.5).",
    )
    parser.add_argument(
        "--max-positions", type=int, default=5,
        help=(
            "Slot constraint for the harness. CRITICAL: must be smaller than "
            "the universe size or the candidate ranking is never truncated "
            "and the cross-sectional toggle has zero effect. Default 5 = "
            "Sim Principal production config."
        ),
    )
    args = parser.parse_args()

    # Imports inside main() so --help works without yfinance.
    from data.yahoo_finance import get_historical_data_batch
    from analysis.harness import ExperimentConfig, HarnessRunner
    from analysis.backtest import signal_from_analyze_stacked
    from config.settings_manager import settings

    # Load OHLCV
    tickers = parse_universe_file(args.universe_file)
    print(f"Loading {args.period} of OHLCV for {len(tickers)} tickers from cache...")
    full_data: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    # Descarga en lote: los cache-misses comparten un crumb por chunk (menos 401).
    fetched = get_historical_data_batch(tickers, period=args.period)
    for t in tickers:
        df = fetched.get(t.upper())
        if df is None or df.empty or "Close" not in df.columns:
            failed.append(t)
        else:
            full_data[t] = df
    if failed:
        print(f"  WARNING: skipping {len(failed)} tickers without data: "
              f"{', '.join(failed)}")
    print(f"  Loaded {len(full_data)}/{len(tickers)} tickers")
    if len(full_data) < 5:
        print("Error: not enough tickers loaded.")
        sys.exit(2)

    # Common index across tickers — used to slice windows.
    common_idx = None
    for df in full_data.values():
        common_idx = df.index if common_idx is None else common_idx.intersection(df.index)
    common_idx = common_idx.sort_values()
    n_bars = len(common_idx)
    print(f"  Common index: {n_bars} bars  "
          f"({common_idx[0].date()} -> {common_idx[-1].date()})")

    # Optional knob overrides — set BEFORE the harness reads them. Restored
    # by HarnessRunner.run_suite's finally block via the toggle snapshot.
    knob_snapshot: dict[str, object] = {}
    for key, val in (
        ("cross_sectional_lookback", args.lookback),
        ("cross_sectional_weight", args.weight),
    ):
        if val is not None:
            knob_snapshot[key] = settings.get(key)
            settings.set(key, val)
            print(f"  Override: {key} = {val}")

    # Build N non-overlapping windows
    edges = [int(round(i * n_bars / args.n_windows)) for i in range(args.n_windows + 1)]
    windows: dict[str, tuple[int, int]] = {}
    for i in range(args.n_windows):
        lo, hi = edges[i], edges[i + 1]
        name = f"w{i+1}" if args.n_windows > 2 else ("early" if i == 0 else "late")
        windows[name] = (lo, hi)
        print(f"  Window {name}: bars [{lo}:{hi}]  "
              f"({common_idx[lo].date()} -> {common_idx[hi-1].date()})")

    # Output directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = repo_root / "data" / "cross_sectional_validation" / ts
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput root: {out_root}")

    signal_fn = signal_from_analyze_stacked(enable_xgboost=True)

    # Two variants. Both lock in the post-Sprint-2 kill_only configuration
    # (HMM off, Stacking off, XGB on, vol_overlay on). The only delta is the
    # T05 toggle.
    variants: list[tuple[str, ExperimentConfig]] = [
        ("kill_only", ExperimentConfig(
            name="kill_only",
            hmm_enabled=False, stacking_enabled=False,
            xgb_signal_enabled=True, vol_overlay_enabled=True,
            cross_sectional_enabled=False,
            description="Sprint 2 kill_only frozen baseline (2026-06-02).",
        )),
        ("cross_sectional", ExperimentConfig(
            name="cross_sectional",
            hmm_enabled=False, stacking_enabled=False,
            xgb_signal_enabled=True, vol_overlay_enabled=True,
            cross_sectional_enabled=True,
            description="kill_only + cross-sectional momentum ranking (T05).",
        )),
    ]

    all_sharpe: dict[str, dict[str, float]] = {w: {} for w in windows}
    all_return: dict[str, dict[str, float]] = {w: {} for w in windows}
    all_maxdd: dict[str, dict[str, float]] = {w: {} for w in windows}
    all_turnover: dict[str, dict[str, float]] = {w: {} for w in windows}

    try:
        for w_name, (i0, i1) in windows.items():
            print(f"\n{'=' * 60}\nWindow: {w_name}  ({i1 - i0} bars)\n{'=' * 60}")
            t_start = time.time()
            window_data = {t: df.loc[common_idx[i0:i1]].copy() for t, df in full_data.items()}

            for variant_label, variant_cfg in variants:
                print(f"  → variant: {variant_label}")
                v_start = time.time()
                runner = HarnessRunner(
                    data=window_data,
                    tickers=list(window_data.keys()),
                    initial_capital=50_000.0,
                    warmup=50,
                    step=5,
                    max_positions=args.max_positions,
                    verbose=False,
                )
                out_dir = out_root / w_name / variant_label
                runner.run_suite(signal_fn, [variant_cfg], output_dir=out_dir)
                m, _, _ = runner.results[variant_cfg.name]
                all_sharpe[w_name][variant_label] = float(m.sharpe_annual)
                all_return[w_name][variant_label] = float(m.period_return)
                all_maxdd[w_name][variant_label] = float(m.max_drawdown)
                all_turnover[w_name][variant_label] = float(getattr(m, "turnover", 0.0))
                print(f"    sharpe={m.sharpe_annual:+.3f}  return={m.period_return:+.2f}%  "
                      f"maxdd={m.max_drawdown:.2f}%  turnover={getattr(m,'turnover',0):.1f}%  "
                      f"({time.time()-v_start:.0f}s)")

            print(f"Window {w_name} total: {(time.time()-t_start)/60:.1f} min")
    finally:
        # Restore any settings knobs we overrode.
        for key, val in knob_snapshot.items():
            settings.set(key, val)

    # ── Consolidated summary ──────────────────────────────────────────────
    w_names = list(windows.keys())

    summary_lines: list[str] = []
    def emit(s=""):
        print(s)
        summary_lines.append(s)

    emit(f"\n{'=' * 76}\nT05 CROSS-SECTIONAL VALIDATION — Sharpe per window\n{'=' * 76}")
    header = f"{'Variant':<18} | " + " | ".join(f"{w:>10}" for w in w_names)
    emit(header)
    emit("-" * len(header))
    for v_label, _ in variants:
        cells = " | ".join(f"{all_sharpe[w].get(v_label, float('nan')):>+10.3f}" for w in w_names)
        emit(f"{v_label:<18} | {cells}")

    emit(f"\n{'=' * 76}\nΔSharpe = cross_sectional − kill_only  (positive = improvement)\n{'=' * 76}")
    deltas = [all_sharpe[w]["cross_sectional"] - all_sharpe[w]["kill_only"] for w in w_names]
    cells = " | ".join(f"{d:>+10.3f}" for d in deltas)
    emit(f"{'Δ Sharpe':<18} | {cells}")
    mean_delta = float(np.mean(deltas)) if deltas else 0.0
    emit(f"\nMean ΔSharpe overall: {mean_delta:+.3f}")

    p_le_zero = bootstrap_p_delta_le_zero(deltas)
    emit(f"Bootstrap P(Δ ≤ 0) over {len(deltas)} windows × 5000 resamples: {p_le_zero:.1%}")

    # Turnover penalty check
    tovr_base = float(np.mean([all_turnover[w]["kill_only"] for w in w_names]))
    tovr_cs = float(np.mean([all_turnover[w]["cross_sectional"] for w in w_names]))
    tovr_lift = (tovr_cs - tovr_base) / max(1e-6, tovr_base)
    emit(f"\nTurnover: kill_only={tovr_base:.1f}%  cross_sectional={tovr_cs:.1f}%  "
         f"lift={tovr_lift:+.1%}")

    # Max DD guardrail
    dd_base = float(np.mean([all_maxdd[w]["kill_only"] for w in w_names]))
    dd_cs = float(np.mean([all_maxdd[w]["cross_sectional"] for w in w_names]))
    dd_diff = dd_cs - dd_base
    emit(f"Max DD: kill_only={dd_base:.1f}%  cross_sectional={dd_cs:.1f}%  diff={dd_diff:+.1f}pp")

    # Verdict per spec
    emit(f"\n{'=' * 76}\nVERDICT\n{'=' * 76}")
    n_neg_windows = sum(1 for d in deltas if d < 0)
    adjusted_delta = mean_delta - (0.05 if tovr_lift > 0.5 else 0.0)
    if tovr_lift > 0.5:
        emit(f"Turnover lift {tovr_lift:+.1%} > 50% — applying −0.05 Sharpe penalty.")
        emit(f"Adjusted mean ΔSharpe: {adjusted_delta:+.3f}")

    if dd_diff > 2.0:
        verdict = "KILL — max DD regression"
    elif n_neg_windows >= 3:
        verdict = "KILL FIRME — negative in ≥3 windows (anti-cherry-pick)"
    elif adjusted_delta >= 0.15 and p_le_zero < 0.15:
        verdict = "SHIP — set cross_sectional_enabled=True"
    elif adjusted_delta >= 0.05 and p_le_zero < 0.25:
        verdict = "TUNE-GRID — borderline; sweep weight ∈ {0.3, 0.7} and lookback ∈ {60, 252} before decision"
    else:
        verdict = "KILL — insufficient lift / unreliable"
    emit(f"\n→ {verdict}")

    # Persist summary as a JSON next to per-window results
    summary = {
        "timestamp": ts,
        "universe": str(args.universe_file),
        "period": args.period,
        "n_windows": args.n_windows,
        "lookback_override": args.lookback,
        "weight_override": args.weight,
        "windows": w_names,
        "sharpe_per_window": all_sharpe,
        "return_per_window": all_return,
        "maxdd_per_window": all_maxdd,
        "turnover_per_window": all_turnover,
        "deltas_per_window": deltas,
        "mean_delta_sharpe": mean_delta,
        "bootstrap_p_delta_le_zero": p_le_zero,
        "turnover_lift_pct": tovr_lift,
        "maxdd_diff_pp": dd_diff,
        "adjusted_mean_delta": adjusted_delta,
        "verdict": verdict,
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (out_root / "summary.txt").write_text("\n".join(summary_lines))

    print(f"\nSummary written to:\n  {out_root / 'summary.json'}\n  {out_root / 'summary.txt'}")


if __name__ == "__main__":
    main()
