"""Ajusta a mano una posición paper por un spin-off (tarea 303).

Cuándo
------
Cuando el scan avisa *«Yahoo reporta un factor … que no es un split simple»* (tarea 297) y el
comunicado de la empresa confirma un spin-off. El scan no lo ajusta solo porque el factor de
Yahoo no alcanza (tarea 298): ``q`` y ``r`` se toman **del comunicado** (8-K / nota de prensa).

Qué hace (ver ``paper_trading/spinoffs.py``)
--------------------------------------------
* Las acciones de antes del ex-date pasan a ``floor(acciones · q)``; la fracción se paga en caja
  al precio de la matriz.
* La escindida se acredita **como caja**: ``acciones_al_ex · r · precio_escindida``, sin comisión.
* El costo total baja en esa caja (devolución de capital); el máximo se divide por el factor.
* Todo queda en ``paper_spinoff_adjustments``, y el cuadre de la 266 se corre **antes** de
  commitear: si no cuadra, no se escribe nada.

Por default es **dry-run**: muestra el antes y el después y no escribe. Con ``--aplicar``
escribe. **Con la app cerrada** (regla de ``settings.json`` y de la DB: dos escritores a la vez
se pisan), y desde Windows, nunca desde un sandbox (regla 5 de ``CLAUDE.md``).

Ejemplo (HON 2026-06-29: Honeywell Aerospace 1 por cada 2 + reverse 1:2)
-------------------------------------------------------------------------
    python scripts/ajustar_spinoff.py --ticker HON --ex-date 2026-06-29 --q 0.5 --r 0.5 \\
        --precio-matriz <cierre de HON el 06-29> --precio-escindida <cierre de la escindida ese día>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ajusta a mano una posición paper por un spin-off (tarea 303).")
    p.add_argument("--account-id", type=int, default=None, help="default: la cuenta viva (is_active)")
    p.add_argument("--ticker", required=True, help="la matriz (la acción que está en cartera)")
    p.add_argument("--ex-date", required=True, help="YYYY-MM-DD, del comunicado")
    p.add_argument(
        "--q", type=float, required=True, help="acciones de la matriz por acción vieja (1 si no hubo split)"
    )
    p.add_argument("--r", type=float, required=True, help="acciones de la escindida por acción vieja")
    p.add_argument("--precio-matriz", type=float, required=True, help="cierre de la matriz el ex-date")
    p.add_argument(
        "--precio-escindida", type=float, required=True, help="cierre de la escindida su primer día"
    )
    p.add_argument("--escindida", default=None, help="ticker de la escindida (sólo para el registro)")
    p.add_argument("--aplicar", action="store_true", help="escribir (sin esto, dry-run)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    from database.models import get_session, init_db
    from paper_trading.account import live_account_id
    from paper_trading.cuadre import cuadrar_en_sesion
    from paper_trading.spinoffs import SpinoffNoAplicable, aplicar_spinoff

    init_db()
    account_id = args.account_id if args.account_id is not None else live_account_id()
    if account_id is None:
        print("No hay cuenta viva y no se pasó --account-id.")
        return 2

    s = get_session()
    try:
        antes = cuadrar_en_sesion(s, account_id)
        if antes:
            print("La cuenta YA no cuadra antes del ajuste; no se toca:")
            for pr in antes:
                print(f"  - {pr}")
            return 1
        try:
            aj = aplicar_spinoff(
                s,
                account_id,
                args.ticker,
                args.ex_date,
                args.q,
                args.r,
                args.precio_matriz,
                args.precio_escindida,
                child_ticker=args.escindida,
            )
        except SpinoffNoAplicable as e:
            print(f"No se ajusta: {e}")
            s.rollback()
            return 1

        hwm = (
            f"{aj.hwm_before:,.2f} → {aj.hwm_after:,.2f}"
            if aj.hwm_before is not None and aj.hwm_after is not None
            else "sin máximo"
        )
        print(f"{args.ticker.upper()} · ex-date {args.ex_date} · cuenta {account_id}")
        print(f"  acciones al ex-date: {aj.shares_at_ex:g} (× q={args.q:g})")
        print(f"  acciones:  {aj.shares_before:g} → {aj.shares_after:g}")
        print(f"  costo:     ${aj.avg_cost_before:,.4f} → ${aj.avg_cost_after:,.4f}")
        print(f"  máximo:    {hwm} (factor {aj.factor:.4f})")
        print(
            f"  caja:      +${aj.cash:,.2f} (escindida ${aj.cash_escindida:,.2f} + fracción ${aj.cash_fraccion:,.2f})"
        )

        despues = cuadrar_en_sesion(s, account_id)
        if despues:
            print("Después del ajuste la cuenta NO cuadra; no se escribe nada:")
            for pr in despues:
                print(f"  - {pr}")
            s.rollback()
            return 1
        print("  cuadre:    cuadra")

        if not args.aplicar:
            s.rollback()
            print("Dry-run: no se escribió nada. Para escribir, repetir con --aplicar (con la app cerrada).")
            return 0
        s.commit()
        print("Escrito.")
        return 0
    finally:
        s.close()


if __name__ == "__main__":
    sys.exit(main())
