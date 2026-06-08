"""
Tests for T-CAT-3 historical reaction + relevance (Sprint 5).

Fully offline: synthetic OHLCV frames and an injected price_loader. No DB, no
network.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from analysis.catalyst_reaction import (
    aggregate,
    build_historical_reaction,
    extract_dollar_amount,
    forward_return,
    lookup_reaction,
    relevance,
)


def _ramp_df(start="2026-01-01", n=40, step=1.0, start_price=100.0):
    """Business-day OHLCV where Close increases by ``step`` each bar."""
    idx = pd.bdate_range(start=start, periods=n)
    close = start_price + step * np.arange(n)
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1000}, index=idx)


# ── forward_return ───────────────────────────────────────────────────────────


def test_forward_return_basic():
    df = _ramp_df(n=20, step=1.0, start_price=100.0)  # 100,101,...
    # event on the first bar; +5 bars → 105/100 - 1 = 0.05
    r = forward_return(df, datetime(2026, 1, 1), 5)
    assert abs(r - 0.05) < 1e-9


def test_forward_return_enters_first_trading_day_on_or_after():
    df = _ramp_df(start="2026-01-01", n=20)
    # 2026-01-03 is a Saturday → entry should be Monday 2026-01-05 (3rd bdate)
    # bdates: 01-01(Thu),01-02(Fri),01-05(Mon)=idx2 price 102; +1 → idx3 103
    r = forward_return(df, datetime(2026, 1, 3), 1)
    assert abs(r - (103.0 / 102.0 - 1.0)) < 1e-9


def test_forward_return_none_when_insufficient_future():
    df = _ramp_df(n=10)
    assert forward_return(df, datetime(2026, 1, 1), 20) is None  # not enough bars


def test_forward_return_none_after_last_bar():
    df = _ramp_df(n=10)
    assert forward_return(df, datetime(2030, 1, 1), 1) is None


def test_forward_return_handles_missing_frame():
    assert forward_return(None, datetime(2026, 1, 1), 5) is None
    assert forward_return(pd.DataFrame(), datetime(2026, 1, 1), 5) is None


# ── aggregate ────────────────────────────────────────────────────────────────


def test_aggregate_stats():
    s = aggregate([0.1, -0.05, 0.2, None, float("nan")])
    assert s.count == 3
    assert abs(s.mean - (0.1 - 0.05 + 0.2) / 3) < 1e-9
    assert 0.0 <= s.hit_rate <= 1.0
    assert abs(s.hit_rate - 2 / 3) < 1e-9


def test_aggregate_empty():
    s = aggregate([])
    assert s.count == 0 and s.mean is None and s.hit_rate is None


# ── build_historical_reaction + lookup ───────────────────────────────────────


def test_build_and_lookup():
    df = _ramp_df(n=40, step=1.0, start_price=100.0)
    loader = lambda t: df  # every ticker uses the ramp
    events = [
        ("NVDA", "earnings_results", datetime(2026, 1, 1)),
        ("NVDA", "earnings_results", datetime(2026, 1, 2)),
        ("AAPL", "mna", datetime(2026, 1, 1)),
    ]
    table = build_historical_reaction(events, loader, horizons=(1, 5))
    assert table["horizons"] == [1, 5]
    # earnings_results global @5d has 2 samples, both positive (ramp up)
    er = table["by_event"]["earnings_results"]["5"]
    assert er["count"] == 2
    assert er["mean"] > 0
    assert er["hit_rate"] == 1.0
    # lookup falls back to global when per-ticker thin
    stat = lookup_reaction(table, "NVDA", "earnings_results", horizon=5, min_count=5)
    assert stat is not None and stat.count >= 2


def test_build_skips_events_without_date_or_type():
    df = _ramp_df(n=20)
    events = [("NVDA", "", datetime(2026, 1, 1)), ("NVDA", "mna", None)]
    table = build_historical_reaction(events, lambda t: df, horizons=(1,))
    assert table["by_event"] == {}


def test_lookup_returns_none_when_absent():
    table = {"by_event": {}, "by_ticker_event": {}, "horizons": [5]}
    assert lookup_reaction(table, "X", "mna", 5) is None


# ── relevance ────────────────────────────────────────────────────────────────


def test_extract_dollar_amount_units():
    assert extract_dollar_amount("wins $5 billion contract") == 5e9
    assert extract_dollar_amount("a $250 million deal") == 250e6
    assert extract_dollar_amount("$1.5B buyback") == 1.5e9
    assert extract_dollar_amount("pays $300,000 fine") == 300000.0
    assert extract_dollar_amount("no money here") is None
    assert extract_dollar_amount(None) is None


def test_extract_dollar_picks_largest():
    assert extract_dollar_amount("$5B deal plus a $10M fee") == 5e9


def test_relevance():
    assert relevance(5e9, 100e9) == 0.05
    assert relevance(None, 100e9) is None
    assert relevance(5e9, 0) is None
    assert relevance(5e9, None) is None


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
