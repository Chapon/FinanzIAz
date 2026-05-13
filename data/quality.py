"""
OHLCV data-quality checks.

Public helpers
--------------
``DataQualityReport``  — summary dataclass returned by ``check_ohlcv``.
``check_ohlcv(df)``    — non-mutating quality scan: NaN counts, calendar
                         gaps, duplicate index, suspicious zero/negative
                         prices.
``clean_ohlcv(df, ...)`` — opinionated cleaner: drops zero/negative prices,
                         de-duplicates the index, optional forward-fill of
                         small NaN gaps. Returns ``(cleaned_df, report)``.

Design
------
- Pure-pandas, no yfinance / DB coupling, so it can be reused by the CSV
  importer, the backtest module, and any future data source.
- Emits structured ``logging`` records — never crashes on bad input.
- Does NOT silently impute: if more than ``max_fill_gap`` consecutive bars
  are missing, ``clean_ohlcv`` leaves them as NaN and reports the gap so the
  caller can decide what to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config.logging_config import get_logger

log = get_logger(__name__)


# Columns we expect on a yfinance OHLCV frame after ``auto_adjust=True``.
OHLC_COLS: tuple[str, ...] = ("Open", "High", "Low", "Close")
PRICE_COLS: tuple[str, ...] = OHLC_COLS  # alias


@dataclass
class DataQualityReport:
    """Summary of issues found in an OHLCV DataFrame."""

    rows: int = 0
    nan_counts: dict[str, int] = field(default_factory=dict)
    duplicate_index: int = 0
    zero_or_negative: dict[str, int] = field(default_factory=dict)
    calendar_gaps: list[tuple[pd.Timestamp, pd.Timestamp, int]] = field(default_factory=list)
    suspicious_jumps: int = 0  # |ret| > 0.5 in a single bar
    is_usable: bool = True  # False if no rows or all-NaN Close
    notes: list[str] = field(default_factory=list)

    def has_issues(self) -> bool:
        return (
            any(self.nan_counts.values())
            or self.duplicate_index > 0
            or any(self.zero_or_negative.values())
            or len(self.calendar_gaps) > 0
            or self.suspicious_jumps > 0
            or not self.is_usable
        )

    def summary(self) -> str:
        if not self.has_issues():
            return f"OK ({self.rows} rows, no issues)"
        parts: list[str] = [f"{self.rows} rows"]
        if any(self.nan_counts.values()):
            parts.append(f"NaNs={self.nan_counts}")
        if self.duplicate_index:
            parts.append(f"dup-idx={self.duplicate_index}")
        if any(self.zero_or_negative.values()):
            parts.append(f"zero/neg={self.zero_or_negative}")
        if self.calendar_gaps:
            parts.append(f"gaps={len(self.calendar_gaps)}")
        if self.suspicious_jumps:
            parts.append(f"|ret|>50% bars={self.suspicious_jumps}")
        if not self.is_usable:
            parts.append("UNUSABLE")
        return " · ".join(parts)


def _detect_calendar_gaps(
    idx: pd.DatetimeIndex,
    *,
    business_days_only: bool = True,
    threshold_days: int = 3,
) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """
    Detect gaps in a daily-bar index where consecutive samples are more
    than ``threshold_days`` apart (excluding weekends if ``business_days_only``).

    A "gap" is reported as ``(prev_date, next_date, missing_bars)`` so the
    caller can log or display them. We don't report 1-bar weekend skips —
    those are normal market closures.
    """
    if len(idx) < 2:
        return []

    gaps: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    if business_days_only:
        # Number of business days between each consecutive pair.
        # ``np.busday_count`` is fast and respects Mon-Fri (no holidays).
        # pandas 2.x tz-aware DatetimeIndex can't be cast directly to
        # datetime64[D]; use .date to strip tz before converting.
        prev = np.array([d.date() for d in idx[:-1]], dtype="datetime64[D]")
        nxt = np.array([d.date() for d in idx[1:]], dtype="datetime64[D]")
        deltas = np.busday_count(prev, nxt)
    else:
        deltas = np.diff(idx).astype("timedelta64[D]").astype(int)

    for i, delta in enumerate(deltas):
        if delta > threshold_days:
            gaps.append((idx[i], idx[i + 1], int(delta) - 1))
    return gaps


def check_ohlcv(
    df: pd.DataFrame | None,
    *,
    business_days_only: bool = True,
    gap_threshold_days: int = 3,
    jump_threshold: float = 0.5,
) -> DataQualityReport:
    """
    Run a non-mutating quality scan on an OHLCV DataFrame.

    ``jump_threshold`` is the absolute single-bar return that we flag as
    "suspicious" (default 50% — any genuine equity move ≥ that is rare and
    usually a stock split / data error).
    """
    rep = DataQualityReport()
    if df is None or len(df) == 0:
        rep.is_usable = False
        rep.notes.append("DataFrame is None or empty")
        return rep

    rep.rows = len(df)

    # NaN counts per column
    for col in PRICE_COLS:
        if col in df.columns:
            rep.nan_counts[col] = int(df[col].isna().sum())
    if "Volume" in df.columns:
        rep.nan_counts["Volume"] = int(df["Volume"].isna().sum())

    # Duplicate index entries (yfinance has been known to emit these)
    if isinstance(df.index, pd.DatetimeIndex):
        rep.duplicate_index = int(df.index.duplicated().sum())

    # Zero / negative price values (always wrong on equities)
    for col in PRICE_COLS:
        if col in df.columns:
            bad = ((df[col] <= 0) & df[col].notna()).sum()
            if bad:
                rep.zero_or_negative[col] = int(bad)

    # Calendar gaps
    if isinstance(df.index, pd.DatetimeIndex):
        rep.calendar_gaps = _detect_calendar_gaps(
            df.index,
            business_days_only=business_days_only,
            threshold_days=gap_threshold_days,
        )

    # Suspicious single-bar jumps
    if "Close" in df.columns:
        close = df["Close"].squeeze().dropna()
        if len(close) > 1:
            rets = close.pct_change().abs()
            rep.suspicious_jumps = int((rets > jump_threshold).sum())

    # Usability gate: at least one Close value
    if "Close" in df.columns:
        if df["Close"].dropna().empty:
            rep.is_usable = False
            rep.notes.append("All Close values are NaN")
    else:
        rep.is_usable = False
        rep.notes.append("Missing Close column")

    return rep


def clean_ohlcv(
    df: pd.DataFrame | None,
    *,
    fill_method: str = "ffill",  # "ffill" | "drop" | "none"
    max_fill_gap: int = 2,  # don't ffill more than N consecutive bars
    drop_zero_prices: bool = True,
) -> tuple[pd.DataFrame | None, DataQualityReport]:
    """
    Apply opinionated cleaning to an OHLCV frame and return the cleaned copy
    plus a report describing what was found / changed.

    Steps
    -----
    1. Quality scan via ``check_ohlcv``.
    2. Drop duplicated index rows (keep first).
    3. Replace zero/negative prices with NaN if ``drop_zero_prices``.
    4. Forward-fill **small** NaN gaps (≤ ``max_fill_gap`` consecutive bars).
       Larger gaps are preserved as NaN so consumers can decide.
    5. Return ``(cleaned_df, report)``.
    """
    report = check_ohlcv(df)
    if df is None or not report.is_usable:
        return df, report

    cleaned = df.copy()

    # 2. De-duplicate index (keep first occurrence)
    if report.duplicate_index:
        cleaned = cleaned[~cleaned.index.duplicated(keep="first")]

    # 3. Zero / negative prices → NaN (will be ffilled / dropped below)
    if drop_zero_prices:
        for col in PRICE_COLS:
            if col in cleaned.columns:
                mask = cleaned[col] <= 0
                if mask.any():
                    cleaned.loc[mask, col] = np.nan

    # 4. Forward-fill small gaps (limit prevents masking long outages)
    if fill_method == "ffill" and max_fill_gap > 0:
        for col in PRICE_COLS:
            if col in cleaned.columns:
                cleaned[col] = cleaned[col].ffill(limit=max_fill_gap)
    elif fill_method == "drop":
        cleaned = cleaned.dropna(subset=[c for c in PRICE_COLS if c in cleaned.columns])

    if report.has_issues():
        log.info("clean_ohlcv: %s", report.summary())

    return cleaned, report
