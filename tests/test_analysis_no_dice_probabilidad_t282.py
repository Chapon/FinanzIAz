"""Tarea 282 — la barra de Analysis no presenta un puntaje de consenso como probabilidad.

El defecto (``docs/auditoria_pantalla_resto_2026-10-02.md`` [A-1]): la barra decía
*«Probabilidad cuantitativa de compra»*, *«zona de compra probable»* y *«▲ Compra 72%»* (o
*«▼ Venta 70%»*, con ``100 − valor``). El número sale de ``compute_signal_probability``, que
combina las señales de los indicadores con el régimen: nunca se midió como probabilidad, y la
medición más cercana (la 73) no encontró relación con el retorno. Es la forma de la 255.

Y el tooltip de XGBoost describía un *«split 80/20»* cuando el camino principal es
walk-forward con calibración isotónica. **Sus umbrales (75/65/35/25) NO se tocaron**: la
auditoría los comparó con los de la barra, pero describen la fila de XGBoost, y ahí coinciden
con el código (``analysis/ml_signals.py``, ``prob_up >= 0.65`` / ``>= 0.75``).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parent.parent


class _Barra:
    def __init__(self):
        self.formato = None

    def setValue(self, v):
        self.valor = v

    def setFormat(self, f):
        self.formato = f

    def setStyleSheet(self, _):
        pass


def _rotulo(prob: float) -> str:
    from ui.analysis_tab import AnalysisTab

    falso = SimpleNamespace(prob_bar=_Barra())
    AnalysisTab._update_prob_bar(falso, prob)
    return falso.prob_bar.formato


@pytest.mark.parametrize(
    "prob,esperado",
    # Las CINCO ramas de `_update_prob_bar`: con tres casos, una rama bajista quedaba sin
    # probar y la mutación al rótulo viejo salía verde.
    [
        (0.72, "▲ Consenso alcista  72/100"),
        (0.60, "▲ Consenso alcista  60/100"),
        (0.50, "⟶ Neutral  50/100"),
        (0.40, "▼ Consenso bajista  40/100"),
        (0.30, "▼ Consenso bajista  30/100"),
    ],
)
def test_el_rotulo_es_un_PUNTAJE_y_no_una_probabilidad(prob, esperado):
    rot = _rotulo(prob)
    assert rot == esperado
    assert "%" not in rot and "Compra" not in rot and "Venta" not in rot


def test_el_tooltip_de_la_barra_no_promete_probabilidad():
    src = (_REPO / "ui" / "analysis_tab.py").read_text(encoding="utf-8")
    assert "Probabilidad cuantitativa" not in src
    assert "probable" not in src
    assert "No es una probabilidad" in src


def test_el_tooltip_de_xgboost_describe_el_metodo_del_codigo():
    from ui.analysis.labels import get_tooltip

    tt = get_tooltip("XGBoost ML")
    assert "walk-forward" in tt and "isotónica" in tt
    assert "Split de entrenamiento:</b> 80%" not in tt


def test_los_umbrales_del_tooltip_de_xgboost_son_los_de_su_fila():
    """La parte de la auditoría que estaba mal: 75/65/35/25 son los de `ml_signals`, no de la barra."""
    src = (_REPO / "analysis" / "ml_signals.py").read_text(encoding="utf-8")
    assert "prob_up >= 0.65" in src and "prob_up >= 0.75" in src
    from ui.analysis.labels import get_tooltip

    tt = get_tooltip("XGBoost ML")
    assert "75%" in tt and "65-75%" in tt
