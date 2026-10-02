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


# ── Home (tarea 264) ─────────────────────────────────────────────────────────

# La cartera que muestra Home. Decisión de Chapa (2026-10-02): *«sólo Mis Acciones»*. Se
# resuelve por NOMBRE —el que él ve en Portfolio— y no por id fijo: un id fijo es la forma
# exacta del defecto que la 264 vino a sacar (Home elegía la cuenta paper 1 por id).
CARTERA_HOME = "Mis Acciones"


def resumen_home(session, nombre: str = CARTERA_HOME) -> dict | None:
    """Lo que Home muestra de la cartera real ``nombre``, o ``None`` si no existe.

    **Sin red:** los precios salen de la última fila de ``price_cache`` de cada ticker, que
    escribe el resto de la app. Un ticker sin fila queda en ``sin_precio`` y **no** se valúa
    al costo: valor y P&L se calculan sólo sobre las posiciones con precio, y Home dice
    cuántas faltan (la lección de la 268 [F-2] y la 281 [P-1]).
    """
    from sqlalchemy import func

    from database.models import Alert, Portfolio, PriceCache

    pf = session.query(Portfolio).filter(Portfolio.name == nombre).first()
    if pf is None:
        return None
    abiertas = [
        p
        for p in session.query(Position)
        .filter(Position.portfolio_id == pf.id)
        .order_by(Position.ticker)
        .all()
        if esta_abierta(p)
    ]
    tickers = sorted({p.ticker for p in abiertas})
    precios: dict[str, tuple[float, datetime | None]] = {}
    if tickers:
        ultimo = (
            session.query(PriceCache.ticker, func.max(PriceCache.fetched_at).label("f"))
            .filter(PriceCache.ticker.in_(tickers))
            .group_by(PriceCache.ticker)
            .subquery()
        )
        for t, px, f in (
            session.query(PriceCache.ticker, PriceCache.price, PriceCache.fetched_at)
            .join(ultimo, (PriceCache.ticker == ultimo.c.ticker) & (PriceCache.fetched_at == ultimo.c.f))
            .all()
        ):
            if px and px > 0:
                precios[t] = (float(px), f)

    con_precio = [p for p in abiertas if p.ticker in precios]
    valor = sum(float(p.quantity) * precios[p.ticker][0] for p in con_precio)
    costo_con_precio = sum(float(p.quantity) * float(p.avg_buy_price) for p in con_precio)
    pl = valor - costo_con_precio
    txs = (
        session.query(Transaction)
        .join(Position, Transaction.position_id == Position.id)
        .filter(Position.portfolio_id == pf.id)
        .order_by(Transaction.date)
        .all()
    )
    invertido_neto = []  # (fecha, compras − ventas acumuladas, a precio de transacción)
    acum = 0.0
    for t in txs:
        signo = 1.0 if str(t.transaction_type).upper() == "BUY" else -1.0
        acum += signo * float(t.quantity) * float(t.price)
        if t.date is not None:
            invertido_neto.append((t.date, acum))
    alertas = (
        session.query(Alert).filter(Alert.portfolio_id == pf.id).filter(Alert.is_active.is_(False)).count()
    )
    fechas = [f for _, f in precios.values() if f is not None]
    return {
        "portfolio_id": pf.id,
        "nombre": pf.name,
        "posiciones": len(abiertas),
        "valor": valor,
        "costo_con_precio": costo_con_precio,
        "costo_total": sum(float(p.quantity) * float(p.avg_buy_price) for p in abiertas),
        "pl": pl,
        "pl_pct": (pl / costo_con_precio * 100.0) if costo_con_precio > 0 else 0.0,
        "sin_precio": sorted(p.ticker for p in abiertas if p.ticker not in precios),
        "torta": sorted(
            ((p.ticker, float(p.quantity) * precios[p.ticker][0]) for p in con_precio),
            key=lambda x: -x[1],
        ),
        "transacciones": len(txs),
        "tx_por_dia": [t.date.date() for t in txs if t.date is not None],
        "invertido_neto": invertido_neto,
        "alertas_disparadas": alertas,
        "precio_mas_viejo": min(fechas) if fechas else None,
    }
