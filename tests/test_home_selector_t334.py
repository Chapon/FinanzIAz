"""Tarea 334 — el botón «Ver sólo ganancias» de Home pasa a ser un selector de tres vistas.

El kill-criteria se fijó en el backlog antes de codear: un selector de tres valores (no tres
botones sueltos), cada vista con su título y subtítulo, cambiar de vista **no** recalcula, y el día
de una venta el test distingue **costo abierto** de **invertido neto**. El caso está elegido para
eso: compra 10 a $100 y vende 5 a $120. Ese día el costo abierto FIFO es $500 (lo que costaron las
5 que quedan) y el invertido neto —compras − ventas a precio de transacción— es $400.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

D0 = date(2026, 3, 2)
CIERRES = [(D0 + timedelta(days=i), p) for i, p in enumerate([100.0, 110.0, 120.0])]


@pytest.fixture
def home(test_db, monkeypatch):
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    import database.cartera_real as cr
    from database.models import Portfolio, Position, Transaction, session_scope

    global _APP
    _APP = QApplication.instance() or QApplication([])  # referencia viva (la lección de la 323)
    with session_scope() as s:
        pf = Portfolio(name="Mis Acciones")
        s.add(pf)
        s.flush()
        p = Position(portfolio_id=pf.id, ticker="AAA", quantity=5, avg_buy_price=100.0)
        s.add(p)
        s.flush()
        s.add(
            Transaction(
                position_id=p.id, transaction_type="BUY", quantity=10, price=100.0, date=datetime(2026, 3, 2)
            )
        )
        s.add(
            Transaction(
                position_id=p.id, transaction_type="SELL", quantity=5, price=120.0, date=datetime(2026, 3, 4)
            )
        )
    monkeypatch.setattr(cr, "cierres_del_cache", lambda ts: {"AAA": CIERRES})
    llamadas = []
    original = cr.resumen_home
    monkeypatch.setattr(cr, "resumen_home", lambda *a, **k: llamadas.append(1) or original(*a, **k))
    from ui.home_tab import HomeTab

    h = HomeTab()
    h.llamadas = llamadas
    yield h
    h.hero_chart.cleanup()
    h.deleteLater()


def _elegir(home, clave):
    i = home.vista_combo.findData(clave)
    assert i >= 0, clave
    home.vista_combo.setCurrentIndex(i)


def _ys_hero(home):
    return [float(y) for y in home.hero_chart.ax.lines[0].get_ydata()]


def _ys_spark(home):
    return [float(y) for y in home.kpi_pl.spark.ax.lines[0].get_ydata()]


def test_es_UN_selector_con_las_tres_vistas_y_arranca_en_valor_de_mercado(home):
    from PyQt6.QtWidgets import QComboBox

    assert isinstance(home.vista_combo, QComboBox)
    claves = [home.vista_combo.itemData(i) for i in range(home.vista_combo.count())]
    assert claves == ["valor", "ganancia", "invertido"]
    textos = [home.vista_combo.itemText(i) for i in range(home.vista_combo.count())]
    assert textos == ["Valor de mercado", "Sólo ganancias", "Monto invertido"]
    assert home.vista_combo.currentData() == "valor"
    assert not hasattr(home, "ganancia_btn"), "quedó el botón viejo al lado del selector"


def test_el_monto_invertido_es_el_costo_abierto_y_NO_el_invertido_neto(home):
    """El día de la venta: costo abierto $500; compras − ventas daría $400."""
    _elegir(home, "invertido")
    assert _ys_hero(home) == [1000.0, 1000.0, 500.0]
    assert "monto invertido, hasta el 04/03: $500" in home.hero_title.text()
    assert "$400" not in home.hero_title.text()
    neto = [v for _, v in home._r["invertido_neto"]]
    assert neto[-1] == pytest.approx(400.0)  # el caso distingue: la otra serie existe y da otro número
    assert "no es compras − ventas" in home.hero_sub.text()


def test_cada_vista_tiene_su_titulo_y_subtitulo_y_cambiar_NO_recalcula(home):
    vistos = {}
    for clave in ("ganancia", "invertido", "valor", "invertido", "ganancia"):
        _elegir(home, clave)
        vistos.setdefault(clave, set()).add((home.hero_title.text(), home.hero_sub.text()))
    assert all(len(v) == 1 for v in vistos.values()), "la misma vista pintó textos distintos"
    titulos = {next(iter(v))[0] for v in vistos.values()}
    subtitulos = {next(iter(v))[1] for v in vistos.values()}
    assert len(titulos) == 3 and len(subtitulos) == 3
    assert home.llamadas == [1], "el selector volvió a armar el resumen"


def test_la_sparkline_de_valor_y_pl_sigue_a_la_vista(home):
    """Graficaba el invertido neto, que no es ninguna de las tres (tanda 2026-10-07 [F-2])."""
    _elegir(home, "valor")
    assert _ys_spark(home) == [1000.0, 1100.0, 600.0]
    _elegir(home, "ganancia")
    assert _ys_spark(home) == pytest.approx([0.0, 100.0, 200.0])
    _elegir(home, "invertido")
    assert _ys_spark(home) == [1000.0, 1000.0, 500.0]
