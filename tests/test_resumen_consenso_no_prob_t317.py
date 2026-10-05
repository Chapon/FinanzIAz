"""Tarea 317 — la línea de resumen de Análisis no presenta el puntaje de consenso como probabilidad.

El defecto: ``analyze()`` armaba *«Prob. venta: 45%»* con el puntaje de consenso, que la 282 ya
había dejado de llamar probabilidad en la barra (*«▼ Consenso bajista 45/100»*, en la misma
pantalla). Y el 45 es el peso **comprador**: se leía como *45% de bajar*. Los cortes tampoco eran
los de la barra (``<= 0,45`` venta contra ``< 0,45`` bajista).
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from analysis.technical import analyze, consenso_txt


def _rotulo_de_la_barra(prob: float) -> str:
    from ui.analysis_tab import AnalysisTab

    falso = SimpleNamespace(prob_bar=MagicMock())
    AnalysisTab._update_prob_bar(falso, prob)
    return falso.prob_bar.setFormat.call_args[0][0]


@pytest.mark.parametrize("prob", [0.20, 0.35, 0.449, 0.45, 0.50, 0.549, 0.55, 0.72, 0.90])
def test_la_linea_dice_lo_MISMO_que_la_barra(prob):
    """Mismo número y mismo sentido; el borde 0,45 es donde antes discrepaban."""
    barra = _rotulo_de_la_barra(prob)
    linea = consenso_txt(prob)
    assert re.search(r"(\d+)/100", barra).group(1) == re.search(r"(\d+)/100", linea).group(1)
    for sentido in ("alcista", "bajista"):
        assert (sentido in barra) == (sentido in linea), (prob, barra, linea)
    assert ("Neutral" in barra) == ("neutral" in linea), (prob, barra, linea)


def test_el_resumen_de_analyze_no_dice_probabilidad(monkeypatch):
    from analysis import ml_signals

    monkeypatch.setattr(ml_signals, "detect_market_regime", lambda df: SimpleNamespace(regime="BULL"))
    monkeypatch.setattr(ml_signals, "compute_signal_probability", lambda signals, ctx: 0.45)
    monkeypatch.setattr(ml_signals, "train_xgboost_signal", lambda df: None)
    monkeypatch.setattr(ml_signals, "train_hmm_signal", lambda df: None)
    from analysis import garch_signals

    monkeypatch.setattr(garch_signals, "train_garch_signal", lambda df: None)
    monkeypatch.setattr("analysis.technical._toggle", lambda key, default=True: False)

    idx = pd.bdate_range("2025-01-02", periods=260)
    close = pd.Series([100 + (i % 7) for i in range(260)], index=idx, dtype=float)
    df = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1e6})
    res = analyze("TST", df)
    assert res.ml_probability == pytest.approx(0.45)
    assert "Prob." not in res.summary and "venta: 45%" not in res.summary
    assert "Consenso neutral 45/100" in res.summary, res.summary
