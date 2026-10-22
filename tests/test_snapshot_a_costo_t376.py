"""Tarea 376 — un snapshot con posiciones a costo lo dice, y la curva no lo lee como mercado.

``compute_equity`` marca a ``avg_cost`` cada posición sin precio. El 2026-10-13 (127/127 sin
precio por el throttle) eso dejó el último snapshot del día de la cuenta 2 **exacto** al
costo, y Home, Paper y Métricas lo pintaron como valor de mercado.

Los casos están elegidos para que la versión sin el arreglo dé otro número: el snapshot a
costo es siempre el **último** del día (el que la curva elegía) y vale distinto del limpio.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _cuenta_con_dos_posiciones():
    from database.models import session_scope
    from paper_trading.models import PaperAccount, PaperPosition

    with session_scope() as s:
        a = PaperAccount(name="Sim Segundo", initial_capital=50_000.0, is_active=True, cash=1_000.0)
        s.add(a)
        s.flush()
        # avg_cost distinto del precio: si a costo y a mercado dieran igual, no se vería nada.
        s.add(PaperPosition(account_id=a.id, ticker="AAA", shares=10, avg_cost=100.0))
        s.add(PaperPosition(account_id=a.id, ticker="BBB", shares=5, avg_cost=200.0))
        return a.id


def test_el_snapshot_cuenta_las_posiciones_a_costo(test_db):
    from paper_trading.account import record_equity_snapshot

    cuenta = _cuenta_con_dos_posiciones()
    completo = record_equity_snapshot(cuenta, {"AAA": 110.0, "BBB": 190.0})
    sin_bbb = record_equity_snapshot(cuenta, {"AAA": 110.0})
    precio_cero = record_equity_snapshot(cuenta, {"AAA": 110.0, "BBB": 0.0})
    assert completo.positions_at_cost == 0
    assert completo.positions_value == pytest.approx(10 * 110 + 5 * 190)
    assert sin_bbb.positions_at_cost == 1
    assert sin_bbb.positions_value == pytest.approx(10 * 110 + 5 * 200)  # BBB a costo
    assert precio_cero.positions_at_cost == 1  # un precio 0 también va a costo


def _snap(cuenta, ts, pos, a_costo):
    from paper_trading.models import PaperEquitySnapshot

    return PaperEquitySnapshot(
        account_id=cuenta,
        snapshot_at=ts,
        cash=1_000.0,
        positions_value=pos,
        total_equity=1_000.0 + pos,
        positions_at_cost=a_costo,
    )


@pytest.fixture
def curva(test_db):
    """Tres días de NY. El 02/03 el último snapshot es a costo y hay uno limpio antes; el 03/03
    sólo hay uno, a costo; el 04/03 es una fila vieja (``NULL``) y otra con 0."""
    from database.models import session_scope
    from paper_trading.models import PaperAccount

    with session_scope() as s:
        a = PaperAccount(name="Sim Segundo", initial_capital=50_000.0, is_active=True)
        s.add(a)
        s.flush()
        s.add_all(
            [
                _snap(a.id, datetime(2026, 3, 2, 15, 0), 49_100.0, 0),
                _snap(a.id, datetime(2026, 3, 2, 20, 0), 48_000.0, 3),
                _snap(a.id, datetime(2026, 3, 3, 18, 0), 47_000.0, 1),
                _snap(a.id, datetime(2026, 3, 4, 15, 0), 49_400.0, None),
                _snap(a.id, datetime(2026, 3, 4, 20, 0), 49_500.0, 0),
            ]
        )
        return a.id


def test_la_equity_diaria_se_queda_con_el_limpio_y_marca_el_dia_que_no_lo_tiene(curva):
    from paper_trading.account import equity_diaria, equity_diaria_marcada

    serie, marcados = equity_diaria_marcada(curva)
    assert serie == [
        (date(2026, 3, 2), 1_000.0, 49_100.0, 50_100.0),  # no el de las 20:00, a costo
        (date(2026, 3, 3), 1_000.0, 47_000.0, 48_000.0),  # el único: entra, marcado
        (date(2026, 3, 4), 1_000.0, 49_500.0, 50_500.0),
    ]
    assert marcados == [date(2026, 3, 3)]
    assert equity_diaria(curva) == serie


def test_la_curva_de_paper_saltea_los_snapshots_a_costo(curva):
    from paper_trading.account import get_equity_curve

    assert [s.positions_value for s in get_equity_curve(curva)] == [49_100.0, 49_400.0, 49_500.0]


def test_home_dice_que_dias_tienen_posiciones_a_costo(curva, monkeypatch):
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    import database.cartera_real as cr

    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(cr, "cierres_del_cache", lambda ts: {})
    from ui.home_tab import HomeTab

    h = HomeTab()
    try:
        for clave, cb in h.cuenta_checks.items():
            cb.setChecked(clave == curva)
        assert "Con posiciones a costo, por falta de precio: 03/03." in h.hero_sub.text()
    finally:
        h.hero_chart.cleanup()
        h.deleteLater()


# ── Los lectores con SQL a mano ──────────────────────────────────────────────


def _con(*, con_columna: bool) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    extra = ", positions_at_cost INT" if con_columna else ""
    con.execute(
        "CREATE TABLE paper_equity_snapshots (id INTEGER PRIMARY KEY, account_id INT, "
        f"snapshot_at TEXT, total_equity REAL, cash REAL, positions_value REAL{extra})"
    )
    return con


def _insertar(con, filas):
    for ts, eq, a_costo in filas:
        if a_costo == "sin":
            con.execute(
                "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity, cash, "
                "positions_value) VALUES (2,?,?,0,?)",
                (ts, eq, eq),
            )
        else:
            con.execute(
                "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity, cash, "
                "positions_value, positions_at_cost) VALUES (2,?,?,0,?,?)",
                (ts, eq, eq, a_costo),
            )


_LIMPIAS = [
    ("2026-06-22 21:08:46", 50_000.0, 0),
    ("2026-06-26 21:08:46", 50_500.0, None),
    ("2026-06-30 15:00:00", 51_000.0, 0),
]
_A_COSTO = ("2026-06-30 21:08:46", 49_000.0, 4)  # el último: la punta, si no se filtra


def test_metricas_vs_spy_no_toma_de_punta_un_snapshot_a_costo(monkeypatch):
    import analysis.metrics_panel as mp

    monkeypatch.setattr(
        mp, "load_close_series", lambda con, t: [("2026-06-22", 100.0), ("2026-06-30", 100.0)]
    )
    con_marca, sin_marca = _con(con_columna=True), _con(con_columna=True)
    _insertar(con_marca, [*_LIMPIAS, _A_COSTO])
    _insertar(sin_marca, _LIMPIAS)
    assert mp._benchmark_panel(con_marca, 2) == mp._benchmark_panel(sin_marca, 2)


def test_metricas_con_una_tabla_vieja_sigue_leyendo():
    import analysis.metrics_panel as mp

    con = _con(con_columna=False)
    assert mp._sin_posiciones_a_costo(con) == ""
    assert mp._sin_posiciones_a_costo(_con(con_columna=True)) != ""


def test_baseline_metrics_saltea_los_snapshots_a_costo():
    from scripts.baseline_metrics import load_snapshots

    con = _con(con_columna=True)
    _insertar(con, [*_LIMPIAS, _A_COSTO])
    assert [s.total_equity for s in load_snapshots(con, 2)] == [50_000.0, 50_500.0, 51_000.0]
    vieja = _con(con_columna=False)
    _insertar(vieja, [(ts, eq, "sin") for ts, eq, _ in [*_LIMPIAS, _A_COSTO]])
    assert len(load_snapshots(vieja, 2)) == 4


# ── La cobertura de scan de barrier_eval ─────────────────────────────────────

LUN, MAR = date(2026, 9, 14), date(2026, 9, 15)


def test_un_dia_cuyo_unico_scan_en_sesion_fue_a_costo_no_evaluo():
    from analysis.harness_config import cobertura_de_scan

    snaps = [datetime(2026, 9, 14, 15, 0), datetime(2026, 9, 15, 15, 0), datetime(2026, 9, 15, 16, 0)]
    a_costo = [datetime(2026, 9, 14, 15, 0), datetime(2026, 9, 15, 15, 0)]
    c = cobertura_de_scan(snaps, LUN, MAR, sin_evaluar=a_costo)
    # El lunes corrió (no es «sin scan») pero no evaluó; el martes tuvo uno limpio.
    assert c == {"habiles": 2, "sin_scan": 0, "sin_scan_en_sesion": 1}
    assert cobertura_de_scan(snaps, LUN, MAR)["sin_scan_en_sesion"] == 0


def test_snapshots_de_scan_separa_los_a_costo_y_tolera_la_tabla_vieja():
    from analysis.harness_config import snapshots_de_scan

    con = _con(con_columna=True)
    _insertar(con, [*_LIMPIAS, _A_COSTO])
    todos, a_costo = snapshots_de_scan(con, 2)
    assert len(todos) == 4
    assert a_costo == [_A_COSTO[0]]
    vieja = _con(con_columna=False)
    _insertar(vieja, [(ts, eq, "sin") for ts, eq, _ in _LIMPIAS])
    assert snapshots_de_scan(vieja, 2) == ([ts for ts, _, _ in _LIMPIAS], [])
