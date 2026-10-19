"""Tarea 371: el gráfico de precio de Análisis no avisa *«not compatible with tight_layout»*.

Chapa lo vio en la consola (2026-10-19). La causa era ``hspace=0.08`` en el gridspec de una
figura con ``tight_layout=True``: matplotlib no puede respetar el espaciado fijado a mano,
avisa y **no aplica** el layout (el gráfico quedaba con márgenes vacíos a los cuatro lados).
La revisión de arquitectura lo atribuía a «matplotlib embebido»; era una línea.
"""

from __future__ import annotations

import os
import warnings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])


def _ohlcv() -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-01", periods=120)
    c = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, len(idx)))
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1e6}, index=idx)


def test_el_grafico_de_precio_se_dibuja_sin_el_aviso_de_tight_layout():
    from ui.chart_widget import ChartWidget

    w = ChartWidget()
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message=".*tight_layout.*")
        w.plot_price_with_indicators("TST", _ohlcv())
        w.figure.canvas.draw()  # el aviso sale al dibujar, no al armar los ejes
    assert len(w.figure.axes) == 3


def test_el_instrumento_ve_el_aviso_cuando_esta():
    """Que el test de arriba no sea verde por no poder ver el aviso (la forma de la 371)."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    f = Figure(tight_layout=True)
    gs = f.add_gridspec(2, 1, hspace=0.08)
    f.add_subplot(gs[0])
    f.add_subplot(gs[1])
    with pytest.warns(UserWarning, match="tight_layout"):
        FigureCanvasAgg(f).draw()
