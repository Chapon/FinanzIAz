"""Tarea 319 — la pestaña Métricas entra en la pantalla: tarjetas compactas, en grupos, con columnas
según el ancho, y sin la tarjeta repetida.

Lo que pasaba (captura de Chapa, 2026-10-05): 13 tarjetas de ~170 px en una grilla fija de 4 y el
panel de score de 300 px dejaban el gráfico de evolución y las tablas debajo del borde. «P/L sin
peor nombre» repetía el subtítulo de «P/L realizado». Y en el primer render del arreglo, los
subtítulos largos fijaban el ancho mínimo de las tarjetas y la fila se pasaba del ancho de la
ventana: el cálculo de columnas usa ahora el ancho mínimo real.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("matplotlib")

from PyQt6.QtWidgets import QApplication

from tests.test_metrics_tab_smoke import _payload_with_data
from ui.dashboard_charts import COMPACT_MIN_HEIGHT, KpiCard
from ui.metrics_tab import GRUPOS_KPI, MetricsTab, columnas_para


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(
    "ancho,n,esperado",
    [(1442, 5, 5), (1000, 5, 4), (640, 5, 3), (300, 5, 1), (5000, 3, 3), (0, 4, 1), (1442, 0, 1)],
)
def test_columnas_segun_el_ancho(ancho, n, esperado):
    assert columnas_para(ancho, n) == esperado


def test_un_ancho_minimo_mayor_baja_las_columnas():
    """Lo que encontró el primer render: con el ancho real de las tarjetas, entran menos."""
    assert columnas_para(1442, 5, ancho_min=200) == 5
    assert columnas_para(1442, 5, ancho_min=320) == 4


def test_la_tarjeta_compacta_es_bastante_mas_baja_y_corta_linea(qapp):
    grande, chica = KpiCard("X", kind="area"), KpiCard("X", kind="area", compact=True)
    assert chica.minimumHeight() == COMPACT_MIN_HEIGHT < 100 < grande.minimumHeight()
    assert chica.delta_lbl.wordWrap() and not grande.delta_lbl.wordWrap()


def test_los_grupos_cubren_TODAS_las_tarjetas_y_sin_la_repetida(qapp):
    tab = MetricsTab(account_id=1)
    en_grupos = [k for _, claves in GRUPOS_KPI for k in claves]
    assert sorted(en_grupos) == sorted(tab.cards), "una tarjeta quedó fuera de los grupos, o sobra"
    assert len(en_grupos) == len(set(en_grupos))
    assert "exworst" not in tab.cards
    assert all(c.compact for c in tab.cards.values())


def test_el_ticker_del_peor_nombre_pasa_al_subtitulo_de_PL(qapp):
    tab = MetricsTab(account_id=1)
    m = _payload_with_data()
    tab._on_result(m)
    peor = m["realized"]["worst_ticker"]
    sub = tab.cards["pnl"].delta_lbl.text()
    assert sub.startswith("sin peor nombre")
    if peor:
        assert f"({peor['ticker']})" in sub


def test_en_una_ventana_angosta_las_tarjetas_no_se_pasan_del_ancho(qapp):
    """El defecto del primer render: la fila pedía más ancho que el del grupo."""
    tab = MetricsTab(account_id=1)
    tab._on_result(_payload_with_data())
    for grupo in tab.grupos:
        for ancho in (700, 1100, 1442):
            grupo.reacomodar(ancho)
            minimo = max(t.minimumSizeHint().width() for t in grupo.tarjetas)
            assert grupo.columnas * minimo + (grupo.columnas - 1) * 12 <= ancho, (grupo.titulo.text(), ancho)
