"""
Portfolio-level risk utilities (T09 of the engine roadmap).

Pure, side-effect-free functions for measuring how diversified — or how
concentrated — a set of names is. The engine uses :func:`mean_correlation` as a
gate when filling free slots so it stops building a "portfolio" that is really
one trade wearing five tickers (the classic 5-big-tech book).

No I/O, no settings access: callers pass in price / return data and the
threshold directly. (Pre-Sprint-3 the threshold lived in
``config.settings_manager`` as ``max_avg_correlation``; both that setting and
its in-engine wiring were removed when attribution showed the gate never
fired in realistic setups. The math is kept for future use.)
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from config.constants import TRADING_DAYS_PER_YEAR

# Daily-returns lookback for the correlation gate, in trading days.
CORRELATION_LOOKBACK: int = 60
# Minimum overlapping observations required before a pairwise correlation is
# trusted — fewer than this and the pair is ignored (too noisy to act on).
MIN_CORRELATION_OBS: int = 20


def daily_returns(close: pd.Series, lookback: int = CORRELATION_LOOKBACK) -> pd.Series:
    """Simple daily pct-change returns over the last ``lookback`` bars.

    Index is preserved so correlations align on common dates. ``fill_method``
    is pinned to ``None`` to avoid the pandas forward-fill deprecation and to
    keep gaps honest (a missing bar should not synthesise a 0 % return).
    """
    s = pd.Series(close, dtype="float64")
    r = s.pct_change(fill_method=None).dropna()
    if lookback and len(r) > lookback:
        r = r.tail(lookback)
    return r


def mean_correlation(
    candidate: pd.Series,
    held: list[pd.Series],
    *,
    min_obs: int = MIN_CORRELATION_OBS,
) -> float | None:
    """Average pairwise Pearson correlation of ``candidate`` vs each ``held`` series.

    Each pair is aligned on its common (inner-joined) dates before correlating.
    A pair is skipped when it has fewer than ``min_obs`` overlapping points or
    when either leg is constant (undefined correlation).

    Returns ``None`` when there is nothing usable to compare against (empty
    ``held`` or every pair skipped). Callers treat ``None`` as "no information —
    do not block".
    """
    corrs: list[float] = []
    for h in held:
        joined = pd.concat([candidate, h], axis=1, join="inner").dropna()
        if len(joined) < min_obs:
            continue
        a = joined.iloc[:, 0]
        b = joined.iloc[:, 1]
        if a.std() == 0 or b.std() == 0:
            continue
        c = float(a.corr(b))
        if np.isfinite(c):
            corrs.append(c)
    if not corrs:
        return None
    return float(np.mean(corrs))


def diversification_ratio(
    returns: pd.DataFrame,
    weights: dict[str, float] | None = None,
) -> float:
    """Diversification ratio = (Σ wᵢ·σᵢ) / σ_portfolio.

    1.0 means no diversification benefit (a perfectly correlated book); the
    higher the value, the more the position-level vols cancel each other. Equal
    weights are used when ``weights`` is omitted. Degenerate inputs (no columns,
    zero portfolio variance) return 1.0 so the metric never blows up.
    """
    if returns is None or returns.shape[1] == 0:
        return 1.0
    cols = list(returns.columns)
    n = len(cols)
    if weights is None:
        w = np.full(n, 1.0 / n)
    else:
        w = np.array([float(weights.get(c, 0.0)) for c in cols], dtype="float64")
        total = w.sum()
        if total <= 0:
            return 1.0
        w = w / total

    cov = returns.cov().to_numpy()
    vols = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    weighted_avg_vol = float(np.dot(w, vols))
    port_var = float(w @ cov @ w)
    if port_var <= 0 or weighted_avg_vol <= 0:
        return 1.0
    return weighted_avg_vol / float(np.sqrt(port_var))


# ── Portfolio volatility targeting overlay (T09 → T10) ──────────────────────────


def returns_frame(
    tickers: list[str],
    history_provider: Callable[[str], pd.DataFrame | None],
    lookback: int = CORRELATION_LOOKBACK,
) -> pd.DataFrame:
    """Assemble a date-aligned daily-returns frame (one column per ticker).

    Tickers with no usable ``Close`` history are dropped. Returns an empty
    frame when nothing usable is found. Columns are aligned on their union of
    dates (NaN where a ticker has no observation that day), which is what
    ``DataFrame.cov`` expects — it uses pairwise-complete observations.
    """
    cols: dict[str, pd.Series] = {}
    for t in tickers:
        df = history_provider(t)
        if df is None or getattr(df, "empty", True) or "Close" not in getattr(df, "columns", []):
            continue
        r = daily_returns(df["Close"].astype(float), lookback)
        if not r.empty:
            cols[t] = r
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols)


def annualized_portfolio_vol(weights: dict[str, float], returns: pd.DataFrame) -> float:
    """Annualised portfolio volatility ``σ = sqrt(wᵀ Σ w) · sqrt(252)``.

    ``Σ`` is the daily-return covariance of ``returns``; ``weights`` maps ticker
    → portfolio weight (need not sum to 1 — the residual is implicit cash, which
    contributes no variance). Returns 0.0 for degenerate inputs so callers can
    safely treat "no estimate" as "do not scale".
    """
    if returns is None or returns.empty or returns.shape[1] == 0:
        return 0.0
    cols = list(returns.columns)
    w = np.array([float(weights.get(c, 0.0)) for c in cols], dtype="float64")
    if not np.any(w):
        return 0.0
    cov = returns.cov().to_numpy()
    if cov.shape[0] != len(w):
        return 0.0
    var_daily = float(w @ cov @ w)
    if not np.isfinite(var_daily) or var_daily <= 0:
        return 0.0
    return float(np.sqrt(var_daily) * np.sqrt(TRADING_DAYS_PER_YEAR))


def apply_portfolio_vol_overlay(
    weights: dict[str, float],
    returns: pd.DataFrame,
    vol_target_annual: float | None,
) -> tuple[dict[str, float], float | None, float]:
    """Scale a whole book down so its annualised σ does not exceed the target.

    Shared, allocation-mode-agnostic risk layer (T10): given target weights and
    a returns frame, estimate the book's annualised σ and, if it exceeds
    ``vol_target_annual``, multiply *every* weight by ``target / σ`` (< 1). The
    book is only ever scaled **down** — long-only, no leverage — with the freed
    weight implicitly going to cash. When σ is already at or below the target
    the weights are returned unchanged.

    ``vol_target_annual`` of ``None`` or ``<= 0`` disables the overlay entirely
    (the single knob doubles as the on/off switch — no separate flag).

    Returns ``(scaled_weights, sigma, factor)`` where ``sigma`` is the estimated
    annualised σ (``None`` when disabled) and ``factor`` is the applied multiplier
    (``1.0`` when disabled, undeterminable, or already within target).
    """
    if vol_target_annual is None or vol_target_annual <= 0:
        return dict(weights), None, 1.0
    sigma = annualized_portfolio_vol(weights, returns)
    if sigma <= 0:
        return dict(weights), sigma, 1.0
    factor = min(1.0, float(vol_target_annual) / sigma)
    if factor >= 1.0:
        return dict(weights), sigma, 1.0
    return {t: w * factor for t, w in weights.items()}, sigma, factor
