"""Tarea 471 — LUGAR-DEL-BLOQUEADO: en vivo, el pick que frena un gate se queda con su lugar.

``generate_trades_analyze_single`` corta los candidatos a ``ranked[:free_slots]`` **antes** de que
el motor corra los gates de compra, así que un pick frenado deja su lugar vacío en ese scan. El
simulador se lo daba al siguiente. ``simulate_portfolio(lugar_del_bloqueado=True)`` modela el vivo.
Lo que se fija:

1. **Sin la opción, nada cambia**; y con ella, sin ningún pick frenado, tampoco.
2. **Con la opción, el pick frenado pierde su lugar** (por el filtro o por el Gate 5) y el
   candidato siguiente no lo recibe; sin la opción, sí.
3. **Los picks son los primeros no tenidos:** un candidato que ya está en cartera no ocupa un lugar
   de pick, como en vivo (el motor los saltea al armar el ranking).
4. **No se combina con el overlay**, cuya previsión replica la otra regla.

Los casos tienen un candidato frenado **arriba** del ranking y otro libre debajo: sin eso, las dos
reglas dan lo mismo y el test no distinguiría nada.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.exit_replay import AtrParams
from analysis.portfolio_sim import simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams


def _barras(n=80, seed=3, inicio="2024-01-02"):
    fechas = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(inicio, periods=n)]
    c = 100.0 * np.cumprod(1.0 + np.random.default_rng(seed).normal(0.0, 0.01, n))
    return [(f, float(x), float(x), float(x), float(x)) for f, x in zip(fechas, c, strict=True)]


BARRAS = {t: _barras(seed=k + 1) for k, t in enumerate(["A", "B", "C", "D"])}
RANGO = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0}  # A primero


def _sim(entradas, **kw):
    kw.setdefault("atr_p", AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False))
    kw.setdefault("costs", CostModel(commission=0.0, slippage=0.0))
    kw.setdefault("so_params", ScaleOutParams())
    kw.setdefault("cap_days", 5)
    kw.setdefault("rank_score", lambda t, _d: RANGO[t])
    return simulate_portfolio(entradas, BARRAS, {}, **kw)


def _firma(res):
    return [(t.ticker, t.entry_date, t.exit_date, t.invested, t.proceeds) for t in res.trades]


# ── 1. sin pick frenado, las dos reglas dan lo mismo ─────────────────────────


def test_sin_pick_frenado_es_identico():
    entradas = [(t, i) for i in (10, 20, 30) for t in "ABCD"]
    sin = _sim(entradas, max_positions=2)
    con = _sim(entradas, max_positions=2, lugar_del_bloqueado=True)
    assert _firma(con) == _firma(sin) and con.equity_curve == sin.equity_curve
    assert con.n_lugar_perdido == 0 and sin.n_lugar_perdido == 0


# ── 2. el pick frenado pierde su lugar ───────────────────────────────────────


def test_el_pick_frenado_por_el_filtro_pierde_su_lugar():
    entradas = [("A", 10), ("B", 10)]
    filtro = lambda t, _d: 0.0 if t == "A" else 1.0  # A, el primero, frenado
    hoy = _sim(entradas, max_positions=1, entry_filter=filtro)
    vivo = _sim(entradas, max_positions=1, entry_filter=filtro, lugar_del_bloqueado=True)
    assert [t.ticker for t in hoy.trades] == ["B"]  # el simulador le daba el lugar a B
    assert vivo.trades == [] and vivo.n_lugar_perdido == 1  # en vivo el lugar queda vacío
    assert vivo.n_no_slot == 1  # B no era pick: no había más lugares


def test_con_dos_lugares_el_frenado_pierde_uno_y_el_otro_se_usa():
    entradas = [("A", 10), ("B", 10), ("C", 10)]
    filtro = lambda t, _d: 0.0 if t == "A" else 1.0
    hoy = _sim(entradas, max_positions=2, entry_filter=filtro)
    vivo = _sim(entradas, max_positions=2, entry_filter=filtro, lugar_del_bloqueado=True)
    assert sorted(t.ticker for t in hoy.trades) == ["B", "C"]
    assert [t.ticker for t in vivo.trades] == ["B"] and vivo.n_lugar_perdido == 1


def test_el_pick_frenado_por_el_gate5_pierde_su_lugar():
    # A pierde en un ciclo que cierra el día 15 y vuelve a ser candidato el 18: el Gate 5 lo frena.
    barras = dict(BARRAS)
    a = list(_barras(seed=9))
    for i in range(11, 16):
        f = a[i][0]
        a[i] = (f, 90.0, 90.0, 90.0, 90.0)
    barras["A"] = a
    entradas = [("A", 10), ("A", 18), ("B", 18)]
    kw = dict(max_positions=1, live_gates=True)
    hoy = simulate_portfolio(
        entradas,
        barras,
        {},
        atr_p=AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False),
        costs=CostModel(commission=0.0, slippage=0.0),
        so_params=ScaleOutParams(),
        cap_days=5,
        rank_score=lambda t, _d: RANGO[t],
        **kw,
    )
    vivo = simulate_portfolio(
        entradas,
        barras,
        {},
        atr_p=AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False),
        costs=CostModel(commission=0.0, slippage=0.0),
        so_params=ScaleOutParams(),
        cap_days=5,
        rank_score=lambda t, _d: RANGO[t],
        lugar_del_bloqueado=True,
        **kw,
    )
    assert hoy.n_gate5_blocked == 1 and vivo.n_gate5_blocked == 1
    assert [t.ticker for t in hoy.trades] == ["A", "B"]
    assert [t.ticker for t in vivo.trades] == ["A"] and vivo.n_lugar_perdido == 1


# ── 3. lo tenido no ocupa lugar de pick ──────────────────────────────────────


def test_lo_tenido_no_ocupa_un_lugar_de_pick():
    # El día 12, A ya está en cartera (entró el 10, tope 5): no es pick y B toma el lugar libre.
    entradas = [("A", 10), ("A", 12), ("B", 12)]
    vivo = _sim(entradas, max_positions=2, lugar_del_bloqueado=True)
    assert [t.ticker for t in vivo.trades] == ["A", "B"]
    assert vivo.n_already_open == 1 and vivo.n_lugar_perdido == 0


# ── 4. no se combina con el overlay ──────────────────────────────────────────


def test_no_se_combina_con_el_overlay():
    with pytest.raises(ValueError, match="lugar_del_bloqueado"):
        _sim(
            [("A", 10)],
            max_positions=1,
            tajada_del_dia=True,
            lugar_del_bloqueado=True,
            vol_overlay=lambda *a: 1.0,
        )


# ── 5. el desvío se declara cuando hay un gate de compra modelado ────────────


def _claves(**kw):
    from analysis.harness_config import LIVE_UNIVERSE_FILE, HarnessConfig, deviations_keyed

    cfg = HarnessConfig(max_positions=10, universe_file=LIVE_UNIVERSE_FILE, n_tickers=126, **kw)
    return {d.clave for d in deviations_keyed(cfg)}


def test_el_desvio_se_declara_con_un_gate_de_compra_y_sin_la_regla_del_vivo():
    assert "lugar_del_bloqueado" in _claves(live_gates=True)
    assert "lugar_del_bloqueado" in _claves(models_earnings_blackout=True)
    assert "lugar_del_bloqueado" not in _claves(live_gates=True, models_lugar_del_bloqueado=True)
    assert "lugar_del_bloqueado" not in _claves()  # sin gates de compra no hay pick frenado
