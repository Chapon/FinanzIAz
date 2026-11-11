"""Tarea 418: Claude recibe la valuación de la tarjeta, los fundamentales anuales de EDGAR y el P/E de Yahoo.

Las dos opiniones de MU del 2026-11-11 pidieron *«ingresos, márgenes, P/E y guidance»*, y la misma
pestaña ya los calculaba en la tarjeta de valuación de la 383 sin mandárselos. Lo que se fija acá:
que lo que recibe Claude sea lo mismo que ve Chapa en la tarjeta, que los años sean los
point-in-time del almacén de la 382, y que el prompt diga lo que la app NO tiene (guidance,
trimestres) para que deje de anotarlo como faltante.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from analysis import opinion_claude as oc
from analysis.valuation import Valuacion
from data.fundamentos_pit import Fundamentos, Registro
from ui.analysis.valuation_card import lineas_de


def _df():
    idx = pd.bdate_range(end="2026-11-11", periods=30)
    close = pd.Series(np.linspace(100, 129, 30), index=idx)
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1e6})


def _valuacion():
    return Valuacion(
        precio=800.0,
        eps=74.33,
        valor_libro_x_accion=121.07,
        numero_graham=449.97,
        margen_graham=-0.778,
        crecimiento=0.12,
        anios_crecimiento=10,
        pe_historico=12.4,
        anios_pe=14,
        precio_en_10=2860.5,
        retorno_anual=0.136,
        precio_max_objetivo=707.1,
        peg=0.15,
        categoria="recuperación",
        motivo_categoria="volvió a ganar después de perder",
        fin_ultimo_anio="2026-09-03",
        avisos=["crecimiento topeado en 15%"],
        calidad={"puntaje": 69.4, "percentiles": {"roe": 20.0, "deuda": 100.0}, "n": 125, "al": "2026-11-12"},
    )


# ── La valuación: lo mismo que la tarjeta ────────────────────────────────────


def test_el_bloque_dice_lo_mismo_que_la_tarjeta():
    v = _valuacion()
    b = oc.bloque_valuacion(v)
    tarjeta = "\n".join(lineas_de(v))
    # Cada número del bloque aparece, con el formato de la tarjeta, en lo que ve Chapa.
    assert f"${b['graham']['valor']:,.2f}" in tarjeta
    assert f"{b['graham']['margen_de_seguridad_pct'] / 100:+.1%}" in tarjeta
    assert f"${b['eps_diluido']:,.2f}" in tarjeta and f"${b['valor_libro_x_accion']:,.2f}" in tarjeta
    assert f"{b['buffettology']['retorno_anual_esperado_pct'] / 100:+.1%}" in tarjeta
    assert f"${b['buffettology']['precio_max_para_15_anual']:,.2f}" in tarjeta
    assert f"${b['buffettology']['precio_en_10_anios']:,.2f}" in tarjeta
    assert f"PE mediano de {b['buffettology']['pe_historico_mediano']:.1f}" in tarjeta
    assert f"PEG {b['lynch']['peg']:.2f}" in tarjeta and b["lynch"]["categoria"] in tarjeta
    assert f"{b['calidad']['puntaje_0_a_100']:.0f}/100 entre 125" in tarjeta
    assert b["avisos"] == v.avisos
    assert b["pe_con_ese_eps"] == pytest.approx(800 / 74.33, abs=0.05)


def test_con_la_tarjeta_callada_no_se_inventa_nada():
    assert oc.bloque_valuacion(None) is None
    datos = oc.armar_datos("mu", _df(), valuacion=None, anuales=[])
    assert "valuacion" not in datos and "fundamentales_anuales" not in datos


def test_sin_eps_positivo_no_hay_pe():
    v = _valuacion()
    v.eps = -5.34
    assert oc.bloque_valuacion(v)["pe_con_ese_eps"] is None


# ── Los años de EDGAR ────────────────────────────────────────────────────────


def _r(concepto, end, filed, val, tag):
    return Registro(concepto=concepto, end=end, filed=filed, val=val, form="10-K", tag=tag)


def _fund():
    regs = []
    for anio, ventas, neta, bruta, eps in [
        ("2023", 15_540e6, -5_833e6, -1_416e6, -5.34),
        ("2024", 25_111e6, 778e6, 5_625e6, 0.70),
        ("2025", 37_378e6, 8_539e6, 14_876e6, 7.59),
    ]:
        end, filed = f"{anio}-08-31", f"{anio}-10-05"
        regs += [
            _r("revenue", end, filed, ventas, "Revenues"),
            _r("ganancia_neta", end, filed, neta, "NetIncomeLoss"),
            _r("ganancia_bruta", end, filed, bruta, "GrossProfit"),
            _r("eps_diluido", end, filed, eps, "EarningsPerShareDiluted"),
        ]
    # El 10-K de 2025 repite 2024 como comparativo: la PRIMERA presentación sigue siendo 2024-10-05.
    regs.append(_r("revenue", "2024-08-31", "2025-10-05", 25_111e6, "Revenues"))
    # Y uno presentado DESPUÉS de la fecha de corte no se conoce todavía (point-in-time).
    regs.append(_r("revenue", "2026-08-31", "2026-12-01", 99e9, "Revenues"))
    return Fundamentos(ticker="MU", registros=regs)


def test_los_anios_en_millones_y_los_margenes_a_mano():
    filas = oc.fundamentales_anuales(_fund(), "2026-11-12")
    assert [f["fin_anio_fiscal"] for f in filas] == ["2023-08-31", "2024-08-31", "2025-08-31"]
    u = filas[-1]
    assert u["ventas_musd"] == 37_378 and u["ganancia_neta_musd"] == 8_539
    assert u["margen_bruto_pct"] == pytest.approx(39.8, abs=0.05)  # 14.876 / 37.378
    assert u["margen_neto_pct"] == pytest.approx(22.8, abs=0.05)  # 8.539 / 37.378
    assert u["eps_diluido"] == 7.59 and u["flujo_operativo_musd"] is None


def test_la_fecha_es_la_primera_presentacion_no_el_comparativo():
    filas = {f["fin_anio_fiscal"]: f for f in oc.fundamentales_anuales(_fund(), "2026-11-12")}
    assert filas["2024-08-31"]["presentado_por_primera_vez"] == "2024-10-05"


def test_cuantos_anios_y_sin_almacen():
    assert len(oc.fundamentales_anuales(_fund(), "2026-11-12", n=2)) == 2
    assert oc.fundamentales_anuales(None, "2026-11-12") == []
    assert oc.fundamentales_anuales(Fundamentos(ticker="X", extranjera=True), "2026-11-12") == []


def test_el_eps_va_en_la_base_de_acciones_de_hoy():
    # Un split 2:1 después de la presentación de 2025 parte su EPS por dos, como en la valuación.
    filas = oc.fundamentales_anuales(_fund(), "2026-11-12", splits=[("2026-01-15", 2.0)])
    assert filas[-1]["eps_diluido"] == pytest.approx(7.59 / 2, abs=0.005)


# ── Lo que se manda y lo que se dice ─────────────────────────────────────────


def test_armar_datos_manda_los_tres_bloques_y_la_version():
    datos = oc.armar_datos(
        "mu",
        _df(),
        company={"name": "Micron", "pe_ratio": 10.77, "eps": 74.3, "beta": 1.5},
        valuacion=_valuacion(),
        anuales=oc.fundamentales_anuales(_fund(), "2026-11-12"),
    )
    assert datos["version_datos"] == oc.VERSION_DATOS >= 3
    assert datos["valuacion"]["graham"]["valor"] == 449.97
    assert len(datos["fundamentales_anuales"]) == 3
    assert datos["yfinance"] == {"pe_trailing": 10.77, "eps_trailing": 74.3, "beta": 1.5}
    json.dumps(datos)


def test_sin_datos_de_yahoo_no_va_el_bloque():
    assert "yfinance" not in oc.armar_datos("mu", _df(), company={"name": "Micron"})


def test_el_prompt_dice_lo_que_la_app_no_tiene():
    p = oc.SYSTEM_PROMPT
    assert "guidance" in p and "trimestrales" in p and "EDGAR" in p and "datos_faltantes" in p
