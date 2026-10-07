"""Tarea 326 — una venta desde la app recalcula el costo por FIFO.

El caso es el de INTC (la 324): dos compras a precios muy distintos. Por promedio, después de
vender el primer lote el costo de lo que queda es ~$52; por FIFO —lo que muestra el desplegable
de Lotes— es $103,53. Antes de la 326 la fila quedaba en el promedio.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from database.cartera_real import registrar_venta
from database.models import Portfolio, Position, Transaction, session_scope


def _intc(con_historia: bool = True) -> int:
    with session_scope() as s:
        pf = Portfolio(name="Mis Acciones")
        s.add(pf)
        s.flush()
        q1, p1, q2, p2 = 9.569235, 30.6212, 4.0, 103.53
        pos = Position(
            portfolio_id=pf.id,
            ticker="INTC",
            quantity=q1 + q2,
            avg_buy_price=(q1 * p1 + q2 * p2) / (q1 + q2),
        )
        s.add(pos)
        s.flush()
        if con_historia:
            s.add(
                Transaction(
                    position_id=pos.id,
                    transaction_type="BUY",
                    quantity=q1,
                    price=p1,
                    date=datetime(2024, 6, 10),
                )
            )
            s.add(
                Transaction(
                    position_id=pos.id,
                    transaction_type="BUY",
                    quantity=q2,
                    price=p2,
                    date=datetime(2026, 7, 21),
                )
            )
        return pos.id


def _vender(pid, qty, precio=121.72):
    with session_scope() as s:
        pos = s.query(Position).filter(Position.id == pid).one()
        registrar_venta(s, pos, qty, precio, 11.36)
    with session_scope() as s:
        p = s.query(Position).filter(Position.id == pid).one()
        return p.quantity, p.avg_buy_price, p.purchase_date


def test_la_venta_deja_el_costo_FIFO_de_lo_que_queda_y_no_el_promedio(test_db):
    qty, costo, fecha = _vender(_intc(), 9.569235)
    assert qty == pytest.approx(4.0)
    assert costo == pytest.approx(103.53)  # el promedio daba ~52
    assert fecha == datetime(2026, 7, 21)  # la del lote que queda: desde ahí cobra dividendos


def test_la_fila_y_el_desplegable_dan_el_mismo_costo(test_db):
    from database.cartera_real import movimientos_de
    from database.lotes import libro_fifo

    pid = _intc()
    _, costo, _ = _vender(pid, 5.0)
    with session_scope() as s:
        libro = libro_fifo(movimientos_de(s.query(Transaction).filter(Transaction.position_id == pid).all()))
    assert costo == pytest.approx(libro.costo_promedio)


def test_sin_historia_completa_sigue_la_cuenta_de_antes(test_db):
    """Una posición sin transacciones: el FIFO no tiene con qué. Descuenta y deja el costo."""
    pid = _intc(con_historia=False)
    with session_scope() as s:
        antes = s.query(Position).filter(Position.id == pid).one().avg_buy_price
    qty, costo, _ = _vender(pid, 5.0)
    assert qty == pytest.approx(9.569235 + 4.0 - 5.0)
    assert costo == pytest.approx(antes)
