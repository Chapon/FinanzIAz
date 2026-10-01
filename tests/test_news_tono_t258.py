"""Tarea 258 — la pestaña Noticias muestra el TONO de cada noticia, de −3 a +3.

Pedido de Chapa (2026-10-01): una escala de 7 niveles en lugar del ±0.36 constante. El nivel
sale de la polaridad del clasificador (``sentiment_score``, [−1, +1]):
``round(3 × sentiment_score)``.

Lo que se fija:

1. **El nivel sale de la polaridad, no del sentimiento.** Los casos usan filas con sentimiento
   *positive* y polaridades distintas: si el tono saliera de ``sentiment`` darían todas +1.
2. **Las filas sin polaridad** (clasificadas antes de OPS1, 2026-07-09) caen a ±1 por el
   sentimiento, no a 0.
3. **Ningún texto lo presenta como pronóstico:** la tarea 255 midió que el signo no predice el
   retorno a 5 días, así que ni la pestaña ni el briefing dicen *impacto esperado*.
"""

from __future__ import annotations

import inspect
import math
import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from analysis import news_digest as nd
from analysis.news_digest import _Row, briefing_prompt, fallback_briefing, rank_news, tone_level


@pytest.mark.parametrize(
    ("score", "nivel"),
    [
        (1.0, 3),
        (0.84, 3),  # la media de las positivas de qwen
        (0.6, 2),
        (0.5, 2),  # 1,5 redondea hacia afuera
        (1 / 6, 1),  # 0,5: el redondeo bancario de round() lo bajaría a 0
        (-1 / 6, -1),
        (0.2, 1),
        (0.1, 0),
        (0.0, 0),
        (-0.2, -1),
        (-0.5, -2),
        (-0.64, -2),  # la media de las negativas de qwen
        (-1.0, -3),
        (1.7, 3),  # fuera de rango: se recorta
        (-4.0, -3),
    ],
)
def test_nivel_desde_la_polaridad(score, nivel):
    assert tone_level(score, "positive" if score >= 0 else "negative") == nivel


def test_el_nivel_no_sale_del_sentimiento():
    # mismas etiquetas, polaridades distintas → niveles distintos
    assert [tone_level(s, "positive") for s in (0.2, 0.6, 0.9)] == [1, 2, 3]


@pytest.mark.parametrize(
    ("sentiment", "nivel"),
    [("positive", 1), ("negative", -1), ("neutral", 0), (None, 0)],
)
def test_sin_polaridad_cae_al_signo_del_sentimiento(sentiment, nivel):
    assert tone_level(None, sentiment) == nivel


def test_polaridad_basura_cae_al_sentimiento():
    assert tone_level(math.nan, "negative") == -1
    assert tone_level("x", "positive") == 1


def _row(i, score, sentiment="positive"):
    return _Row(
        id=i,
        ticker=f"T{i}",
        title=f"titular {i}",
        source="finnhub:Yahoo",
        url=None,
        published_at=datetime(2026, 10, 1, 10, 0),
        event_type="earnings_results",
        sentiment=sentiment,
        classifier_confidence=0.6,
        sentiment_score=score,
    )


def test_el_briefing_recibe_el_nivel_y_no_habla_de_impacto_esperado():
    items = rank_news([_row(1, 0.9), _row(2, -0.6, "negative")])
    prompt = briefing_prompt(items)
    assert "[+3] T1" in prompt and "[-2] T2" in prompt
    assert "impacto esperado" not in prompt.lower()
    assert "impacto esperado" not in nd._BRIEFING_SYSTEM.lower()
    assert "pronóstico" in nd._BRIEFING_SYSTEM
    assert "impacto esperado" not in fallback_briefing(items).lower()
    assert "tono +3" in fallback_briefing(items)


def test_la_pestaña_no_dice_impacto_esperado():
    pytest.importorskip("PyQt6.QtWidgets")
    import ui.news_tab as nt

    texto = inspect.getsource(nt).lower()
    assert "impacto esperado" not in texto
    assert "impact score" not in texto
    assert [c[0] for c in nt.COLUMNS][2] == "Tono"


def test_la_celda_muestra_el_nivel_y_ordena_por_su_modulo():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    import ui.news_tab as nt

    app = QApplication.instance() or QApplication([])  # sin referencia, el GC la destruye
    tab = nt.NewsTab()
    assert app is not None
    tab._populate_table(rank_news([_row(1, 0.2), _row(2, -0.95, "negative"), _row(3, 0.0, "neutral")]))
    celdas = [tab.table.item(r, 2).text() for r in range(3)]
    assert celdas == ["-3", "+1", "0"]
    assert tab.table.item(0, 2).data(Qt.ItemDataRole.UserRole) == 3
