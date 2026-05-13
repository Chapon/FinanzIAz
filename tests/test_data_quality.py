"""
Tests for ``data.quality`` — OHLCV validation + cleaning.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.quality import check_ohlcv, clean_ohlcv


def _df(rows: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = pd.Series(np.linspace(100, 110, rows), index=idx)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1_000_000.0,
        },
        index=idx,
    )


def test_check_ohlcv_clean_frame_has_no_issues():
    rep = check_ohlcv(_df())
    assert rep.is_usable
    assert not rep.has_issues()
    assert rep.rows == 30


def test_check_ohlcv_detects_zero_prices():
    df = _df()
    df.loc[df.index[5], "Close"] = 0
    df.loc[df.index[10], "Close"] = -1
    rep = check_ohlcv(df)
    assert rep.has_issues()
    assert rep.zero_or_negative.get("Close") == 2


def test_check_ohlcv_detects_calendar_gaps():
    df = _df(rows=30)
    # Drop a 5-day chunk to create a business-day gap
    df = pd.concat([df.iloc[:10], df.iloc[16:]])
    rep = check_ohlcv(df)
    assert len(rep.calendar_gaps) >= 1


def test_check_ohlcv_rejects_all_nan_close():
    df = _df()
    df["Close"] = np.nan
    rep = check_ohlcv(df)
    assert not rep.is_usable


def test_clean_ohlcv_replaces_zeros_and_ffills():
    df = _df()
    df.loc[df.index[5], "Close"] = 0  # zero → NaN → ffilled
    cleaned, _rep = clean_ohlcv(df, fill_method="ffill", max_fill_gap=2)
    assert cleaned is not None
    # No more zeros after cleaning
    assert (cleaned["Close"] > 0).all()


def test_clean_ohlcv_drops_duplicate_index():
    df = _df()
    dup = df.iloc[[5]]
    df_with_dup = pd.concat([df, dup])
    cleaned, rep = clean_ohlcv(df_with_dup)
    assert rep.duplicate_index == 1
    # Cleaned has unique index
    assert not cleaned.index.duplicated().any()


def test_clean_ohlcv_returns_none_for_unusable_input():
    """Empty / None inputs round-trip through with usable=False, no exception."""
    cleaned, rep = clean_ohlcv(None)
    assert cleaned is None
    assert not rep.is_usable

    _cleaned2, rep2 = clean_ohlcv(pd.DataFrame())
    assert not rep2.is_usable
