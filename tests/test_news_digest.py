"""
Tests for analysis/news_digest.py (Noticias tab backend).

All offline: ranking over fake rows, briefing prompt/fallback determinism,
Ollama briefer with injected ``http_post``, and the window query against the
in-memory ``test_db`` fixture.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from analysis.news_digest import (
    DigestItem,
    _Row,
    briefing_prompt,
    classify_missing,
    default_window,
    fallback_briefing,
    fetch_news_window,
    harvested_today,
    make_ollama_briefer,
    rank_news,
    refresh_due,
    run_catalyst_harvest_only,
    run_catalyst_refresh,
    unclassified_count,
)


def _row(
    id=1,
    ticker="NVDA",
    title="t",
    source="yahoo_rss",
    url=None,
    published_at=None,
    event_type=None,
    sentiment=None,
    conf=None,
):
    return _Row(
        id=id,
        ticker=ticker,
        title=title,
        source=source,
        url=url,
        published_at=published_at,
        event_type=event_type,
        sentiment=sentiment,
        classifier_confidence=conf,
    )


# ── rank_news ────────────────────────────────────────────────────────────────


def test_rank_orders_by_abs_impact_desc():
    rows = [
        _row(id=1, title="ruido", event_type="stock_movement", sentiment="positive", conf=0.6),
        _row(id=2, title="guidance cut", event_type="guidance_cut", sentiment="negative", conf=0.9),
        _row(id=3, title="m&a", event_type="mna", sentiment="positive", conf=0.9),
    ]
    ranked = rank_news(rows)
    # prior(mna)=0.85 y prior(guidance_cut)=0.80 >> prior(stock_movement)=0.15
    assert [it.news_id for it in ranked][:2] == [3, 2]
    assert ranked[-1].news_id == 1
    # el negativo conserva signo negativo, el ranking usa |impacto|
    cut = next(it for it in ranked if it.news_id == 2)
    assert cut.impact < 0 and cut.direction == -1


def test_rank_unclassified_rows_sink_but_dont_crash():
    rows = [
        _row(id=1, title="sin clasificar"),  # event_type/sentiment/conf = None
        _row(id=2, title="resultados", event_type="earnings_results", sentiment="positive", conf=0.8),
    ]
    ranked = rank_news(rows)
    assert ranked[0].news_id == 2
    # neutral/None → direction 0 → impacto 0
    assert ranked[1].impact == 0.0


def test_rank_dedups_same_ticker_title_keeps_best():
    rows = [
        _row(id=1, title="NVDA beats estimates", source="yahoo_rss",
             event_type="stock_movement", sentiment="positive", conf=0.5),
        _row(id=2, title="NVDA beats  estimates", source="sec_8k",
             event_type="earnings_results", sentiment="positive", conf=0.9),
    ]
    ranked = rank_news(rows)
    assert len(ranked) == 1
    assert ranked[0].news_id == 2  # se queda la copia mejor clasificada


def test_rank_top_n_and_empty():
    assert rank_news([]) == []
    rows = [
        _row(id=i, title=f"t{i}", event_type="mna", sentiment="positive", conf=0.9)
        for i in range(10)
    ]
    assert len(rank_news(rows, top_n=3)) == 3


def test_rank_failsoft_on_bad_market_cap_loader():
    def boom(_ticker):
        raise RuntimeError("yfinance down")

    rows = [_row(id=1, event_type="mna", sentiment="positive", conf=0.9)]
    ranked = rank_news(rows, market_cap_loader=boom)
    assert len(ranked) == 1 and ranked[0].impact > 0


# ── classify_missing ─────────────────────────────────────────────────────────


def test_classify_missing_fills_unclassified_rows_only():
    rows = [
        _row(id=1, title="Company agrees to acquire rival in $5 billion deal"),
        _row(id=2, title="ya clasificada", event_type="mna", sentiment="positive", conf=0.9),
    ]
    out = classify_missing(rows)
    # la fila NULL recibe clasificación heurística (al menos deja de ser None)
    assert out[0].event_type is not None
    assert out[0].classifier_confidence is not None
    # la ya clasificada pasa intacta (qwen/nocturno es la fuente de verdad)
    assert out[1] is rows[1]


def test_classify_missing_then_rank_gives_nonzero_impact():
    rows = [
        _row(id=1, title="Company raises full-year guidance after record quarter"),
    ]
    ranked = rank_news(classify_missing(rows))
    # con clasificación al vuelo el impacto ya no queda clavado en 0 genérico
    assert ranked[0].event_type is not None


# ── briefing ─────────────────────────────────────────────────────────────────


def _items(n=2):
    rows = [
        _row(id=i, ticker=f"TK{i}", title=f"titular {i}",
             event_type="mna", sentiment="positive", conf=0.9,
             published_at=datetime(2026, 6, 12, 9, 0))
        for i in range(n)
    ]
    return rank_news(rows)


def test_briefing_prompt_contains_headlines_and_caps_items():
    items = _items(20)
    prompt = briefing_prompt(items, max_items=5)
    assert "titular 0" in prompt
    assert prompt.count("\n") == 5  # encabezado + 5 líneas


def test_fallback_briefing_deterministic_and_mentions_top():
    items = _items(3)
    text = fallback_briefing(items)
    assert "3 noticias" in text
    assert items[0].ticker in text
    assert fallback_briefing([]) == "Sin noticias en la ventana seleccionada."


def test_ollama_briefer_happy_path_with_injected_post():
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "Briefing de prueba."}}

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return FakeResp()

    briefer = make_ollama_briefer(model="qwen2.5:14b", http_post=fake_post)
    out = briefer(_items())
    assert out == "Briefing de prueba."
    assert captured["url"].endswith("/api/chat")
    assert captured["payload"]["model"] == "qwen2.5:14b"


def test_ollama_briefer_returns_none_on_failure_and_empty_items():
    def fake_post(url, json=None, timeout=None):
        raise ConnectionError("ollama down")

    briefer = make_ollama_briefer(http_post=fake_post)
    assert briefer(_items()) is None  # caller cae a fallback_briefing
    assert briefer([]) is None


# ── fetch_news_window (in-memory DB) ─────────────────────────────────────────


def _seed(rows):
    from database.models import NewsEvent, session_scope

    with session_scope() as s:
        for i, (ticker, title, pub, fetched) in enumerate(rows):
            s.add(
                NewsEvent(
                    ticker=ticker,
                    title=title,
                    source="yahoo_rss",
                    published_at=pub,
                    fetched_at=fetched,
                    content_hash=f"h{i}",
                )
            )


def test_fetch_window_filters_by_published_at(test_db):
    now = datetime(2026, 6, 12, 12, 0)
    _seed(
        [
            ("NVDA", "dentro", now - timedelta(hours=3), now),
            ("NVDA", "fuera", now - timedelta(days=5), now - timedelta(days=5)),
        ]
    )
    since, until = default_window(1, now=now)
    rows = fetch_news_window(since, until=until)
    assert [r.title for r in rows] == ["dentro"]


def test_fetch_window_undated_rows_use_fetched_at(test_db):
    now = datetime(2026, 6, 12, 12, 0)
    _seed(
        [
            ("NVDA", "sin fecha reciente", None, now - timedelta(hours=2)),
            ("NVDA", "sin fecha vieja", None, now - timedelta(days=9)),
        ]
    )
    since, until = default_window(1, now=now)
    rows = fetch_news_window(since, until=until)
    assert [r.title for r in rows] == ["sin fecha reciente"]


def test_fetch_window_ticker_filter_and_order(test_db):
    now = datetime(2026, 6, 12, 12, 0)
    _seed(
        [
            ("NVDA", "vieja", now - timedelta(hours=10), now),
            ("NVDA", "nueva", now - timedelta(hours=1), now),
            ("PLTR", "otra", now - timedelta(hours=1), now),
        ]
    )
    since, until = default_window(1, now=now)
    rows = fetch_news_window(since, until=until, tickers=["nvda"])
    assert [r.title for r in rows] == ["nueva", "vieja"]


def test_refresh_due_when_no_harvest_today(test_db):
    now = datetime(2026, 6, 12, 9, 0)
    # cosecha de ayer, clasificada → falta harvest de hoy
    _seed([("NVDA", "ayer", now - timedelta(days=1), now - timedelta(days=1))])
    from database.models import NewsEvent, session_scope

    with session_scope() as s:
        s.query(NewsEvent).update({"event_type": "other"})
    assert not harvested_today(now=now)
    assert refresh_due(now=now)


def test_refresh_due_when_backlog_unclassified(test_db):
    now = datetime(2026, 6, 12, 9, 0)
    # cosecha de hoy pero sin clasificar → backlog
    _seed([("NVDA", "hoy", now, now)])
    assert harvested_today(now=now)
    assert unclassified_count() == 1
    assert refresh_due(now=now)


def test_refresh_not_due_when_fresh_and_classified(test_db):
    now = datetime(2026, 6, 12, 9, 0)
    _seed([("NVDA", "hoy", now, now)])
    from database.models import NewsEvent, session_scope

    with session_scope() as s:
        s.query(NewsEvent).update({"event_type": "other"})
    assert unclassified_count() == 0
    assert not refresh_due(now=now)


def test_run_catalyst_refresh_calls_both_with_bat_args():
    calls = {}

    def fake_harvest(argv):
        calls["harvest"] = argv
        return 0

    def fake_classify(argv):
        calls["classify"] = argv
        return 0

    res = run_catalyst_refresh(harvest_main=fake_harvest, classify_main=fake_classify)
    assert res == {"harvest_rc": 0, "classify_rc": 0}
    # mismas fuentes que el .bat nocturno y el harvest horario (finnhub incluido,
    # alineado 2026-07-12 al mover el scheduling in-app)
    assert calls["harvest"] == ["--sources", "yfinance,sec,finnhub"]
    # mismos args del .bat nocturno (hybrid-ollama + qwen2.5:14b)
    assert calls["classify"][:2] == ["--backend", "hybrid-ollama"]
    assert "qwen2.5:14b" in calls["classify"]


def test_run_catalyst_refresh_harvest_crash_still_classifies():
    def boom(argv):
        raise RuntimeError("EDGAR down")

    def fake_classify(argv):
        return 0

    res = run_catalyst_refresh(harvest_main=boom, classify_main=fake_classify)
    assert res["harvest_rc"] == -1
    assert res["classify_rc"] == 0  # el backlog previo se clasifica igual


def test_run_catalyst_harvest_only_uses_bat_sources_and_no_classify():
    calls = {}

    def fake_harvest(argv):
        calls["harvest"] = argv
        return 0

    res = run_catalyst_harvest_only(harvest_main=fake_harvest)
    assert res == {"harvest_rc": 0}  # sin classify_rc: no toca la GPU
    # mismas fuentes que el .bat (finnhub incluido; se saltea solo sin API key)
    assert calls["harvest"] == ["--sources", "yfinance,sec,finnhub"]


def test_run_catalyst_harvest_only_crash_is_contained():
    def boom(argv):
        raise RuntimeError("EDGAR down")

    res = run_catalyst_harvest_only(harvest_main=boom)
    assert res == {"harvest_rc": -1}  # nunca lanza (QThread lo llama directo)


def test_fetch_window_rows_are_rankeable(test_db):
    now = datetime(2026, 6, 12, 12, 0)
    _seed([("NVDA", "x", now - timedelta(hours=1), now)])
    since, until = default_window(1, now=now)
    ranked = rank_news(fetch_news_window(since, until=until))
    assert len(ranked) == 1
    assert isinstance(ranked[0], DigestItem)
