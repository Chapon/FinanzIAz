"""Tarea 394 — el percentil de calidad compara a todos con lo que todos sabían.

El almacén de la 382 se rehace de a un ticker (al abrirlo en Análisis) y el resto queda con la
fecha en que se bajó. Antes, el percentil del ticker abierto salía de su 10-K nuevo contra el año
viejo de sus pares. Ahora todos se miden antes del ``generado`` más viejo, y la tarjeta lo dice.
"""

from __future__ import annotations

from datetime import date

import pytest

from analysis.calidad import corte_comun, patas_de, puntajes
from data import fundamentos_pit as fp
from data.fundamentos_pit import Fundamentos, Registro

PARES_GENERADOS = "2026-10-21"
FECHA = "2026-12-02"


def _r(c, y, v, filed=None):
    return Registro(c, f"{y}-12-31", filed or f"{y + 1}-02-15", v, "10-K", "X")


def _empresa(ticker, ganancias, generado, extra=()) -> Fundamentos:
    regs = []
    for i, g in enumerate(ganancias):
        y = 2015 + i
        regs += [_r("ganancia_neta", y, g), _r("patrimonio", y, 100.0), _r("activos", y, 1000.0)]
    return Fundamentos(ticker=ticker, registros=regs + list(extra), generado=generado)


def _pares() -> dict[str, Fundamentos]:
    # Once años (2015–2025) cada uno, con regularidades distintas: 0.9, 0.8, 0.7 y 0.6.
    base = [10.0 + i for i in range(11)]
    out = {}
    for k, t in enumerate(("P1", "P2", "P3", "P4"), start=1):
        g = list(base)
        for j in range(k):
            g[2 + 2 * j] = g[1 + 2 * j] - 0.5  # un año que cae
        out[t] = _empresa(t, g, PARES_GENERADOS)
    return out


def _abierto() -> Fundamentos:
    """Creció los once años; su 10-K del 2026, presentado el 2026-11-20, trae un derrumbe."""
    nuevo = [
        _r("ganancia_neta", 2026, 1.0, filed="2026-11-20"),
        _r("patrimonio", 2026, 100.0, filed="2026-11-20"),
        _r("activos", 2026, 1000.0, filed="2026-11-20"),
    ]
    return _empresa("A", [10.0 + i for i in range(11)], "2026-12-01", nuevo)


@pytest.fixture
def almacen(tmp_path, monkeypatch):
    from ui.analysis import worker

    monkeypatch.setattr(fp, "STORE_DIR", tmp_path)
    monkeypatch.setattr(worker, "_POBLACION", {})
    for f in _pares().values():
        fp.guardar(f, tmp_path)
    return tmp_path


def test_el_corte_es_el_generado_mas_viejo_y_no_pasa_de_la_fecha():
    pares = _pares()
    assert corte_comun({**pares, "A": _abierto()}, FECHA) == PARES_GENERADOS
    # Los que no traen ``generado`` (o no tienen archivo) no cuentan.
    assert corte_comun({"A": _abierto(), "X": Fundamentos("X"), "Y": None}, FECHA) == "2026-12-01"
    assert corte_comun({"A": _abierto()}, "2026-11-01") == "2026-11-01"


def test_el_abierto_se_mide_con_lo_que_sabian_sus_pares(almacen):
    """El caso que distingue: a la fecha, el derrumbe del 2026 lo baja; al corte, no existe."""
    from ui.analysis.worker import calidad_en_el_universo

    abierto = _abierto()
    r = calidad_en_el_universo("A", abierto, FECHA)
    assert r is not None and r["al"] == PARES_GENERADOS and r["n"] == 5

    todos = {**_pares(), "A": abierto}
    al_corte = puntajes({t: patas_de(f, PARES_GENERADOS) for t, f in todos.items()})["A"]
    a_la_fecha = puntajes({t: patas_de(f, FECHA) for t, f in todos.items()})["A"]
    assert r["puntaje"] == pytest.approx(al_corte["puntaje"])
    assert r["percentiles"] == pytest.approx(al_corte["percentiles"])
    # Si no difirieran, el test no fijaría nada (como antes de la 394, con la fecha).
    assert a_la_fecha["percentiles"]["regularidad"] < al_corte["percentiles"]["regularidad"]
    assert a_la_fecha["puntaje"] < al_corte["puntaje"]


def test_con_el_almacen_parejo_el_corte_es_esa_fecha(almacen):
    from ui.analysis.worker import calidad_en_el_universo

    par = _pares()["P1"]
    r = calidad_en_el_universo("P1", par, FECHA)
    assert r is not None and r["al"] == PARES_GENERADOS and r["n"] == 4


def test_la_tarjeta_dice_el_corte_y_como_ponerlo_al_dia():
    from ui.analysis.valuation_card import _corte

    reciente = _corte({"al": "2026-11-01"}, hoy=date(2026, 11, 20))
    assert reciente == ", todas con lo presentado antes del 2026-11-01"
    viejo = _corte({"al": PARES_GENERADOS}, hoy=date(2026, 12, 1))
    assert "antes del 2026-10-21" in viejo and "hace 41 días" in viejo
    assert "scripts/build_fundamentals_pit.py" in viejo
    assert _corte({}) == ""


def test_la_linea_de_la_tarjeta_lleva_el_corte():
    from analysis.valuation import Valuacion
    from ui.analysis.valuation_card import lineas_de

    v = Valuacion(
        precio=10.0,
        calidad={"puntaje": 72.4, "percentiles": {"roe": 90.0}, "n": 125, "al": date.today().isoformat()},
    )
    linea = lineas_de(v)[-1]
    assert f"entre 125 empresas (ROE estable p90), todas con lo presentado antes del {date.today()}." in linea
    assert "build_fundamentals_pit" not in linea


def test_el_build_rehace_tambien_lo_que_esta_en_el_almacen_fuera_del_universo(tmp_path):
    """Uno analizado una vez y afuera del universo frenaría el corte para siempre."""
    from scripts.build_fundamentals_pit import a_rehacer

    fp.guardar(_empresa("ZZZ", [1.0, 2.0], "2025-01-01"), tmp_path)
    fp.guardar(_empresa("KO", [1.0, 2.0], PARES_GENERADOS), tmp_path)
    assert a_rehacer(["ko", "JPM"], store=tmp_path) == ["KO", "JPM", "ZZZ"]
