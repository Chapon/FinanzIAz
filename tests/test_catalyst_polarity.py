"""Polaridad numérica point-in-time en el classify (OPS1(a)).

En la MISMA llamada del classify, además del ``event_type``/``sentiment``
categóricos, se persiste ``sentiment_score`` ∈ [-1,+1] y ``relevance`` ∈ [0,1]
(costo marginal ~cero). Empieza a acumular histórico point-in-time para el
meta-modelo (tarea 9). NO entra a ninguna decisión (regla 3).
"""

from __future__ import annotations

from datetime import datetime

from data.catalyst_classifier import (
    _OLLAMA_FORMAT,
    Classification,
    _parse_llm_json,
    classify,
    heuristic_classify,
    make_ollama_backend,
)
from database.models import NewsEvent, session_scope
from scripts.classify_catalysts import classify_events


# ── Heurístico: dirección categórica a media escala + relevancia=confianza ────


def test_heuristic_positive_emits_positive_score():
    c = heuristic_classify("NVDA beats earnings, tops estimates", None, "yfinance")
    assert c.sentiment == "positive"
    assert c.sentiment_score == 0.5  # +positive a media escala
    assert c.relevance == c.confidence  # relevancia = confianza (proxy honesto)


def test_heuristic_negative_emits_negative_score():
    c = heuristic_classify("Acme plunges on lawsuit and downgrade", None, "yfinance")
    assert c.sentiment == "negative"
    assert c.sentiment_score == -0.5


def test_heuristic_neutral_no_cue_is_zero_low_relevance():
    c = heuristic_classify("A quiet day at the office", None, "yfinance")
    assert c.sentiment == "neutral"
    assert c.sentiment_score == 0.0
    assert c.relevance == 0.20  # sin cue → confianza baja


def test_heuristic_sec_relevance_tracks_confidence():
    c = heuristic_classify(
        "AAPL 8-K: Results of Operations", "Items: 2.02", "sec_8k", "AAPL"
    )
    assert c.confidence >= 0.9
    assert c.relevance == c.confidence  # item-code estructurado → alta relevancia
    assert -1.0 <= c.sentiment_score <= 1.0


# ── LLM parse: extrae los numéricos, o los deriva si faltan ───────────────────


def test_parse_llm_json_extracts_numeric_fields():
    c = _parse_llm_json(
        '{"event_type":"mna","sentiment":"negative","confidence":0.7,'
        '"sentiment_score":-0.8,"relevance":0.92}'
    )
    assert c.sentiment_score == -0.8
    assert c.relevance == 0.92


def test_parse_llm_json_derives_when_numeric_absent():
    # Sin sentiment_score/relevance → deriva del categórico (positive→0.5) y 0.5.
    c = _parse_llm_json('{"event_type":"mna","sentiment":"positive","confidence":0.8}')
    assert c.sentiment_score == 0.5
    assert c.relevance == 0.5


# ── coerción: clampea la basura del LLM al rango ──────────────────────────────


def test_classify_clamps_out_of_range_polarity():
    def bad(t, c, s, k=None):
        return Classification("mna", "positive", 0.8, "llm", 5.0, -3.0)

    out = classify("x", None, "yfinance", backend=bad)
    assert out.sentiment_score == 1.0  # 5.0 → clamp a +1
    assert out.relevance == 0.0  # -3.0 → clamp a 0


# ── Ollama: structured outputs (JSON schema), no "json" ───────────────────────


def test_ollama_uses_structured_format_schema():
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "message": {
                    "content": '{"event_type":"mna","sentiment":"positive",'
                    '"confidence":0.9,"sentiment_score":0.7,"relevance":0.95}'
                }
            }

    def poster(url, json=None, timeout=None):
        captured["json"] = json
        return _Resp()

    backend = make_ollama_backend(http_post=poster)
    c = backend("Acme to acquire Beta", None, "yfinance", "ACME")

    # El payload pide structured outputs con el schema, no el viejo "json".
    assert captured["json"]["format"] == _OLLAMA_FORMAT
    assert captured["json"]["format"] != "json"
    # Y parsea los numéricos que devolvió el modelo.
    assert c.sentiment_score == 0.7
    assert c.relevance == 0.95


# ── Persistencia en news_events ───────────────────────────────────────────────


def _seed_one(ticker: str, title: str, source: str, h: str) -> None:
    with session_scope() as s:
        s.add(NewsEvent(ticker=ticker, title=title, source=source, content_hash=h))


def test_runner_persists_polarity(test_db):
    _seed_one("NVDA", "NVDA beats earnings, tops estimates", "yfinance", "p1")
    classify_events(now=datetime(2026, 7, 9, 12, 0))
    with session_scope() as s:
        e = s.query(NewsEvent).filter_by(ticker="NVDA").first()
    assert e.sentiment_score == 0.5  # heurístico positivo
    assert e.relevance is not None and 0.0 <= e.relevance <= 1.0


def test_runner_dry_run_does_not_persist_polarity(test_db):
    _seed_one("NVDA", "NVDA beats earnings, tops estimates", "yfinance", "p2")
    classify_events(dry_run=True)
    with session_scope() as s:
        e = s.query(NewsEvent).filter_by(ticker="NVDA").first()
    assert e.sentiment_score is None and e.relevance is None
