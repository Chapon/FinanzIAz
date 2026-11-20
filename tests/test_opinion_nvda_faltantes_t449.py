"""Tarea 449 — los faltantes de la opinión de NVDA del 2026-11-20.

(a) Las recomendaciones de analistas llegaban sin el mes en curso: Yahoo las ordena del más viejo
al más nuevo y se tomaban las tres primeras. (b) La relevancia 0,20 de la heurística, con la regla
del 0,2 del prompt, hacía que Claude descartara toda noticia provisional. (c) La opinión registraba
el commit del arranque aunque el módulo que la armó se hubiera importado después, de otro árbol.
"""

from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd

from analysis import opinion_claude as oc
from config import codigo

# El orden real de Yahoo (518 de 563 tickers del cache el 2026-11-20), con los números de NVDA.
_NVDA = [
    {"period": "-3m", "strongBuy": 9, "buy": 48, "hold": 2, "sell": 1, "strongSell": 0},
    {"period": "-2m", "strongBuy": 10, "buy": 49, "hold": 2, "sell": 1, "strongSell": 0},
    {"period": "-1m", "strongBuy": 10, "buy": 49, "hold": 2, "sell": 1, "strongSell": 0},
    {"period": "0m", "strongBuy": 11, "buy": 34, "hold": 15, "sell": 2, "strongSell": 0},
]


# ── (a) las recomendaciones ──────────────────────────────────────────────────


def test_llega_el_mes_en_curso_primero():
    assert [r["period"] for r in oc.recomendaciones_recientes(_NVDA)] == ["0m", "-1m", "-2m"]


def test_con_menos_meses_o_basura_no_se_rompe():
    assert [r["period"] for r in oc.recomendaciones_recientes(_NVDA[2:])] == ["0m", "-1m"]
    assert oc.recomendaciones_recientes(None) == []
    assert [r["period"] for r in oc.recomendaciones_recientes([{"period": "raro"}, _NVDA[3]])] == [
        "0m",
        "raro",
    ]


def _df():
    idx = pd.bdate_range(end="2026-11-19", periods=30)
    close = pd.Series(np.linspace(200, 137, 30), index=idx)
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1_000.0})


def test_armar_datos_manda_el_cambio_despues_del_desplome():
    datos = oc.armar_datos(
        "nvda", _df(), analyst={"recommendations": _NVDA, "price_targets": {"mean": 246.7}}
    )
    recs = datos["analistas"]["recomendaciones"]
    assert recs[0]["period"] == "0m" and recs[0]["buy"] == 34 and recs[0]["hold"] == 15
    assert "0m es el mes en curso" in datos["analistas"]["periodos"]


# ── (b) la relevancia de la heurística ───────────────────────────────────────


def _fila(**kw):
    base = {"provisional": False, "classified_by": "ollama-7n", "relevance": 0.2}
    return SimpleNamespace(**{**base, **kw})


def test_la_relevancia_de_un_modelo_se_manda_tal_cual():
    assert oc.relevancia_medida(_fila()) == 0.2
    assert oc.relevancia_medida(_fila(classified_by="ollama", relevance=0.85)) == 0.85


def test_la_de_la_heuristica_no_se_manda():
    assert oc.relevancia_medida(_fila(provisional=True)) is None
    assert oc.relevancia_medida(_fila(classified_by="heuristic", relevance=0.9)) is None
    assert oc.relevancia_medida(_fila(classified_by="fallback")) is None


def test_el_prompt_dice_que_la_heuristica_no_mide_relevancia():
    assert "la heurística no la mide" in oc.SYSTEM_PROMPT


# ── (c) el código con que se armó ────────────────────────────────────────────

_A = codigo.EstadoDelCodigo("a" * 40)
_B = codigo.EstadoDelCodigo("b" * 40)


def test_mezclado():
    assert not codigo.mezclado(_A, _A)
    assert codigo.mezclado(_A, _B)
    assert codigo.mezclado(_A, codigo.EstadoDelCodigo("a" * 40, ("analysis/opinion_claude.py",)))
    assert not codigo.mezclado(codigo.EstadoDelCodigo(None), _B)
    assert not codigo.mezclado(_A, codigo.EstadoDelCodigo(None))


def _guardar(monkeypatch, arranque, ahora):
    monkeypatch.setattr(codigo, "al_arrancar", lambda: arranque)
    monkeypatch.setattr(codigo, "estado_del_codigo", lambda *a, **k: ahora)
    op = oc.Opinion("MANTENER", 38, "tesis", [], [], [], oc.MODELO, 1.0)
    return oc.guardar("NVDA", op, {"precio": 137.78}, hoy=date(2026, 11, 20))


def _codigo_guardado():
    from database.models import ClaudeOpinion, session_scope

    with session_scope() as s:
        f = s.query(ClaudeOpinion).one()
        return f.codigo_commit, f.codigo_wip


def test_con_el_arbol_cambiado_la_opinion_no_queda_limpia(test_db, monkeypatch, caplog):
    """El caso de NVDA: arrancó en un commit limpio y el árbol cambió antes del pedido."""
    with caplog.at_level(logging.WARNING):
        assert _guardar(monkeypatch, _A, _B) is True
    assert _codigo_guardado() == ("a" * 40, True)
    assert any("código mezclado" in r.getMessage() for r in caplog.records)


def test_con_el_arbol_igual_queda_como_antes(test_db, monkeypatch):
    assert _guardar(monkeypatch, _A, _A) is False
    assert _codigo_guardado() == ("a" * 40, False)


def test_la_tarjeta_avisa_que_hay_que_reabrir(qapp):
    # `qapp` (pytest-qt) y no un QApplication propio: el propio se destruye al terminar el test y
    # el que importa después la pestaña Cartera se queda sin pool de hilos (la 448).
    from ui.analysis.opinion_card import AVISO_MEZCLADO, OpinionCard

    card = OpinionCard()
    op = oc.Opinion("MANTENER", 38, "tesis", [], [], [], oc.MODELO, 74.7)
    card._worker = SimpleNamespace(mezclado=True)
    card._listo(True, op)
    assert AVISO_MEZCLADO in card.estado.text() and "abrir_app.bat" in card.estado.text()
    card._worker = SimpleNamespace(mezclado=False)
    card._listo(True, op)
    assert AVISO_MEZCLADO not in card.estado.text()


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 13
