"""Tarea 325 — Portfolio con un desplegable por ticker (Lotes, Transacciones, Dividendos).

Pedido de Chapa (2026-10-07), con dos capturas de Yahoo. Lo que se fija:

* las filas del desplegable salen del libro FIFO (tarea 324), sin Qt;
* las cerradas se ven, rotuladas «Cerrada», y **no** suman a las tarjetas;
* con un desplegable abierto, la fila de la tabla deja de ser el índice en ``_positions``: el
  análisis, la venta y el menú tienen que ir a la posición de esa fila y no a la de al lado.
"""

from __future__ import annotations

import os
from datetime import date, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication

from database.lotes import Movimiento, libro_fifo
from ui.portfolio_detalle import filas_lotes, filas_transacciones

# Global, como en la 323: un fixture de módulo soltaba la QApplication y Qt se llevaba singletons.
_APP = QApplication.instance() or QApplication([])


# ── Las filas, sin Qt ────────────────────────────────────────────────────────


def _libro_intc():
    return libro_fifo(
        [
            Movimiento(date(2024, 6, 10), "BUY", 9.569235, 30.6212, 6.98),
            Movimiento(date(2026, 7, 21), "BUY", 4.0, 103.53, 0.35),
            Movimiento(date(2026, 9, 23), "SELL", 9.569235, 121.72, 11.36),
        ]
    )


def test_los_lotes_son_los_ABIERTOS_valuados_al_precio():
    (lote,) = filas_lotes(_libro_intc(), 113.15, hoy=date(2026, 10, 7))
    assert lote["fecha"] == date(2026, 7, 21) and lote["acciones"] == 4.0
    assert lote["ganancia"] == pytest.approx(4 * (113.15 - 103.53))
    assert lote["anual_pct"] is None  # menos de un año: anualizar 78 días inventa un número


def test_sin_precio_el_lote_NO_se_valua_al_costo():
    (lote,) = filas_lotes(_libro_intc(), None)
    assert lote["valor"] is None and lote["ganancia"] is None


def test_la_ganancia_anual_de_un_lote_de_mas_de_un_anio():
    lb = libro_fifo([Movimiento(date(2024, 10, 7), "BUY", 10, 100.0)])
    (lote,) = filas_lotes(lb, 121.0, hoy=date(2026, 10, 7))  # +21% en dos años
    assert lote["anual_pct"] == pytest.approx(10.0, abs=0.02)


def test_las_transacciones_van_de_la_mas_nueva_a_la_mas_vieja_con_su_realizada():
    filas = filas_transacciones(_libro_intc())
    assert [f["tipo"] for f in filas] == ["Venta", "Compra", "Compra"]
    venta = filas[0]
    assert venta["realizada"] == pytest.approx(9.569235 * 121.72 - 11.36 - (9.569235 * 30.6212 + 6.98))
    assert filas[1]["realizada"] is None  # el lote de julio no se vendió


# ── La tabla ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tab(test_db, monkeypatch):
    """Una cartera con dos abiertas (AAA, CCC) y una cerrada (BBB), sin workers ni red."""
    from database.models import Portfolio, Position, Transaction, session_scope
    from ui.portfolio_tab import PortfolioTab

    for nombre in ("_fetch_prices", "_fetch_dividends", "_fetch_signals"):
        monkeypatch.setattr(PortfolioTab, nombre, lambda self: None)
    with session_scope() as s:
        pf = Portfolio(name="Mis Acciones")
        s.add(pf)
        s.flush()
        for t, q, txs in (
            ("AAA", 10.0, [("BUY", 10.0, 50.0)]),
            ("BBB", 0.0, [("BUY", 5.0, 20.0), ("SELL", 5.0, 30.0)]),
            ("CCC", 2.0, [("BUY", 2.0, 100.0)]),
        ):
            p = Position(
                portfolio_id=pf.id, ticker=t, quantity=q, avg_buy_price=50.0 if t == "AAA" else 100.0
            )
            s.add(p)
            s.flush()
            for k, (tipo, cant, px) in enumerate(txs):
                s.add(
                    Transaction(
                        position_id=p.id,
                        transaction_type=tipo,
                        quantity=cant,
                        price=px,
                        fees=0.0,
                        date=datetime(2026, 1, 2 + k),
                    )
                )
    w = PortfolioTab()
    yield w
    w.deleteLater()


def _textos(w, col):
    out = []
    for r in range(w.table.rowCount()):
        it = w.table.item(r, col)
        out.append(it.text() if it else None)
    return out


def test_la_cerrada_se_ve_rotulada_y_NO_suma_a_las_tarjetas(tab):
    from ui.portfolio_tab import _COL_TICKER

    assert _textos(tab, _COL_TICKER) == ["AAA", "CCC", "BBB"]  # abiertas primero
    assert _textos(tab, 2) == ["Abierta", "Abierta", "Cerrada"]
    assert [p.ticker for p in tab._positions] == ["AAA", "CCC"]
    assert _textos(tab, 12)[2] == "+$50.00"  # la realizada de BBB: 5 × (30 − 20)


def test_la_flecha_abre_y_cierra_el_desplegable(tab):
    from ui.portfolio_detalle import DetallePosicion

    tab._on_cell_clicked(0, 0)
    assert tab.table.rowCount() == 4
    assert isinstance(tab.table.cellWidget(1, 0), DetallePosicion)
    assert tab.table.columnSpan(1, 0) == tab.table.columnCount()
    assert [tab.table.cellWidget(1, 0).tabText(i) for i in range(3)] == [
        "Lotes",
        "Transacciones",
        "Dividendos",
    ]
    tab._on_cell_clicked(0, 0)
    assert tab.table.rowCount() == 3


def test_con_un_desplegable_abierto_cada_fila_es_SU_posicion(tab):
    """Antes se indexaba ``_positions[row]``: con AAA abierta, la fila 2 (CCC) daba la cerrada BBB… o nada."""
    emitidas = []
    tab.position_selected.connect(emitidas.append)
    tab._on_cell_clicked(0, 0)  # AAA, desplegable, CCC, BBB
    assert tab._pos_en(1) is None  # el desplegable no es una posición
    tab.table.setCurrentCell(2, 1)
    tab._analyze_selected()
    assert emitidas[-1].ticker == "CCC"
    assert tab.sell_btn.isEnabled()
    tab.table.setCurrentCell(3, 1)  # la cerrada: se analiza, no se vende
    assert not tab.sell_btn.isEnabled() and tab.analyze_btn.isEnabled()


# ── Que se lea (captura de Chapa, 2026-10-07: columnas cortadas y filas tapadas) ─


def test_ninguna_celda_ni_encabezado_queda_mas_ancho_que_su_columna():
    """Medido con la fuente y el padding del tema: ``resizeColumnsToContents`` medía sin ellos."""
    from PyQt6.QtGui import QFont, QFontMetrics

    from ui import portfolio_detalle as pd
    from ui.portfolio_detalle import DetallePosicion

    d = DetallePosicion(_libro_intc(), 113.15, [("2026-08-07", 0.125, 13.569235, 1.70)])
    f = QFont(pd._FAMILIA)
    f.setPixelSize(pd._CELDA_PX)
    fm = QFontMetrics(f)
    for i in range(d.count()):
        t = d.widget(i)
        for c in range(t.columnCount()):
            for r in range(t.rowCount()):
                assert t.columnWidth(c) >= fm.horizontalAdvance(t.item(r, c).text()) + 2 * 14, (i, r, c)
        # todas las filas entran: alto fijo ≥ encabezado + filas con su padding vertical
        assert t.height() >= t.rowCount() * (fm.height() + 2 * 10)
