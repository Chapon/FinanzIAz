"""Tarea 384 — puntaje de calidad del negocio, y el instrumento que mide si anticipa el retorno."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from analysis.calidad import patas_de, puntajes
from data.fundamentos_pit import Fundamentos, Registro
from scripts.measure_calidad_t384 import (
    diferencial_tercios,
    ic_bloques,
    primeros_dias_de_mes,
    spearman,
)

_REPO = Path(__file__).resolve().parent.parent


def _r(c, y, v):
    return Registro(c, f"{y}-12-31", f"{y + 1}-02-15", v, "10-K", "X")


def _empresa(ganancias, patrimonio=100.0, activos=1000.0, bruta=None, deuda=None) -> Fundamentos:
    regs = []
    for i, g in enumerate(ganancias):
        y = 2015 + i
        regs += [_r("ganancia_neta", y, g), _r("patrimonio", y, patrimonio), _r("activos", y, activos)]
        if bruta is not None:
            regs.append(_r("ganancia_bruta", y, bruta))
        if deuda is not None:
            regs.append(_r("deuda_lp", y, deuda))
    return Fundamentos(ticker="X", registros=regs)


def test_el_roe_premia_lo_estable_no_solo_lo_alto():
    """Las dos tienen ROE medio 20%; la que salta entre 0% y 40% queda debajo de la pareja."""
    pareja = patas_de(_empresa([20.0, 20.0, 20.0, 20.0]), "2030-01-01")
    saltona = patas_de(_empresa([0.0, 40.0, 0.0, 40.0]), "2030-01-01")
    assert pareja["roe"] == pytest.approx(0.20)
    assert saltona["roe"] == pytest.approx(0.20 - 0.20)


def test_las_otras_patas_a_mano():
    p = patas_de(_empresa([10.0, 12.0, 12.0, 15.0], bruta=300.0, deuda=45.0), "2030-01-01")
    assert p["rentab_bruta"] == pytest.approx(0.3)
    assert p["deuda"] == pytest.approx(3.0)  # 45 / la última ganancia (15)
    assert p["regularidad"] == pytest.approx(2 / 3)  # creció 2 de 3 años; el que quedó igual no cuenta


def test_sin_ganancia_positiva_no_hay_pata_de_deuda_y_lo_futuro_no_cuenta():
    p = patas_de(_empresa([10.0, 12.0, 11.0, -5.0], deuda=45.0), "2030-01-01")
    assert p["deuda"] is None
    # El 10-K de 2018 se presentó el 2019-02-15: antes de eso, la serie tiene 3 años.
    assert patas_de(_empresa([10.0, 12.0, 11.0, 15.0]), "2019-02-15")["regularidad"] is None


def test_la_deuda_va_invertida_y_falta_una_pata_no_hunde_el_puntaje():
    pob = {
        "A": {"roe": 0.30, "rentab_bruta": None, "deuda": 1.0, "regularidad": 1.0},
        "B": {"roe": 0.20, "rentab_bruta": None, "deuda": 5.0, "regularidad": 0.5},
        "C": {"roe": 0.10, "rentab_bruta": None, "deuda": 9.0, "regularidad": 0.0},
        "D": {"roe": 0.25, "rentab_bruta": None, "deuda": None, "regularidad": None},
    }
    s = puntajes(pob)
    assert s["A"]["percentiles"]["deuda"] == pytest.approx(100.0)  # la que menos debe
    assert s["C"]["percentiles"]["deuda"] == pytest.approx(0.0)
    assert s["A"]["puntaje"] > s["B"]["puntaje"] > s["C"]["puntaje"]
    assert s["D"]["puntaje"] is None  # una sola pata: no alcanza


def test_spearman_y_tercios_ordenan_bien():
    xs = list(range(12))
    assert spearman(xs, [x**3 for x in xs]) == pytest.approx(1.0)  # monótona no lineal: Pearson daría menos
    assert spearman(xs, [-x for x in xs]) == pytest.approx(-1.0)
    assert spearman(xs[:9], xs[:9]) is None  # menos de 10 pares
    # 12 nombres: el tercio alto (8..11) rinde 10 y el bajo (0..3) rinde 0.
    assert diferencial_tercios(xs, [10.0 if x >= 8 else 0.0 for x in xs]) == pytest.approx(10.0)


def test_primer_dia_de_cada_mes():
    cal = ["2026-01-02", "2026-01-05", "2026-02-02", "2026-02-03", "2026-03-02"]
    assert primeros_dias_de_mes(cal) == ["2026-01-02", "2026-02-02", "2026-03-02"]


def test_el_ic_por_bloques_es_mas_ancho_que_el_de_meses_sueltos():
    """Una serie con rachas: remuestreando bloques de 6 el IC tiene que ser más ancho que con 1."""
    serie = ([0.1] * 6 + [-0.1] * 6) * 5
    ancho = lambda r: r["ic95"][1] - r["ic95"][0]
    assert ancho(ic_bloques(serie, 6)) > ancho(ic_bloques(serie, 1))
    assert ic_bloques([0.1, 0.2], 6)["ic95"] is None  # poca serie para el bloque


def test_la_tarjeta_muestra_la_calidad_y_dice_que_no_anticipa():
    from analysis.valuation import Valuacion
    from ui.analysis.valuation_card import lineas_de

    v = Valuacion(
        precio=10.0, calidad={"puntaje": 72.4, "percentiles": {"roe": 90.0, "deuda": 55.0}, "n": 125}
    )
    linea = lineas_de(v)[-1]
    assert "Calidad del negocio: 72/100 entre 125 empresas" in linea
    assert "ROE estable p90" in linea and "deuda baja p55" in linea
    assert "no lo anticipó" in linea


def test_nada_del_motor_importa_la_calidad():
    culpables = []
    for p in (_REPO / "paper_trading").glob("*.py"):
        for nodo in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.module.endswith("calidad"):
                culpables.append(p.name)
    assert culpables == []
