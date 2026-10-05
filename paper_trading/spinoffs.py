"""Ajuste a mano de una posición abierta por un spin-off (tarea 303).

Qué faltaba
-----------
El scan no ajusta spin-offs: la 298 mostró que el factor que publica Yahoo no alcanza (HON
2026 queda a 1,9–3,2 pp de la medida independiente, y un factor solo no separa el ``2,793``
podrido de AVB del ``2,39`` real de DuPont). El aviso de la 297 mandaba entonces a *«revisar
a mano»*, y no había ninguna forma de hacerlo sin editar ``finanzias.db`` —y el cuadre de la
266 habría marcado la edición como descuadre—.

Qué hace
--------
Con ``q`` (acciones de la matriz por acción vieja) y ``r`` (de la escindida) **tomados del
comunicado**, y los precios del primer día de las dos:

* **acciones:** las que había **antes** del ex-date pasan a ``floor(acciones · q)``; las
  compradas desde el ex-date ya están en la escala nueva y no se tocan. La fracción se paga
  en caja al precio de la matriz, como hace un broker (*cash in lieu*);
* **caja:** la escindida se acredita **como caja** al precio de su primer día —decisión de
  Chapa (2026-10-05), la misma opción que los dividendos de la 222—, sin comisión;
* **costo:** el costo total baja en la caja recibida (devolución de capital). Así la ganancia
  no realizada de la posición queda **idéntica** a la de antes del evento y no aparece una
  ganancia realizada sin una orden detrás. Si el costo quedara en cero o menos, no se ajusta;
* **máximo:** es un precio, así que se divide por el factor ``q + r·P_escindida/P_matriz``
  (el mismo que publica Yahoo, pero calculado con los datos del comunicado).

Todo queda en ``paper_spinoff_adjustments``: el cuadre suma su caja y reconstruye las
acciones con ``share_ratio``; el ajuste de splits lo cuenta como evento ya aplicado; y el aviso
de la 297 deja de repetirse para ese ex-date.

La protección, la misma que la de los splits: si la historia de órdenes (con los splits y
spin-offs ya registrados) no reproduce las acciones de la posición, no se toca.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from database.models import utcnow_naive
from paper_trading.dividends import dia

_TOL_ACCIONES = 1e-6


class SpinoffNoAplicable(ValueError):
    """El ajuste no se puede hacer; el mensaje dice por qué."""


@dataclass(frozen=True)
class AjusteSpinoff:
    shares_at_ex: float
    share_ratio: float
    shares_before: float
    shares_after: float
    avg_cost_before: float
    avg_cost_after: float
    hwm_before: float | None
    hwm_after: float | None
    cash_escindida: float
    cash_fraccion: float
    factor: float

    @property
    def cash(self) -> float:
        return self.cash_escindida + self.cash_fraccion


def acciones_a_la_fecha(
    fills_t: list[tuple[str, float]], aplicados_t: list[tuple[str, float]], fecha: str | None
) -> float:
    """Acciones según los fills y los eventos ya aplicados, **antes** de ``fecha``.

    ``fecha=None`` = hoy (todo). Misma convención que los splits: un evento del día ``d`` va
    antes que los fills de ese día, y un fill del día del ex-date ya es posterior.
    """
    corriente = 0.0
    i = 0
    for ex, ratio in sorted(aplicados_t):
        if fecha is not None and ex >= fecha:
            break
        while i < len(fills_t) and fills_t[i][0] < ex:
            corriente += fills_t[i][1]
            i += 1
        if corriente > _TOL_ACCIONES:
            corriente *= ratio
    while i < len(fills_t) and (fecha is None or fills_t[i][0] < fecha):
        corriente += fills_t[i][1]
        i += 1
    return corriente


def calcular_ajuste(
    shares: float,
    avg_cost: float,
    hwm: float | None,
    shares_at_ex: float,
    q: float,
    r: float,
    precio_matriz: float,
    precio_escindida: float,
) -> AjusteSpinoff:
    """El ajuste, sin tocar nada. **Pura.** Levanta ``SpinoffNoAplicable`` si no se puede."""
    for nombre, v in (("q", q), ("precio de la matriz", precio_matriz)):
        if not (v > 0) or math.isinf(v):
            raise SpinoffNoAplicable(f"{nombre} tiene que ser > 0 (vino {v!r})")
    for nombre, v in (("r", r), ("precio de la escindida", precio_escindida)):
        if not (v >= 0) or math.isinf(v):
            raise SpinoffNoAplicable(f"{nombre} tiene que ser >= 0 (vino {v!r})")
    if r == 0 and q == 1:
        raise SpinoffNoAplicable("q=1 y r=0 no es un evento: no hay nada que ajustar")
    if shares_at_ex <= _TOL_ACCIONES:
        raise SpinoffNoAplicable("la posición no tenía acciones antes del ex-date: el evento no la toca")
    if shares_at_ex > shares + _TOL_ACCIONES:
        raise SpinoffNoAplicable(
            f"la posición tenía {shares_at_ex:g} acciones al ex-date y hoy tiene {shares:g}: "
            "hubo ventas después del evento y el ajuste ya no se puede reconstruir"
        )

    nuevas_al_ex = math.floor(shares_at_ex * q + 1e-9)
    if nuevas_al_ex <= 0:
        raise SpinoffNoAplicable(
            f"{shares_at_ex:g} acciones × q={q:g} no llega a una acción entera de la matriz"
        )
    fraccion = shares_at_ex * q - nuevas_al_ex
    cash_fraccion = fraccion * precio_matriz if fraccion > _TOL_ACCIONES else 0.0
    cash_escindida = shares_at_ex * r * precio_escindida
    cash = cash_escindida + cash_fraccion

    shares_after = shares - shares_at_ex + nuevas_al_ex
    costo_total = shares * avg_cost
    costo_nuevo = costo_total - cash
    if costo_nuevo <= 0:
        raise SpinoffNoAplicable(
            f"la caja del evento (${cash:,.2f}) supera el costo de la posición (${costo_total:,.2f}): "
            "con devolución de capital el costo quedaría en cero o negativo"
        )
    factor = q + r * precio_escindida / precio_matriz
    return AjusteSpinoff(
        shares_at_ex=shares_at_ex,
        share_ratio=nuevas_al_ex / shares_at_ex,
        shares_before=shares,
        shares_after=float(shares_after),
        avg_cost_before=avg_cost,
        avg_cost_after=costo_nuevo / shares_after,
        hwm_before=hwm,
        hwm_after=(hwm / factor) if hwm is not None else None,
        cash_escindida=cash_escindida,
        cash_fraccion=cash_fraccion,
        factor=factor,
    )


def eventos_aplicados(session, account_id: int) -> dict[tuple[str, str], float]:
    """``{(ticker, ex_date): ratio de acciones}`` de los splits y spin-offs ya registrados."""
    from paper_trading.models import PaperSpinoffAdjustment, PaperSplitAdjustment

    out = {
        (str(a.ticker).upper(), a.ex_date): float(a.ratio)
        for a in session.query(PaperSplitAdjustment).filter(PaperSplitAdjustment.account_id == account_id)
    }
    for a in session.query(PaperSpinoffAdjustment).filter(PaperSpinoffAdjustment.account_id == account_id):
        out[(str(a.ticker).upper(), a.ex_date)] = float(a.share_ratio)
    return out


def aplicar_spinoff(
    session,
    account_id: int,
    ticker: str,
    ex_date: str,
    q: float,
    r: float,
    precio_matriz: float,
    precio_escindida: float,
    child_ticker: str | None = None,
) -> AjusteSpinoff:
    """Ajusta la posición, acredita la caja y escribe el ledger, **en la sesión dada**.

    No commitea: el script decide (``--aplicar``) o hace rollback (el default). Levanta
    ``SpinoffNoAplicable`` sin tocar nada si el ajuste no se puede hacer.
    """
    from paper_trading.models import (
        PaperAccount,
        PaperOrder,
        PaperPosition,
        PaperSpinoffAdjustment,
    )

    ticker = ticker.upper()
    hoy = dia(utcnow_naive()) or ""
    if not ex_date or len(ex_date) != 10 or ex_date > hoy:
        raise SpinoffNoAplicable(f"ex-date inválido o futuro: {ex_date!r} (hoy es {hoy})")
    acct = session.query(PaperAccount).filter(PaperAccount.id == account_id).one_or_none()
    if acct is None:
        raise SpinoffNoAplicable(f"no existe la cuenta {account_id}")
    pos = (
        session.query(PaperPosition)
        .filter(PaperPosition.account_id == account_id, PaperPosition.ticker == ticker)
        .one_or_none()
    )
    if pos is None or float(pos.shares or 0.0) <= _TOL_ACCIONES:
        raise SpinoffNoAplicable(f"la cuenta {account_id} no tiene una posición abierta en {ticker}")

    aplicados = eventos_aplicados(session, account_id)
    if (ticker, ex_date) in aplicados:
        raise SpinoffNoAplicable(f"{ticker} ya tiene un split o spin-off registrado el {ex_date}")

    fills_t = sorted(
        (d, (1.0 if str(o.side).upper() == "BUY" else -1.0) * float(o.fill_shares))
        for o in session.query(PaperOrder)
        .filter(PaperOrder.account_id == account_id, PaperOrder.ticker == ticker)
        .filter(PaperOrder.status == "filled", PaperOrder.fill_shares.isnot(None))
        if (d := dia(o.filled_at)) is not None
    )
    aplicados_t = sorted((ex, ratio) for (t, ex), ratio in aplicados.items() if t == ticker)
    reales = float(pos.shares)
    esperadas = acciones_a_la_fecha(fills_t, aplicados_t, None)
    if abs(esperadas - reales) > _TOL_ACCIONES * max(1.0, reales):
        raise SpinoffNoAplicable(
            f"la historia de órdenes da {esperadas:g} acciones de {ticker} y la posición tiene "
            f"{reales:g}: no se ajusta a ciegas"
        )
    if any(ex > ex_date for ex, _ in aplicados_t):
        raise SpinoffNoAplicable(
            f"{ticker} tiene un evento registrado después del {ex_date}: aplicarlo fuera de orden "
            "dejaría mal las acciones"
        )
    if any(d >= ex_date and a < 0 for d, a in fills_t):
        raise SpinoffNoAplicable(
            f"hubo ventas de {ticker} desde el {ex_date}: no se sabe cuántas de las acciones "
            "vendidas eran de antes del evento"
        )
    al_ex = acciones_a_la_fecha(fills_t, aplicados_t, ex_date)

    aj = calcular_ajuste(
        reales,
        float(pos.avg_cost),
        float(pos.high_water_mark) if pos.high_water_mark is not None else None,
        al_ex,
        q,
        r,
        precio_matriz,
        precio_escindida,
    )
    pos.shares = aj.shares_after
    pos.avg_cost = aj.avg_cost_after
    pos.high_water_mark = aj.hwm_after
    pos.updated_at = utcnow_naive()
    acct.cash = float(acct.cash) + aj.cash
    session.add(
        PaperSpinoffAdjustment(
            account_id=account_id,
            ticker=ticker,
            ex_date=ex_date,
            child_ticker=(child_ticker or None) and child_ticker.upper(),
            q=q,
            r=r,
            parent_price=precio_matriz,
            child_price=precio_escindida,
            shares_at_ex=aj.shares_at_ex,
            share_ratio=aj.share_ratio,
            shares_before=aj.shares_before,
            shares_after=aj.shares_after,
            avg_cost_before=aj.avg_cost_before,
            avg_cost_after=aj.avg_cost_after,
            hwm_before=aj.hwm_before,
            hwm_after=aj.hwm_after,
            cash=aj.cash,
            applied_at=utcnow_naive(),
        )
    )
    session.flush()
    return aj
