"""Tarea 456 — el pasivo, la regla de ``w`` y el gate de ``run_activo_pasivo_t456``.

Todo offline y sobre datos fabricados. Cada caso está elegido para que la versión correcta y la
defectuosa **difieran** (el rebalanceo que no ocurre, la ``w`` más baja en vez de la más alta,
el veredicto dado vuelta): el caso natural suele ser degenerado y sale verde sin fijar nada.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from analysis.exit_replay import max_drawdown
from scripts import run_activo_pasivo_t456 as t456
from scripts.run_exit_policy_t170 import D1_MIN_DCAGR_OOS, D2_MIN_FOLDS, D5_DD_TOL


def _habiles(desde: str, hasta: str) -> list[str]:
    d, fin, out = date.fromisoformat(desde), date.fromisoformat(hasta), []
    while d <= fin:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ── mezcla_constante ─────────────────────────────────────────────────────────


def test_sin_costos_w1_es_el_cociente_de_cierres():
    fechas = _habiles("2021-01-04", "2021-06-30")
    rng = np.random.default_rng(1)
    precio = dict(zip(fechas, 100 * np.cumprod(1 + rng.normal(0, 0.01, len(fechas))), strict=True))
    curva = t456.mezcla_constante(fechas, precio, 1.0, costo=0.0, capital=50_000)
    assert curva[-1][1] / 50_000 == pytest.approx(precio[fechas[-1]] / precio[fechas[0]], abs=1e-12)


def test_w0_queda_plano():
    fechas = _habiles("2021-01-04", "2021-03-31")
    precio = {d: 100.0 + i for i, d in enumerate(fechas)}
    curva = t456.mezcla_constante(fechas, precio, 0.0, costo=0.0015, capital=1_000)
    assert all(v == pytest.approx(1_000) for _, v in curva)


def test_el_rebalanceo_mensual_OCURRE():
    """Enero duplica el precio y febrero lo devuelve. Con rebalanceo, el 1/2 la mezcla vuelve a
    50/50 sobre 1,5 y febrero termina en 0,75 + 0,375 = 1,125. Sin rebalanceo, terminaría en
    1,0 exacto (0,5 de acciones a la mitad de precio + 0,5 de caja). Distingue las dos."""
    fechas = ["2021-01-04", "2021-01-29", "2021-02-01", "2021-02-26"]
    precio = {"2021-01-04": 100.0, "2021-01-29": 200.0, "2021-02-01": 200.0, "2021-02-26": 100.0}
    curva = dict(t456.mezcla_constante(fechas, precio, 0.5, costo=0.0, capital=1.0))
    assert curva["2021-01-29"] == pytest.approx(1.5)
    assert curva["2021-02-26"] == pytest.approx(1.125)


def test_los_costos_restan():
    fechas = _habiles("2021-01-04", "2021-12-31")
    rng = np.random.default_rng(7)
    precio = dict(zip(fechas, 100 * np.cumprod(1 + rng.normal(0, 0.02, len(fechas))), strict=True))
    sin = t456.mezcla_constante(fechas, precio, 0.7, costo=0.0, capital=1.0)
    con = t456.mezcla_constante(fechas, precio, 0.7, costo=0.0015, capital=1.0)
    assert con[-1][1] < sin[-1][1]
    # con w=1 los costos nunca dejan a la mezcla por encima del activo
    uno = t456.mezcla_constante(fechas, precio, 1.0, costo=0.0015, capital=1.0)
    assert all(v <= precio[d] / precio[fechas[0]] + 1e-12 for d, v in uno)


def test_w_fuera_de_rango_es_error():
    with pytest.raises(ValueError):
        t456.mezcla_constante(["2021-01-04"], {"2021-01-04": 1.0}, 1.2, costo=0.0, capital=1.0)


# ── w_por_regla ──────────────────────────────────────────────────────────────


def _con_caida_del_50() -> tuple[list[str], dict[str, float]]:
    """Una caída del 50% adentro de un solo mes: la caída de la mezcla es w × 50%."""
    fechas = _habiles("2021-03-01", "2021-03-31")
    precio = {d: 100.0 - 50.0 * i / (len(fechas) - 1) for i, d in enumerate(fechas)}
    return fechas, precio


def test_la_regla_elige_la_w_MAS_ALTA_que_cumple():
    """Con objetivo 25% cumplen 0,05 … 0,50. La correcta es 0,50; una versión que se quedara
    con la primera que cumple daría 0,05."""
    fechas, precio = _con_caida_del_50()
    w = t456.w_por_regla(0.25, fechas, precio, costo=0.0, capital=1.0)
    assert w == pytest.approx(0.50)
    curva = t456.mezcla_constante(fechas, precio, w, costo=0.0, capital=1.0)
    assert max_drawdown(curva) <= 0.25 + 1e-12


def test_la_regla_da_None_si_ninguna_cumple():
    fechas, precio = _con_caida_del_50()
    assert t456.w_por_regla(0.01, fechas, precio, costo=0.0, capital=1.0) is None


def test_la_regla_da_1_si_el_activo_cae_menos_que_el_objetivo():
    fechas, precio = _con_caida_del_50()
    assert t456.w_por_regla(0.60, fechas, precio, costo=0.0, capital=1.0) == pytest.approx(1.0)


# ── serie_en_calendario e indice_universo ───────────────────────────────────


def test_la_serie_arrastra_el_ultimo_cierre_y_exige_el_primero():
    fechas = ["2021-01-04", "2021-01-05", "2021-01-06"]
    s = t456.serie_en_calendario(fechas, {"2021-01-04": 10.0, "2021-01-06": 12.0})
    assert s == {"2021-01-04": 10.0, "2021-01-05": 10.0, "2021-01-06": 12.0}
    with pytest.raises(ValueError):
        t456.serie_en_calendario(fechas, {"2021-01-05": 10.0})


def test_el_indice_vuelve_a_partes_iguales_cada_mes():
    """A duplica en enero y B queda quieta. Sin rebalanceo, febrero (A vuelve a 100) dejaría el
    índice en 1,0; con rebalanceo el 1/2 queda 0,75 de A y 0,75 de B, y febrero cierra en 1,125."""
    fechas = ["2021-01-04", "2021-01-29", "2021-02-01", "2021-02-26"]
    a = {"2021-01-04": 100.0, "2021-01-29": 200.0, "2021-02-01": 200.0, "2021-02-26": 100.0}
    b = dict.fromkeys(fechas, 50.0)
    idx = t456.indice_universo(fechas, {"A": a, "B": b}, costo=0.0)
    assert idx["2021-01-29"] == pytest.approx(1.5)
    assert idx["2021-02-26"] == pytest.approx(1.125)


def test_un_ticker_nuevo_entra_recien_en_el_rebalanceo_siguiente():
    fechas = ["2021-01-04", "2021-01-15", "2021-02-01", "2021-02-26"]
    a = dict.fromkeys(fechas, 10.0)
    c = {"2021-01-15": 10.0, "2021-02-01": 10.0, "2021-02-26": 20.0}  # aparece a mitad de enero
    idx = t456.indice_universo(fechas, {"A": a, "C": c}, costo=0.0)
    assert idx["2021-01-15"] == pytest.approx(1.0)  # todavía es sólo A
    assert idx["2021-02-26"] == pytest.approx(1.5)  # desde febrero, mitad y mitad


# ── evaluar (el gate) ────────────────────────────────────────────────────────


def _curva(fechas: list[str], deriva: float, ruido: float, semilla: int) -> list[tuple[str, float]]:
    rng = np.random.default_rng(semilla)
    v = 50_000 * np.cumprod(1 + deriva + rng.normal(0, ruido, len(fechas)))
    return list(zip(fechas, v.tolist(), strict=True))


def _par(fechas, deriva_v, deriva_p, *, beta_v=0.6, beta_p=0.6, semilla=0):
    """Vivo y pasivo movidos por el MISMO mercado más un ruido propio chico, como en la
    realidad: el bootstrap pareado cancela lo común y queda el efecto. Con ruidos
    independientes el IC de cinco años mide 14 pp de ancho y ningún caso decide."""
    rng = np.random.default_rng(semilla)
    m = rng.normal(0, 0.01, len(fechas))
    v = 50_000 * np.cumprod(1 + deriva_v + beta_v * m + rng.normal(0, 0.001, len(fechas)))
    p = 50_000 * np.cumprod(1 + deriva_p + beta_p * m + rng.normal(0, 0.001, len(fechas)))
    return list(zip(fechas, v.tolist(), strict=True)), list(zip(fechas, p.tolist(), strict=True))


@pytest.fixture(scope="module")
def calendario() -> list[str]:
    return _habiles("2017-09-01", "2026-08-31")


def test_un_pasivo_que_rinde_claramente_mas_GANA(calendario):
    vivo, pasivo = _par(calendario, 0.0001, 0.0005, semilla=1)
    ev = t456.evaluar(vivo, pasivo, resamples=300)
    assert ev["veredicto"] == t456.PASIVO_GANA, ev["condiciones"]


def test_el_espejo_cuando_la_estrategia_rinde_mas(calendario):
    vivo, pasivo = _par(calendario, 0.0005, 0.0001, semilla=2)
    ev = t456.evaluar(vivo, pasivo, resamples=300)
    assert ev["veredicto"] == t456.ESTRATEGIA_GANA, ev["espejo"]


def test_con_la_misma_deriva_no_es_decidible(calendario):
    vivo, pasivo = _par(calendario, 0.0003, 0.0003, semilla=3)
    assert t456.evaluar(vivo, pasivo, resamples=300)["veredicto"] == t456.NO_DECIDIBLE


def test_un_pasivo_que_gana_pero_cae_mucho_mas_NO_pasa_C4(calendario):
    """El pasivo rinde más pero con el doble de exposición al mercado: C1 pasa y C4 no, así
    que no gana. Es la condición que impide comprar retorno con riesgo."""
    vivo, pasivo = _par(calendario, 0.0001, 0.0006, beta_v=0.5, beta_p=1.2, semilla=4)
    ev = t456.evaluar(vivo, pasivo, resamples=300)
    assert ev["condiciones"]["C1"] and not ev["condiciones"]["C4"], ev
    assert ev["veredicto"] != t456.PASIVO_GANA


def test_un_delta_grande_con_el_IC_cruzando_el_cero_NO_alcanza(calendario):
    """C1, C2 y C4 pasan y sólo C3 decide: con ruidos independientes el Δ da +3,8 pp y 4 de 5
    folds, y el IC va de −3,8 a +10,6. Es el riesgo que el §4 del pre-registro escribió antes de
    correr: un punto estimado grande no es evidencia si el intervalo cruza el cero."""
    vivo = _curva(calendario, 0.0001, 0.004, 1)
    pasivo = _curva(calendario, 0.0006, 0.004, 2)
    ev = t456.evaluar(vivo, pasivo, resamples=300)
    c = ev["condiciones"]
    assert c["C1"] and c["C2"] and c["C4"] and not c["C3"], ev
    assert ev["veredicto"] == t456.NO_DECIDIBLE


def test_calendarios_distintos_es_error(calendario):
    vivo = _curva(calendario, 0.0001, 0.004, 9)
    i = next(k for k, (d, _) in enumerate(vivo) if d >= "2023-01-01")  # una fecha DEL test
    with pytest.raises(ValueError):
        t456.evaluar(vivo, vivo[:i] + vivo[i + 1 :], resamples=50)


def test_los_umbrales_SON_los_de_la_T170():
    """El pre-registro los hereda de la T170; importados, no copiados."""
    assert t456.C1_MIN_DCAGR == D1_MIN_DCAGR_OOS
    assert t456.C2_MIN_FOLDS == D2_MIN_FOLDS
    assert t456.C4_DD_TOL == D5_DD_TOL
    assert (t456.OOS_DESDE, t456.OOS_HASTA) == ("2021-08-01", "2026-07-31")
    assert t456.GRILLA_W[0] == pytest.approx(0.05) and t456.GRILLA_W[-1] == pytest.approx(1.0)
    assert len(t456.GRILLA_W) == 20


# ── sanity ───────────────────────────────────────────────────────────────────


def test_el_control_del_pasivo_pasa_con_precios_cualquiera():
    fechas = _habiles("2020-01-02", "2020-12-31")
    rng = np.random.default_rng(11)
    precio = dict(zip(fechas, 300 * np.cumprod(1 + rng.normal(0, 0.02, len(fechas))), strict=True))
    assert t456.control_pasivo(fechas, precio, 50_000)["OK"]


class _T:
    def __init__(self, f: float) -> None:
        self.size_factor = f


class _R:
    def __init__(self, fs: list[float]) -> None:
        self.trades = [_T(f) for f in fs]


def test_fraccion_escalada_cuenta_las_entradas_tocadas():
    assert t456.fraccion_escalada(_R([1.0, 0.25, 1.0, 0.25])) == pytest.approx(0.5)
    assert t456.fraccion_escalada(_R([])) == 0.0
