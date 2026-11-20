"""Tarea 439 — una noticia sin ``published_at`` ya no rompe la lista que recibe la opinión de Claude.

``fetch_news_window`` trae a propósito las filas que la fuente no fechó (por ``fetched_at``), y
``noticias_recientes`` usa ``f.published_at or f.fetched_at`` para su hora: el ``_Row`` no tenía
``fetched_at`` y una sola fila sin fecha daba ``AttributeError``. Latente: el 2026-11-19 la DB viva
no tenía ninguna; el test de la 417 lo tapaba con un ``SimpleNamespace`` que sí tenía el campo.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

from analysis import news_digest as nd
from analysis import opinion_claude as oc


def test_una_noticia_sin_fecha_va_con_la_hora_en_que_se_vio(test_db, monkeypatch):
    from database.models import NewsEvent, session_scope

    monkeypatch.setattr("database.models.utcnow_naive", lambda: datetime(2026, 11, 12, 0, 0))
    with session_scope() as s:
        s.add(
            NewsEvent(
                ticker="MU",
                title="sin fecha de la fuente",
                source="yfinance:search",
                content_hash="s1",
                published_at=None,
                fetched_at=datetime(2026, 11, 11, 20, 30),  # 15:30 ET
                event_type="other",
                classified_by="ollama-7n",
                sentiment_score=0.0,
                relevance=0.5,
            )
        )
    (n,) = oc.noticias_recientes("MU")
    assert n["publicada"] == "2026-11-11 15:30 ET"


def test_el_row_tiene_los_campos_que_usa_la_opinion():
    """Lo que `noticias_recientes` lee de cada fila tiene que existir en el `_Row` real."""
    campos = {f.name for f in dataclasses.fields(nd._Row)}
    usados = {"published_at", "fetched_at", "title", "event_type", "sentiment_score", "source"}
    usados |= {"provisional", "classified_by", "relevance", "content"}
    assert usados <= campos, f"faltan en _Row: {sorted(usados - campos)}"
