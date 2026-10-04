"""Tarea 302 — en la escala de 7 niveles, el rótulo de sentimiento sale del signo del nivel.

qwen devuelve ``sentiment`` y ``sentiment_level`` por separado, y nada exigía que coincidieran.
La auditoría del 2026-10-04 ([I-1]) contó 51 noticias con el rótulo contra el signo del puntaje
(una de 861 en la escala nueva: ON, «positive» con −1/3). La pestaña Noticias pinta el rótulo y
el color desde ``sentiment`` (``ui/news_tab.py``) y el tono desde ``sentiment_score``
(``analysis/news_digest.tone_level``), así que Chapa veía «Positivo» en verde con tono −1.

Los casos usan un rótulo **contrario** al nivel: con el rótulo coherente la versión vieja también
pasaría, y el test no fijaría nada.
"""

from __future__ import annotations

import json

import pytest

from analysis.news_digest import tone_level
from data import catalyst_classifier as cc


@pytest.mark.parametrize(
    "rotulo_de_qwen,nivel,esperado",
    [
        ("positive", -1, "negative"),  # el caso de ON (id 72859)
        ("negative", 2, "positive"),
        ("positive", 0, "neutral"),
        ("neutral", -3, "negative"),
        ("basura", 3, "positive"),
    ],
)
def test_el_rotulo_sale_del_signo_del_nivel(rotulo_de_qwen, nivel, esperado):
    c = cc._parse_llm_json(json.dumps({"sentiment": rotulo_de_qwen, "sentiment_level": nivel}), tag="ollama")
    assert c.classifier == "ollama" + cc.SUFIJO_ESCALA_7
    assert c.sentiment == esperado
    assert tone_level(c.sentiment_score, c.sentiment) == nivel


@pytest.mark.parametrize("nivel", range(-3, 4))
def test_rotulo_y_tono_nunca_se_contradicen_en_la_escala_de_7(nivel):
    for rotulo in ("positive", "negative", "neutral"):
        c = cc.classify(
            "t",
            None,
            "rss",
            backend=lambda *a, r=rotulo: cc._parse_llm_json(
                json.dumps({"sentiment": r, "sentiment_level": nivel})
            ),
        )
        signo = (c.sentiment_score > 0) - (c.sentiment_score < 0)
        assert {"positive": 1, "negative": -1, "neutral": 0}[c.sentiment] == signo


def test_sin_nivel_el_camino_viejo_conserva_el_rotulo_de_qwen():
    """Sin `sentiment_level` no hay escala de 7: no hay de dónde derivar el rótulo, y se
    mantiene el comportamiento anterior (las 50 filas viejas incoherentes no se reescriben)."""
    c = cc._parse_llm_json(json.dumps({"sentiment": "positive", "sentiment_score": -0.4}), tag="ollama")
    assert c.classifier == "ollama" and c.sentiment == "positive"
