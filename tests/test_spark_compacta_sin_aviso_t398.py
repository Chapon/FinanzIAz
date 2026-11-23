"""Tarea 398 — la sparkline de las tarjetas compactas de Métricas se dibuja sin el aviso de tight_layout.

El log tenía *«Tight layout not applied. The bottom and top margins cannot be made large enough…»*
de a dos —uno desde ``main.py:104`` (`app.exec()`) y otro desde ``_Sparkline.set_series``— en dos
sesiones de unas cincuenta. Era la tarjeta compacta de la 319: su sparkline mide 28 px y el margen
por defecto del ``tight_layout`` (1,08 tamaños de letra) no entra. La primera firma es el dibujado
al mostrarse la pestaña Métricas; la segunda, ``set_series`` cuando llegan las métricas. Una vez por
sesión, por el filtro ``default`` de Python (una vez por línea), y sólo en las sesiones en que se
abrió esa pestaña.

Los avisos se **registran** en vez de volverse error: un error dentro del ``paintEvent`` lo dispara
Qt desde C++, y PyQt6 aborta el proceso.
"""

from __future__ import annotations

import os
import warnings

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("matplotlib")

from PyQt6.QtWidgets import QApplication

from tests.test_metrics_tab_smoke import _payload_with_data
from ui.dashboard_charts import COMPACT_SPARK_HEIGHT, KpiCard
from ui.metrics_tab import MetricsTab

# Una referencia global, como en la 319 (tarea 323: un fixture de módulo soltaba la QApplication).
_APP = QApplication.instance() or QApplication([])


def _avisos_de_layout(registro) -> list[str]:
    return [f"{os.path.basename(w.filename)}:{w.lineno}" for w in registro if "ight layout" in str(w.message)]


def _mostrar(widget) -> None:
    widget.show()
    for _ in range(5):
        _APP.processEvents()


@pytest.mark.parametrize("kind", ["area", "bar", "spike"])
def test_la_tarjeta_compacta_se_dibuja_y_recibe_la_serie_sin_aviso(kind):
    with warnings.catch_warnings(record=True) as registro:
        warnings.simplefilter("always")
        card = KpiCard("X", kind=kind, compact=True)
        card.resize(220, 120)
        _mostrar(card)  # el dibujado del event loop: la firma de main.py:104
        card.set_series([1.0, 2.0, 3.0, 2.0, 4.0, 0.5])  # la de dashboard_charts.py:286
        _APP.processEvents()
    try:
        assert card.spark.canvas.height() == COMPACT_SPARK_HEIGHT
        assert _avisos_de_layout(registro) == []
    finally:
        card.close()


def test_la_curva_compacta_ocupa_el_lienzo():
    """Que el layout se aplicó, no que se tapó el aviso: los márgenes por defecto dejaban x en 0,12–0,90."""
    card = KpiCard("X", kind="area", compact=True)
    card.resize(220, 120)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _mostrar(card)
        card.set_series([1.0, 3.0, 2.0])
    try:
        pos = card.spark.ax.get_position()
        assert pos.x1 - pos.x0 > 0.95
        assert pos.y1 - pos.y0 > 0.75
    finally:
        card.close()


def test_la_tarjeta_de_home_sigue_con_el_margen_de_siempre():
    card = KpiCard("X", kind="area")
    assert card.spark.figure.get_layout_engine().get()["pad"] == pytest.approx(1.08)


def test_la_pestana_metricas_se_dibuja_sin_aviso():
    """El camino de la app: la pestaña mostrada y después las métricas, con sus 12 tarjetas compactas."""
    with warnings.catch_warnings(record=True) as registro:
        warnings.simplefilter("always")
        tab = MetricsTab(account_id=1)
        tab.resize(1442, 900)
        _mostrar(tab)
        tab._on_result(_payload_with_data())
        for _ in range(5):
            _APP.processEvents()
    try:
        assert all(c.compact for c in tab.cards.values())
        assert _avisos_de_layout(registro) == []
    finally:
        tab.close()
