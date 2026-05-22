"""
Portfolio-level risk utilities (T09 of the engine roadmap).

Pure, side-effect-free functions for measuring how diversified — or how
concentrated — a set of names is. The engine uses :func:`mean_correlation` as a
gate when filling free slots so it stops building a "portfolio" that is really
one trade wearing five tickers (the classic 5-big-tech book).

No I/O, no settings access: callers pass in price / return data and the
threshold lives in ``config.settings_manager`` (``max_avg_correlation``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

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
