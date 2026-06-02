"""
Régime-conditional attribution analyzer (T-régimen-2, Sprint 2 fase 2).

Given the output directory of ``scripts/harness_walkforward.py`` (one window
or several), this script:

  1. Loads the per-variant equity curve CSVs that ``HarnessRunner.save_results``
     persists (since the patch for T-régimen-2).
  2. Builds a market proxy daily return series (equal-weighted average of all
     cached tickers in the universe by default, or a user-supplied series).
  3. Calls :func:`analysis.regime_detector.detect_regime_series` on the proxy
     to tag every trading day with one of the four buckets.
  4. For every variant, slices the daily portfolio returns by régime and
     computes per-régime annualised Sharpe.
  5. Compares each ablation variant to ``baseline`` to produce a feature × régime
     ΔSharpe table.

The output is the "table 4 features × 4 régimes" that T-régimen-2 needs to
make per-feature decisions:

  * ΔSharpe same sign in every régime → keep firm or kill firm (no switching).
  * ΔSharpe of opposite sign across régimes → candidate for feature switching.

Usage:
    python scripts/regime_attribution.py data/harness_walkforward/<timestamp>/

Or for a single-window harness output (scripts/harness.py output):
    python scripts/regime_attribution.py --single-window data/harness_results/<timestamp>/

The script is intentionally POST-HOC: it does not re-run any backtest. It only
slices what is already on disk. To get fresh data, re-run the walk-forward;
this script processes its output.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from analysis.regime_detector import (  # noqa: E402
    REGIME_BEAR,
    REGIME_BULL_QUIET,
    REGIME_BULL_VOLATILE,
    REGIME_LATERAL,
    REGIME_WARMUP,
    RegimeConfig,
    detect_regime_series,
)

# Project annualisation convention. Re-imported here to keep this script
# runnable in isolation without the config package.
try:
    from config.constants import TRADING_DAYS_PER_YEAR  # noqa: E402
except Exception:  # pragma: no cover
    TRADING_DAYS_PER_YEAR = 252

NON_WARMUP_REGIMES = (
    REGIME_BULL_QUIET,
    REGIME_BULL_VOLATILE,
    REGIME_LATERAL,
    REGIME_BEAR,
)


# ── Pure analysis primitives ────────────────────────────────────────────────


def equity_to_daily_returns(equity: pd.Series) -> pd.Series:
    """Convert an equity curve to daily returns. NaNs from pct_change are
    dropped — the first bar has no previous, so it cannot contribute."""
    return equity.astype(float).pct_change().dropna()


def annualised_sharpe(returns: pd.Series,
                      trading_days_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Annualised Sharpe (no risk-free rate). Returns NaN for fewer than 2
    observations or zero variance — both indicate the bucket can't be measured."""
    r = returns.dropna()
    if len(r) < 2:
        return float("nan")
    sd = float(r.std(ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(r.mean() / sd * np.sqrt(trading_days_per_year))


def slice_returns_by_regime(returns: pd.Series, regimes: pd.Series) -> dict[str, pd.Series]:
    """Group a returns series by the régime label of each day.

    The two series must share an index (or be alignable). Days whose régime is
    ``warmup`` are excluded. Returns a dict mapping each non-warmup régime
    label to the subset of returns observed during that régime.
    """
    aligned = pd.concat([returns.rename("ret"), regimes.rename("reg")], axis=1)
    aligned = aligned.dropna(subset=["ret"])  # keep all regimes incl warmup briefly
    out: dict[str, pd.Series] = {}
    for reg in NON_WARMUP_REGIMES:
        sub = aligned.loc[aligned["reg"] == reg, "ret"]
        out[reg] = sub
    return out


@dataclass
class RegimeSharpe:
    """Per-régime Sharpe for a single variant, plus bar counts."""
    variant: str
    sharpe_by_regime: dict[str, float]
    n_by_regime: dict[str, int]
    sharpe_overall: float
    n_overall: int

    def to_dict(self) -> dict:
        return asdict(self)


def compute_variant_regime_sharpe(equity: pd.Series,
                                  regimes: pd.Series,
                                  variant_name: str,
                                  trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
                                  ) -> RegimeSharpe:
    """For one variant's equity curve, compute Sharpe within each régime and
    the overall Sharpe over all non-warmup bars."""
    rets = equity_to_daily_returns(equity)
    by_reg = slice_returns_by_regime(rets, regimes)
    sharpe_by = {k: annualised_sharpe(v, trading_days_per_year) for k, v in by_reg.items()}
    n_by = {k: int(len(v)) for k, v in by_reg.items()}
    all_non_warmup = pd.concat(by_reg.values()) if by_reg else pd.Series(dtype=float)
    return RegimeSharpe(
        variant=variant_name,
        sharpe_by_regime=sharpe_by,
        n_by_regime=n_by,
        sharpe_overall=annualised_sharpe(all_non_warmup, trading_days_per_year),
        n_overall=int(len(all_non_warmup)),
    )


def delta_sharpe_table(per_variant: dict[str, RegimeSharpe],
                       baseline_name: str = "baseline") -> pd.DataFrame:
    """Build the headline N × 4 table: variant rows, régime columns, cell =
    ΔSharpe vs the baseline variant.

    The baseline row itself is included with all zeros — useful sanity check.
    Variants missing the baseline name raise.
    """
    if baseline_name not in per_variant:
        raise KeyError(f"baseline variant {baseline_name!r} not in results "
                       f"(have: {list(per_variant)})")
    base = per_variant[baseline_name].sharpe_by_regime
    rows = {}
    for name, rs in per_variant.items():
        rows[name] = {
            reg: (rs.sharpe_by_regime.get(reg, float("nan"))
                  - base.get(reg, float("nan")))
            for reg in NON_WARMUP_REGIMES
        }
    return pd.DataFrame(rows).T[list(NON_WARMUP_REGIMES)]


def verdict_for_feature(delta_row: pd.Series, tolerance: float = 0.05) -> str:
    """Classify a single ablation's per-régime ΔSharpe row into a verdict.

    Δ is the ablation Sharpe minus baseline Sharpe. So:
      * If Δ > 0 in régime R: the feature *hurts* in régime R (disabling
        improved Sharpe). Disable here.
      * If Δ < 0 in régime R: the feature *helps* in régime R (disabling
        worsened Sharpe). Enable here.
      * Within ±tolerance: no measurable effect.

    Returns:
      * ``"keep_all"`` — every measurable régime says enable (Δ < -tolerance).
      * ``"kill_all"`` — every measurable régime says disable (Δ > +tolerance).
      * ``"switch"``  — at least one régime helps and one hurts.
      * ``"no_effect"`` — no régime has |Δ| > tolerance.
      * ``"undetermined"`` — too few measurable bars to call.
    """
    measurable = delta_row.dropna()
    if measurable.empty:
        return "undetermined"
    helps = (measurable < -tolerance).any()
    hurts = (measurable > +tolerance).any()
    if helps and hurts:
        return "switch"
    if helps and not hurts:
        return "keep_all"
    if hurts and not helps:
        return "kill_all"
    return "no_effect"


# ── IO helpers ──────────────────────────────────────────────────────────────


def load_variant_equity(window_dir: Path) -> dict[str, pd.Series]:
    """Read every <variant>.equity.csv under a window directory.

    Expects layout:  ``<window_dir>/results/<variant>.equity.csv``

    Each CSV has columns ``date,equity``. Returns dict variant_name → Series.
    """
    results = window_dir / "results"
    if not results.exists():
        raise FileNotFoundError(f"no results/ subdir at {window_dir}")
    out = {}
    for csv in sorted(results.glob("*.equity.csv")):
        name = csv.name[: -len(".equity.csv")]
        df = pd.read_csv(csv, parse_dates=["date"], index_col="date")
        out[name] = df["equity"].astype(float)
    if not out:
        raise FileNotFoundError(
            f"no *.equity.csv under {results}/. The harness must be re-run "
            "after the T-régimen-2 patch to persist equity curves."
        )
    return out


def build_proxy_returns(equities: dict[str, pd.Series],
                        proxy_series: Optional[pd.Series] = None,
                        bh_equity: Optional[pd.Series] = None) -> pd.Series:
    """Build the market-proxy daily return series to feed the régime detector.

    Priority order (most → least accurate):

    1. ``proxy_series`` if supplied (e.g. SPY Close, or any external proxy
       passed via ``--proxy-csv``). Most accurate, callers' choice.
    2. ``bh_equity`` if supplied (buy-and-hold equal-weighted benchmark that
       portfolio_backtest computes and which save_results persists as
       ``<variant>.bh_equity.csv`` since 2026-06-01). This tracks the
       UNDERLYING market, not the strategy's equity, so it sees shocks the
       strategy de-risks through.
    3. Fallback: equal-weighted mean of the *variant equity curves*. THIS
       SUPPRESSES regime amplitude — the strategies de-risk during shocks,
       so a bear or vol_volatile day vanishes from this proxy even though
       the market saw it. Use only when (1) and (2) are unavailable. Empirical
       observation 2026-06-01: on the same window, this fallback reported 0
       bars of bull_volatile + 0 bars of bear, while bh_equity correctly
       identified 10 + 34 bars respectively.
    """
    if proxy_series is not None:
        return proxy_series.pct_change().dropna()
    if bh_equity is not None and len(bh_equity) > 0:
        return bh_equity.pct_change().dropna()
    # Fallback path — flagged as suboptimal above.
    frame = pd.concat(equities.values(), axis=1, keys=list(equities))
    proxy_eq = frame.mean(axis=1).dropna()
    return proxy_eq.pct_change().dropna()


def load_bh_equity(window_dir: Path) -> Optional[pd.Series]:
    """Pick the first available ``<variant>.bh_equity.csv`` under the window's
    results directory. Returns None if no such file exists (older harness
    runs predate the 2026-06-01 patch and won't have these)."""
    results = window_dir / "results"
    if not results.exists():
        return None
    bh_files = sorted(results.glob("*.bh_equity.csv"))
    if not bh_files:
        return None
    df = pd.read_csv(bh_files[0], parse_dates=["date"], index_col="date")
    col = "bh_equity" if "bh_equity" in df.columns else df.columns[0]
    return df[col].astype(float)


def stitch_global_bh_equity(window_dirs: list[Path]) -> Optional[pd.Series]:
    """Concatenate the buy-and-hold equity curves from every available window
    into a single continuous series, sorted by date and de-duplicated.

    Why this exists: running the régime detector independently on each window
    means each window pays a 60-bar warmup cost — the first ~3 months of each
    window are unclassified ``warmup``. For walk-forward outputs that span
    several years split into 4+ windows, this can hide a régime that happens
    to fall in a window's leading bars (concrete example 2026-06-01: the
    Q1 2025 bear started 2025-03-12 and w4 began 2025-03-03, so the bear was
    fully inside w4's warmup and disappeared from the per-window detector).

    The régime is a property of the *market* at each timestamp, not of the
    window we're slicing. Computing it once on the stitched 5y series and
    then slicing per window pays warmup only once at the absolute start.

    Returns None when no bh_equity files are found anywhere.
    """
    pieces: list[pd.Series] = []
    for d in window_dirs:
        s = load_bh_equity(d)
        if s is not None and len(s) > 0:
            pieces.append(s)
    if not pieces:
        return None
    full = pd.concat(pieces).sort_index()
    # Drop duplicates that might exist on window seams.
    full = full[~full.index.duplicated(keep="first")]
    # The absolute level of each window's bh_equity restarts at initial_capital;
    # to make a meaningful continuous series, rescale each segment to chain on
    # the previous segment's last value. Without this, the seams produce
    # artificial jumps that look like one-day shocks to the régime detector.
    if len(pieces) > 1:
        rescaled = [pieces[0].copy()]
        for piece in pieces[1:]:
            last_prev = rescaled[-1].iloc[-1]
            first_cur = piece.iloc[0]
            if first_cur == 0:
                continue
            scale = last_prev / first_cur
            rescaled.append(piece * scale)
        full = pd.concat(rescaled).sort_index()
        full = full[~full.index.duplicated(keep="first")]
    return full


def attribution_for_window(window_dir: Path,
                           proxy_series: Optional[pd.Series] = None,
                           cfg: Optional[RegimeConfig] = None,
                           regime_series: Optional[pd.Series] = None) -> dict:
    """Run the full per-window attribution pipeline.

    Parameters
    ----------
    window_dir
        Directory containing ``results/<variant>.equity.csv`` files.
    proxy_series
        Optional explicit market proxy series (Close prices, e.g. SPY). Used
        only when ``regime_series`` is not supplied.
    cfg
        Régime detector configuration. Used only when ``regime_series`` is
        computed locally.
    regime_series
        Pre-computed régime label series spanning at least this window's date
        range. When supplied, the function does NOT re-detect régime — it
        slices the pre-computed labels to the variant equity dates. This is
        the recommended path for multi-window walk-forward analysis (see
        :func:`stitch_global_bh_equity`): computing régime once on the full
        timeline avoids paying 60-bar warmup at every window boundary.

    Returns a JSON-serializable dict with the régime distribution, per-variant
    per-régime Sharpe, the ΔSharpe table, and per-feature verdicts.
    """
    equities = load_variant_equity(window_dir)
    if "baseline" not in equities:
        raise KeyError(f"baseline.equity.csv missing under {window_dir}/results")

    if regime_series is not None:
        # Slice the global régime labels to the dates this window's baseline
        # equity covers. Any bar without a label (e.g. before the global
        # warmup ended) keeps NaN → treated as warmup downstream.
        baseline_idx = equities["baseline"].index
        regimes = regime_series.reindex(baseline_idx).fillna(REGIME_WARMUP)
    else:
        # Legacy per-window path. Proxy priority: explicit > persisted bh_equity
        # > equity-mean fallback.
        bh_equity = load_bh_equity(window_dir) if proxy_series is None else None
        proxy_returns = build_proxy_returns(equities, proxy_series=proxy_series,
                                            bh_equity=bh_equity)
        proxy_close = (1.0 + proxy_returns).cumprod() * 100.0
        proxy_df = pd.DataFrame({"Close": proxy_close})
        regime_df = detect_regime_series(proxy_df, cfg or RegimeConfig())
        regimes = regime_df["regime"]

    per_variant: dict[str, RegimeSharpe] = {}
    for name, eq in equities.items():
        per_variant[name] = compute_variant_regime_sharpe(eq, regimes, variant_name=name)

    delta = delta_sharpe_table(per_variant, baseline_name="baseline")
    verdicts = {name: verdict_for_feature(delta.loc[name])
                for name in delta.index if name != "baseline"}

    regime_dist = (regimes[regimes != REGIME_WARMUP].value_counts(normalize=True)
                   .to_dict())
    return {
        "window": str(window_dir.name),
        "regime_distribution": {k: float(v) for k, v in regime_dist.items()},
        "per_variant": {name: rs.to_dict() for name, rs in per_variant.items()},
        "delta_sharpe": {name: row.to_dict() for name, row in delta.iterrows()},
        "verdicts": verdicts,
    }


# ── Reporting ───────────────────────────────────────────────────────────────


def format_table(report: dict) -> str:
    """Pretty-print a single-window report as a text table."""
    lines = []
    lines.append(f"=== Window: {report['window']} ===")
    dist = report["regime_distribution"]
    lines.append("Régime distribution:  " + "  ".join(
        f"{k}={v:.1%}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1])
    ))
    lines.append("")
    lines.append("Per-variant Sharpe by régime (n bars in parentheses):")
    header = f"  {'variant':<18} " + " ".join(f"{r:>16}" for r in NON_WARMUP_REGIMES) + f"  {'overall':>10}"
    lines.append(header)
    for name, rs in report["per_variant"].items():
        cells = []
        for reg in NON_WARMUP_REGIMES:
            s = rs["sharpe_by_regime"].get(reg)
            n = rs["n_by_regime"].get(reg, 0)
            cell = f"{s:+.2f}({n})" if s == s else f"  n/a ({n})"  # NaN check
            cells.append(f"{cell:>16}")
        s_all = rs["sharpe_overall"]
        all_cell = f"{s_all:+.2f}" if s_all == s_all else "n/a"
        lines.append(f"  {name:<18} " + " ".join(cells) + f"  {all_cell:>10}")
    lines.append("")
    lines.append("ΔSharpe vs baseline (ablation − baseline; positive = feature hurts):")
    lines.append(f"  {'variant':<18} " + " ".join(f"{r:>16}" for r in NON_WARMUP_REGIMES) + f"  {'verdict':>12}")
    for name, row in report["delta_sharpe"].items():
        if name == "baseline":
            continue
        cells = []
        for reg in NON_WARMUP_REGIMES:
            d = row.get(reg)
            cells.append(f"{d:+.2f}" if d == d else "n/a")
        verdict = report["verdicts"].get(name, "?")
        lines.append(f"  {name:<18} " + " ".join(f"{c:>16}" for c in cells) + f"  {verdict:>12}")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("root", type=Path,
                   help="harness_walkforward/<ts>/ (multi-window) or harness_results/<ts>/ (single)")
    p.add_argument("--single-window", action="store_true",
                   help="Treat ROOT as a single window (no early_12m/late_12m subdirs).")
    p.add_argument("--proxy-csv", type=Path, default=None,
                   help="Optional CSV with date,Close for an explicit market proxy "
                        "(e.g. SPY). If omitted, an equal-weight proxy is built "
                        "from the variant equity curves themselves.")
    args = p.parse_args(argv)

    if not args.root.exists():
        print(f"Error: {args.root} does not exist", file=sys.stderr)
        return 2

    proxy_series = None
    if args.proxy_csv is not None:
        df = pd.read_csv(args.proxy_csv, parse_dates=[0], index_col=0)
        # Be lenient about the column name.
        col = "Close" if "Close" in df.columns else df.columns[0]
        proxy_series = df[col].astype(float)

    # Discover windows
    if args.single_window:
        windows = [args.root]
    else:
        windows = [d for d in sorted(args.root.iterdir())
                   if d.is_dir() and (d / "results").exists()]
        if not windows:
            print(f"No window subdirectories with results/ found under {args.root}",
                  file=sys.stderr)
            return 2

    # Global régime detection (multi-window only). Stitch every window's
    # bh_equity into one continuous series, run the detector once, and pass
    # the per-bar labels to each window's attribution. This pays 60-bar
    # warmup only at the absolute start of the 5y series, instead of once
    # per window — which is what makes régimes near a window edge (like the
    # Q1 2025 bear that started 9 days after w4 began) actually visible.
    global_regime: Optional[pd.Series] = None
    if proxy_series is None and len(windows) > 1:
        stitched = stitch_global_bh_equity(windows)
        if stitched is not None and len(stitched) > 60:
            stitched_df = pd.DataFrame({"Close": stitched})
            global_regime_df = detect_regime_series(stitched_df, RegimeConfig())
            global_regime = global_regime_df["regime"]
            non_warmup = global_regime[global_regime != REGIME_WARMUP]
            print(f"Global régime detection: {len(stitched)} bars "
                  f"({stitched.index[0].date()} → {stitched.index[-1].date()}), "
                  f"non-warmup={len(non_warmup)}")
            dist = (non_warmup.value_counts(normalize=True)
                    .to_dict())
            print(f"  Global distribution: " + "  ".join(
                f"{k}={v:.1%}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1])
            ))
            print()
    elif proxy_series is not None:
        # If an explicit proxy CSV is given, also compute régime globally on
        # it (otherwise each window slices a 60-bar warmup off the proxy
        # individually for no reason).
        proxy_df = pd.DataFrame({"Close": proxy_series.astype(float)})
        global_regime_df = detect_regime_series(proxy_df, RegimeConfig())
        global_regime = global_regime_df["regime"]

    reports = []
    for w in windows:
        try:
            r = attribution_for_window(w, proxy_series=proxy_series,
                                       regime_series=global_regime)
        except (FileNotFoundError, KeyError) as e:
            print(f"  SKIP {w.name}: {e}", file=sys.stderr)
            continue
        reports.append(r)
        print(format_table(r))
        print()

    if reports:
        out = args.root / "regime_attribution.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(reports, f, indent=2, default=str)
        print(f"Wrote {out}")

    return 0 if reports else 1


if __name__ == "__main__":
    sys.exit(main())
