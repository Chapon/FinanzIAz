"""Tarea 332 — Home con un botón que saca la plata puesta y grafica sólo la ganancia.

El kill-criteria se fijó en el backlog antes de codear; cada test es uno de sus puntos. Los casos
están elegidos para que la versión correcta y la ingenua **difieran**: una venta baja el valor de
mercado a la mitad y deja la ganancia total igual, y «valor − compras» daría −400 donde la
ganancia es +200.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

from database.cartera_real import dividendos_cobrados, ganancias_diarias, valor_diario
from database.lotes import Movimiento, libro_fifo

D0 = date(2026, 3, 2)


def _dias(n, precios):
    return [(D0 + timedelta(days=i), p) for i, p in zip(range(n), precios, strict=True)]


def _caso():
    movs = {
        "AAA": [
            Movimiento(D0, "BUY", 10, 100.0, 1.0),
            Movimiento(D0 + timedelta(days=2), "SELL", 5, 120.0, 1.0),
        ],
        "BBB": [Movimiento(D0 + timedelta(days=1), "BUY", 4, 50.0, 0.0)],
    }
    cierres = {"AAA": _dias(4, [100.0, 110.0, 120.0, 120.0]), "BBB": _dias(4, [50.0, 50.0, 55.0, 60.0])}
    calendario = {"BBB": [((D0 + timedelta(days=3)).isoformat(), 0.5)]}
    return movs, cierres, calendario


def _eventos(movs):
    return [
        (m.fecha, t, m.cantidad if m.tipo == "BUY" else -m.cantidad) for t, ms in movs.items() for m in ms
    ]


# (1) ────────────────────────────────────────────────────────────────────────


def test_valor_es_costo_mas_no_realizado_y_la_serie_de_valor_es_la_de_siempre():
    movs, cierres, cal = _caso()
    serie, _ = ganancias_diarias(movs, cierres, cal)
    viejo, _ = valor_diario(_eventos(movs), cierres)
    assert [(d, x["valor"]) for d, x in serie] == viejo
    for _, x in serie:
        assert x["valor"] == pytest.approx(x["costo"] + x["no_realizado"])
        assert x["total"] == pytest.approx(x["no_realizado"] + x["realizado"] + x["dividendos"])


# (2) ────────────────────────────────────────────────────────────────────────


def test_el_ultimo_dia_cierra_con_el_libro_FIFO_y_con_dividendos_cobrados():
    movs, cierres, cal = _caso()
    serie, _ = ganancias_diarias(movs, cierres, cal)
    ult = serie[-1][1]
    assert ult["realizado"] == pytest.approx(sum(libro_fifo(ms).realizado for ms in movs.values()))
    eventos_bbb = [(m.fecha.isoformat(), m.cantidad) for m in movs["BBB"]]
    assert ult["dividendos"] == pytest.approx(dividendos_cobrados(eventos_bbb, cal["BBB"]))
    assert ult["dividendos"] == pytest.approx(4 * 0.5)


# (3) ────────────────────────────────────────────────────────────────────────


def test_una_venta_pasa_plata_de_no_realizada_a_realizada_y_el_total_no_salta():
    """Sin comisiones ni otro ticker, para ver la venta sola: valor a la mitad, total igual."""
    con = {"AAA": [Movimiento(D0, "BUY", 10, 100.0), Movimiento(D0 + timedelta(days=2), "SELL", 5, 120.0)]}
    sin = {"AAA": [Movimiento(D0, "BUY", 10, 100.0)]}
    cierres = {"AAA": _dias(3, [100.0, 110.0, 120.0])}
    s_con, _ = ganancias_diarias(con, cierres, {})
    s_sin, _ = ganancias_diarias(sin, cierres, {})
    dia_venta_con, dia_venta_sin = s_con[2][1], s_sin[2][1]
    assert dia_venta_con["valor"] == 600.0 and dia_venta_sin["valor"] == 1200.0
    assert dia_venta_con["total"] == dia_venta_sin["total"] == 200.0  # «valor − compras» daría −400
    assert (dia_venta_con["no_realizado"], dia_venta_con["realizado"]) == (100.0, 100.0)
    assert s_con[1][1]["realizado"] == 0.0  # el día anterior todavía no había realizada


def test_el_dividendo_entra_el_dia_del_ex_date_y_no_antes():
    movs, cierres, cal = _caso()
    serie, _ = ganancias_diarias(movs, cierres, cal)
    assert [x["dividendos"] for _, x in serie] == [0.0, 0.0, 0.0, 2.0]


def test_la_realizada_descuenta_las_comisiones():
    movs, cierres, cal = _caso()
    serie, _ = ganancias_diarias(movs, cierres, cal)
    # 5 × (120 − 100) − 1 de la venta − 0,5 (la mitad de la comisión de compra)
    assert serie[2][1]["realizado"] == pytest.approx(100.0 - 1.0 - 0.5)


# ── El calendario sin red ────────────────────────────────────────────────────


def test_un_ticker_sin_filas_en_el_cache_se_dice_y_NO_es_no_paga(test_db):
    from database.cartera_real import calendario_del_cache
    from database.models import DividendCalendarCache, session_scope

    with session_scope() as s:
        s.add(DividendCalendarCache(ticker="AAA", ex_date="2026-03-05", amount=0.5))
        s.add(DividendCalendarCache(ticker="NOP", ex_date="0000-00-00", amount=0.0))  # «no paga»
    with session_scope() as s:
        cal, faltan = calendario_del_cache(s, ["AAA", "NOP", "ZZZ"])
    assert cal == {"AAA": [("2026-03-05", 0.5)], "NOP": [], "ZZZ": []}
    assert faltan == ["ZZZ"]


# (4) La pantalla ───────────────────────────────────────────────────────────

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
    monkeypatch.setattr(cr, "cierres_del_cache", lambda ts: {"AAA": _dias(3, [100.0, 110.0, 120.0])})
    llamadas = []
    original = cr.resumen_home
    monkeypatch.setattr(cr, "resumen_home", lambda *a, **k: llamadas.append(1) or original(*a, **k))
    from ui.home_tab import HomeTab

    h = HomeTab()
    h.llamadas = llamadas
    yield h
    h.hero_chart.cleanup()
    h.deleteLater()


def test_el_boton_alterna_valor_y_ganancia_SIN_recalcular(home):
    assert "valor de mercado" in home.hero_title.text()
    assert home.ganancia_btn.isEnabled()
    home.ganancia_btn.setChecked(True)
    assert "ganancia, hasta el 04/03: +$200" in home.hero_title.text()
    assert "realizada $100" in home.hero_sub.text()
    assert home.ganancia_btn.text() == "Ver valor de mercado"
    home.ganancia_btn.setChecked(False)
    assert "valor de mercado" in home.hero_title.text()
    assert home.llamadas == [1], "el botón volvió a armar el resumen"


def test_el_subtitulo_ya_no_dice_que_el_grafico_NO_es_valor_de_mercado(home):
    """Desde la 305 el gráfico es el valor de mercado, y el subtítulo fijo decía lo contrario."""
    assert "no es valor de mercado" not in home.hero_sub.text()
    assert "incluye la plata puesta" in home.hero_sub.text()
