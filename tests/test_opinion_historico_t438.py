"""Tarea 438 — pedir la opinión de nuevo el mismo día ya no pierde la anterior.

``claude_opinions`` es una por ``(ticker, día)`` a propósito (la 320: la medición de la 321 no cuenta
dos veces la misma decisión). El 2026-11-11 la de MU se pisó dos veces —15:02Z, 18:13Z y 21:00Z— y
con ella la evidencia de origen de ocho tareas abiertas. Chapa eligió el 2026-11-19 un histórico:
la tabla sigue igual y la reemplazada se copia antes, entera.
"""

from __future__ import annotations

import json
from datetime import date

from analysis import opinion_claude as oc
from config import codigo

_DIA = date(2026, 11, 11)


def _op(rec, conf, tesis):
    return oc.Opinion(rec, conf, tesis, ["r"], ["c"], ["f"], oc.MODELO, 12.3)


def test_dos_pedidos_el_mismo_dia_dejan_la_primera_en_el_historico(test_db, monkeypatch):
    from database.models import ClaudeOpinion, ClaudeOpinionReemplazada, session_scope

    monkeypatch.setattr(codigo, "al_arrancar", lambda: codigo.EstadoDelCodigo("c" * 40, ("x.py",)))
    oc.guardar("MU", _op("COMPRAR", 70, "la de las 15:02"), {"precio": 787.0, "version_datos": 2}, hoy=_DIA)
    oc.guardar("MU", _op("MANTENER", 55, "la de las 18:13"), {"precio": 811.5, "version_datos": 4}, hoy=_DIA)
    oc.guardar("MU", _op("VENDER", 40, "la de las 21:00"), {"precio": 805.0, "version_datos": 5}, hoy=_DIA)

    with session_scope() as s:
        (vigente,) = s.query(ClaudeOpinion).all()
        viejas = s.query(ClaudeOpinionReemplazada).order_by(ClaudeOpinionReemplazada.id).all()
        assert vigente.recomendacion == "VENDER"
        assert [(v.recomendacion, v.precio) for v in viejas] == [("COMPRAR", 787.0), ("MANTENER", 811.5)]
        primera = viejas[0]
        assert json.loads(primera.respuesta_json)["tesis"] == "la de las 15:02"
        assert json.loads(primera.datos_json) == {"precio": 787.0, "version_datos": 2}
        assert (primera.ticker, primera.fecha, primera.opinion_id) == ("MU", "2026-11-11", vigente.id)
        assert primera.codigo_commit == "c" * 40 and primera.codigo_wip is True
        assert primera.reemplazada_at is not None and primera.creado_at is not None

    # La tarjeta muestra la última, como siempre.
    op, _cuando = oc.opinion_de_hoy("MU", hoy=_DIA)
    assert (op.recomendacion, op.tesis) == ("VENDER", "la de las 21:00")


def test_un_pedido_por_dia_no_deja_nada_en_el_historico(test_db):
    from database.models import ClaudeOpinionReemplazada, session_scope

    oc.guardar("MU", _op("COMPRAR", 70, "a"), {"precio": 1.0}, hoy=date(2026, 11, 10))
    oc.guardar("MU", _op("VENDER", 40, "b"), {"precio": 2.0}, hoy=_DIA)
    with session_scope() as s:
        assert s.query(ClaudeOpinionReemplazada).count() == 0


def test_el_historico_copia_todas_las_columnas_de_la_opinion():
    """Si `claude_opinions` suma una columna, el histórico la tiene que tener y copiarla."""
    from database.models import COLUMNAS_OPINION, ClaudeOpinion, ClaudeOpinionReemplazada

    propias = {c.name for c in ClaudeOpinion.__table__.columns} - {"id"}
    assert set(COLUMNAS_OPINION) == propias
    assert propias <= {c.name for c in ClaudeOpinionReemplazada.__table__.columns}
