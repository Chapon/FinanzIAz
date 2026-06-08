"""
Tests for the per-ticker catalyst feed (Sprint 5 · T-CAT-1 output utility).

Uses the in-memory ``test_db`` fixture; seeds a few NewsEvents and asserts the
read-only feed orders newest-first, filters by ticker/source, and sorts rows
with a NULL ``published_at`` to the bottom.
"""

from __future__ import annotations

from datetime import datetime

from database.models import NewsEvent, session_scope
from scripts.news_feed import recent_news


def _seed():
    rows = [
        # (ticker, title, source, published_at, hash)
        ("NVDA", "NVDA newest", "yfinance", datetime(2026, 6, 6, 10, 0), "h1"),
        ("NVDA", "NVDA older", "sec_8k", datetime(2026, 6, 1, 9, 0), "h2"),
        ("NVDA", "NVDA undated", "yahoo_rss", None, "h3"),
        ("PLTR", "PLTR news", "yfinance", datetime(2026, 6, 5, 12, 0), "h4"),
    ]
    with session_scope() as s:
        for ticker, title, source, pub, h in rows:
            s.add(
                NewsEvent(
                    ticker=ticker,
                    title=title,
                    source=source,
                    url=None,
                    published_at=pub,
                    content_hash=h,
                )
            )


def test_recent_news_newest_first_and_nulls_last(test_db):
    _seed()
    rows = recent_news(ticker="NVDA")
    titles = [r.title for r in rows]
    assert titles == ["NVDA newest", "NVDA older", "NVDA undated"]


def test_recent_news_filters_by_ticker(test_db):
    _seed()
    rows = recent_news(ticker="PLTR")
    assert [r.ticker for r in rows] == ["PLTR"]
    assert rows[0].title == "PLTR news"


def test_recent_news_filters_by_source(test_db):
    _seed()
    rows = recent_news(source="sec_8k")
    assert len(rows) == 1
    assert rows[0].source == "sec_8k"
    assert rows[0].ticker == "NVDA"


def test_recent_news_filters_by_ticker_list(test_db):
    _seed()
    rows = recent_news(tickers=["NVDA", "PLTR"])
    assert {r.ticker for r in rows} == {"NVDA", "PLTR"}
    # newest across both is NVDA 2026-06-06
    assert rows[0].title == "NVDA newest"


def test_recent_news_respects_limit(test_db):
    _seed()
    rows = recent_news(tickers=["NVDA", "PLTR"], limit=2)
    assert len(rows) == 2


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
