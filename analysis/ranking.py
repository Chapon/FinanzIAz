"""
Cross-sectional ranking utilities (Sprint 4 / T05).

Pure functions: no DB, no settings, no logging. The strategies and the harness
read the ``cross_sectional_*`` settings and pass the values in.

Two helpers:

* :func:`momentum_percentile` — relative momentum rank of each ticker against
  the rest of the universe at a given bar. Output ∈ [0, 1].
* :func:`combine_score` — blend an absolute strength (e.g. ``ml_probability``)
  with a cross-sectional percentile via a weight in [0, 1].

Design notes (full spec in docs/sprint4_t05_cross_sectional_spec.md):

* Tickers with fewer than ``lookback + 1`` close observations cannot be ranked
  and receive 0.5 (neutral). The same fallback applies to a NaN / inf return.
* Ranking uses ``rank(method="average")``: stable, handles ties by averaging
  positions. Equivalent to the classical empirical CDF when there are no ties.
* The function does *not* mutate inputs and tolerates an empty input dict.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

NEUTRAL_PERCENTILE: float = 0.5
"""Score assigned to tickers that cannot be ranked (insufficient history / NaN)."""


def momentum_percentile(
    closes_by_ticker: Mapping[str, pd.Series],
    lookback: int,
) -> dict[str, float]:
    """Cross-sectional momentum percentile per ticker.

    For each ticker with at least ``lookback + 1`` close observations, compute
    the return over the last ``lookback`` bars and convert it to a percentile
    rank in [0, 1] against the rest of the rankable tickers in the input.

    Tickers without enough history (or whose return is NaN / inf) get
    :data:`NEUTRAL_PERCENTILE`. If *no* ticker can be ranked, every ticker
    gets the neutral value — the caller can still combine with absolute
    strength and the cross-sectional contribution simply disappears.

    Parameters
    ----------
    closes_by_ticker:
        Mapping ticker → close-price series. Series must be indexed in
        ascending order; only the last ``lookback + 1`` rows are used.
    lookback:
        Number of bars to compute the return over. Must be a positive int.

    Returns
    -------
    dict[str, float]
        Ticker → percentile rank in [0, 1].

    Raises
    ------
    ValueError
        If ``lookback < 1``.
    """
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")

    # Step 1: compute return per ticker, separating "rankable" from "neutral".
    returns: dict[str, float] = {}
    for ticker, series in closes_by_ticker.items():
        if series is None or len(series) < lookback + 1:
            continue
        # Force numeric, drop NaN tail — caller may pass partly-NaN series.
        tail = pd.to_numeric(series.iloc[-(lookback + 1) :], errors="coerce")
        if tail.isna().any():
            continue
        start = float(tail.iloc[0])
        end = float(tail.iloc[-1])
        if start <= 0 or not math.isfinite(start) or not math.isfinite(end):
            continue
        ret = end / start - 1.0
        if not math.isfinite(ret):
            continue
        returns[ticker] = ret

    # Step 2: rank the rankable returns. Tickers not in ``returns`` get neutral.
    result: dict[str, float] = {ticker: NEUTRAL_PERCENTILE for ticker in closes_by_ticker}

    if not returns:
        return result

    # rank(method="average") on a 1-element series returns 1.0 which would map
    # to percentile 1.0. With a single rankable ticker there is no cross-section
    # to compare against — give it the neutral value too, so the score behaves
    # like "no cross-sectional information available" rather than "best in
    # class". This matches the convention used in `momentum_percentile` callers.
    if len(returns) == 1:
        only_ticker = next(iter(returns))
        result[only_ticker] = NEUTRAL_PERCENTILE
        return result

    ret_series = pd.Series(returns, dtype="float64")
    # Average ranking handles ties: tied returns share the midpoint of the
    # positions they would have occupied. Resulting ranks are in [1, N].
    ranks = ret_series.rank(method="average")
    n = len(ret_series)
    # Percentile = (rank - 1) / (n - 1) maps the worst → 0.0 and the best → 1.0.
    # This is the empirical CDF excluding the point itself — symmetric and
    # interpretable.
    percentiles = (ranks - 1.0) / (n - 1.0)

    for ticker, pct in percentiles.items():
        result[ticker] = float(pct)

    return result


def combine_score(absolute: float, relative: float, weight: float) -> float:
    """Blend an absolute strength with a cross-sectional percentile.

    Returns ``(1 - weight) * absolute + weight * relative``, clipped to
    [0, 1]. Both ``absolute`` and ``relative`` are expected in [0, 1]; the
    clamp is a safety net for callers that hand in something slightly outside
    the range (e.g. NaN-coerced defaults).

    ``weight`` must be in [0, 1]:

    * 0.0 → pure absolute (legacy behaviour).
    * 1.0 → pure cross-sectional.
    * 0.5 → equal-weight blend (Sprint 4 default).

    Parameters
    ----------
    absolute:
        Absolute strength (e.g. ``_default_strength`` from strategies.py).
    relative:
        Cross-sectional percentile (e.g. output of :func:`momentum_percentile`).
    weight:
        Blend factor for the cross-sectional component.

    Returns
    -------
    float
        Blended score in [0, 1].

    Raises
    ------
    ValueError
        If ``weight`` is outside [0, 1].
    """
    if not (0.0 <= weight <= 1.0):
        raise ValueError(f"weight must be in [0, 1], got {weight}")

    # NaN propagates silently otherwise — coerce to neutral, the rationale
    # matches the per-ticker fallback in momentum_percentile.
    if absolute is None or not math.isfinite(absolute):
        absolute = NEUTRAL_PERCENTILE
    if relative is None or not math.isfinite(relative):
        relative = NEUTRAL_PERCENTILE

    blended = (1.0 - weight) * float(absolute) + weight * float(relative)
    return float(max(0.0, min(1.0, blended)))


def blended_scores(
    strengths: Mapping[str, float],
    closes_by_ticker: Mapping[str, pd.Series],
    lookback: int,
    weight: float,
) -> dict[str, float]:
    """Convenience: compute percentiles + blend per ticker in one call.

    Useful at call sites that already have a ``strengths`` dict and a
    ``closes`` dict to hand in. Tickers in ``strengths`` but missing from
    ``closes_by_ticker`` are blended against the neutral percentile.
    """
    percentiles = momentum_percentile(closes_by_ticker, lookback)
    return {
        ticker: combine_score(strengths.get(ticker, 0.0), percentiles.get(ticker, NEUTRAL_PERCENTILE), weight)
        for ticker in strengths
    }
