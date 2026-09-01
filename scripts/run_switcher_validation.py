"""
Validate the régime-aware feature switcher derived in T-régimen-2.

Runs three variants over the same walk-forward windows, persists equity
curves so downstream tools can analyse them, and prints a consolidated
Sharpe comparison:

  1. **baseline** — production-as-of-2026-06-01 settings: every feature ON
     (hmm + stacking + xgb + vol_overlay). The "before" picture.
  2. **kill_only** — applies the unconditional kills from T-régimen-2 but
     keeps vol_overlay enabled in every régime: hmm OFF, stacking OFF,
     xgb ON, vol_overlay ON. Isolates the value of the kills alone, with
     no switching dynamics.
  3. **full_switcher** — kills PLUS régime-aware vol_overlay (from
     ``paper_trading.feature_switch.policy_from_attribution_2026_06_01``).
     This is the policy we want to validate.

Verdict
-------

If ``full_switcher.sharpe > baseline.sharpe`` by ≥ +0.3 (with consistent
sign across windows), the régime-aware feature switching has captured the
alpha that Sprint 2 fase 1 attribution promised. Per the closure documented
in ``docs/sprint2_kill_criteria.md``, that is the definitive answer to the
"do the features switch by régime?" question.

Three concrete numbers to read off the output:

  * ΔSharpe(kill_only − baseline)        — value of the kills alone
  * ΔSharpe(full_switcher − baseline)    — total package
  * ΔSharpe(full_switcher − kill_only)   — value of switching alone

Usage
-----

    python scripts/run_switcher_validation.py data/harness_universe_42.txt \
        -p 5y --n-windows 4

Cost: same order of magnitude as ``scripts/harness_walkforward.py`` since
this also runs N variants × N windows. With the default args
(-p 5y --n-windows 4, 3 variants) expect ~2-3 hours.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


def parse_universe_file(path: Path) -> list[str]:
    """Same parser as ``scripts/harness_walkforward.py`` — per-line, # is a
    comment, commas allowed inside non-comment lines."""
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
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("universe_file", type=Path)
    parser.add_argument("-p", "--period", default="5y", help="Cache period to load (default: 5y).")
    parser.add_argument(
        "--n-windows", type=int, default=4, help="Number of non-overlapping windows (default: 4)."
    )
    args = parser.parse_args()

    # Imports inside main() so --help works without yfinance.
    from analysis.backtest import signal_from_analyze_stacked
    from analysis.harness import ExperimentConfig, HarnessRunner
    from analysis.regime_detector import RegimeConfig, detect_regime_series
    from data.yahoo_finance import get_historical_data_batch
    from paper_trading.feature_switch import (
        policy_from_attribution_2026_06_01,
        validate_policy_coverage,
    )

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
        print(f"  WARNING: skipping {len(failed)} tickers without data: {', '.join(failed)}")
    print(f"  Loaded {len(full_data)}/{len(tickers)} tickers")
    if len(full_data) < 5:
        print("Error: not enough tickers loaded.")
        sys.exit(2)

    # Common index across tickers — used to slice windows.
    common_idx = None
    for df in full_data.values():
        common_idx = df.index if common_idx is None else common_idx.intersection(df.index)
    if common_idx is None:  # `full_data` vacio: no hay indice comun que ordenar
        raise SystemExit("sin datos: no hay indice comun entre los tickers")
    common_idx = common_idx.sort_values()
    n_bars = len(common_idx)
    print(f"  Common index: {n_bars} bars  ({common_idx[0].date()} -> {common_idx[-1].date()})")

    # Build a market proxy from equal-weighted ticker returns over the FULL
    # period (not per-window — see T-régimen-2 docs for why per-window
    # warmup eats régimes near window edges). The régime detector then runs
    # ONCE on this full series. Each window's HarnessRunner gets the same
    # global régime series; it will only consult bars inside its own slice.
    print("\nBuilding global market proxy + régime series from cache...")
    rets_frame = pd.concat(
        [df["Close"].astype(float).pct_change().rename(t) for t, df in full_data.items()],
        axis=1,
    )
    proxy_rets = rets_frame.mean(axis=1).dropna()
    proxy_close = 100.0 * (1.0 + proxy_rets).cumprod()
    regime_df = detect_regime_series(pd.DataFrame({"Close": proxy_close}), RegimeConfig())
    regime_series = regime_df["regime"]
    from analysis.regime_detector import REGIME_WARMUP

    non_warmup = regime_series[regime_series != REGIME_WARMUP]
    print(f"  Global régime series: {len(regime_series)} bars  non-warmup={len(non_warmup)}")
    dist = non_warmup.value_counts(normalize=True).to_dict()
    print(
        "  Distribution: " + "  ".join(f"{k}={v:.1%}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1]))
    )

    # Build the policy and sanity-check coverage.
    policy = policy_from_attribution_2026_06_01()
    coverage_warnings = validate_policy_coverage(policy)
    if coverage_warnings:
        print("\nWARNING: policy coverage incomplete:")
        for w in coverage_warnings:
            print(f"  - {w}")

    # Build N non-overlapping windows
    edges = [round(i * n_bars / args.n_windows) for i in range(args.n_windows + 1)]
    windows: dict[str, tuple[int, int]] = {}
    for i in range(args.n_windows):
        lo, hi = edges[i], edges[i + 1]
        name = f"w{i + 1}" if args.n_windows > 2 else ("early_12m" if i == 0 else "late_12m")
        windows[name] = (lo, hi)
        print(f"  Window {name}: bars [{lo}:{hi}]  ({common_idx[lo].date()} -> {common_idx[hi - 1].date()})")

    # Output directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = repo_root / "data" / "switcher_validation" / ts
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput root: {out_root}")

    signal_fn = signal_from_analyze_stacked(enable_xgboost=True)

    # Three variants. ExperimentConfig is the static toggle bag; per-window
    # we may pass a régime series + policy to HarnessRunner to wire the
    # régime-aware vol_overlay closure.
    variants: list[tuple[str, ExperimentConfig, bool]] = [
        (
            "baseline",
            ExperimentConfig(
                name="baseline",
                hmm_enabled=True,
                stacking_enabled=True,
                xgb_signal_enabled=True,
                vol_overlay_enabled=True,
                description="Production-as-of-2026-06-01: all features ON",
            ),
            False,
        ),  # régime-aware mode OFF
        (
            "kill_only",
            ExperimentConfig(
                name="kill_only",
                hmm_enabled=False,
                stacking_enabled=False,
                xgb_signal_enabled=True,
                vol_overlay_enabled=True,
                description="Kills only (HMM/Stacking off, XGB+vol_overlay always on)",
            ),
            False,
        ),
        (
            "full_switcher",
            ExperimentConfig(
                name="full_switcher",
                hmm_enabled=False,
                stacking_enabled=False,
                xgb_signal_enabled=True,
                # vol_overlay_enabled is IGNORED in régime-aware mode; the policy
                # decides per bar. We set it to True so the legacy path would
                # also evaluate the overlay if the régime-aware wiring failed.
                vol_overlay_enabled=True,
                description="Kills + régime-aware vol_overlay",
            ),
            True,
        ),  # régime-aware mode ON
    ]

    all_sharpe: dict[str, dict[str, float]] = {w: {} for w in windows}
    all_return: dict[str, dict[str, float]] = {w: {} for w in windows}
    all_maxdd: dict[str, dict[str, float]] = {w: {} for w in windows}

    for w_name, (i0, i1) in windows.items():
        print(f"\n{'=' * 60}\nWindow: {w_name}  ({i1 - i0} bars)\n{'=' * 60}")
        t_start = time.time()
        window_data = {t: df.loc[common_idx[i0:i1]].copy() for t, df in full_data.items()}

        for variant_label, variant_cfg, regime_aware in variants:
            print(f"  → variant: {variant_label}")
            v_start = time.time()
            # Build a fresh runner per variant. For full_switcher, plumb
            # régime series + policy so the vol_overlay closure becomes
            # régime-aware.
            kwargs: dict[str, Any] = dict(
                data=window_data,
                tickers=list(window_data.keys()),
                initial_capital=50_000.0,
                warmup=50,
                step=5,
                verbose=False,
            )
            if regime_aware:
                kwargs["regime_series"] = regime_series
                kwargs["vol_overlay_policy"] = policy

            runner = HarnessRunner(**kwargs)
            # Save under <out_root>/<window>/<variant>/  so each variant gets
            # its own results directory mirroring harness_walkforward layout.
            out_dir = out_root / w_name / variant_label
            runner.run_suite(signal_fn, [variant_cfg], output_dir=out_dir)
            m, _, _ = runner.results[variant_cfg.name]
            all_sharpe[w_name][variant_label] = float(m.sharpe_annual)
            all_return[w_name][variant_label] = float(m.period_return)
            all_maxdd[w_name][variant_label] = float(m.max_drawdown)
            print(
                f"    sharpe={m.sharpe_annual:+.3f}  return={m.period_return:+.2f}%  "
                f"maxdd={m.max_drawdown:.2f}%  ({time.time() - v_start:.0f}s)"
            )

        print(f"Window {w_name} total: {(time.time() - t_start) / 60:.1f} min")

    # ── Consolidated summary ──────────────────────────────────────────────
    variant_labels = [v[0] for v in variants]
    w_names = list(windows.keys())

    summary_lines: list[str] = []

    def emit(s=""):
        print(s)
        summary_lines.append(s)

    emit(f"\n{'=' * 76}\nT-RÉGIMEN-3 SWITCHER VALIDATION — Sharpe per window\n{'=' * 76}")
    header = f"{'Variant':<18} | " + " | ".join(f"{w:>10}" for w in w_names)
    emit(header)
    emit("-" * len(header))
    for v in variant_labels:
        cells = " | ".join(f"{all_sharpe[w].get(v, float('nan')):>+10.3f}" for w in w_names)
        emit(f"{v:<18} | {cells}")

    emit(f"\n{'=' * 76}\nΔSharpe vs baseline  (positive = improvement)\n{'=' * 76}")
    for v in variant_labels[1:]:  # skip baseline
        deltas = [all_sharpe[w].get(v, 0.0) - all_sharpe[w].get("baseline", 0.0) for w in w_names]
        cells = " | ".join(f"{d:>+10.3f}" for d in deltas)
        mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
        # Verdict: all same sign + mean ≥ 0.3 → SOLID. Mixed → check breakdown.
        signs = [(+1 if d >= 0 else -1) for d in deltas]
        stable_pos = all(s > 0 for s in signs) and mean_delta >= 0.30
        stable_neg = all(s < 0 for s in signs) and mean_delta <= -0.30
        if stable_pos:
            verdict = "ALPHA"
        elif stable_neg:
            verdict = "REGRESSION"
        elif all(s > 0 for s in signs):
            verdict = "POS BUT SMALL"
        elif all(s < 0 for s in signs):
            verdict = "NEG BUT SMALL"
        else:
            verdict = "MIXED"
        emit(f"{v:<18} | {cells} | mean={mean_delta:+.3f}  {verdict}")

    emit(
        f"\n{'=' * 76}\nΔSharpe full_switcher vs kill_only  "
        f"(positive = switching adds value beyond kills)\n{'=' * 76}"
    )
    deltas_switch = [
        all_sharpe[w].get("full_switcher", 0.0) - all_sharpe[w].get("kill_only", 0.0) for w in w_names
    ]
    cells = " | ".join(f"{d:>+10.3f}" for d in deltas_switch)
    mean_d = sum(deltas_switch) / len(deltas_switch) if deltas_switch else 0.0
    emit(f"switching delta    | {cells} | mean={mean_d:+.3f}")

    # Persist summary
    summary_txt = out_root / "summary.txt"
    summary_txt.write_text("\n".join(summary_lines), encoding="utf-8")
    summary_json = out_root / "summary.json"
    with open(summary_json, "w") as f:
        json.dump(
            {
                "sharpe": all_sharpe,
                "period_return": all_return,
                "max_drawdown": all_maxdd,
                "windows": {n: [int(lo), int(hi)] for n, (lo, hi) in windows.items()},
            },
            f,
            indent=2,
        )
    emit(f"\nWrote {summary_txt}")
    emit(f"Wrote {summary_json}")
    print("\nDone.  Total time: see per-window readouts above.")


if __name__ == "__main__":
    main()
