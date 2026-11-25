"""Tarea 465 — REGIMEN-CONTRA-SU-CAJA: las piezas del runner, sin datos de mercado.

El runner (`scripts/run_regimen_caja_t465.py`) compara el escalado por régimen contra una caja
constante cuya `w` se fija en un tramo y se mide en el otro, en los dos sentidos. Lo que se fija:

1. **La regla de `w`:** la más alta de la grilla cuya mezcla no cae más que el objetivo, y `None`
   si ninguna. Con una caída objetivo entre dos `w`, la elegida es la de abajo.
2. **La lectura:** los dos tramos ⇒ se sostiene; ninguno ⇒ no; uno ⇒ depende del tramo.
3. **Un tramo:** la `w` sale de la calibración y no del test, y S y D se miden en el test. El caso
   sintético tiene una caída fuerte sólo en el test, para que una `w` calibrada en el test diera
   otra cosa.
4. **Los tramos son los del pre-registro**, y se cubren entre los dos sin solaparse.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import scripts.run_regimen_caja_t465 as r
from analysis.exit_replay import max_drawdown
from scripts.run_activo_pasivo_t456 import mezcla_constante


def _curva(rets, desde="2017-01-02"):
    fechas = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(desde, periods=len(rets))]
    return list(zip(fechas, (50_000.0 * np.cumprod(1.0 + np.asarray(rets))).tolist(), strict=True))


# ── 1. la regla de w ─────────────────────────────────────────────────────────


def test_w_es_la_mas_alta_que_no_cae_mas_que_el_objetivo():
    sin = _curva(np.random.default_rng(1).normal(0.0005, 0.015, 600))
    fechas, precio = [d for d, _ in sin], dict(sin)
    dd = {
        w: max_drawdown(mezcla_constante(fechas, precio, w, costo=0.0, capital=50_000.0)) for w in (0.6, 0.61)
    }
    assert dd[0.6] < dd[0.61]
    objetivo = (dd[0.6] + dd[0.61]) / 2  # entre dos w: tiene que elegir la de abajo
    assert r.w_por_caida(sin, objetivo, costo=0.0, capital=50_000.0) == 0.6
    assert r.w_por_caida(sin, 1.0, costo=0.0, capital=50_000.0) == 1.0
    assert r.w_por_caida(sin, 0.0, costo=0.0, capital=50_000.0) is None
    assert r.w_por_caida([], 0.2, costo=0.0, capital=50_000.0) is None


# ── 2. la lectura ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pasa", "esperado"),
    [
        ({"A": True, "B": True}, r.SE_SOSTIENE),
        ({"A": False, "B": False}, r.NO_SE_SOSTIENE),
        ({"A": True, "B": False}, r.DEPENDE),
        ({"A": False, "B": True}, r.DEPENDE),
    ],
)
def test_la_lectura(pasa, esperado):
    assert r.veredicto(pasa) == esperado


# ── 3. un tramo ───────────────────────────────────────────────────────────────


def _caso():
    """2017-2021 tranquilo, 2021-2026 con un derrumbe. El régimen corta la mitad de cada día malo."""
    fechas = pd.bdate_range("2017-01-02", "2026-08-31")
    rng = np.random.default_rng(5)
    base = rng.normal(0.0005, 0.01, len(fechas))
    crash = (fechas >= "2022-03-01") & (fechas < "2022-04-15")
    base[crash] = -0.02
    reg = np.where(base < 0, base * 0.5, base * 0.9)
    return _curva(reg), _curva(base)


def test_un_tramo_calibra_w_en_la_calibracion_y_mide_en_el_test():
    reg, sin = _caso()
    a = r.evaluar_tramo(reg, sin, r.TRAMOS[0], costo=0.0, capital=50_000.0, resamples=100)
    b = r.evaluar_tramo(reg, sin, r.TRAMOS[1], costo=0.0, capital=50_000.0, resamples=100)
    # La w de A sale de la caída del régimen ANTES del derrumbe; la de B, de la de DESPUÉS.
    assert a["dd_calibracion_regimen"] == pytest.approx(max_drawdown(r.cortar(reg, None, "2021-07-31")))
    assert b["dd_calibracion_regimen"] == pytest.approx(
        max_drawdown(r.cortar(reg, "2021-08-01", "2026-07-31"))
    )
    assert a["w"] != b["w"]
    assert a["test"].startswith("2021-08-02") and b["test"].endswith("2021-07-30")
    # La caja del test es la mezcla con la w de la CALIBRACIÓN, y esa w no es la que daría el test.
    sin_t = r.cortar(sin, "2021-08-01", "2026-07-31")
    caja_t = mezcla_constante([d for d, _ in sin_t], dict(sin_t), a["w"], costo=0.0, capital=50_000.0)
    assert a["caja"]["max_dd"] == pytest.approx(max_drawdown(caja_t))
    dd_reg_test = max_drawdown(r.cortar(reg, "2021-08-01", "2026-07-31"))
    assert r.w_por_caida(sin_t, dd_reg_test, costo=0.0, capital=50_000.0) != a["w"]
    assert a["regimen"]["max_dd"] == pytest.approx(dd_reg_test)
    assert a["S"] == (a["regimen"]["sharpe"] >= a["caja"]["sharpe"])
    assert a["D"] == (a["regimen"]["max_dd"] <= a["caja"]["max_dd"] + 0.01)
    assert a["pasa"] == (a["S"] and a["D"])
    assert a["boot_sharpe"]["observed"] == pytest.approx(
        a["regimen"]["sharpe"] - a["caja"]["sharpe"], rel=1e-9
    )
    assert set(a["ventanas_regimen"]) == set(a["ventanas_caja"])


def test_sin_w_el_tramo_no_tiene_comparacion():
    reg, sin = _caso()
    plano = [(d, 50_000.0) for d, _ in reg]  # el régimen no cae nunca: ninguna w alcanza
    t = r.evaluar_tramo(plano, sin, r.TRAMOS[0], costo=0.0, capital=50_000.0, resamples=50)
    assert t["w"] is None and "pasa" not in t


# ── 4. los tramos del pre-registro ───────────────────────────────────────────


def test_los_tramos_son_los_del_prerregistro():
    (na, ca0, ca1, ta0, ta1), (nb, cb0, cb1, tb0, tb1) = r.TRAMOS
    assert (na, nb) == ("A", "B")
    assert (ca0, ca1, ta0, ta1) == (None, "2021-07-31", "2021-08-01", "2026-07-31")
    assert (cb0, cb1, tb0, tb1) == ("2021-08-01", "2026-07-31", None, "2021-07-31")
    assert r.GRILLA_W[0] == 0.01 and r.GRILLA_W[-1] == 1.0 and len(r.GRILLA_W) == 100
    assert r.D_TOL == 0.01
