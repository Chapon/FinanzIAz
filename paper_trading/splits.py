"""Ajuste de las posiciones abiertas por split (tarea 262).

Qué pasaba
----------
El motor no miraba splits. Un split N:1 de una acción en cartera dejaba ``shares``,
``avg_cost`` y ``high_water_mark`` en la escala vieja; el guard de precio aceptaba el
precio post-split (al tercer rechazo, o antes si el cache ya se había rebajado) y desde
ese scan ``compute_equity`` valuaba las acciones viejas al precio nuevo: la equity caía
(1−1/N) de golpe. Si el máximo había superado alguna vez al costo, el trailing —armado con
una ATR N veces más chica— vendía en ese mismo scan; si no, vendía la señal después. La
pérdida realizada era de, por ejemplo, el 50% en un 2:1 o el 96% en un 25:1, y no existía.
El caso no es teórico: BKNG partió 25:1 el 2026-04-06. Ver ``docs/auditoria_cuentas_2026-10-02.md`` [G-1].

Qué hace
--------
Antes de la equity, de los stops y de la estrategia, el scan reconstruye la historia de
cada posición abierta —sus fills, en orden, con los splits intercalados— y aplica los
splits **plausibles** (``2:1``, ``3:2``, ``1:10``; no el ``2,793`` fantasma de AVB) que la
posición atravesó y que el ledger todavía no tiene:

* las acciones que había **antes** del ex-date se multiplican por N; las compradas después
  ya están en la escala nueva y no se tocan;
* el **costo total** se conserva, así que ``avg_cost`` se recalcula;
* el ``high_water_mark`` es un precio, así que se divide por N.

Por qué no hay ventana, a diferencia de los dividendos
-------------------------------------------------------
Los dividendos se acreditan en ``(último scan, hoy]``. Acá eso sería un agujero: si
yfinance publica el split con un día de demora, la ventana ya pasó y el ajuste no se
aplicaría nunca, y un ajuste que falta **vende**. Alcanza con el ledger para no aplicar
dos veces, y con exigir que la posición haya tenido acciones **antes** del ex-date para
no tocar splits viejos de un ticker comprado después.

La protección: si la historia no reproduce la posición, no se toca
-------------------------------------------------------------------
Las acciones que resultan de los fills con los splits **ya aplicados** tienen que ser las
que la posición tiene hoy. Si no coinciden —un fill a mano, un ledger borrado, un split que
el calendario cambió— el ajuste no se aplica y se avisa: ajustar a ciegas puede duplicar
acciones, que es peor que el defecto que esto arregla.

Nada de esto pega a la red: los eventos llegan como parámetro. El engine los lee del memo
de ``data.yahoo_finance.get_split_events``, que el warm-up del scan llena antes.
"""

from __future__ import annotations

from dataclasses import dataclass

from database.models import utcnow_naive
from paper_trading.dividends import dia

# Tolerancia para comparar acciones reconstruidas contra las de la posición. Las acciones
# son enteras desde la T-shares-enteras, pero el ledger y los ratios fraccionarios (3:2)
# producen floats.
_TOL_ACCIONES = 1e-6

# Los denominadores de un split real: 2:1, 3:2, 5:4, 1:10. Mismo criterio que
# `data/yahoo_finance.is_plausible_split`; se duplica a propósito —`paper_trading/` no
# depende de `data/yahoo_finance`, que arrastra yfinance y la red— y un test fija que los
# dos digan lo mismo.
_DENOMINADORES = (1, 2, 3, 4, 5, 8, 10)


def es_split_plausible(ratio: float | None) -> bool:
    """True si ``ratio`` es una fracción simple, como un split real."""
    if ratio is None:
        return False
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return False
    if not (r > 0) or r == 1.0 or r != r or r == float("inf"):
        return False
    for den in _DENOMINADORES:
        num = r * den
        if abs(num - round(num)) <= 1e-6 and 1 <= round(num) <= 50:
            return True
    return False


@dataclass(frozen=True)
class AjustePendiente:
    ticker: str
    ex_date: str
    ratio: float
    acciones_antes: float  # las de la posición hoy
    acciones_despues: float


@dataclass(frozen=True)
class PosicionInconsistente:
    ticker: str
    esperadas: float
    reales: float


def ajustes_pendientes(
    fills: list[tuple[str, str, float, str]],
    eventos: dict[str, list[tuple[str, float]]],
    ya_aplicados: set[tuple[str, str]],
    posiciones: dict[str, float],
    hoy: str,
) -> tuple[list[AjustePendiente], list[PosicionInconsistente]]:
    """Qué splits falta aplicar a las posiciones abiertas, y cuáles no se pueden aplicar.

    **Función pura.** ``fills`` son ``(ticker, side, acciones, filled_at)`` de la cuenta;
    ``eventos`` es ``{ticker: [(ex_date, ratio), ...]}``; ``ya_aplicados`` son los
    ``(ticker, ex_date)`` del ledger; ``posiciones`` son las acciones de hoy por ticker.

    Convención de fechas, la misma que los dividendos (``acciones_antes_del_ex_date``): un
    fill del **mismo día** del ex-date ya es post-split.
    """
    pendientes: list[AjustePendiente] = []
    inconsistentes: list[PosicionInconsistente] = []
    por_ticker: dict[str, list[tuple[str, float]]] = {}
    for ticker, side, acciones, filled_at in fills:
        d = dia(filled_at)
        if d is None or not acciones:
            continue
        signo = 1.0 if str(side).upper() == "BUY" else -1.0
        por_ticker.setdefault(str(ticker).upper(), []).append((d, signo * float(acciones)))

    for ticker, reales in sorted(posiciones.items()):
        if reales <= _TOL_ACCIONES:
            continue
        fills_t = sorted(por_ticker.get(ticker, []))
        splits_t = sorted(
            (ex, float(r)) for ex, r in eventos.get(ticker, []) if ex and ex <= hoy and es_split_plausible(r)
        )
        if not splits_t:
            continue

        # Línea de tiempo: en cada fecha, primero los splits de ese día (un fill del día
        # del ex-date ya es post-split) y después los fills.
        corriente = 0.0
        nuevos: list[tuple[str, float, float]] = []  # (ex_date, ratio, acciones a esa fecha)
        i = 0
        for ex, ratio in splits_t:
            while i < len(fills_t) and fills_t[i][0] < ex:
                corriente += fills_t[i][1]
                i += 1
            if corriente <= _TOL_ACCIONES:
                continue  # no había acciones antes del ex-date: el split no la toca
            if (ticker, ex) in ya_aplicados:
                corriente *= ratio
            else:
                nuevos.append((ex, ratio, corriente))
                corriente *= ratio
        while i < len(fills_t):
            corriente += fills_t[i][1]
            i += 1

        if not nuevos:
            continue
        # Lo que la posición debería tener HOY si los splits nuevos todavía no se aplicaron.
        esperadas_sin_nuevos = _acciones_sin(fills_t, splits_t, ya_aplicados, ticker)
        if abs(esperadas_sin_nuevos - reales) > _TOL_ACCIONES * max(1.0, reales):
            inconsistentes.append(PosicionInconsistente(ticker, esperadas_sin_nuevos, reales))
            continue
        acciones = reales
        for ex, ratio, a_esa_fecha in nuevos:
            # Las acciones de antes del ex-date pasan a valer `ratio`; las demás, igual.
            despues = acciones + a_esa_fecha * (ratio - 1.0)
            pendientes.append(AjustePendiente(ticker, ex, ratio, acciones, despues))
            acciones = despues
    return pendientes, inconsistentes


def _acciones_sin(
    fills_t: list[tuple[str, float]],
    splits_t: list[tuple[str, float]],
    ya_aplicados: set[tuple[str, str]],
    ticker: str,
) -> float:
    """Acciones de hoy según los fills y **sólo** los splits que el ledger ya aplicó."""
    corriente = 0.0
    i = 0
    for ex, ratio in splits_t:
        while i < len(fills_t) and fills_t[i][0] < ex:
            corriente += fills_t[i][1]
            i += 1
        if corriente > _TOL_ACCIONES and (ticker, ex) in ya_aplicados:
            corriente *= ratio
    while i < len(fills_t):
        corriente += fills_t[i][1]
        i += 1
    return corriente


def aplicar_splits(
    session, acct, positions: list, eventos: dict[str, list[tuple[str, float]]]
) -> tuple[list[dict], list[str]]:
    """Ajusta las posiciones abiertas de ``acct`` y escribe el ledger.

    Devuelve ``(ajustes, avisos)``: un dict por ajuste aplicado, para reportar, y un texto
    por posición que no se pudo ajustar porque su historia no la reproduce.

    Corre **adentro de la transacción del scan**, antes de la equity, de los stops ATR y
    del máximo, sobre los mismos objetos ``PaperPosition`` que el scan usa después.
    """
    from paper_trading.models import PaperOrder, PaperSplitAdjustment

    abiertas = {str(p.ticker).upper(): p for p in positions if float(p.shares or 0.0) > _TOL_ACCIONES}
    if not abiertas or not any(eventos.get(t) for t in abiertas):
        return [], []

    fills = [
        (o.ticker, o.side, float(o.fill_shares or 0.0), o.filled_at)
        for o in session.query(PaperOrder)
        .filter(PaperOrder.account_id == acct.id)
        .filter(PaperOrder.status == "filled")
        .filter(PaperOrder.fill_shares.isnot(None))
        .filter(PaperOrder.ticker.in_(sorted(abiertas)))
        .all()
    ]
    ya = {
        (str(a.ticker).upper(), a.ex_date)
        for a in session.query(PaperSplitAdjustment).filter(PaperSplitAdjustment.account_id == acct.id).all()
    }
    pendientes, inconsistentes = ajustes_pendientes(
        fills,
        {t: eventos.get(t, []) for t in abiertas},
        ya,
        {t: float(p.shares) for t, p in abiertas.items()},
        dia(utcnow_naive()) or "",
    )

    ajustes: list[dict] = []
    for aj in pendientes:
        pos = abiertas[aj.ticker]
        costo_total = float(pos.shares) * float(pos.avg_cost)
        avg_antes = float(pos.avg_cost)
        hwm_antes = float(pos.high_water_mark) if pos.high_water_mark is not None else None
        pos.shares = aj.acciones_despues
        pos.avg_cost = costo_total / aj.acciones_despues
        pos.high_water_mark = (hwm_antes / aj.ratio) if hwm_antes is not None else None
        pos.updated_at = utcnow_naive()
        session.add(
            PaperSplitAdjustment(
                account_id=acct.id,
                ticker=aj.ticker,
                ex_date=aj.ex_date,
                ratio=aj.ratio,
                shares_before=aj.acciones_antes,
                shares_after=aj.acciones_despues,
                avg_cost_before=avg_antes,
                avg_cost_after=float(pos.avg_cost),
                hwm_before=hwm_antes,
                hwm_after=pos.high_water_mark,
                applied_at=utcnow_naive(),
            )
        )
        ajustes.append(
            {
                "ticker": aj.ticker,
                "ex_date": aj.ex_date,
                "ratio": aj.ratio,
                "shares_before": aj.acciones_antes,
                "shares_after": aj.acciones_despues,
                "avg_cost_after": float(pos.avg_cost),
            }
        )
    avisos = [
        f"{x.ticker}: hay un split sin aplicar pero la historia de órdenes da {x.esperadas:g} "
        f"acciones y la posición tiene {x.reales:g} — NO se ajusta; revisar a mano"
        for x in inconsistentes
    ]
    return ajustes, avisos
