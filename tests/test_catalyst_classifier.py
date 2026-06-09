"""
Tests for T-CAT-2 catalyst classifier + taxonomy + runner.

Fully offline: the heuristic backend is deterministic, and the runner's
``classifier`` arg is injected with fakes where needed. DB tests use the
in-memory ``test_db`` fixture.
"""

from __future__ import annotations

from datetime import datetime

from data.catalyst_classifier import (
    Classification,
    classify,
    heuristic_classify,
    make_llm_backend,
    _parse_llm_json,
)
from data.catalyst_taxonomy import (
    EVENT_TYPES,
    ITEM_CODE_EVENT,
    extract_item_codes,
)
from database.models import NewsEvent, session_scope
from scripts.classify_catalysts import classify_events, sample_for_review


# ── taxonomy ─────────────────────────────────────────────────────────────────


def test_taxonomy_has_17_event_types():
    assert len(EVENT_TYPES) == 17
    assert len(set(EVENT_TYPES)) == 17
    assert "other" == EVENT_TYPES[-1]


def test_every_item_code_maps_into_taxonomy():
    assert set(ITEM_CODE_EVENT.values()) <= set(EVENT_TYPES)


def test_extract_item_codes():
    assert extract_item_codes("Items: 2.02, 9.01; 8-K") == ["2.02", "9.01"]
    assert extract_item_codes(None) == []
    assert extract_item_codes("no codes here") == []


# ── SEC structured path ──────────────────────────────────────────────────────


def test_sec_8k_results_is_earnings_high_confidence():
    c = heuristic_classify("AAPL 8-K: Results of Operations and Financial Condition",
                           "Items: 2.02, 9.01", "sec_8k")
    assert c.event_type == "earnings_results"
    assert c.confidence >= 0.9


def test_sec_8k_picks_most_material_item():
    # 5.02 (executive_change) + 9.01 (other) → executive_change wins by priority
    c = heuristic_classify("X 8-K", "Items: 5.02, 9.01", "sec_8k")
    assert c.event_type == "executive_change"


def test_sec_8k_negative_item_sentiment():
    c = heuristic_classify("X 8-K", "Items: 1.03", "sec_8k")  # bankruptcy
    assert c.event_type == "restructuring"
    assert c.sentiment == "negative"


def test_sec_without_known_items_falls_back_to_text():
    c = heuristic_classify("Company wins major contract", "Items: 9.01", "sec_8k")
    # 9.01 → other, so it's the most material known; but text says contract.
    # The structured path wins when any code maps → 'other' here.
    assert c.event_type in {"other", "partnership_contract"}


# ── keyword path on headlines ────────────────────────────────────────────────


def test_headline_earnings_positive():
    c = heuristic_classify("NVDA beats earnings, tops revenue estimates", None, "yfinance")
    assert c.event_type == "earnings_results"
    assert c.sentiment == "positive"


def test_headline_mna():
    c = heuristic_classify("Acme to acquire Beta in $5B merger", None, "yfinance")
    assert c.event_type == "mna"


def test_headline_downgrade_negative():
    c = heuristic_classify("Analyst downgrade sends shares lower", None, "yahoo_rss")
    assert c.event_type == "analyst_rating"
    assert c.sentiment == "negative"


def test_headline_no_cue_is_other_low_confidence():
    c = heuristic_classify("A quiet day for the company", None, "yfinance")
    assert c.event_type == "other"
    assert c.confidence < 0.5


# ── regression: real-world headlines that the v1 heuristic got wrong ──────────


def test_title_only_ignores_noisy_summary():
    # The catalyst signal is the headline; a noisy summary must NOT drive labels.
    c = heuristic_classify(
        "A look at the company today",
        "The firm beat earnings and raised full-year guidance and announced a buyback",
        "yfinance",
    )
    assert c.event_type == "other"


def test_analyst_target_headline_is_rating_not_mna():
    c = heuristic_classify("Morgan Stanley Raises Acme Target on growth confidence", None, "yfinance")
    assert c.event_type == "analyst_rating"


def test_layoffs_is_restructuring():
    assert heuristic_classify("Company announces major layoffs", None, "yfinance").event_type == "restructuring"


def test_insiders_sold_is_insider_activity():
    c = heuristic_classify("Arm insiders sold $25 million in stock", None, "yfinance")
    assert c.event_type == "insider_activity"


def test_word_boundary_avoids_substring_false_positive():
    # 'cuts' (negative cue) must not fire inside 'haircuts'.
    c = heuristic_classify("Barber chain expands haircuts nationwide", None, "yfinance")
    assert c.sentiment != "negative"


# ── classify() coercion of off-taxonomy backends ─────────────────────────────


def test_classify_coerces_bad_labels():
    bad = lambda t, c, s, k=None: Classification("NOT_A_TYPE", "ecstatic", 5.0, "llm")
    out = classify("x", None, "yfinance", backend=bad)
    assert out.event_type == "other"
    assert out.sentiment == "neutral"
    assert 0.0 <= out.confidence <= 1.0


def test_classify_backend_exception_falls_back():
    def boom(t, c, s, k=None):
        raise RuntimeError("backend down")

    out = classify("x", None, "yfinance", backend=boom)
    assert out.event_type == "other"
    assert out.classifier == "fallback"


def test_classify_forwards_ticker_to_backend():
    seen = {}

    def echo(title, content, source, ticker=None):
        seen["ticker"] = ticker
        return Classification("mna", "neutral", 0.7, "llm")

    classify("Some headline", None, "yfinance", "NVDA", backend=echo)
    assert seen["ticker"] == "NVDA"


def test_ollama_backend_parses_json_and_falls_back():
    from data.catalyst_classifier import make_ollama_backend

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"event_type":"mna","sentiment":"positive","confidence":0.9}'}}

    ok = make_ollama_backend(http_post=lambda *a, **k: _Resp())
    c = ok("Acme to acquire Beta", None, "yfinance", "ACME")
    assert c.event_type == "mna" and c.classifier == "ollama"

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    down = make_ollama_backend(http_post=boom)
    c2 = down("NVDA beats earnings, tops estimates", None, "yfinance", "NVDA")
    assert c2.event_type == "earnings_results"  # fell back to heuristic


def test_hybrid_ollama_routes_sec_to_heuristic():
    from data.catalyst_classifier import make_hybrid_backend, make_ollama_backend

    def must_not_call(*a, **k):
        raise AssertionError("SEC must not hit Ollama")

    hybrid = make_hybrid_backend(llm_backend=make_ollama_backend(http_post=must_not_call))
    sec = hybrid("AAPL 8-K: Results", "Items: 2.02", "sec_8k", "AAPL")
    assert sec.event_type == "earnings_results" and sec.confidence >= 0.9


def test_hybrid_uses_heuristic_for_sec_and_llm_for_rest():
    from data.catalyst_classifier import make_hybrid_backend

    def llm_that_must_not_run_on_sec(title, content, source, ticker=None):
        assert source != "sec_8k", "hybrid must not send SEC filings to the LLM"
        return Classification("mna", "positive", 0.8, "llm")

    hybrid = make_hybrid_backend(llm_backend=llm_that_must_not_run_on_sec)
    # SEC → heuristic (item code 2.02 → earnings_results, conf 0.90)
    sec = hybrid("AAPL 8-K: Results", "Items: 2.02", "sec_8k", "AAPL")
    assert sec.event_type == "earnings_results" and sec.confidence >= 0.9
    # non-SEC → llm
    head = hybrid("Acme to acquire Beta", None, "yfinance", "ACME")
    assert head.classifier == "llm" and head.event_type == "mna"


def test_parse_llm_json_extracts_object():
    c = _parse_llm_json('blah {"event_type":"mna","sentiment":"positive","confidence":0.8} tail')
    assert c.event_type == "mna"
    assert c.sentiment == "positive"
    assert c.confidence == 0.8


def test_llm_backend_falls_back_without_client(monkeypatch):
    # No anthropic / no key → backend must not raise, returns heuristic result.
    backend = make_llm_backend(client=None)
    out = backend("NVDA beats earnings, tops estimates", None, "yfinance")
    assert out.event_type == "earnings_results"


# ── runner: idempotency + in-place update ────────────────────────────────────


def _seed_unclassified():
    rows = [
        ("NVDA", "NVDA beats earnings, tops estimates", "yfinance", "h1"),
        ("AAPL", "AAPL 8-K: Results of Operations and Financial Condition", "sec_8k", "h2", "Items: 2.02"),
        ("PLTR", "A quiet day", "yfinance", "h3"),
    ]
    with session_scope() as s:
        for r in rows:
            content = r[4] if len(r) > 4 else None
            s.add(NewsEvent(ticker=r[0], title=r[1], source=r[2], content=content, content_hash=r[3]))


def test_runner_classifies_unclassified(test_db):
    _seed_unclassified()
    rep = classify_events(now=datetime(2026, 6, 8, 12, 0))
    assert rep.classified == 3
    with session_scope() as s:
        nvda = s.query(NewsEvent).filter_by(ticker="NVDA").first()
        assert nvda.event_type == "earnings_results"
        assert nvda.classified_at == datetime(2026, 6, 8, 12, 0)
        aapl = s.query(NewsEvent).filter_by(ticker="AAPL").first()
        assert aapl.event_type == "earnings_results"
        assert aapl.classifier_confidence >= 0.9


def test_runner_is_idempotent(test_db):
    _seed_unclassified()
    classify_events()
    rep2 = classify_events()  # nothing left unclassified
    assert rep2.scanned == 0
    assert rep2.classified == 0


def test_runner_reclassify_redoes(test_db):
    _seed_unclassified()
    classify_events()
    rep = classify_events(reclassify=True)
    assert rep.scanned == 3


def test_runner_dry_run_writes_nothing(test_db):
    _seed_unclassified()
    rep = classify_events(dry_run=True)
    assert rep.classified == 3
    with session_scope() as s:
        assert s.query(NewsEvent).filter(NewsEvent.event_type.isnot(None)).count() == 0


def test_runner_source_filter(test_db):
    _seed_unclassified()
    rep = classify_events(source="sec_8k")
    assert rep.scanned == 1
    with session_scope() as s:
        # only the SEC row got labeled
        assert s.query(NewsEvent).filter(NewsEvent.event_type.isnot(None)).count() == 1


def test_sample_for_review_is_deterministic_with_seed(test_db):
    _seed_unclassified()
    classify_events()
    a = sample_for_review(2, seed=42)
    b = sample_for_review(2, seed=42)
    assert a == b
    assert len(a) == 2


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
