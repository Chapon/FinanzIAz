"""Tarea 359 — el gráfico grande de Home puede mostrar también las cuentas de paper trading.

El kill-criteria se fijó en el backlog antes de codear. El caso de snapshots está elegido para que
las versiones equivocadas den otro número: el 02/03 hay tres snapshots en hora de Nueva York
—15:00 y 20:00 UTC, y el de las **01:00 UTC del 03/03**, que allá son las 20:00 del 02/03—. Por
día de NY y quedándose con el último: 50.300. Por día UTC daría 50.200; quedándose con el primero,
50.100.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

D0 = date(2026, 3, 2)
CIERRES = [(D0 + timedelta(days=i), p) for i, p in enumerate([100.0, 110.0, 120.0])]
# (snapshot_at UTC, efectivo, posiciones)
SNAPS = [
    (datetime(2026, 3, 2, 15, 0), 1_000.0, 49_100.0),
    (datetime(2026, 3, 2, 20, 0), 1_000.0, 49_200.0),
    (datetime(2026, 3, 3, 1, 0), 1_000.0, 49_300.0),  # 20:00 del 02/03 en Nueva York
    (datetime(2026, 3, 3, 18, 0), 900.0, 49_000.0),
]


@pytest.fixture
def home(test_db, monkeypatch):
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    import database.cartera_real as cr
    from database.models import Portfolio, Position, Transaction, session_scope
    from paper_trading.models import PaperAccount, PaperEquitySnapshot

    global _APP
    _APP = QApplication.instance() or QApplication([])  # referencia viva (la lección de la 323)
    with session_scope() as s:
        pf = Portfolio(name="Mis Acciones")
        s.add(pf)
        s.flush()
        p = Position(portfolio_id=pf.id, ticker="AAA", quantity=10, avg_buy_price=100.0)
        s.add(p)
        s.flush()
        s.add(
            Transaction(
                position_id=p.id, transaction_type="BUY", quantity=10, price=100.0, date=datetime(2026, 3, 2)
            )
        )
        cerrada = PaperAccount(name="Sim Principal", initial_capital=50_000.0, is_active=False)
        viva = PaperAccount(name="Sim Segundo", initial_capital=50_000.0, is_active=True)
        s.add_all([cerrada, viva])
        s.flush()
        for ts, cash, pos in SNAPS:
            s.add(
                PaperEquitySnapshot(
                    account_id=viva.id,
                    snapshot_at=ts,
                    cash=cash,
                    positions_value=pos,
                    total_equity=cash + pos,
                )
            )
        ids = {"cerrada": cerrada.id, "viva": viva.id}
    monkeypatch.setattr(cr, "cierres_del_cache", lambda ts: {"AAA": CIERRES})
    llamadas = []
    original = cr.resumen_home
    monkeypatch.setattr(cr, "resumen_home", lambda *a, **k: llamadas.append(1) or original(*a, **k))
    from ui.home_tab import HomeTab

    h = HomeTab()
    h.llamadas = llamadas
    h.ids = ids
    yield h
    h.hero_chart.cleanup()
    h.deleteLater()


def _elegir(combo, dato):
    i = combo.findData(dato)
    assert i >= 0, dato
    combo.setCurrentIndex(i)


def _linea(home, rotulo=None):
    """Los y de la serie del gráfico grande; ``set_lineas`` dibuja antes la línea de cero."""
    lineas = [ln for ln in home.hero_chart.ax.lines if rotulo is None or ln.get_label() == rotulo]
    return [float(y) for y in lineas[0].get_ydata()]


def _ys_spark(home):
    return [float(y) for y in home.kpi_pl.spark.ax.lines[0].get_ydata()]


def test_el_selector_trae_la_cartera_primero_y_todas_las_paper_con_la_cerrada_rotulada(home):
    from PyQt6.QtWidgets import QComboBox

    assert isinstance(home.cuenta_combo, QComboBox)
    textos = [home.cuenta_combo.itemText(i) for i in range(home.cuenta_combo.count())]
    assert textos == ["Mis Acciones", "Paper · Sim Principal (cerrada)", "Paper · Sim Segundo"]
    assert home.cuenta_combo.currentData() is None
    assert home.hero_title.text().startswith("Mis Acciones — valor de mercado")


def test_un_punto_por_dia_de_Nueva_York_y_es_el_ULTIMO_snapshot(home):
    from paper_trading.account import equity_diaria

    assert equity_diaria(home.ids["viva"]) == [
        (date(2026, 3, 2), 1_000.0, 49_300.0, 50_300.0),
        (date(2026, 3, 3), 900.0, 49_000.0, 49_900.0),
    ]
    _elegir(home.cuenta_combo, home.ids["viva"])
    assert _linea(home) == [50_300.0, 49_900.0]
    assert "Sim Segundo — valor de la cuenta, hasta el 03/03: $49,900" in home.hero_title.text()


def test_la_ganancia_es_equity_menos_capital_inicial(home):
    _elegir(home.cuenta_combo, home.ids["viva"])
    _elegir(home.vista_combo, "ganancia")
    assert _linea(home, "Ganancia total") == pytest.approx([300.0, -100.0])
    assert home.hero_title.text().endswith("hasta el 03/03: -$100"), home.hero_title.text()  # no «$-100»
    assert "Capital inicial $50,000" in home.hero_sub.text()


def test_la_tercera_vista_de_una_paper_es_efectivo_y_posiciones_y_vuelve_con_la_cartera(home):
    i = home.vista_combo.findData("invertido")
    _elegir(home.cuenta_combo, home.ids["viva"])
    _elegir(home.vista_combo, "invertido")
    assert home.vista_combo.itemText(i) == "Efectivo y posiciones"
    assert _linea(home, "En posiciones") == [49_300.0, 49_000.0]
    assert _linea(home, "Efectivo") == [1_000.0, 900.0]
    assert "no a costo" in home.hero_sub.text()
    _elegir(home.cuenta_combo, None)
    assert home.vista_combo.itemText(i) == "Monto invertido"
    assert "Mis Acciones — monto invertido" in home.hero_title.text()


def test_las_tarjetas_y_la_sparkline_siguen_siendo_de_la_cartera_y_no_se_recalcula(home):
    spark = _ys_spark(home)
    valor = home.kpi_pl.value_lbl.text()
    # Con la cartera elegida la sparkline sigue a la vista (tarea 334): las vistas se recorren
    # con la cuenta paper elegida, que no tiene que moverla.
    _elegir(home.cuenta_combo, home.ids["viva"])
    for clave in ("ganancia", "invertido", "valor", "ganancia"):
        _elegir(home.vista_combo, clave)
        assert _ys_spark(home) == spark, f"la cuenta paper movió la sparkline de «Mis Acciones» ({clave})"
    _elegir(home.cuenta_combo, None)
    _elegir(home.cuenta_combo, home.ids["viva"])
    assert home.kpi_pl.value_lbl.text() == valor
    assert home.llamadas == [1], "cambiar de cuenta volvió a armar el resumen de «Mis Acciones»"


def test_una_cuenta_sin_snapshots_lo_dice(home):
    _elegir(home.cuenta_combo, home.ids["cerrada"])
    assert "sin historia de equity" in home.hero_title.text()
    assert "Sim Principal" in home.hero_title.text()
