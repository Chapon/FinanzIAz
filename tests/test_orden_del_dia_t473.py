"""Tarea 473 — ORDEN-DEL-DIA-SIN-DECLARAR: el orden de los candidatos del día, como en vivo.

``simulate_portfolio`` sin ``rank_score`` procesa los candidatos en orden alfabético; el vivo, por
``_default_strength("BUY", ml_probability)``. Lo que se fija:

1. **Paridad con el motor:** ``fuerza_del_vivo`` es ``_default_strength("BUY", p)`` en todo el rango
   (falta, NaN, fuera de [0, 1], los bordes).
2. **El orden del vivo cambia quién entra:** con un lugar y dos candidatos, el alfabético toma al
   primero del abecedario y el del vivo al de mayor probabilidad (un caso donde difieren).
3. **Un nombre desconocido es un error**, y el del vivo sin store también.
4. **El desvío se declara** en todo harness con cartera que no ordena como el vivo, y no en uno sin
   cartera ni en uno que sí ordena como el vivo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.exit_replay import AtrParams
from analysis.harness_config import LIVE_UNIVERSE_FILE, HarnessConfig, deviations_keyed
from analysis.orden_del_dia import (
    ORDEN_ALFABETICO,
    ORDEN_VIVO,
    fuerza_del_vivo,
    orden_del_vivo,
    rank_del_orden,
)
from analysis.portfolio_sim import simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams
from paper_trading.strategies import _default_strength


@pytest.mark.parametrize("p", [None, float("nan"), float("inf"), -0.2, 0.0, 0.37, 0.999, 1.0, 1.4])
def test_paridad_con_default_strength(p):
    assert fuerza_del_vivo(p) == _default_strength("BUY", p)


def _barras(n=40):
    fechas = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-02", periods=n)]
    c = 100.0 * np.cumprod(1.0 + np.random.default_rng(1).normal(0.0, 0.01, n))
    return [(f, float(x), float(x), float(x), float(x)) for f, x in zip(fechas, c, strict=True)]


def test_el_orden_del_vivo_cambia_quien_entra():
    barras = {"AAA": _barras(), "ZZZ": _barras()}
    fecha = barras["AAA"][10][0]
    score_by = {"AAA": {fecha: 0.51}, "ZZZ": {fecha: 0.83}}  # ZZZ tiene más probabilidad
    kw = dict(
        max_positions=1,
        atr_p=AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False),
        costs=CostModel(commission=0.0, slippage=0.0),
        so_params=ScaleOutParams(),
        cap_days=5,
    )
    entradas = [("AAA", 10), ("ZZZ", 10)]
    alfa = simulate_portfolio(
        entradas, barras, {}, rank_score=rank_del_orden(ORDEN_ALFABETICO, score_by), **kw
    )
    vivo = simulate_portfolio(entradas, barras, {}, rank_score=rank_del_orden(ORDEN_VIVO, score_by), **kw)
    assert [t.ticker for t in alfa.trades] == ["AAA"]
    assert [t.ticker for t in vivo.trades] == ["ZZZ"]


def test_sin_probabilidad_el_vivo_le_da_uno():
    rank = orden_del_vivo({"KO": {"2024-01-02": 0.4}})
    assert rank("KO", "2024-01-02") == pytest.approx(0.4)
    assert rank("KO", "2024-01-03") == 1.0 and rank("PEP", "2024-01-02") == 1.0


def test_nombres_desconocidos_y_el_vivo_sin_store():
    with pytest.raises(ValueError, match="orden desconocido"):
        rank_del_orden("ranking", {})
    with pytest.raises(ValueError, match="score_by"):
        rank_del_orden(ORDEN_VIVO, None)
    assert rank_del_orden(ORDEN_ALFABETICO, None) is None


def _claves(**kw):
    cfg = HarnessConfig(max_positions=10, universe_file=LIVE_UNIVERSE_FILE, n_tickers=126, **kw)
    return {d.clave for d in deviations_keyed(cfg)}


def test_el_desvio_se_declara_en_todo_harness_con_cartera_que_no_ordena_como_el_vivo():
    assert "orden_del_dia" in _claves()
    assert "orden_del_dia" not in _claves(orden_del_vivo=True)
    sin_cartera = HarnessConfig(
        max_positions=None, universe_file=LIVE_UNIVERSE_FILE, n_tickers=126, per_trade=True
    )
    assert "orden_del_dia" not in {d.clave for d in deviations_keyed(sin_cartera)}
