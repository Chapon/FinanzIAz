"""Tarea 440 — Claude recibe la deuda, los activos, el patrimonio y las acciones de cada año, y los
múltiplos del último año fiscal.

La opinión de TTWO del 2026-11-20 pidió la deuda y la cantidad de acciones *«para calcular múltiplos
que funcionen con ganancias negativas (precio/ventas…)»*. El almacén de EDGAR ya las tenía
(`deuda_lp`, `acciones_diluidas`, `activos`, `patrimonio`) y `fundamentales_anuales` no las mandaba.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from analysis import opinion_claude as oc
from data.fundamentos_pit import Fundamentos, Registro

# Las acciones, la deuda y el patrimonio CAMBIAN entre años: un bloque que tome otro año que el
# último da otro número.
_ANIOS = [
    # año, ventas, acciones, deuda, activos, patrimonio
    ("2023", 15_540e6, 1_090e6, 13_000e6, 64_000e6, 40_000e6),
    ("2024", 25_111e6, 1_110e6, 12_500e6, 69_000e6, 45_000e6),
    ("2025", 37_378e6, 1_130e6, 11_000e6, 80_000e6, 50_000e6),
]


def _r(concepto, end, filed, val, tag):
    return Registro(concepto=concepto, end=end, filed=filed, val=val, form="10-K", tag=tag)


def _fund(sin=()):
    regs = []
    for anio, ventas, acciones, deuda, activos, patrimonio in _ANIOS:
        end, filed = f"{anio}-08-31", f"{anio}-10-05"
        regs += [
            _r("revenue", end, filed, ventas, "Revenues"),
            _r("ganancia_neta", end, filed, ventas * 0.1, "NetIncomeLoss"),
            _r("acciones_diluidas", end, filed, acciones, "WeightedAverageNumberOfDilutedSharesOutstanding"),
            _r("deuda_lp", end, filed, deuda, "LongTermDebtNoncurrent"),
            _r("activos", end, filed, activos, "Assets"),
            _r("patrimonio", end, filed, patrimonio, "StockholdersEquity"),
        ]
    regs = [r for r in regs if (r.concepto, r.end[:4]) not in sin]
    return Fundamentos(ticker="MU", registros=regs)


def _anuales(**kw):
    return oc.fundamentales_anuales(kw.pop("fund", None) or _fund(), "2026-11-12", **kw)


def test_cada_anio_trae_su_deuda_activos_patrimonio_y_acciones():
    filas = {f["fin_anio_fiscal"][:4]: f for f in _anuales()}
    assert filas["2023"]["acciones_diluidas_m"] == 1_090.0
    assert filas["2025"]["acciones_diluidas_m"] == 1_130.0
    assert filas["2024"]["deuda_lp_musd"] == 12_500
    assert filas["2025"]["activos_musd"] == 80_000
    assert filas["2025"]["patrimonio_musd"] == 50_000


def test_las_acciones_van_en_la_base_de_hoy():
    """Como el EPS (418): un 2:1 posterior a la presentación duplica las acciones."""
    filas = _anuales(splits=[("2026-01-15", 2.0)])
    assert filas[-1]["acciones_diluidas_m"] == 2_260.0


def test_sin_deuda_informada_es_null_no_cero():
    filas = _anuales(fund=_fund(sin={("deuda_lp", "2025")}))
    assert filas[-1]["deuda_lp_musd"] is None


def test_los_multiplos_del_ultimo_anio_calculados_a_mano():
    m = oc.bloque_multiplos(100.0, _anuales())
    assert m["fin_anio_fiscal"] == "2025-08-31"
    assert m["capitalizacion_musd"] == 113_000  # 100 × 1.130 M, no las de 2023 (109.000)
    assert m["precio_ventas"] == pytest.approx(3.02, abs=0.005)  # 113.000 / 37.378
    assert m["deuda_lp_sobre_patrimonio"] == pytest.approx(0.22, abs=0.005)  # 11.000 / 50.000
    assert "no las de hoy" in m["nota"]


def test_sin_acciones_del_ultimo_anio_no_hay_capitalizacion():
    """Las de 2024 están, pero con dilución serían de otra empresa: no se usan."""
    m = oc.bloque_multiplos(100.0, _anuales(fund=_fund(sin={("acciones_diluidas", "2025")})))
    assert m["capitalizacion_musd"] is None and m["precio_ventas"] is None
    assert m["deuda_lp_sobre_patrimonio"] == pytest.approx(0.22, abs=0.005)


def test_con_patrimonio_negativo_no_hay_deuda_sobre_patrimonio():
    anuales = _anuales()
    anuales[-1]["patrimonio_musd"] = -5_000
    assert oc.bloque_multiplos(100.0, anuales)["deuda_lp_sobre_patrimonio"] is None


def test_sin_nada_que_calcular_se_calla():
    anuales = _anuales(fund=_fund(sin={("acciones_diluidas", "2025"), ("deuda_lp", "2025")}))
    assert oc.bloque_multiplos(100.0, anuales) is None
    assert oc.bloque_multiplos(100.0, []) is None
    assert oc.bloque_multiplos(None, _anuales()) is None


def _df(ultimo: float = 100.0):
    idx = pd.bdate_range(end="2026-11-11", periods=30)
    close = pd.Series(np.linspace(80, ultimo, 30), index=idx)
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1_000.0})


def test_armar_datos_manda_los_multiplos_con_el_precio_del_df():
    datos = oc.armar_datos("mu", _df(100.0), anuales=_anuales())
    assert datos["multiplos"]["capitalizacion_musd"] == 113_000
    assert datos["fundamentales_anuales"][-1]["deuda_lp_musd"] == 11_000
    json.dumps(datos)
    assert "multiplos" not in oc.armar_datos("mu", _df(100.0))


def test_el_prompt_explica_la_capitalizacion_y_la_deuda_null():
    p = oc.SYSTEM_PROMPT
    assert "multiplos" in p and "no por las de hoy" in p and "no que sea cero" in p


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 9
