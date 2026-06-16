"""
Tests for T-CAT-0 harvester (Sprint 5 · Catalyst Intelligence Engine).

Fully offline: no network, no real yfinance. The harvester's ``collector`` arg
is injected with deterministic fakes, and the DB is the in-memory ``test_db``
fixture from conftest. We assert the two things T-CAT-0 must guarantee:
idempotency (re-running adds no duplicates) and point-in-time append-only
(one estimate snapshot per ticker/metric/period/day).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from data.news_sources import (
    EstimateSnapshot,
    NewsItem,
    _CollectResult,
    content_hash,
    parse_yf_news_item,
)
from database.models import AnalystEstimateSnapshot, NewsEvent, session_scope
from scripts.harvest_catalysts import canonical_url, harvest, resolve_universe


# ── fake collectors ──────────────────────────────────────────────────────────


def _fixed_collector(news_by_ticker, est_by_ticker=None):
    est_by_ticker = est_by_ticker or {}

    def _collect(ticker, sources=None):
        return _CollectResult(
            news=list(news_by_ticker.get(ticker, [])),
            estimates=list(est_by_ticker.get(ticker, [])),
        )

    return _collect


def _news(ticker, title, when=None, url=None, source="yfinance"):
    return NewsItem(ticker=ticker, title=title, source=source, published_at=when, url=url)


# ── content_hash ─────────────────────────────────────────────────────────────


def test_content_hash_ignores_case_and_whitespace():
    when = datetime(2026, 6, 5, 14, 30)
    a = content_hash("NVDA", "Nvidia  Beats   Earnings", when)
    b = content_hash("nvda", "nvidia beats earnings", when)
    assert a == b


def test_content_hash_differs_by_hour():
    a = content_hash("NVDA", "headline", datetime(2026, 6, 5, 14, 0))
    b = content_hash("NVDA", "headline", datetime(2026, 6, 5, 16, 0))
    assert a != b


# ── parse_yf_news_item (both yfinance shapes) ────────────────────────────────


def test_parse_yf_news_legacy_shape():
    raw = {"title": "NVDA pops", "link": "http://x", "providerPublishTime": 1_700_000_000}
    item = parse_yf_news_item("nvda", raw)
    assert item is not None
    assert item.ticker == "NVDA"
    assert item.url == "http://x"
    assert item.published_at is not None


def test_parse_yf_news_nested_shape():
    raw = {
        "content": {
            "title": "PLTR wins contract",
            "summary": "big deal",
            "pubDate": "2026-06-05T14:30:00Z",
            "canonicalUrl": {"url": "http://y"},
        }
    }
    item = parse_yf_news_item("PLTR", raw)
    assert item is not None
    assert item.title == "PLTR wins contract"
    assert item.content == "big deal"
    assert item.url == "http://y"
    assert item.published_at == datetime(2026, 6, 5, 14, 30)


def test_parse_yf_news_no_title_returns_none():
    assert parse_yf_news_item("X", {"link": "http://x"}) is None
    assert parse_yf_news_item("X", "not a dict") is None


# ── harvest: basic insert ────────────────────────────────────────────────────


def test_harvest_inserts_news_and_estimates(test_db):
    when = datetime(2026, 6, 5, 14, 0)
    collector = _fixed_collector(
        {"NVDA": [_news("NVDA", "beat", when)]},
        {"NVDA": [EstimateSnapshot("NVDA", "eps", "0q", 1.8, 42)]},
    )
    rep = harvest(["NVDA"], collector=collector, now=datetime(2026, 6, 5, 18, 0))
    assert rep.news_new == 1
    assert rep.est_new == 1
    with session_scope() as s:
        assert s.query(NewsEvent).count() == 1
        assert s.query(AnalystEstimateSnapshot).count() == 1
        row = s.query(AnalystEstimateSnapshot).first()
        # snapshot_date truncated to midnight of the run day
        assert row.snapshot_date == datetime(2026, 6, 5, 0, 0)


# ── harvest: idempotency ─────────────────────────────────────────────────────


def test_harvest_is_idempotent_same_day(test_db):
    when = datetime(2026, 6, 5, 14, 0)
    collector = _fixed_collector(
        {"NVDA": [_news("NVDA", "beat", when)]},
        {"NVDA": [EstimateSnapshot("NVDA", "eps", "0q", 1.8, 42)]},
    )
    now = datetime(2026, 6, 5, 18, 0)
    harvest(["NVDA"], collector=collector, now=now)
    rep2 = harvest(["NVDA"], collector=collector, now=now)
    assert rep2.news_new == 0
    assert rep2.news_dup == 1
    assert rep2.est_new == 0
    assert rep2.est_dup == 1
    with session_scope() as s:
        assert s.query(NewsEvent).count() == 1
        assert s.query(AnalystEstimateSnapshot).count() == 1


def test_news_dedup_within_same_batch(test_db):
    when = datetime(2026, 6, 5, 14, 0)
    dupe = _news("NVDA", "beat", when)
    collector = _fixed_collector({"NVDA": [dupe, dupe]})
    rep = harvest(["NVDA"], collector=collector, now=when)
    assert rep.news_new == 1
    assert rep.news_dup == 1
    with session_scope() as s:
        assert s.query(NewsEvent).count() == 1


# ── canonical_url ────────────────────────────────────────────────────────────


def test_canonical_url_none_and_empty():
    assert canonical_url(None) is None
    assert canonical_url("") is None
    assert canonical_url("   ") is None
    assert canonical_url("not-a-url") is None  # no host


def test_canonical_url_strips_tracking_www_slash_scheme():
    a = canonical_url("http://www.Reuters.com/tech/nvda-deal/?utm_source=x&fbclid=y")
    b = canonical_url("https://reuters.com/tech/nvda-deal")
    assert a == b == "https://reuters.com/tech/nvda-deal"


def test_canonical_url_keeps_meaningful_query_sorted():
    assert canonical_url("https://x.com/a?b=2&a=1#frag") == "https://x.com/a?a=1&b=2"


# ── harvest: URL dedup across sources ────────────────────────────────────────


def test_url_dedup_within_batch_across_sources(test_db):
    when = datetime(2026, 6, 5, 14, 0)
    # Same article, two outlets, DIFFERENT titles → content_hash differs, but the
    # canonical URL is identical (one has tracking params) → must collapse to 1.
    a = _news("NVDA", "NVDA lands deal", when, url="https://www.reuters.com/nvda?utm_source=z", source="finnhub:Reuters")
    b = _news("NVDA", "Nvidia signs supply pact", when, url="https://reuters.com/nvda", source="yfinance")
    collector = _fixed_collector({"NVDA": [a, b]})
    rep = harvest(["NVDA"], collector=collector, now=when)
    assert rep.news_new == 1
    assert rep.news_dup == 1
    with session_scope() as s:
        assert s.query(NewsEvent).count() == 1


def test_url_dedup_against_already_stored_row(test_db):
    when = datetime(2026, 6, 5, 14, 0)
    first = _news("NVDA", "NVDA lands deal", when, url="https://reuters.com/nvda")
    harvest(["NVDA"], collector=_fixed_collector({"NVDA": [first]}), now=when)
    # A later run sees the same URL with a different headline → still a dup.
    again = _news("NVDA", "Totally different headline", when, url="https://reuters.com/nvda")
    rep = harvest(["NVDA"], collector=_fixed_collector({"NVDA": [again]}), now=when)
    assert rep.news_new == 0
    assert rep.news_dup == 1
    with session_scope() as s:
        assert s.query(NewsEvent).count() == 1


def test_distinct_urls_are_not_deduped(test_db):
    when = datetime(2026, 6, 5, 14, 0)
    a = _news("NVDA", "story one", when, url="https://reuters.com/one")
    b = _news("NVDA", "story two", when, url="https://reuters.com/two")
    rep = harvest(["NVDA"], collector=_fixed_collector({"NVDA": [a, b]}), now=when)
    assert rep.news_new == 2
    with session_scope() as s:
        assert s.query(NewsEvent).count() == 2


# ── harvest: estimate append-only across days ────────────────────────────────


def test_estimate_one_snapshot_per_day(test_db):
    est = {"NVDA": [EstimateSnapshot("NVDA", "eps", "0q", 1.8, 42)]}
    collector = _fixed_collector({}, est)
    harvest(["NVDA"], collector=collector, now=datetime(2026, 6, 5, 18, 0))
    harvest(["NVDA"], collector=collector, now=datetime(2026, 6, 6, 18, 0))
    with session_scope() as s:
        assert s.query(AnalystEstimateSnapshot).count() == 2  # one per day


# ── harvest: a failing ticker does not sink the run ──────────────────────────


def test_failing_source_is_isolated(test_db):
    when = datetime(2026, 6, 5, 14, 0)

    def collector(ticker, sources=None):
        if ticker == "BAD":
            raise RuntimeError("source down")
        return _CollectResult(news=[_news(ticker, "ok", when)])

    rep = harvest(["BAD", "NVDA"], collector=collector, now=when)
    assert "BAD" in rep.failed
    assert rep.news_new == 1
    with session_scope() as s:
        tickers = {r.ticker for r in s.query(NewsEvent).all()}
        assert tickers == {"NVDA"}


# ── harvest: dry-run writes nothing ──────────────────────────────────────────


def test_dry_run_writes_nothing(test_db):
    when = datetime(2026, 6, 5, 14, 0)
    collector = _fixed_collector({"NVDA": [_news("NVDA", "beat", when)]})
    rep = harvest(["NVDA"], collector=collector, now=when, dry_run=True)
    assert rep.news_new == 1  # counted, but...
    with session_scope() as s:
        assert s.query(NewsEvent).count() == 0  # ...not persisted


# ── resolve_universe: watchlist ∪ positions ──────────────────────────────────


def test_resolve_universe_unions_watchlist_and_positions(test_db):
    from paper_trading.models import PaperAccount, PaperPosition, PaperWatchlistItem

    with session_scope() as s:
        acct = PaperAccount(name="Sim Test")
        s.add(acct)
        s.flush()
        s.add(PaperWatchlistItem(account_id=acct.id, ticker="NVDA"))
        s.add(PaperWatchlistItem(account_id=acct.id, ticker="PLTR"))
        s.add(PaperPosition(account_id=acct.id, ticker="RKLB", shares=10, avg_cost=5.0))
        s.add(PaperPosition(account_id=acct.id, ticker="ZERO", shares=0, avg_cost=5.0))  # excluded
        acct_id = acct.id

    universe = resolve_universe(acct_id)
    assert universe == ["NVDA", "PLTR", "RKLB"]  # sorted, ZERO (0 shares) excluded


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
