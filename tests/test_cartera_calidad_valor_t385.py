"""Tarea 385 — las piezas del runner de la cartera de calidad y valor, con casos hechos a mano."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from data.fundamentos_pit import Fundamentos, Registro
from scripts.run_cartera_calidad_valor_t385 import (
    cagr_en,
    caida_maxima,
    calidad_mas_valor,
    criterios,
    fechas_de_rebalanceo,
    los_mejores,
    recortado_a,
    simular,
)


def test_primer_dia_habil_de_abril_de_cada_anio():
    cal = ["2017-03-31", "2017-04-03", "2017-04-04", "2018-04-02", "2018-05-01"]
    assert fechas_de_rebalanceo(cal) == ["2017-04-03", "2018-04-02"]


def test_los_mejores_sin_none_y_empates_por_ticker():
    assert los_mejores({"B": 1.0, "A": 1.0, "C": None, "D": 3.0}, n=2) == ["D", "A"]


def test_calidad_mas_valor_elige_barato_dentro_de_la_mitad_buena():
    """El más barato (Z) tiene mala calidad: no entra, aunque sea el de mayor retorno."""
    calidad = {"A": 90.0, "B": 80.0, "C": 20.0, "Z": 10.0}
    retorno = {"A": 0.05, "B": 0.10, "C": 0.12, "Z": 0.30}
    assert calidad_mas_valor(calidad, retorno, n=2) == ["B", "A"]


def test_simular_rebalancea_y_cobra_lo_operado():
    """A sube de 10 a 20 y B queda en 10. Rebalanceo en el día 1.

    Día 0: compra 0,5 en cada uno, paga 1,0 × 0,01 → 0,99. Día 1: vale 0,495×2 + 0,495 = 1,485;
    pasar a mitad y mitad opera |0,7425−0,99| + |0,7425−0,495| = 0,495 y paga 0,00495 → 1,48005.
    Día 2: A vuelve a 10 → la mitad en A cae a la mitad.
    """
    precios = np.array([[10.0, 10.0], [20.0, 10.0], [10.0, 10.0]])
    v = simular(precios, ["A", "B"], [0, 1], [["A", "B"], ["A", "B"]], costo=0.01)
    assert v[0] == pytest.approx(0.99)
    assert v[1] == pytest.approx(1.48005)
    assert v[2] == pytest.approx(1.48005 / 2 / 2 + 1.48005 / 2)
    # Sin rebalanceo en el día 1 el día 2 da otra cosa: 0,99 justo (A vuelve a 10).
    sin = simular(precios, ["A", "B"], [0], [["A", "B"]], costo=0.01)
    assert sin[2] == pytest.approx(0.99)


def test_un_ticker_sin_precio_en_el_rebalanceo_no_entra():
    precios = np.array([[10.0, 0.0], [11.0, 10.0]])
    v = simular(precios, ["A", "B"], [0], [["A", "B"]], costo=0.0)
    assert v[1] == pytest.approx(1.1)  # todo en A


def test_caida_maxima_y_subventanas():
    v = np.array([1.0, 2.0, 1.0, 1.5])
    assert caida_maxima(v) == pytest.approx(0.5)
    fechas = ["2019-12-30", "2019-12-31", "2020-01-02", "2020-01-03"]
    assert cagr_en(v, fechas, "2020-01-01", "2020-12-31") == pytest.approx(1.5**252 - 1)
    assert cagr_en(v, fechas, "2021-01-01", "2021-12-31") is None


def _bs(observado, ci_low):
    return lambda base, cand: SimpleNamespace(observed=observado, ci_low=ci_low, ci_high=ci_low + 0.1)


def test_criterios_pasa_solo_con_los_cinco():
    fechas = [f"20{y}-06-01" for y in (17, 18, 19, 20, 21, 22, 23, 24)]
    universo = np.array([1.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35])
    buena = np.array([1.0, 1.10, 1.20, 1.30, 1.40, 1.50, 1.60, 1.70])
    r = criterios(buena, universo, fechas, cagr_azar=[0.0] * 200, bootstrap=_bs(0.05, 0.01))
    assert r["pasa"] and r["subventanas_ganadas"] == 3
    # La misma cartera, con el azar ganándole: falla sólo el criterio 5. (Las series de 8 puntos se
    # anualizan como si fueran días, así que el crecimiento es enorme: el azar tiene que ser mayor.)
    r5 = criterios(buena, universo, fechas, cagr_azar=[1e300] * 200, bootstrap=_bs(0.05, 0.01))
    assert not r5["pasa"] and not r5["c5_seleccion"] and r5["c1_rendimiento"]
    # Y con un bootstrap que cruza el cero: falla sólo el 2.
    r2 = criterios(buena, universo, fechas, cagr_azar=[0.0] * 200, bootstrap=_bs(0.05, -0.01))
    assert not r2["pasa"] and not r2["c2_no_es_suerte"] and r2["c5_seleccion"]


def test_el_criterio_5_es_contra_el_percentil_90_y_no_contra_la_mediana():
    """La cartera le gana a la mediana del azar pero no a su percentil 90: no pasa."""
    fechas = [f"20{y}-06-01" for y in (17, 18, 19, 20, 21, 22, 23, 24)]
    universo = np.array([1.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35])
    buena = np.array([1.0, 1.10, 1.20, 1.30, 1.40, 1.50, 1.60, 1.70])
    c = criterios(buena, universo, fechas, cagr_azar=[0.0], bootstrap=_bs(0.05, 0.01))["cagr"]
    azar = [c / 2] * 150 + [c * 2] * 50  # mediana c/2, percentil 90 2c
    assert not criterios(buena, universo, fechas, cagr_azar=azar, bootstrap=_bs(0.05, 0.01))["c5_seleccion"]


def test_el_criterio_4_pide_dos_de_tres_subventanas():
    """Gana sólo la primera sub-ventana (2017-2019) y después queda quieta: 1 de 3 no alcanza."""
    fechas = [f"20{y}-06-01" for y in (17, 18, 19, 20, 21, 22, 23, 24)]
    universo = np.array([1.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35])
    cartera = np.array([1.0, 1.20, 1.40, 1.40, 1.40, 1.40, 1.40, 1.40])
    r = criterios(cartera, universo, fechas, cagr_azar=[0.0], bootstrap=_bs(0.05, 0.01))
    assert r["subventanas_ganadas"] == 1
    assert not r["c4_estabilidad"]


def test_el_recorte_deja_solo_lo_presentado_antes():
    f = Fundamentos(
        ticker="X",
        registros=[
            Registro("ganancia_neta", "2019-12-31", "2020-02-01", 1.0, "10-K", "NetIncomeLoss"),
            Registro("ganancia_neta", "2020-12-31", "2021-02-01", 2.0, "10-K", "NetIncomeLoss"),
        ],
    )
    assert [r.end for r in recortado_a(f, "2021-02-01").registros] == ["2019-12-31"]
    assert recortado_a(None, "2021-01-01") is None
