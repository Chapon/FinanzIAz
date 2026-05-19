"""
Average True Range (ATR) helper — Wilder's smoothing.

Used by the paper-trading engine's ATR-stop gate (T01 of the engine roadmap)
to size stop-loss, take-profit and trailing-stop triggers in volatility units
rather than fixed percentages.

ATR is the rolling Wilder-smoothed average of the True Range:

    TR_t = max(High_t - Low_t,
               |High_t - Close_{t-1}|,
               |Low_t  - Close_{t-1}|)

    ATR_0    = mean(TR_1 .. TR_n)               # bootstrap with simple MA
    ATR_t    = ((n-1) * ATR_{t-1} + TR_t) / n   # Wilder recursive smoothing

The helper is intentionally minimal — one well-tested function that returns
either the full ATR series or just the most recent value. Callers that need
percent-of-price (ATR%) can compute it themselves; this module stays in raw
price units to keep semantics unambiguous.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series | None:
    """
    Return the ATR series for an OHLCV DataFrame using Wilder's smoothing.

    Parameters
    ----------
    df
        OHLCV DataFrame with at least ``High``, ``Low``, ``Close`` columns
        (the yfinance standard schema used everywhere in this codebase).
    period
        Lookback in bars (default 14, the textbook Wilder default).

    Returns
    -------
    pd.Series indexed like ``df`` (NaN for the first ``period`` rows),
    or ``None`` if the input cannot produce a meaningful ATR (missing
    columns, all-NaN, fewer than ``period + 1`` bars).
    """
    if df is None or len(df) <= period:
        return None
    required = {"High", "Low", "Close"}
    if not required.issubset(df.columns):
        return None

    high = df["High"].astype(float).squeeze()
    low = df["Low"].astype(float).squeeze()
    close = df["Close"].astype(float).squeeze()

    if high.isna().all() or low.isna().all() or close.isna().all():
        return None

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Wilder smoothing: equivalent to EMA with alpha = 1/period (adjust=False)
    # bootstrapped with the simple mean of the first ``period`` TR values.
    # `ewm(alpha=1/period, adjust=False)` matches the Wilder recursion after
    # the first valid value, which we seed with the SMA below.
    tr_seed = tr.iloc[1 : period + 1].mean()  # first period TRs (TR_1..TR_n)
    if not np.isfinite(tr_seed):
        return None

    atr = tr.copy().astype(float)
    atr.iloc[: period + 1] = np.nan
    atr.iloc[period] = float(tr_seed)
    n = float(period)
    for i in range(period + 1, len(tr)):
        prev = atr.iloc[i - 1]
        cur_tr = tr.iloc[i]
        if not np.isfinite(prev) or not np.isfinite(cur_tr):
            atr.iloc[i] = prev
            continue
        atr.iloc[i] = ((n - 1.0) * prev + cur_tr) / n
    return atr


def compute_atr(df: pd.DataFrame, period: int = 14) -> float | None:
    """
    Return the latest ATR value as a float, or ``None`` if not computable.

    Convenience wrapper around ``compute_atr_series`` for callers that only
    need the most recent reading (the paper-trading engine's stop gate is
    one such caller).
    """
    series = compute_atr_series(df, period=period)
    if series is None:
        return None
    # Walk back to the last finite value — guards against trailing NaN
    # from forward-fill misses.
    for val in reversed(series.tolist()):
        if val is not None and np.isfinite(val) and val > 0:
            return float(val)
    return None
