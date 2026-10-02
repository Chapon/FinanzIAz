"""Operaciones de la cartera real que no pueden depender de Qt (tarea 277).

La venta vivía entera en ``ui/dialogs.py::SellPositionDialog``, y en una venta **total**
hacía ``session.delete(pos)``. Con ``Position.transactions`` en
``cascade="all, delete-orphan"`` y la sesión de la app (``autoflush=False``), eso borraba
la compra —ticker, costo, fecha— y dejaba la venta **huérfana**: invisible para los
reportes, que filtran por las posiciones que existen. Ver
``docs/auditoria_cuentas_real_2026-10-02.md`` [R-1].

Ahora una posición vendida entera queda en **cantidad 0** con todas sus transacciones, y
las vistas de tenencias filtran las de cantidad 0. Volver a comprar el ticker reusa la
fila (los *merges* ya lo hacían) y reinicia la fecha de compra, que es la que usa el
cálculo de dividendos.
"""

from __future__ import annotations

from datetime import datetime

from database.models import Position, Transaction, utcnow_naive

# Por debajo de esto, una posición está cerrada. Las cantidades son floats (hay acciones
# fraccionarias en la cartera real), y una resta puede dejar 1e-12.
CERRADA_TOL = 1e-8


def esta_abierta(pos) -> bool:
    return float(pos.quantity or 0.0) > CERRADA_TOL


def registrar_venta(session, pos: Position, qty: float, price: float, fees: float = 0.0) -> Transaction:
    """Registra la venta de ``qty`` acciones de ``pos`` y descuenta la cantidad.

    **No borra la posición nunca**: una venta total la deja en cantidad 0, con su compra y
    su venta ligadas. Borrarla destruía el único registro del costo y del P&L realizado.
    """
    tx = Transaction(
        position_id=pos.id,
        transaction_type="SELL",
        quantity=qty,
        price=price,
        fees=fees,
    )
    session.add(tx)
    restante = float(pos.quantity) - float(qty)
    pos.quantity = 0.0 if abs(restante) < CERRADA_TOL else restante
    pos.updated_at = utcnow_naive()
    return tx


def reabrir_si_cerrada(pos: Position, fecha: datetime | None) -> None:
    """Si ``pos`` estaba cerrada, la próxima compra arranca un lote nuevo: fecha nueva.

    Los *merges* de alta e importación conservan la fecha **más vieja** para el cálculo de
    dividendos; con una posición cerrada, esa fecha es la del lote ya vendido, y los
    dividendos se contarían desde ahí.
    """
    if not esta_abierta(pos):
        pos.purchase_date = fecha or utcnow_naive()
