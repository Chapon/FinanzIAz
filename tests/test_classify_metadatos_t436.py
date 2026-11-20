"""Tarea 436 — los metadatos del classify dicen lo que pasó.

- ``classified_at`` era el ``now`` del ARRANQUE de la corrida, y los checkpoints de la 409 grababan
  ese mismo valor: en la del 11/11, filas que fallaron entre las 21:13 y las 21:42Z quedaron con
  21:02:48Z, y hay corridas de 7 h.
- Lo que el LLM no pudo clasificar (Ollama caído, timeout) caía a la heurística rotulado
  ``heuristic``, igual que lo heurístico por diseño, y la cola —``event_type IS NULL``— no lo volvía
  a tomar: quedaba como clasificación definitiva (134 en noviembre).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from data import catalyst_classifier as cc
from data.catalyst_classifier import Classification
from database.models import NewsEvent, session_scope
from scripts.classify_catalysts import classify_events

_T0 = datetime(2026, 11, 11, 21, 2, 48)


def _sembrar(n: int, **campos) -> None:
    with session_scope() as s:
        for i in range(n):
            s.add(
                NewsEvent(
                    ticker="MU", title=f"titular {i}", source="yfinance", content_hash=f"h{i}", **campos
                )
            )


def _qwen(title, content, source, ticker):
    return Classification(
        "earnings", "positive", 0.9, classifier="ollama-7n", sentiment_score=0.66, relevance=0.9
    )


def test_dos_lotes_de_una_corrida_graban_horas_distintas(test_db):
    _sembrar(4)
    horas = iter([_T0 + timedelta(minutes=10), _T0 + timedelta(minutes=40)])
    classify_events(classifier=_qwen, checkpoint=2, reloj=lambda: next(horas))
    with session_scope() as s:
        cuando = sorted({e.classified_at for e in s.query(NewsEvent).all()})
    assert cuando == [_T0 + timedelta(minutes=10), _T0 + timedelta(minutes=40)]


def test_sin_reloj_y_con_now_se_usa_now_como_antes(test_db):
    _sembrar(2)
    classify_events(classifier=_qwen, now=_T0)
    with session_scope() as s:
        assert {e.classified_at for e in s.query(NewsEvent).all()} == {_T0}


def _ollama_caido():
    def post(*a, **kw):
        raise TimeoutError("Ollama no contestó")

    return cc.make_ollama_backend(model="qwen", http_post=post)


def test_un_LLM_caido_deja_el_respaldo_rotulado_fallback():
    c = _ollama_caido()("Micron sube 11%", None, "finnhub:Benzinga", "MU")
    assert c.classifier == cc.RESPALDO == "fallback"


def test_la_heuristica_por_diseno_sigue_rotulada_heuristic():
    assert cc.heuristic_classify("8-K", None, "sec_8k", "MU").classifier == "heuristic"


def test_lo_rotulado_fallback_vuelve_a_la_cola_y_qwen_lo_reclasifica(test_db):
    _sembrar(1)
    classify_events(classifier=lambda *a: cc.classify(*a, backend=_ollama_caido()), now=_T0)
    with session_scope() as s:
        (e,) = s.query(NewsEvent).all()
        assert e.classified_by == "fallback" and e.event_type is not None
    rep = classify_events(classifier=_qwen, now=_T0 + timedelta(hours=1))
    assert rep.classified == 1
    with session_scope() as s:
        (e,) = s.query(NewsEvent).all()
        assert e.classified_by == "ollama-7n" and e.event_type == "earnings"


def test_lo_clasificado_por_qwen_no_vuelve_a_la_cola(test_db):
    _sembrar(1)
    classify_events(classifier=_qwen, now=_T0)
    assert classify_events(classifier=_qwen, now=_T0).classified == 0
