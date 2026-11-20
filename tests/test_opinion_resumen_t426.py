"""Tarea 426 — Claude recibe el resumen de cada noticia, cuando la fuente lo trae.

En la opinión de MU del 2026-11-11 pidió *«detalles de la noticia de Anthropic y de la noticia del
retiro en el directorio»*: se le mandaba sólo el título, y la DB tiene un resumen para 8.080 de
12.717 noticias de una semana (Finnhub/Yahoo ~207 caracteres). Las de ``yfinance:search`` vienen
vacías —las dos que pidió eran de ésas—, y el prompt dice que eso no es un faltante.
"""

from __future__ import annotations

import json
from datetime import datetime

from analysis import opinion_claude as oc


def test_un_resumen_largo_se_recorta_y_lo_dice():
    texto = "palabra " * 100  # 800 caracteres
    r = oc.resumen(texto)
    assert len(r) == oc.MAX_RESUMEN and r.endswith("…")


def test_un_resumen_corto_va_entero_y_en_una_linea():
    assert oc.resumen("  Micron sube\n\tpor la demanda de HBM  ") == "Micron sube por la demanda de HBM"


def test_sin_texto_es_null():
    assert oc.resumen(None) is None
    assert oc.resumen("") is None
    assert oc.resumen("   \n ") is None


def _noticia(s, i, content, source="finnhub:Benzinga"):
    from database.models import NewsEvent

    s.add(
        NewsEvent(
            ticker="MU",
            title=f"titular {i}",
            source=source,
            content=content,
            content_hash=f"h{i}",
            published_at=datetime(2026, 11, 11, 15, i),
            event_type="other",
            classified_by="ollama-7n",
            sentiment_score=0.0,
            relevance=0.8,
        )
    )


def test_las_noticias_traen_su_resumen_o_null(test_db, monkeypatch):
    from database.models import session_scope

    monkeypatch.setattr("database.models.utcnow_naive", lambda: datetime(2026, 11, 12, 0, 0))
    with session_scope() as s:
        _noticia(s, 1, "Micron firmó un acuerdo con Anthropic por memoria HBM.")
        _noticia(s, 2, None, source="yfinance:search")
    por_titulo = {n["titulo"]: n["resumen"] for n in oc.noticias_recientes("MU")}
    assert por_titulo == {
        "titular 1": "Micron firmó un acuerdo con Anthropic por memoria HBM.",
        "titular 2": None,
    }


def test_las_provisionales_tambien_traen_su_resumen(test_db, monkeypatch):
    """Las que qwen no clasificó pasan por la heurística (406): el resumen no se puede perder ahí."""
    from database.models import NewsEvent, session_scope

    monkeypatch.setattr("database.models.utcnow_naive", lambda: datetime(2026, 11, 12, 0, 0))
    with session_scope() as s:
        s.add(
            NewsEvent(
                ticker="MU",
                title="Micron reports record revenue",
                source="finnhub:Benzinga",
                content="Ingresos récord por la demanda de centros de datos.",
                content_hash="p1",
                published_at=datetime(2026, 11, 11, 15, 0),
            )
        )
    (n,) = oc.noticias_recientes("MU")
    assert "heuristica provisional" in n["clasificador"]
    assert n["resumen"] == "Ingresos récord por la demanda de centros de datos."


def test_quince_resumenes_largos_entran_en_lo_que_se_manda(test_db, monkeypatch):
    """El tamaño, medido: 15 noticias con el resumen al tope suman pocos KB al JSON."""
    from database.models import session_scope

    monkeypatch.setattr("database.models.utcnow_naive", lambda: datetime(2026, 11, 12, 0, 0))
    with session_scope() as s:
        for i in range(20):
            _noticia(s, i, "x" * 2_000)
    noticias = oc.noticias_recientes("MU")
    assert len(noticias) == oc.MAX_NOTICIAS
    assert len(json.dumps(noticias, ensure_ascii=False).encode("utf-8")) < 12_000


def test_el_prompt_dice_que_un_resumen_que_no_esta_no_es_un_faltante():
    assert "resumen null" in oc.SYSTEM_PROMPT


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 7
