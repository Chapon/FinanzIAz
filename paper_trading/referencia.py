"""La curva de referencia que no elige nada (tarea 377).

Una cuenta paper se compara contra **su mismo universo sin elegir**: los tickers de su watchlist
en partes iguales, comprados el día del alta y rebalanceados a partes iguales el primer día hábil
de cada mes, con los mismos costos que paga el motor. Es lo que contesta *«¿la selección de la app
suma o resta?»*: el 2026-10-20, Sim Segundo daba +3,2% y su universo mantenido sin elegir +5,2%
(``docs/rendimiento_app_vs_cartera_2026-10-20.md``).

Es **display-only** (regla 3): no escribe la DB y no toca el motor.

Lo que **no** es, y el rótulo lo tiene que decir:

- **No es point-in-time:** el universo es la watchlist de **hoy**. Un ticker agregado en septiembre
  entra desde el alta, como si hubiera estado.
- **Acciones fraccionarias:** el motor compra enteras; acá el peso es exacto. La diferencia es
  de redondeo, no de política.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import numpy as np

# Un ticker cuyo último cierre quedó más de estas ruedas atrás del más reciente se da por
# muerto (deslistado, fusión): se mantiene a su último cierre y se nombra, en vez de cortar la
# curva de todos en su fecha. La vara es la de los frames atrasados de ``parquet_cache``
# (``FRAME_MAX_ATRASO_RUEDAS``), la misma que usa la 369.
MAX_ATRASO_RUEDAS = 5

# ``costo(side, acciones, precio) -> dólares`` de un fill. ``None`` ⇒ sin costos.
Costo = Callable[[str, float, float], float]


@dataclass
class CurvaReferencia:
    """La curva y lo que quedó afuera o quieto, para rotularlo."""

    serie: list[tuple[date, float]] = field(default_factory=list)
    # Sin cierre en el día de arranque (o sin ningún cierre): no entran.
    sin_historia: list[str] = field(default_factory=list)
    # ``(ticker, último cierre)``: dejaron de cotizar y se mantienen a ese precio.
    quietos: list[tuple[str, date]] = field(default_factory=list)
    costos: float = 0.0
    n: int = 0


def _ruedas_entre(a: date, b: date) -> int:
    return int(np.busday_count(a, b))


def curva_sin_elegir(
    cierres: dict[str, list[tuple[date, float]]],
    capital: float,
    desde: date,
    costo: Costo | None = None,
    *,
    rebalancear: bool = True,
) -> CurvaReferencia:
    """Partes iguales desde ``desde``, rebalanceadas el primer día de cada mes. Pura.

    ``cierres`` es ``{ticker: [(día, cierre)]}`` ascendente (``cierres_del_cache``). El calendario
    es la unión de los días con cierre, desde el último ``<= desde`` (el precio que había el día
    del alta). Ese día se compra ``capital / n`` de cada uno al cierre. El primer día de cada mes nuevo se lleva todo
    de vuelta a ``valor / n``. El costo de cada compra o venta se descuenta del valor, repartido
    en partes iguales. La curva termina en el último día que tienen **todos** los tickers vivos,
    para que ninguno quede congelado sin que se diga. Los que dejaron de cotizar
    (``MAX_ATRASO_RUEDAS``) se mantienen a su último cierre y vuelven en ``quietos``.

    El costo del rebalanceo se calcula sobre el objetivo **antes** de descontarlo. La diferencia
    con iterar hasta el punto fijo es costo × costo, despreciable a estas tasas.
    """
    out = CurvaReferencia()
    if capital <= 0:
        return out
    validas = {t: [(d, float(c)) for d, c in s if c and c > 0] for t, s in cierres.items()}
    con_algo = {t: s for t, s in validas.items() if s}
    out.sin_historia = sorted(t for t in cierres if not validas.get(t))
    if not con_algo:
        return out

    # El arranque es el último cierre que había el día del alta —lo que puede comprar la cuenta
    # ese día—, no el primero posterior: la cuenta 2 se dio de alta un feriado (Juneteenth,
    # 2026-06-19) y compró a los cierres del 18. Sin cierre anterior, el primero que haya.
    todos = sorted({d for s in con_algo.values() for d, _ in s})
    previos = [d for d in todos if d <= desde]
    d0 = previos[-1] if previos else next((d for d in todos if d >= desde), None)
    if d0 is None:
        return out
    calendario = [d for d in todos if d >= d0]
    # Entra quien tiene precio el día de arranque: su cierre de ese día o el último anterior.
    entran = {t: s for t, s in con_algo.items() if s[0][0] <= d0}
    out.sin_historia = sorted(set(out.sin_historia) | (set(con_algo) - set(entran)))
    if not entran:
        return out

    ultimo = {t: s[-1][0] for t, s in entran.items()}
    mas_nuevo = max(ultimo.values())
    muertos = {t for t, u in ultimo.items() if _ruedas_entre(u, mas_nuevo) > MAX_ATRASO_RUEDAS}
    vivos = [t for t in entran if t not in muertos]
    fin = min(ultimo[t] for t in vivos) if vivos else mas_nuevo
    out.quietos = sorted((t, ultimo[t]) for t in muertos)

    tickers = sorted(entran)
    n = len(tickers)
    out.n = n
    idx = {t: 0 for t in tickers}
    precio: dict[str, float] = {}

    def _avanzar(d: date) -> None:
        for t in tickers:
            s = entran[t]
            i = idx[t]
            while i < len(s) and s[i][0] <= d:
                precio[t] = s[i][1]
                i += 1
            idx[t] = i

    def _costo(side: str, acciones: float, p: float) -> float:
        if costo is None or acciones <= 1e-12:
            return 0.0
        return float(costo(side, acciones, p))

    acciones: dict[str, float] = {}
    mes_previo = None
    for d in calendario:
        if d > fin:
            break
        _avanzar(d)
        if not acciones:
            gasto = sum(_costo("BUY", capital / n / precio[t], precio[t]) for t in tickers)
            out.costos += gasto
            neto = capital - gasto
            acciones = {t: neto / n / precio[t] for t in tickers}
        elif rebalancear and (d.year, d.month) != mes_previo:
            valor = sum(acciones[t] * precio[t] for t in tickers)
            gasto = 0.0
            for t in tickers:
                delta = valor / n / precio[t] - acciones[t]
                gasto += _costo("BUY" if delta > 0 else "SELL", abs(delta), precio[t])
            out.costos += gasto
            neto = valor - gasto
            acciones = {t: neto / n / precio[t] for t in tickers}
        mes_previo = (d.year, d.month)
        out.serie.append((d, sum(acciones[t] * precio[t] for t in tickers)))
    return out


def costo_del_motor(account_id: int) -> Costo:
    """El costo de un fill como lo cobra el motor (``engine._fill_trade``): la comisión del
    plan activo —o la tasa de la cuenta en ``legacy``— más el slippage de la cuenta."""
    from config.settings_manager import settings
    from paper_trading.account import get_account
    from paper_trading.costs import commission_from_legacy, get_active_commission_model

    acct = get_account(account_id)
    if acct is None:
        raise ValueError(f"no existe la cuenta {account_id}")
    plan = str(settings.get("ibkr_commission_plan", "tiered")).lower()
    comision = commission_from_legacy(acct.commission) if plan == "legacy" else get_active_commission_model()
    slip = float(acct.slippage or 0.0)

    def _costo(side: str, acciones: float, precio: float) -> float:
        return comision.cost(side=side, shares=acciones, price=precio) + acciones * precio * slip

    return _costo


def referencia_de_cuenta(account_id: int, cierres: dict | None = None) -> CurvaReferencia:
    """La referencia de una cuenta paper: su watchlist de hoy, su capital y su alta (día de NY)."""
    from database.cartera_real import cierres_del_cache
    from paper_trading.account import get_account, get_watchlist

    acct = get_account(account_id)
    if acct is None:
        return CurvaReferencia()
    tickers = get_watchlist(account_id)
    if cierres is None:
        cierres = cierres_del_cache(tickers)
    return curva_sin_elegir(
        {t: cierres.get(t, []) for t in tickers},
        float(acct.initial_capital),
        dia_de_alta(acct.created_at),
        costo_del_motor(account_id),
    )


def dia_de_alta(creada) -> date:
    """El día de Nueva York en que se creó la cuenta (``created_at`` es UTC naive)."""
    from datetime import timezone

    from data.yahoo_finance import market_timezone

    tz = market_timezone()
    if tz is None:
        return creada.date()
    return creada.replace(tzinfo=timezone.utc).astimezone(tz).date()
