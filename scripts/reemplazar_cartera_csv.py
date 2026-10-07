"""Reconstruye una cartera real desde el CSV de Yahoo Finance, con compras y ventas (tarea 324).

Cuándo
------
Cuando la cartera de la app quedó atrás de la de Yahoo. «Mis Acciones» tenía siete posiciones
con una sola compra cada una, y seis de ellas con la fecha de la importación del 2026-04-14
(tarea 312). El CSV de Chapa del 2026-10-07 trae la historia completa: 20 operaciones, con las
ventas y el split de NVDA.

Qué hace
--------
* Lee el CSV con ``data.csv_importer``: ``Transaction Type`` da compra o venta, y una fila sin
  lotes (un ticker de la cartera sin operaciones) se omite.
* Arma cada ticker con ``database.lotes``: el par «Stock Split» de Yahoo pasa a ser un split
  (cantidades ajustadas, realizada cero) y los lotes abiertos salen por FIFO.
* Con ``--aplicar`` hace un backup, **borra** las posiciones de la cartera y la reconstruye.
  Empresa y sector se conservan de los tickers que ya estaban. Si un ticker no cierra (vende
  más de lo que tiene), no toca nada.

Por default es **dry-run**: muestra lo que quedaría y no escribe. Con ``--aplicar`` escribe,
**con la app cerrada** (dos escritores a la vez se pisan) y desde Windows, nunca desde un
sandbox (regla 5 de ``CLAUDE.md``).

    python scripts/reemplazar_cartera_csv.py portfolio.csv
    python scripts/reemplazar_cartera_csv.py portfolio.csv --aplicar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reconstruye una cartera real desde un CSV de Yahoo (tarea 324).")
    p.add_argument("csv", help="el export de la cartera de Yahoo Finance")
    p.add_argument("--cartera", default="Mis Acciones", help="nombre de la cartera (default: Mis Acciones)")
    p.add_argument("--aplicar", action="store_true", help="escribir (sin esto, dry-run)")
    return p


def armar_desde_csv(path: str):
    """``(armadas, resultado del parser)``."""
    from data.csv_importer import parse_csv_file
    from database.lotes import Movimiento, armar_posiciones

    res = parse_csv_file(path)
    movs: dict[str, list] = {}
    for r in res.rows:
        if r.trade_date is None:
            raise SystemExit(f"{r.ticker}: una operación sin fecha; corregí el CSV antes de reemplazar")
        movs.setdefault(r.ticker, []).append(
            Movimiento(r.trade_date, r.tipo, r.quantity, r.buy_price, r.commission, r.notes)
        )
    return armar_posiciones(movs), res


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    armadas, res = armar_desde_csv(args.csv)

    for w in res.warnings:
        print(f"aviso: {w}")
    for s in res.skipped:
        print(f"omitida línea {s['line']}: {s['reason']}")
    print(f"\n{'Ticker':6} {'Estado':8} {'Cant.':>10} {'Costo/acc':>10} {'Realizada':>11}  Notas")
    for a in armadas:
        lb = a.libro
        estado = "ERROR" if lb.error else ("abierta" if lb.abierta else "cerrada")
        notas = "; ".join(
            [f"split {s.ratio:g}:1 del {s.fecha}" for s in a.splits]
            + a.avisos
            + ([lb.error] if lb.error else [])
        )
        print(
            f"{a.ticker:6} {estado:8} {lb.cantidad:>10.4f} {lb.costo_promedio:>10.4f} {lb.realizado:>11,.2f}  {notas}"
        )
    if any(a.libro.error for a in armadas):
        print("\nHay tickers que no cierran: no se escribe nada.")
        return 1
    if not args.aplicar:
        print("\nDry-run: no se escribió nada. Con --aplicar se reemplaza la cartera.")
        return 0

    from database.backup import backup_database
    from database.cartera_real import reemplazar_cartera
    from database.models import Portfolio, init_db, session_scope

    init_db()
    copia = backup_database(reason="pre-reemplazar-cartera-csv")
    if copia is None:
        print("No se pudo hacer el backup: no se escribe nada.")
        return 1
    print(f"\nbackup: {copia}")
    with session_scope() as s:
        pf = s.query(Portfolio).filter(Portfolio.name == args.cartera).first()
        if pf is None:
            print(f"No existe la cartera '{args.cartera}'.")
            return 1
        out = reemplazar_cartera(s, pf.id, armadas, nota="Importado desde CSV (tarea 324)")
    print(f"borradas {out['borradas']}, creadas {out['nuevas']}, errores {out['errores'] or 'ninguno'}")
    return 0 if not out["errores"] else 1


if __name__ == "__main__":
    sys.exit(main())
