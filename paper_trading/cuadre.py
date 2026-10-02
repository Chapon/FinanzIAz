"""Cuadre de caja y posiciones contra las órdenes, en cada scan (tarea 266).

Qué faltaba
-----------
``reconcile_account`` sólo expira órdenes pendientes. Que la caja sea **capital inicial +
ventas − compras − comisiones + dividendos**, y que las acciones de cada posición sean las de
sus fills, no lo verificaba nadie: el 2026-10-02 cuadraba al centavo en las dos cuentas
(``docs/auditoria_cuentas_2026-10-02.md`` [G-2]), pero la caja ya se corrigió a mano una vez
(las KLAC anuladas de E5) y un descuadre futuro —un fill mal registrado, una edición a mano,
un bug— no avisaría.

Dos trampas del instrumento, que el cuadre de la auditoría ya encontró
----------------------------------------------------------------------
* El **slippage va dentro del** ``fill_price``: restar además ``slippage_cost`` descuadra una
  cuenta sana (+$412 y +$374 en las cuentas 1 y 2).
* Las órdenes **anuladas** (``voided``) no cuentan: sólo ``status = 'filled'``.

Y una tercera, de la 262: las acciones de una posición que atravesó un split no son la suma de
sus fills. Se reconstruyen con los splits del ledger (``paper_split_adjustments``), con la misma
función que usa el ajuste.
"""

from __future__ import annotations

from collections import defaultdict

from config.logging_config import get_logger
from paper_trading.dividends import dia

log = get_logger(__name__)

_TOL_ACCIONES = 1e-6
# Un centavo por fill: el redondeo de cada fill es de centavos, y con cientos de fills un
# cero exacto sería exigir de más.
_TOL_CAJA_POR_FILL = 0.01


def descuadres(
    initial_capital: float,
    cash: float,
    fills: list[tuple[str, str, float, float, float, object]],
    dividendos: float,
    splits: dict[tuple[str, str], float],
    posiciones: dict[str, float],
) -> list[str]:
    """Qué no cuadra, en texto. ``[]`` = cuadra. **Pura.**

    ``fills`` son ``(ticker, side, acciones, precio, comisión, filled_at)`` de las órdenes
    ``filled``; ``splits`` es ``{(ticker, ex_date): ratio}`` del ledger; ``posiciones`` son las
    acciones de hoy por ticker.
    """
    from paper_trading.splits import _acciones_sin

    esperada = float(initial_capital) + float(dividendos)
    por_ticker: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for ticker, side, acciones, precio, comision, filled_at in fills:
        notional = float(acciones) * float(precio)
        if str(side).upper() == "BUY":
            esperada -= notional + float(comision or 0.0)
            signo = 1.0
        else:
            esperada += notional - float(comision or 0.0)
            signo = -1.0
        d = dia(filled_at)
        if d is not None:
            por_ticker[str(ticker).upper()].append((d, signo * float(acciones)))

    problemas: list[str] = []
    tol = _TOL_CAJA_POR_FILL * max(1, len(fills))
    if abs(float(cash) - esperada) > tol:
        problemas.append(
            f"caja ${float(cash):,.2f} y las órdenes dan ${esperada:,.2f} (diferencia ${float(cash) - esperada:+,.2f})"
        )

    for ticker in sorted(set(por_ticker) | set(posiciones)):
        splits_t = sorted((ex, r) for (t, ex), r in splits.items() if t == ticker)
        esperadas = _acciones_sin(sorted(por_ticker.get(ticker, [])), splits_t, set(splits), ticker)
        reales = float(posiciones.get(ticker, 0.0))
        if abs(esperadas - reales) > _TOL_ACCIONES * max(1.0, abs(reales)):
            problemas.append(
                f"{ticker}: la posición tiene {reales:g} acciones y las órdenes dan {esperadas:g}"
            )
    return problemas


def cuadrar_cuenta(account_id: int) -> list[str] | None:
    """Lee la cuenta en una sesión propia y devuelve sus descuadres.

    ``[]`` = cuadra; ``None`` = **no se pudo cuadrar** (se loguea). No es lo mismo, y la
    primera versión los confundía: con la DB sin migrar (sin ``paper_split_adjustments``) el
    error devolvía ``[]`` y el cuadre decía «cuadra» sin haber mirado nada.
    """
    try:
        from database.models import session_scope
        from paper_trading.models import (
            PaperAccount,
            PaperDividendCredit,
            PaperOrder,
            PaperPosition,
            PaperSplitAdjustment,
        )

        with session_scope() as s:
            acct = s.query(PaperAccount).filter(PaperAccount.id == account_id).one_or_none()
            if acct is None:
                return None
            fills = [
                (
                    o.ticker,
                    o.side,
                    float(o.fill_shares),
                    float(o.fill_price),
                    float(o.commission_paid or 0.0),
                    o.filled_at,
                )
                for o in s.query(PaperOrder)
                .filter(PaperOrder.account_id == account_id)
                .filter(PaperOrder.status == "filled")
                .filter(PaperOrder.fill_shares.isnot(None))
                .filter(PaperOrder.fill_price.isnot(None))
                .all()
            ]
            divs = sum(
                float(c.cash or 0.0)
                for c in s.query(PaperDividendCredit)
                .filter(PaperDividendCredit.account_id == account_id)
                .all()
            )
            splits = {
                (str(a.ticker).upper(), a.ex_date): float(a.ratio)
                for a in s.query(PaperSplitAdjustment)
                .filter(PaperSplitAdjustment.account_id == account_id)
                .all()
            }
            posiciones = {
                str(p.ticker).upper(): float(p.shares)
                for p in s.query(PaperPosition).filter(PaperPosition.account_id == account_id).all()
                if float(p.shares or 0.0) > _TOL_ACCIONES
            }
            return descuadres(float(acct.initial_capital), float(acct.cash), fills, divs, splits, posiciones)
    except Exception:
        log.exception("cuadre: no se pudo cuadrar la cuenta %s", account_id)
        return None


# Último descuadre avisado por cuenta: se avisa una vez por descuadre DISTINTO, y al volver a
# cuadrar se rearma. Un descuadre persiste entre scans; 40 Slacks iguales por día no sirven.
_avisado: dict[int, tuple[str, ...]] = {}
_notifier = None  # inyectable en tests; None → integrations.slack.default_notifier


def chequear_y_avisar(account_id: int, account_name: str) -> list[str]:
    """Cuadra la cuenta; si no cuadra, ERROR al log siempre y Slack una vez por descuadre."""
    problemas = cuadrar_cuenta(account_id)
    if problemas is None:
        return ["no se pudo cuadrar la cuenta (ver el log)"]
    if not problemas:
        _avisado.pop(account_id, None)
        return []
    for pr in problemas:
        log.error("Cuadre de %s (cuenta %d): %s", account_name, account_id, pr)
    firma = tuple(problemas)
    if _avisado.get(account_id) != firma:
        _avisado[account_id] = firma
        try:
            from config.settings_manager import settings

            if bool(settings.get("slack_data_outage_enabled", True)):
                from integrations.slack import default_notifier

                texto = (
                    f"🧮 *FinanzIAs · {account_name} no cuadra* — "
                    + "; ".join(problemas[:5])
                    + (f" (y {len(problemas) - 5} más)" if len(problemas) > 5 else "")
                    + ". Revisar las órdenes de la cuenta."
                )
                (_notifier or default_notifier)(texto)
        except Exception:
            log.debug("Slack del cuadre falló (fail-open)", exc_info=True)
    return [f"no cuadra: {p}" for p in problemas]
