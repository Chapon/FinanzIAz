"""Crédito de dividendos al motor vivo (tarea 222).

Qué hace y por qué
-------------------
Hasta acá el motor **no miraba dividendos**: la cuenta pasaba por el ex-date, veía caer
el precio y no recibía el efectivo. Medido sobre la cuenta 2 el 2026-09-21: **$322,77 en
3,05 meses = 2,54%/año**, el 62% de todo su P&L neto realizado. El harness, en cambio,
corre sobre barras ``auto_adjust=True`` —total-return— así que los cobra siempre.

Chapa eligió, con los costos de las dos opciones medidos delante (2026-09-25),
**acreditar el efectivo a la caja al ex-date** y **sólo hacia adelante**. Lo que eso
mueve, medido sobre la cuenta 2 antes de decidir:

* cierra el **99,1%** del desvío contra el harness (quedan ~$2,77 de los $322,77) —con el
  crédito andando, que hasta la tarea 350 no andaba (ver abajo)—;
* mueve el sizing de las compras en **0,78% la mediana** (p90 2,5%), porque con
  ``equal_weight`` el target es ``available / len(picks)`` y la caja entra ahí;
* **no mueve los slots**: en toda la vida de la cuenta hubo **0** BUYs sin llenar, así
  que nunca faltó caja para un nombre. El enunciado de la tarea suponía que sí.

Lo que NO cierra, y va dicho
-----------------------------
``auto_adjust=True`` **reinvierte** el dividendo en el precio (la posición crece); la
caja acreditada queda quieta hasta la próxima compra. Sobre la cuenta 2 eso vale ~$2,77
— el 0,9% del desvío—, así que el desvío `dividendos` del registro de harness **se
achica y se re-describe, no se borra**.

Sólo hacia adelante, y cómo se implementa eso (rehecho en la tarea 350)
------------------------------------------------------------------------
**Lo que había no cobró nunca.** La ventana de cada scan era ``(último scan, hoy]``, y
Yahoo publica el ex-date en ``.dividends`` **uno o más días tarde**: GE no lo traía en el
fetch de las 22:16 UTC de su propio ex-date y apareció dos días después. Cuando el ex-date
entraba al cache ya había quedado a la izquierda de la ventana. Resultado, medido el
2026-10-10: ``paper_dividend_credits`` con **0 filas** y $93,96 devengados sin cobrar
(DHR, BMY, GE). El docstring decía que esto cerraba el 99,1% del desvío; en el tramo vivo
el desvío era el **100%**.

Ahora el crédito se decide contra el **ledger**: todo ex-date posterior a
``PISO_DIVIDENDOS`` —la víspera de la puesta en marcha de la 222—, con acciones al ex-date
y sin fila en ``PaperDividendCredit``, se acredita una vez, llegue cuando llegue. El piso
fijo es lo que conserva el «sólo hacia adelante» de la 222 (nada anterior a su puesta en
marcha se cobra), y no depende de cuándo corrió el último scan. Lo devengado entre la 222
y la 350 **sí** se acredita: es lo que la decisión de la 222 ya mandaba cobrar, y Chapa lo
confirmó el 2026-10-11.

Nada de esto pega a la red: se lee ``dividend_calendar_cache``, que el warm-up del scan
puebla antes (mismo lugar donde ya se calienta el cache de barras).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from database.models import session_scope, utcnow_naive  # noqa: F401  (re-export para tests)

# Fecha centinela de `data/yahoo_finance._SIN_DIVIDENDOS`: "este ticker se chequeó y no
# paga". Se duplica el literal a propósito —`paper_trading/` no debe depender de
# `data/yahoo_finance`, que arrastra yfinance y la red— y un test fija que los tres
# literales del repo coincidan. Misma forma con que la 71 resolvió los de reproducción.
_SIN_DIVIDENDOS = "0000-00-00"

# Tarea 350: el límite izquierdo, EXCLUSIVO, de lo que el motor acredita. Es la víspera de la
# puesta en marcha de la 222 (`210b940`, 2026-09-25): ese día el primer scan tenía la ventana
# `(2026-09-24, hoy]`, así que este piso es exactamente lo que la 222 decidió cobrar. Medido
# contra la DB el 2026-10-11: con 09-23, 09-24 o 09-25 lo pendiente es el mismo ($93,96).
PISO_DIVIDENDOS = "2026-09-24"

# Cuántos días después de vender se sigue calentando el calendario de un ticker (tarea 350).
# Yahoo publica el ex-date tarde (dos días en GE): un ticker vendido entre el ex-date y la
# publicación ya no es posición abierta y, sin esto, su calendario no se refrescaba nunca.
DIAS_ATRASO_CALENDARIO = 10


def dia(ts) -> str | None:
    """``YYYY-MM-DD`` de un timestamp/str, o ``None``."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d")
    s = str(ts)
    return s[:10] if len(s) >= 10 else None


def acciones_antes_del_ex_date(eventos: list[tuple[str, float]], ex_date: str) -> float:
    """Acciones en cartera **estrictamente antes** de ``ex_date``.

    ``eventos`` son ``(día, acciones con signo)`` — positivo BUY, negativo SELL.

    **La convención es la de la T220/T221 y es la misma en los dos lados:** hay que tener
    la acción *antes* del ex-date, así que un fill del mismo día **no cobra**. Es la
    convención con la que se midieron los $322,77 y con la que el panel los reproduce
    ticker por ticker, y que el motor use otra sería volver a tener dos aritméticas del
    mismo número — el defecto que las tareas 224 y 230 acaban de sacar del dashboard.
    """
    return sum(q for d, q in eventos if d < ex_date)


def acciones_al_ex_date_con_splits(
    eventos: list[tuple[str, float]], ex_date: str, splits: list[tuple[str, float]]
) -> float:
    """Como ``acciones_antes_del_ex_date``, pero en la escala de los splits ya aplicados (tarea 333).

    ``splits`` son ``(ex_date del split, ratio)`` que el ledger ya aplicó a la posición. Un fill
    anterior a un split que ocurre **hasta** el ex-date del dividendo cuenta ``ratio`` veces: el
    calendario viene **ajustado** por los splits posteriores (la 331), así que su $/acción es el
    de las acciones de después. Sin esto, una posición comprada antes de un 10:1 cobraría 1/10.
    Un fill del mismo día del split ya es post-split (la convención de ``splits.ajustes_pendientes``).
    """
    total = 0.0
    for d, q in eventos:
        if d >= ex_date:
            continue
        for ex_split, ratio in splits:
            if d < ex_split <= ex_date:
                q *= ratio
        total += q
    return total


def creditos_pendientes(
    fills: list[tuple[str, str, float, str]],
    calendario: dict[str, list[tuple[str, float]]],
    ya_acreditados: set[tuple[str, str]],
    desde: str | None,
    hasta: str,
    splits: dict[str, list[tuple[str, float]]] | None = None,
) -> list[tuple[str, str, float, float]]:
    """``(ticker, ex_date, acciones, $/acción)`` de lo que falta acreditar.

    **Función pura**: no toca la DB ni el reloj, así que la ventana y la convención de
    quién cobra se pueden testear sin montar un scan entero.

    ``fills`` son ``(ticker, side, acciones, filled_at)``; ``desde`` es el piso y es
    **exclusivo**, ``hasta`` es hoy e **inclusivo**. El motor pasa ``PISO_DIVIDENDOS``, no el
    día del último scan (tarea 350: el ex-date llega tarde y esa ventana ya lo había pasado);
    lo que evita el doble crédito es ``ya_acreditados``, no la ventana. ``desde=None`` ⇒ no
    se acredita nada.

    ``splits`` (tarea 333) son ``{ticker: [(ex_date, ratio)]}`` de los ajustes **ya aplicados**
    a la posición —splits de la 262 y spin-offs de la 303, con su ``share_ratio``—: los fills
    son crudos y el calendario está ajustado, así que sin ellos un ex-date posterior a un split
    cobraría 1/N.
    """
    if not fills or desde is None:
        return []

    por_ticker: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for ticker, side, acciones, filled_at in fills:
        d = dia(filled_at)
        if d is None or not acciones:
            continue
        signo = 1.0 if str(side).upper() == "BUY" else -1.0
        por_ticker[str(ticker).upper()].append((d, signo * float(acciones)))

    pendientes: list[tuple[str, str, float, float]] = []
    for ticker, eventos in sorted(por_ticker.items()):
        for ex_date, monto in calendario.get(ticker, []):
            if ex_date == _SIN_DIVIDENDOS:
                # **Es redundante, y va dicho.** Probado por mutación: sacarlo no cambia
                # nada, y por DOS razones independientes — `"0000-00-00"` ordena antes
                # que cualquier fecha ISO, así que el filtro de ventana de abajo ya lo
                # descarta; y aunque entrara, ninguna compra puede ser anterior a esa
                # fecha, así que `acciones_antes_del_ex_date` daría 0. Se deja por
                # legibilidad —la fila necesita nombre donde se lee— pero un comentario
                # que dijera que ESTO es lo que la frena dirigiría mal a quien venga a
                # tocar el filtro. Es la misma conclusión a la que llegó la 221 con su
                # centinela, con una razón más.
                continue
            if not (desde < ex_date <= hasta):
                continue
            if (ticker, ex_date) in ya_acreditados:
                continue
            acciones = acciones_al_ex_date_con_splits(eventos, ex_date, (splits or {}).get(ticker, []))
            if acciones > 0 and monto:
                pendientes.append((ticker, ex_date, acciones, float(monto)))
    return pendientes


def acreditar_dividendos(session, acct, desde: str | None, hasta: str) -> list[dict]:
    """Acredita a ``acct.cash`` los dividendos de ``(desde, hasta]`` que el ledger no tiene.

    Devuelve una lista de dicts por crédito, para que el scan los pueda reportar. No
    pega a la red: el calendario tiene que estar en ``dividend_calendar_cache``, que el
    warm-up del scan puebla antes (``_warm_up_dividend_calendar``).

    Corre **adentro de la transacción del scan y antes de la estrategia**, a propósito:
    con ``equal_weight`` el target de cada compra es ``available / len(picks)`` y
    ``available`` sale de ``account.cash``, así que acreditar después dejaría la caja
    afuera del sizing del mismo scan — que es justamente lo que la opción (i) vino a
    cambiar.
    """
    from database.models import DividendCalendarCache
    from paper_trading.models import (
        PaperDividendCredit,
        PaperOrder,
        PaperSpinoffAdjustment,
        PaperSplitAdjustment,
    )

    fills = [
        (o.ticker, o.side, float(o.fill_shares or 0.0), o.filled_at)
        for o in session.query(PaperOrder)
        .filter(PaperOrder.account_id == acct.id)
        .filter(PaperOrder.status == "filled")
        .filter(PaperOrder.fill_shares.isnot(None))
        .all()
    ]
    if not fills:
        return []

    tickers = sorted({str(t).upper() for t, *_ in fills})
    calendario: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for fila in session.query(DividendCalendarCache).filter(DividendCalendarCache.ticker.in_(tickers)).all():
        calendario[str(fila.ticker).upper()].append((fila.ex_date, float(fila.amount or 0.0)))

    ya = {
        (str(c.ticker).upper(), c.ex_date)
        for c in session.query(PaperDividendCredit).filter(PaperDividendCredit.account_id == acct.id).all()
    }

    # Tarea 333: los ajustes ya aplicados, para llevar los fills crudos a la escala del calendario.
    splits: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for modelo, campo in ((PaperSplitAdjustment, "ratio"), (PaperSpinoffAdjustment, "share_ratio")):
        for a in session.query(modelo).filter(modelo.account_id == acct.id).all():
            splits[str(a.ticker).upper()].append((a.ex_date, float(getattr(a, campo))))

    creditos = []
    for ticker, ex_date, acciones, monto in creditos_pendientes(fills, calendario, ya, desde, hasta, splits):
        efectivo = acciones * monto
        acct.cash = float(acct.cash) + efectivo
        session.add(
            PaperDividendCredit(
                account_id=acct.id,
                ticker=ticker,
                ex_date=ex_date,
                shares=acciones,
                amount_per_share=monto,
                cash=efectivo,
                credited_at=utcnow_naive(),
            )
        )
        creditos.append({"ticker": ticker, "ex_date": ex_date, "shares": acciones, "cash": efectivo})
    return creditos
