"""
Statistical market-regime detector (T-régimen-1, Sprint 2 fase 2).

Pure function: takes a market-proxy OHLCV DataFrame (e.g. SPY) and returns a
per-bar regime classification using two ingredients:

  * Rolling annualised Sharpe of the proxy (default window: 60 bars).
  * Realised annualised volatility of the proxy (default window: 30 bars).

The two are crossed into four buckets:

  * ``bull_quiet``    — Sharpe above +threshold AND vol below threshold
  * ``bull_volatile`` — Sharpe above +threshold AND vol at/above threshold
  * ``lateral``       — |Sharpe| at/below threshold (vol ignored)
  * ``bear``          — Sharpe below −threshold (vol ignored — bear is by
                        definition a vol regime)

Why this and not the existing HMM / GARCH detectors:

  * The HMM in ``analysis.ml_signals.detect_market_regime_hmm`` is one of the
    *features* under evaluation in Sprint 2; using it as the régime detector
    creates a circular dependency.
  * The rule-based ``detect_market_regime`` in the same module is per-ticker
    and returns the *current* state only; régime-conditional attribution needs
    a *historical series* of the global market state.
  * GARCH captures variance shifts but not direction.

The contract is intentionally minimal: pure function, no DB, no settings, no
logger. Callers are responsible for supplying clean OHLCV data and persisting
results. This mirrors the discipline of ``paper_trading/gates.py`` (Sprint 1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Re-use the project-wide annualisation constant when available; fall back to
# 252 so this module remains importable in isolation (e.g. notebooks).
try:
    from config.constants import TRADING_DAYS_PER_YEAR
except Exception:  # pragma: no cover - defensive import
    TRADING_DAYS_PER_YEAR = 252


# ── Constants ────────────────────────────────────────────────────────────────

REGIME_BULL_QUIET = "bull_quiet"
REGIME_BULL_VOLATILE = "bull_volatile"
REGIME_LATERAL = "lateral"
REGIME_BEAR = "bear"
REGIME_WARMUP = "warmup"  # not enough history to classify yet

VALID_REGIMES = (
    REGIME_BULL_QUIET,
    REGIME_BULL_VOLATILE,
    REGIME_LATERAL,
    REGIME_BEAR,
)


@dataclass(frozen=True)
class RegimeConfig:
    """All tunables for the detector in one place.

    Defaults are first-pass calibration intended for daily US-equity proxies
    (SPY-like). They are NOT empirically optimised — the validation step in
    T-régimen-1 measures their behaviour against historical regimes.
    """

    sharpe_window: int = 60
    vol_window: int = 30
    # Annualised Sharpe; |s| <= this → lateral. Calibration note: a 60-bar
    # rolling Sharpe of a zero-drift series has std ≈ √(252/60) ≈ 2.05, so a
    # tight deadband would misclassify pure noise as bull/bear. 1.0 keeps the
    # lateral band wide enough to absorb sample-mean variance, while still
    # being narrow enough that real SPY bull/bear regimes (typical 60d Sharpe
    # |1.5–3|) cross it cleanly.
    sharpe_threshold: float = 1.0
    vol_threshold: float = 0.18  # annualised σ; vol >= this → "volatile"
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR
    min_run_length: int = 5  # hysteresis: new regime must hold this long to flip


# ── Core detection ──────────────────────────────────────────────────────────


def _classify(sharpe: float, vol: float, cfg: RegimeConfig) -> str:
    """Single-point classifier. NaN-safe: returns ``warmup`` if either input
    is NaN (rolling windows not yet filled)."""
    if pd.isna(sharpe) or pd.isna(vol):
        return REGIME_WARMUP
    if sharpe < -cfg.sharpe_threshold:
        return REGIME_BEAR
    if sharpe > cfg.sharpe_threshold:
        return REGIME_BULL_VOLATILE if vol >= cfg.vol_threshold else REGIME_BULL_QUIET
    return REGIME_LATERAL


def _smooth_min_run_length(regimes: list[str], min_run_length: int) -> list[str]:
    """Hysteresis: hold the previous regime until a NEW one persists for at
    least ``min_run_length`` consecutive bars. The very first non-warmup label
    becomes the initial committed regime.

    This is a one-pass causal filter — no look-ahead. Each bar's output depends
    only on bars at-or-before it.
    """
    if min_run_length <= 1:
        return list(regimes)

    out: list[str] = []
    committed: str | None = None  # last regime we've "accepted"
    candidate: str | None = None  # potential next regime currently building support
    candidate_count = 0

    for r in regimes:
        if r == REGIME_WARMUP:
            out.append(REGIME_WARMUP)
            candidate = None
            candidate_count = 0
            continue

        if committed is None:
            # First non-warmup bar: accept immediately. There's nothing prior
            # to protect, and refusing to commit would leave a long lead-in of
            # "warmup" labels that the caller cannot use.
            committed = r
            candidate = None
            candidate_count = 0
            out.append(committed)
            continue

        if r == committed:
            # Same as committed: reset any candidate tally.
            candidate = None
            candidate_count = 0
            out.append(committed)
            continue

        # r is different from committed: it's challenging.
        if candidate == r:
            candidate_count += 1
        else:
            candidate = r
            candidate_count = 1

        if candidate_count >= min_run_length:
            # New regime sustained long enough; promote it.
            committed = candidate
            candidate = None
            candidate_count = 0

        out.append(committed)

    return out


def detect_regime_series(
    market_df: pd.DataFrame,
    cfg: RegimeConfig | None = None,
) -> pd.DataFrame:
    """Compute the per-bar regime classification of a market proxy.

    Parameters
    ----------
    market_df
        OHLCV DataFrame with at least a ``Close`` column, indexed by date.
        Typically SPY 1d bars. The function does NOT fetch or cache data; the
        caller is responsible.
    cfg
        Optional :class:`RegimeConfig`. Defaults are first-pass calibration.

    Returns
    -------
    pd.DataFrame
        Same index as ``market_df``. Columns:
          * ``sharpe`` — rolling annualised Sharpe (``sharpe_window`` bars)
          * ``vol``    — realised annualised vol (``vol_window`` bars)
          * ``regime_raw`` — unsmoothed regime label per bar
          * ``regime`` — smoothed regime label per bar (hysteresis applied)

    Notes
    -----
    The function is referentially transparent: same input → same output. It is
    safe to call inside a tight loop (e.g. per-bar in a backtester) but if the
    same series is used repeatedly the caller should compute once and slice.
    """
    if cfg is None:
        cfg = RegimeConfig()

    if "Close" not in market_df.columns:
        raise ValueError("market_df must contain a 'Close' column")
    if cfg.sharpe_window < 2 or cfg.vol_window < 2:
        raise ValueError("sharpe_window and vol_window must be >= 2")

    close = market_df["Close"].squeeze().astype(float)
    returns = close.pct_change()

    sqrt_year = float(cfg.trading_days_per_year) ** 0.5

    mean_annual = returns.rolling(cfg.sharpe_window).mean() * cfg.trading_days_per_year
    std_annual = returns.rolling(cfg.sharpe_window).std() * sqrt_year
    # Sharpe with no risk-free rate. NaN propagates safely; we mask div-by-0.
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = mean_annual / std_annual.replace(0.0, np.nan)

    vol = returns.rolling(cfg.vol_window).std() * sqrt_year

    raw = [_classify(s, v, cfg) for s, v in zip(sharpe.values, vol.values)]
    smoothed = _smooth_min_run_length(raw, cfg.min_run_length)

    return pd.DataFrame(
        {
            "sharpe": sharpe.values,
            "vol": vol.values,
            "regime_raw": raw,
            "regime": smoothed,
        },
        index=market_df.index,
    )


# ── Convenience helpers ─────────────────────────────────────────────────────


def regime_at(market_df: pd.DataFrame, when: pd.Timestamp | str | None = None,
              cfg: RegimeConfig | None = None) -> str:
    """Return the regime label at a single point in time.

    If ``when`` is None, returns the regime at the last bar of ``market_df``.
    Useful as a single-point lookup wrapper around :func:`detect_regime_series`.
    """
    series = detect_regime_series(market_df, cfg)
    if when is None:
        return str(series["regime"].iloc[-1])
    ts = pd.Timestamp(when)
    # asof: most recent bar at or before ``when``
    matches = series.index <= ts
    if not matches.any():
        return REGIME_WARMUP
    return str(series.loc[matches, "regime"].iloc[-1])


def regime_distribution(market_df: pd.DataFrame,
                        cfg: RegimeConfig | None = None,
                        include_warmup: bool = False) -> dict[str, float]:
    """Return the empirical share of each regime over the input window.

    Useful to sanity-check that thresholds aren't producing a degenerate
    histogram (e.g. 99% lateral).
    """
    series = detect_regime_series(market_df, cfg)
    labels = series["regime"]
    if not include_warmup:
        labels = labels[labels != REGIME_WARMUP]
    if labels.empty:
        return {}
    counts = labels.value_counts(normalize=True)
    return {str(k): float(v) for k, v in counts.items()}


def regime_run_lengths(market_df: pd.DataFrame,
                       cfg: RegimeConfig | None = None) -> pd.DataFrame:
    """Compress the regime series into consecutive runs.

    Returns a DataFrame with one row per run: ``start``, ``end``, ``regime``,
    ``length`` (in bars). Excludes warmup runs.
    """
    series = detect_regime_series(market_df, cfg)
    reg = series["regime"]
    runs = []
    cur_start = None
    cur_label = None
    for ts, lab in reg.items():
        if lab == REGIME_WARMUP:
            if cur_label is not None:
                # close previous run
                runs.append((cur_start, prev_ts, cur_label))
                cur_label = None
            prev_ts = ts
            continue
        if cur_label is None:
            cur_start = ts
            cur_label = lab
        elif lab != cur_label:
            runs.append((cur_start, prev_ts, cur_label))
            cur_start = ts
            cur_label = lab
        prev_ts = ts
    if cur_label is not None:
        runs.append((cur_start, prev_ts, cur_label))

    if not runs:
        return pd.DataFrame(columns=["start", "end", "regime", "length"])
    df = pd.DataFrame(runs, columns=["start", "end", "regime"])
    # length in bars: count of bars between start and end inclusive within reg
    lengths = []
    for s, e in zip(df["start"], df["end"]):
        lengths.append(int(((reg.index >= s) & (reg.index <= e)).sum()))
    df["length"] = lengths
    return df
