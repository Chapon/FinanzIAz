"""Tarea 390 — una pata de calidad, el EPS de la tarjeta y la cobertura de la 382 cuentan sólo si su
último año es el de la ganancia (o el anterior). Antes tomaban el último dato aunque fuera de 2013."""

from __future__ import annotations

from analysis.calidad import patas_de
from analysis.valuation import valuar
from data.fundamentos_pit import Fundamentos, Registro, es_vigente
from scripts.build_fundamentals_pit import cobertura

HOY = "2027-01-01"


def _r(c, y, v):
    return Registro(c, f"{y}-12-31", f"{y + 1}-02-15", v, "10-K", "X")


def _empresa(hasta_bruta: int, hasta_deuda: int, hasta_eps: int = 2025) -> Fundamentos:
    """Ganancia de 2016 a 2025; ganancia bruta, deuda y EPS cortan en el año que se diga."""
    regs = []
    for y in range(2005, 2026):
        if y >= 2016:
            regs += [_r("ganancia_neta", y, 10.0 + y - 2016), _r("patrimonio", y, 100.0)]
        regs.append(_r("activos", y, 1000.0))
        if y <= hasta_bruta:
            regs.append(_r("ganancia_bruta", y, 300.0))
        if y <= hasta_deuda:
            regs.append(_r("deuda_lp", y, 45.0))
        if y <= hasta_eps:
            regs.append(_r("eps_diluido", y, 1.0 + (y - 2005) * 0.1))
    return Fundamentos(ticker="X", registros=regs)


def test_la_pata_de_hace_una_decada_queda_vacia():
    """Ganancia hasta 2025, ganancia bruta hasta 2014 y deuda hasta 2013: ninguna de las dos patas."""
    p = patas_de(_empresa(hasta_bruta=2014, hasta_deuda=2013), HOY)
    assert p["rentab_bruta"] is None
    assert p["deuda"] is None
    assert p["roe"] is not None and p["regularidad"] is not None  # las que usan la ganancia siguen


def test_la_del_anio_anterior_entra_y_la_de_hace_dos_no():
    """El borde: con la ganancia en 2025, 2024 todavía cuenta y 2023 ya no."""
    p = patas_de(_empresa(hasta_bruta=2024, hasta_deuda=2024), HOY)
    assert p["rentab_bruta"] == 0.3
    assert p["deuda"] == 45.0 / 19.0  # la deuda de 2024 sobre la ganancia de 2025
    p = patas_de(_empresa(hasta_bruta=2023, hasta_deuda=2023), HOY)
    assert p["rentab_bruta"] is None and p["deuda"] is None


def test_es_vigente_tolera_el_ejercicio_de_53_semanas_y_pide_ganancia():
    g = [("2024-12-28", 1.0), ("2025-12-27", 1.0)]
    assert es_vigente("2024-12-28", g)  # 364 días
    assert es_vigente("2023-12-30", [("2025-01-03", 1.0)])  # 370 días
    assert not es_vigente("2023-12-30", g)
    assert not es_vigente("2025-12-27", [])


def test_la_tarjeta_avisa_si_el_eps_quedo_atras_de_la_ganancia():
    viejo = valuar(_empresa(2025, 2025, hasta_eps=2021), 50.0, [], HOY)
    assert "el EPS termina en 2021 y la ganancia en 2025" in viejo.avisos
    vigente = valuar(_empresa(2025, 2025, hasta_eps=2025), 50.0, [], HOY)
    assert not any("EPS termina" in a for a in vigente.avisos)


def test_la_cobertura_cuenta_por_anio_vigente_no_por_cantidad():
    """Diez años de ganancia bruta que terminan en 2014 no cubren nada."""
    fund = {"VIEJA": _empresa(2014, 2025), "AL_DIA": _empresa(2025, 2025)}
    ok, faltan = cobertura(fund, HOY, min_anios=8)["ganancia_bruta"]
    assert ok == 1
    assert faltan == ["VIEJA:0"]
    assert cobertura(fund, HOY, min_anios=8)["ganancia_neta"][0] == 2
