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

from datetime import date, datetime

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


# ── Valor de mercado diario (tarea 305) ──────────────────────────────────────


def valor_diario(
    eventos: list[tuple[date, str, float]],
    cierres: dict[str, list[tuple[date, float]]],
) -> tuple[list[tuple[date, float]], list[str]]:
    """Valor de mercado de la cartera por rueda, desde la primera transacción. Puro.

    ``eventos`` son ``(día, ticker, acciones con signo)`` —BUY positivo, SELL negativo—, y
    ``cierres`` el cierre diario de cada ticker. Cada rueda vale ``Σ acciones de ese día ×
    cierre de ese día`` (una transacción del día ya cuenta ese día).

    Lo que **no** hace, a propósito, para no pintar un hueco como dato:

    - un ticker sin cierres queda **afuera** y se devuelve en la segunda lista, en vez de
      valuarse en cero;
    - la serie **termina** en la última rueda que tienen todos los tickers con historia: más
      allá, uno de ellos quedaría congelado en su último cierre sin que nada lo diga. Adentro,
      una rueda que le falta a un ticker (un feriado distinto) toma su cierre anterior.

    Antes Home graficaba el capital invertido neto, que en una cartera comprada en un solo
    día es **un punto**: *«el home solo grafica 1 día»* (Chapa, 2026-10-04).
    """
    if not eventos:
        return [], []
    tickers = sorted({t for _, t, _ in eventos})
    sin_historia = [t for t in tickers if not cierres.get(t)]
    con_historia = [t for t in tickers if cierres.get(t)]
    if not con_historia:
        return [], sin_historia
    desde = min(d for d, _, _ in eventos)
    hasta = min(max(d for d, _ in cierres[t]) for t in con_historia)
    ruedas = sorted({d for t in con_historia for d, _ in cierres[t] if desde <= d <= hasta})
    por_ticker = {t: dict(cierres[t]) for t in con_historia}
    ordenados = sorted(eventos)
    acciones: dict[str, float] = dict.fromkeys(con_historia, 0.0)
    ultimo_cierre: dict[str, float] = {}
    for t in con_historia:  # el cierre previo a la primera rueda, por si la primera le falta
        previos = [(d, c) for d, c in cierres[t] if d < desde]
        if previos:
            ultimo_cierre[t] = max(previos)[1]
    serie: list[tuple[date, float]] = []
    i = 0
    for dia in ruedas:
        while i < len(ordenados) and ordenados[i][0] <= dia:
            _, t, q = ordenados[i]
            if t in acciones:
                acciones[t] += q
            i += 1
        for t in con_historia:
            if dia in por_ticker[t]:
                ultimo_cierre[t] = por_ticker[t][dia]
        serie.append(
            (dia, sum(q * ultimo_cierre.get(t, 0.0) for t, q in acciones.items() if q > CERRADA_TOL))
        )
    return serie, sin_historia


def cierres_del_cache(tickers: list[str]) -> dict[str, list[tuple[date, float]]]:
    """Cierres diarios del cache local, **sin red** (Home no puede colgarse esperando a Yahoo).

    Por ticker, de todos sus frames ``1d`` (cualquier período), el que **termina más tarde**:
    el ``1y`` lo refresca la pestaña Portfolio y los largos pueden estar congelados (la 286).
    No es ``latest_1d``, que elige el bajado más recientemente. Un ticker sin ningún frame
    no aparece, y ``valor_diario`` lo reporta.
    """
    from data import parquet_cache

    out: dict[str, list[tuple[date, float]]] = {}
    for t in tickers:
        try:
            frames = [
                df for df in parquet_cache.all_1d(t) if df is not None and not df.empty and "Close" in df
            ]
        except Exception:
            frames = []
        if frames:
            mejor = max(frames, key=lambda df: df.index.max())
            out[t] = [(ts.date(), float(c)) for ts, c in mejor["Close"].dropna().items()]
    return out


# ── Home (tarea 264) ─────────────────────────────────────────────────────────

# La cartera que muestra Home. Decisión de Chapa (2026-10-02): *«sólo Mis Acciones»*. Se
# resuelve por NOMBRE —el que él ve en Portfolio— y no por id fijo: un id fijo es la forma
# exacta del defecto que la 264 vino a sacar (Home elegía la cuenta paper 1 por id).
CARTERA_HOME = "Mis Acciones"


def resumen_home(session, nombre: str = CARTERA_HOME, cierres=None) -> dict | None:
    """Lo que Home muestra de la cartera real ``nombre``, o ``None`` si no existe.

    **Sin red:** los precios salen de la última fila de ``price_cache`` de cada ticker, que
    escribe el resto de la app. Un ticker sin fila queda en ``sin_precio`` y **no** se valúa
    al costo: valor y P&L se calculan sólo sobre las posiciones con precio, y Home dice
    cuántas faltan (la lección de la 268 [F-2] y la 281 [P-1]).

    ``cierres`` (tarea 305) da los cierres diarios por ticker para ``valor_diario``; por
    default ``cierres_del_cache``, que tampoco usa la red.
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
    eventos = [
        (
            t.date.date(),
            t.position.ticker,
            (1.0 if str(t.transaction_type).upper() == "BUY" else -1.0) * float(t.quantity),
        )
        for t in txs
        if t.date is not None and t.position is not None
    ]
    try:
        provider = cierres or cierres_del_cache
        serie_valor, sin_historia = valor_diario(eventos, provider(sorted({e[1] for e in eventos})))
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception("Home: no se pudo armar el valor diario; queda el invertido neto")
        serie_valor, sin_historia = [], []
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
        "valor_diario": serie_valor,
        "valor_diario_sin_historia": sin_historia,
        "alertas_disparadas": alertas,
        "precio_mas_viejo": min(fechas) if fechas else None,
    }


# ── Dividendos cobrados, por lote (tarea 281) ─────────────────────────────────


def dividendos_cobrados(eventos: list[tuple[str, float]], calendario: list[tuple[str, float]]) -> float:
    """Efectivo de dividendos que cobró una posición, lote por lote. Puro.

    ``eventos`` son ``(día 'YYYY-MM-DD', acciones con signo)`` de sus transacciones —BUY
    positivo, SELL negativo—; ``calendario`` son ``(ex_date, $/acción)``.

    Reemplaza el cálculo de la pestaña Portfolio, que multiplicaba el dividendo por acción
    desde **una sola** fecha (``purchase_date``) por la cantidad **actual**: en una posición
    comprada en tramos contaba dividendos de acciones que todavía no se tenían
    (``docs/auditoria_pantalla_resto_2026-10-02.md`` [P-2]). Acá cobra, en cada ex-date,
    lo que había **antes** de esa fecha — la convención de la 222 (``acciones_antes_del_ex_date``):
    una compra del mismo día del ex-date no cobra.
    """
    from paper_trading.dividends import acciones_antes_del_ex_date

    total = 0.0
    for ex_date, monto in calendario:
        # Un ex-date anterior a la primera compra (o el centinela «no paga») no necesita un
        # filtro propio: ahí `acciones_antes_del_ex_date` da 0. Probado por mutación: un
        # `ex_date <= primera_compra` acá no cambiaba nada, y se sacó.
        if not monto:
            continue
        acciones = acciones_antes_del_ex_date(eventos, ex_date)
        if acciones > 0:
            total += acciones * float(monto)
    return total


def valor_y_pl(positions, prices: dict) -> dict:
    """Valor, P&L y % de las posiciones **con precio**, y cuáles no lo tienen (tareas 281/268).

    Una posición sin precio **no** se valúa al costo en silencio: queda en ``sin_precio`` y fuera
    del valor y de la ganancia; el % es sobre el costo de las que sí tienen precio. ``prices`` es
    ``{ticker: {"price": float, ...}}``, el formato de la pestaña Portfolio. Lo usan los reportes
    Excel y PDF, que tenían el mismo defecto que las tarjetas de la 281.
    """
    con = [p for p in positions if prices.get(p.ticker)]
    valor = sum(p.quantity * prices[p.ticker]["price"] for p in con)
    costo_con = sum(p.quantity * p.avg_buy_price for p in con)
    pl = valor - costo_con
    return {
        "valor": valor,
        "invertido": sum(p.quantity * p.avg_buy_price for p in positions),
        "pl": pl,
        "pl_pct": (pl / costo_con * 100.0) if costo_con > 0 else 0.0,
        "sin_precio": sorted(p.ticker for p in positions if not prices.get(p.ticker)),
    }
