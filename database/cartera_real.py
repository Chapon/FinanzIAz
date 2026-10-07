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


# ── Compras, ventas y splits desde un CSV (tarea 324) ────────────────────────


def movimientos_de(txs) -> list:
    """Las ``Transaction`` de una posición como ``lotes.Movimiento``, para el libro FIFO."""
    from database.lotes import Movimiento

    return [
        Movimiento(
            fecha=t.date.date() if t.date is not None else date.min,
            tipo="BUY" if str(t.transaction_type).upper() == "BUY" else "SELL",
            cantidad=float(t.quantity),
            precio=float(t.price),
            comision=float(t.fees or 0.0),
            nota=t.notes or "",
        )
        for t in txs
    ]


def recalcular_posicion(pos: Position, txs) -> str | None:
    """Cantidad, costo y fecha de ``pos`` desde **todas** sus transacciones, por FIFO.

    El costo es el de los lotes abiertos (el que muestra Yahoo, y el de la vista desplegable);
    sin ventas, es el promedio ponderado de siempre. Una posición cerrada conserva el promedio
    de sus compras, porque ``avg_buy_price`` no admite nulos. La fecha de compra es la del lote
    abierto más viejo, que es desde donde cobra dividendos. Devuelve el error del libro, si hubo.
    """
    from database.lotes import libro_fifo

    movs = movimientos_de(txs)
    libro = libro_fifo(movs)
    if libro.error:
        return libro.error
    pos.quantity = libro.cantidad if libro.abierta else 0.0
    if libro.abierta:
        pos.avg_buy_price = libro.costo_promedio
        pos.purchase_date = datetime.combine(libro.fecha_lote_mas_viejo, datetime.min.time())
    else:
        compras = [m for m in movs if m.tipo == "BUY"]
        q = sum(m.cantidad for m in compras)
        pos.avg_buy_price = sum(m.cantidad * m.precio for m in compras) / q if q else 0.0
    pos.updated_at = utcnow_naive()
    return None


def guardar_armadas(session, portfolio_id: int, armadas, info: dict | None = None, nota: str = "") -> dict:
    """Guarda ``armadas`` (de ``lotes.armar_posiciones``) en la cartera ``portfolio_id``.

    Un ticker que ya está en la cartera **suma** sus transacciones y se recalcula entero; uno
    nuevo se crea. Un ticker cuyo libro da error (vende más de lo que tiene) no se guarda y
    queda en ``errores``. ``info`` es ``{ticker: (empresa, sector)}`` para las posiciones nuevas.
    """
    info = info or {}
    out: dict = {"nuevas": 0, "actualizadas": 0, "errores": {}}
    for arm in armadas:
        if arm.libro.error:
            out["errores"][arm.ticker] = arm.libro.error
            continue
        pos = (
            session.query(Position)
            .filter(Position.portfolio_id == portfolio_id)
            .filter(Position.ticker == arm.ticker)
            .first()
        )
        if pos is None:
            empresa, sector = info.get(arm.ticker, (None, None))
            pos = Position(
                portfolio_id=portfolio_id,
                ticker=arm.ticker,
                company_name=empresa,
                sector=sector,
                quantity=0.0,
                avg_buy_price=0.0,
                notes=nota or None,
            )
            session.add(pos)
            session.flush()
            out["nuevas"] += 1
        else:
            out["actualizadas"] += 1
        for m in arm.movimientos:
            session.add(
                Transaction(
                    position_id=pos.id,
                    transaction_type=m.tipo,
                    quantity=m.cantidad,
                    price=m.precio,
                    fees=m.comision,
                    date=datetime.combine(m.fecha, datetime.min.time()),
                    notes=m.nota or nota or None,
                )
            )
        session.flush()
        txs = session.query(Transaction).filter(Transaction.position_id == pos.id).all()
        error = recalcular_posicion(pos, txs)
        if error:  # con lo que ya había en la cartera, el libro no cierra: no se guarda nada de este
            raise ValueError(f"{arm.ticker}: {error}")
    return out


def reemplazar_cartera(session, portfolio_id: int, armadas, nota: str = "") -> dict:
    """Borra las posiciones de la cartera y la reconstruye desde ``armadas``.

    Conserva empresa y sector de los tickers que ya estaban. Si algún ticker da error, no toca
    nada: reemplazar a medias dejaría la cartera sin las posiciones que no se pudieron armar.
    """
    errores = {a.ticker: a.libro.error for a in armadas if a.libro.error}
    if errores:
        return {"nuevas": 0, "actualizadas": 0, "errores": errores, "borradas": 0}
    viejas = session.query(Position).filter(Position.portfolio_id == portfolio_id).all()
    info = {p.ticker: (p.company_name, p.sector) for p in viejas}
    for p in viejas:
        session.delete(p)  # se lleva sus transacciones por la cascada
    session.flush()
    out = guardar_armadas(session, portfolio_id, armadas, info, nota)
    out["borradas"] = len(viejas)
    return out


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
    - la serie **termina** en la última rueda que tienen todos los tickers con historia **que
      siguen en cartera** (tarea 309; si se vendió todo, en el último cierre que haya): más
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
    # El corte mira sólo los tickers que siguen EN CARTERA (tarea 309): uno vendido no aporta
    # valor después de la venta, y su cache deja de refrescarse (si no está en el universo del
    # scan, sólo lo refresca Portfolio mientras está en cartera). Antes cortaba en el último
    # cierre del ticker más atrasado de toda la historia, y la primera venta congelaba el gráfico.
    finales: dict[str, float] = {}
    for _, t, q in eventos:
        finales[t] = finales.get(t, 0.0) + q
    en_cartera = [t for t in con_historia if finales.get(t, 0.0) > CERRADA_TOL]
    ultimos = {t: max(d for d, _ in cierres[t]) for t in con_historia}
    hasta = min(ultimos[t] for t in en_cartera) if en_cartera else max(ultimos.values())
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


def ganancias_diarias(
    movs: dict[str, list],
    cierres: dict[str, list[tuple[date, float]]],
    calendario: dict[str, list[tuple[str, float]]],
) -> tuple[list[tuple[date, dict]], list[str]]:
    """La ganancia de la cartera por rueda, separada de la plata puesta (tarea 332). Puro.

    ``movs`` es ``{ticker: [lotes.Movimiento]}``. Por cada rueda de ``valor_diario`` —mismos
    días, mismo valor— devuelve ``{valor, costo, no_realizado, realizado, dividendos, total}``:

    - ``costo``: lo que siguen costando, por FIFO, las acciones en cartera ese día. Es la
      «plata puesta»: la app no registra depósitos de efectivo, sólo compras y ventas.
    - ``no_realizado = valor − costo``. ``valor`` y ``costo`` cuentan sólo los tickers **con**
      cierres, igual que ``valor_diario``; los otros vuelven en la segunda lista.
    - ``realizado``: el acumulado de las ventas hasta ese día, con las dos comisiones.
    - ``dividendos``: el acumulado cobrado hasta ese día (ex-date ≤ día; convención de la 222).

    Las convenciones son las de Portfolio, para que los dos lugares den el mismo número: el
    costo sin la comisión de compra (``avg_buy_price``), la realizada con comisiones.
    """
    from database.lotes import libro_fifo

    eventos = [
        (m.fecha, t, m.cantidad if m.tipo == "BUY" else -m.cantidad) for t, ms in movs.items() for m in ms
    ]
    serie_valor, sin_historia = valor_diario(eventos, cierres)
    if not serie_valor:
        return [], sin_historia
    con_historia = {t for t in movs if cierres.get(t)}
    detalle_div = {
        t: dividendos_detalle(
            [(m.fecha.isoformat(), m.cantidad if m.tipo == "BUY" else -m.cantidad) for m in ms],
            calendario.get(t, []),
        )
        for t, ms in movs.items()
    }
    ordenados = {
        t: sorted(ms, key=lambda m: (m.fecha, 0 if m.tipo == "BUY" else 1)) for t, ms in movs.items()
    }
    memo: dict[tuple[str, int], object] = {}  # el libro sólo cambia el día de una transacción

    def libro_al(t: str, dia: date):
        n = sum(1 for m in ordenados[t] if m.fecha <= dia)
        if (t, n) not in memo:
            memo[(t, n)] = libro_fifo(ordenados[t][:n])
        return memo[(t, n)]

    out = []
    for dia, valor in serie_valor:
        libros = {t: libro_al(t, dia) for t in movs}
        costo = sum(lo.cantidad * lo.precio for t in con_historia for lo in libros[t].lotes)
        realizado = sum(lb.realizado for lb in libros.values())
        dividendos = sum(c for t in movs for ex, _, _, c in detalle_div[t] if ex[:10] <= dia.isoformat())
        no_realizado = valor - costo
        out.append(
            (
                dia,
                {
                    "valor": valor,
                    "costo": costo,
                    "no_realizado": no_realizado,
                    "realizado": realizado,
                    "dividendos": dividendos,
                    "total": no_realizado + realizado + dividendos,
                },
            )
        )
    return out, sin_historia


def calendario_del_cache(session, tickers: list[str]) -> tuple[dict[str, list[tuple[str, float]]], list[str]]:
    """Ex-dates de ``dividend_calendar_cache``, **sin red** (Home), y los tickers que no tienen fila.

    Un ticker que nunca se pidió no tiene fila y **no** es lo mismo que «no paga» (que guarda
    el centinela ``0000-00-00``): se devuelve aparte para decirlo, no se cuenta como cero.
    """
    from database.models import DividendCalendarCache

    out: dict[str, list[tuple[str, float]]] = {t: [] for t in tickers}
    vistos: set[str] = set()
    if tickers:
        for f in (
            session.query(DividendCalendarCache)
            .filter(DividendCalendarCache.ticker.in_(tickers))
            .order_by(DividendCalendarCache.ex_date)
        ):
            vistos.add(f.ticker)
            if f.ex_date != "0000-00-00" and f.amount:
                out[f.ticker].append((f.ex_date, float(f.amount)))
    return out, sorted(set(tickers) - vistos)


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
        dict_cierres = provider(sorted({e[1] for e in eventos}))
        serie_valor, sin_historia = valor_diario(eventos, dict_cierres)
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception("Home: no se pudo armar el valor diario; queda el invertido neto")
        serie_valor, sin_historia, dict_cierres = [], [], None
    # Tarea 332: la ganancia separada de la plata puesta, para el botón de Home.
    serie_ganancia, sin_calendario = [], []
    if dict_cierres is not None:
        try:
            movs: dict[str, list] = {}
            for t in txs:
                if t.date is not None and t.position is not None:
                    movs.setdefault(t.position.ticker, []).extend(movimientos_de([t]))
            calendario, sin_calendario = calendario_del_cache(session, sorted(movs))
            serie_ganancia, _ = ganancias_diarias(movs, dict_cierres, calendario)
        except Exception:
            from config.logging_config import get_logger

            get_logger(__name__).exception("Home: no se pudo armar la ganancia diaria")
            serie_ganancia, sin_calendario = [], []
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
        "ganancia_diaria": serie_ganancia,
        "ganancia_sin_calendario": sin_calendario,
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
    return sum(cobrado for _, _, _, cobrado in dividendos_detalle(eventos, calendario))


def dividendos_detalle(
    eventos: list[tuple[str, float]], calendario: list[tuple[str, float]]
) -> list[tuple[str, float, float, float]]:
    """``(ex_date, $/acción, acciones, cobrado)`` de cada pago que cobró la posición. Puro.

    Lo que lista la pestaña «Dividendos» de la vista desplegable (tarea 325), y lo que suma
    ``dividendos_cobrados``: la misma aritmética en los dos lados.
    """
    from paper_trading.dividends import acciones_antes_del_ex_date

    out = []
    for ex_date, monto in calendario:
        # Un ex-date anterior a la primera compra (o el centinela «no paga») no necesita un
        # filtro propio: ahí `acciones_antes_del_ex_date` da 0. Probado por mutación: un
        # `ex_date <= primera_compra` acá no cambiaba nada, y se sacó.
        if not monto:
            continue
        acciones = acciones_antes_del_ex_date(eventos, ex_date)
        if acciones > CERRADA_TOL:
            out.append((ex_date, float(monto), acciones, acciones * float(monto)))
    return out


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
