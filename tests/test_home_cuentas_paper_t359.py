"""Tareas 359 y 360 — el gráfico grande de Home muestra también las cuentas de paper trading,
tildadas en checkboxes: una o varias a la vez, en el mismo eje (la 360; la 359 era un desplegable).

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


def _tildar(home, *claves):
    """Deja tildadas exactamente esas cuentas (None = la cartera) — tarea 360."""
    for clave, cb in home.cuenta_checks.items():
        cb.setChecked(clave in claves)


def _linea(home, rotulo=None):
    """Los y de la serie del gráfico grande; ``set_lineas`` dibuja antes la línea de cero."""
    lineas = [ln for ln in home.hero_chart.ax.lines if rotulo is None or ln.get_label() == rotulo]
    return [float(y) for y in lineas[0].get_ydata()]


def _ys_spark(home):
    return [float(y) for y in home.kpi_pl.spark.ax.lines[0].get_ydata()]


def _elegir_vista(home, clave):
    i = home.vista_combo.findData(clave)
    assert i >= 0, clave
    home.vista_combo.setCurrentIndex(i)


def test_un_checkbox_por_cuenta_la_cartera_primero_y_sola_tildada(home):
    from PyQt6.QtWidgets import QCheckBox, QComboBox

    assert not hasattr(home, "cuenta_combo"), "quedó el desplegable de la 359"
    assert all(isinstance(cb, QCheckBox) for cb in home.cuenta_checks.values())
    assert [cb.text() for cb in home.cuenta_checks.values()] == [
        "Mis Acciones",
        "Paper · Sim Principal (cerrada)",
        "Paper · Sim Segundo",
    ]
    assert list(home.cuenta_checks) == [None, home.ids["cerrada"], home.ids["viva"]]
    assert [cb.isChecked() for cb in home.cuenta_checks.values()] == [True, False, False]
    assert home.findChildren(QComboBox) == [home.vista_combo], "hay otro desplegable además del de vistas"
    assert home.hero_title.text().startswith("Mis Acciones — valor de mercado")


def test_un_punto_por_dia_de_Nueva_York_y_es_el_ULTIMO_snapshot(home):
    from paper_trading.account import equity_diaria

    assert equity_diaria(home.ids["viva"]) == [
        (date(2026, 3, 2), 1_000.0, 49_300.0, 50_300.0),
        (date(2026, 3, 3), 900.0, 49_000.0, 49_900.0),
    ]
    _tildar(home, home.ids["viva"])
    assert _linea(home) == [50_300.0, 49_900.0]
    assert "Sim Segundo — valor de la cuenta, hasta el 03/03: $49,900" in home.hero_title.text()


def test_la_ganancia_es_equity_menos_capital_inicial(home):
    _tildar(home, home.ids["viva"])
    _elegir_vista(home, "ganancia")
    assert _linea(home, "Ganancia total") == pytest.approx([300.0, -100.0])
    assert home.hero_title.text().endswith("hasta el 03/03: -$100"), home.hero_title.text()  # no «$-100»
    assert "Capital inicial $50,000" in home.hero_sub.text()


def test_la_tercera_vista_de_una_paper_es_efectivo_y_posiciones_y_vuelve_con_la_cartera(home):
    i = home.vista_combo.findData("invertido")
    _tildar(home, home.ids["viva"])
    _elegir_vista(home, "invertido")
    assert home.vista_combo.itemText(i) == "Efectivo y posiciones"
    assert _linea(home, "En posiciones") == [49_300.0, 49_000.0]
    assert _linea(home, "Efectivo") == [1_000.0, 900.0]
    assert "no a costo" in home.hero_sub.text()
    _tildar(home, None)
    assert home.vista_combo.itemText(i) == "Monto invertido"
    assert "Mis Acciones — monto invertido" in home.hero_title.text()


def test_las_tarjetas_y_la_sparkline_siguen_siendo_de_la_cartera_y_no_se_recalcula(home):
    """La sparkline es de la cartera en la vista elegida (tarea 334), tilde lo que se tilde."""
    valor = home.kpi_pl.value_lbl.text()
    de_la_cartera = {}
    for clave in ("ganancia", "invertido", "valor"):
        _elegir_vista(home, clave)
        de_la_cartera[clave] = _ys_spark(home)
    assert de_la_cartera["valor"] != de_la_cartera["invertido"]  # el caso distingue las vistas
    for tildadas in ((home.ids["viva"],), (None, home.ids["viva"]), ()):
        _tildar(home, *tildadas)
        for clave in ("ganancia", "invertido", "valor"):
            _elegir_vista(home, clave)
            assert _ys_spark(home) == de_la_cartera[clave], f"la sparkline se movió con {tildadas} ({clave})"
    assert home.kpi_pl.value_lbl.text() == valor
    assert home.llamadas == [1], "tildar cuentas volvió a armar el resumen de «Mis Acciones»"


def test_una_cuenta_sin_snapshots_lo_dice(home):
    _tildar(home, home.ids["cerrada"])
    assert "sin historia de equity" in home.hero_title.text()
    assert "Sim Principal" in home.hero_title.text()


# ── Tarea 360: varias cuentas a la vez, en el mismo eje ─────────────────────────


def test_dos_tildadas_van_en_UN_eje_cada_una_con_sus_fechas(home):
    """La cartera tiene tres cierres (02 al 04/03) y la paper dos días: no se recortan al común."""
    import matplotlib.dates as mdates

    _tildar(home, None, home.ids["viva"])
    assert len(home.hero_chart.figure.axes) == 1
    lineas = {ln.get_label(): ln for ln in home.hero_chart.ax.lines}
    assert set(lineas) == {"Mis Acciones", "Sim Segundo"}
    fechas = {k: [mdates.num2date(x).date() for x in ln.get_xdata()] for k, ln in lineas.items()}
    assert fechas["Mis Acciones"] == [d for d, _ in CIERRES]
    assert fechas["Sim Segundo"] == [date(2026, 3, 2), date(2026, 3, 3)]
    assert [float(y) for y in lineas["Mis Acciones"].get_ydata()] == [1_000.0, 1_100.0, 1_200.0]
    assert [float(y) for y in lineas["Sim Segundo"].get_ydata()] == [50_300.0, 49_900.0]
    assert lineas["Mis Acciones"].get_color() != lineas["Sim Segundo"].get_color()
    assert home.hero_title.text() == "2 cuentas — valor"


def test_varias_en_ganancia_y_en_la_tercera_vista_rotulan_que_es_cada_linea(home):
    _tildar(home, None, home.ids["viva"])
    _elegir_vista(home, "ganancia")
    assert _linea(home, "Mis Acciones") == pytest.approx([0.0, 100.0, 200.0])
    assert _linea(home, "Sim Segundo") == pytest.approx([300.0, -100.0])
    assert "-$100" in home.hero_sub.text()
    _elegir_vista(home, "invertido")
    assert home.vista_combo.itemText(home.vista_combo.findData("invertido")) == "Invertido / en posiciones"
    assert _linea(home, "Mis Acciones (costo)") == [1_000.0, 1_000.0, 1_000.0]
    assert _linea(home, "Sim Segundo (posiciones a mercado)") == [49_300.0, 49_000.0]


def test_una_tildada_sin_datos_entre_varias_se_dice_y_las_otras_se_grafican(home):
    _tildar(home, None, home.ids["cerrada"])
    assert {ln.get_label() for ln in home.hero_chart.ax.lines} == {"Mis Acciones"}
    assert "sin datos: Paper · Sim Principal (cerrada)" in home.hero_sub.text()


def test_ninguna_tildada_lo_dice(home):
    _tildar(home)
    assert home.hero_title.text() == "Ninguna cuenta tildada"
    assert not [ln for ln in home.hero_chart.ax.lines if ln.get_label() in ("Mis Acciones", "Sim Segundo")]


def test_lo_tildado_sobrevive_al_refresco(home):
    _tildar(home, None, home.ids["viva"])
    home.refresh()
    assert [cb.isChecked() for cb in home.cuenta_checks.values()] == [True, False, True]
    assert home.hero_title.text() == "2 cuentas — valor"
