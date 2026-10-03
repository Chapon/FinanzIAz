"""Tarea 259 — qwen califica el tono en 7 niveles; las noticias viejas se quedan con el suyo.

De 53.788 noticias clasificadas, ``round(3 × score)`` daba −2, 0, +2 o +3 en el 99,6%: el prompt
pedía un número en [−1, +1] sin decir qué significaba cada tramo. Decisión de Chapa (2026-10-03):
aceptar los 4 valores en lo viejo y pedir los 7 niveles desde ahora.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from analysis.news_digest import _Row, rank_news, tone_level
from data import catalyst_classifier as cc
from scripts.classify_catalysts import classify_events
from tests.test_catalyst_classifier import _fake_backend_classifier, _seed_unclassified


def test_el_prompt_pide_el_nivel_entero_con_una_rubrica_por_nivel():
    p = cc._LLM_SYSTEM
    assert '"sentiment_level"' in p and "INTEGER from -3 to +3" in p
    for nivel in ("+3 =", "+2 =", "+1 =", "0 =", "-1 =", "-2 =", "-3 ="):
        assert nivel in p, f"falta la rúbrica del nivel {nivel}"
    # Los dos errores de la muestra de la 280
    assert "PREVIEW" in p and "not earnings_results" in p
    assert "rival winning a contract" in p


def test_el_schema_de_ollama_obliga_el_nivel_entero():
    props = cc._OLLAMA_FORMAT["properties"]
    assert props["sentiment_level"] == {"type": "integer", "enum": [-3, -2, -1, 0, 1, 2, 3]}
    assert "sentiment_level" in cc._OLLAMA_FORMAT["required"]
    assert "sentiment_score" not in cc._OLLAMA_FORMAT["required"]


@pytest.mark.parametrize("nivel", [-3, -2, -1, 0, 1, 2, 3])
def test_cada_nivel_llega_intacto_a_la_pestaña(nivel):
    """El ida y vuelta nivel → score (nivel/3) → tone_level devuelve el mismo nivel."""
    c = cc._parse_llm_json(json.dumps({"sentiment": "neutral", "sentiment_level": nivel}), tag="ollama")
    assert c.sentiment_score == pytest.approx(nivel / 3)
    assert c.classifier == "ollama-7n"
    assert tone_level(c.sentiment_score, c.sentiment) == nivel


def test_un_nivel_fuera_de_rango_se_recorta():
    c = cc._parse_llm_json('{"sentiment_level": 7}', tag="ollama")
    assert c.sentiment_score == pytest.approx(1.0) and c.classifier == "ollama-7n"


@pytest.mark.parametrize(
    "cuerpo", ['{"sentiment_score": 0.7}', '{"sentiment_level": "alto"}', '{"sentiment_level": true}']
)
def test_sin_nivel_valido_es_el_camino_viejo_y_NO_lleva_el_sufijo(cuerpo):
    c = cc._parse_llm_json(cuerpo, tag="ollama")
    assert c.classifier == "ollama", "una respuesta sin nivel no es de la escala de 7"


def test_el_backend_de_ollama_de_punta_a_punta():
    enviado = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "event_type": "upgrade",
                            "sentiment": "positive",
                            "confidence": 0.8,
                            "sentiment_level": 1,
                            "relevance": 0.9,
                        }
                    )
                }
            }

    def post(url, json=None, timeout=None):
        enviado.update(json)
        return _Resp()

    backend = cc.make_ollama_backend(http_post=post)
    c = cc.classify("Analyst nudges target up", None, "yfinance", "AAA", backend=backend)
    assert (c.classifier, tone_level(c.sentiment_score, c.sentiment)) == ("ollama-7n", 1)
    assert enviado["format"]["properties"]["sentiment_level"]["enum"] == [-3, -2, -1, 0, 1, 2, 3]


def _row(classified_by):
    return _Row(
        1, "AAA", "t", "yfinance", None, datetime(2026, 10, 3), "other", "positive", 0.5, 2 / 3, classified_by
    )


def test_la_pestaña_sabe_qué_filas_son_de_la_escala_vieja():
    assert rank_news([_row("ollama-7n")])[0].escala_7 is True
    assert rank_news([_row("ollama")])[0].escala_7 is False
    assert rank_news([_row(None)])[0].escala_7 is False


def test_el_runner_no_cuenta_el_tag_de_7_niveles_como_caída_del_LLM(test_db):
    _seed_unclassified()
    rep = classify_events(
        classifier=_fake_backend_classifier("ollama-7n"),
        llm_tag="ollama",
        llm_exempt_sources=frozenset({"sec_8k"}),
    )
    assert rep.llm_fallbacks == 0


def test_la_celda_de_tono_vieja_lleva_el_aviso(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from ui.news_tab import TONO_ESCALA_VIEJA, NewsTab

    _app = QApplication.instance() or QApplication([])
    tab = NewsTab()
    nuevo, viejo = rank_news([_row("ollama-7n")])[0], rank_news([_row("ollama")])[0]
    from dataclasses import replace

    tab._populate_table([nuevo, replace(viejo, news_id=2, title="otra")])
    tips = {tab.table.item(r, 7).text(): tab.table.item(r, 2).toolTip() for r in range(2)}
    assert tips == {"t": "", "otra": TONO_ESCALA_VIEJA}
