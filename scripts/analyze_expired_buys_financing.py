"""
Validación — aprobación encadenada de BUY/SELL en manual (tarea ② · N2).

Pregunta: de las BUYs que **expiraron** en la cuenta manual, ¿cuántas se
habrían concretado bajo *aprobación encadenada* (la BUY no expira mientras
haya una SELL pendiente del mismo scan que, al aprobarse, libera el cash)?

Contrafactual (data-driven, read-only sobre un backup):
  Para cada BUY expirada, se clasifica la CAUSA (de ``notes``) y se busca si en
  el mismo scan (mismo minuto de ``created_at``) hubo una/varias SELL cuyos
  proceeds reales cubrirían el ``target_dollars`` de la BUY. Si las cubren, esa
  entrada era **recuperable**: con encadenado la BUY queda pending hasta que se
  apruebe la SELL y después se llena (``_fill_trade`` topa en cash real → nunca
  sobre-apalanca).

Solo las expiraciones por ``cash o shares insuficientes`` están en scope: las de
``approved-limbo`` (bug T7.2, ya resuelto) y ``sin precio`` (robustez de datos,
bugs B1/B3) tienen otra causa y NO las arregla esta tarea.

Uso:
    python scripts/analyze_expired_buys_financing.py [--db PATH] [--account 1]
        [--json]

No escribe la DB.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

DEFAULT_DB = "finanzias.db"

CAUSE_CASH = "cash o shares insuficientes"
CAUSE_LIMBO = "approved-limbo"
CAUSE_NOPRICE = "sin precio"


def _scan_bucket(ts: str | None) -> str:
    """Agrupa por scan: minuto de created_at (las órdenes de un scan comparten
    el timestamp de creación al minuto)."""
    return (ts or "")[:16]


def _cause(notes: str | None) -> str:
    n = notes or ""
    if CAUSE_CASH in n:
        return "cash_insuficiente"
    if CAUSE_LIMBO in n:
        return "approved_limbo"
    if CAUSE_NOPRICE in n:
        return "sin_precio"
    return "otro"


def run(db_path: Path, account_id: int):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        c = con.cursor()
        exp = c.execute(
            "SELECT id,ticker,target_dollars,created_at,notes FROM paper_orders "
            "WHERE account_id=? AND side='BUY' AND status='expired' ORDER BY created_at",
            (account_id,),
        ).fetchall()
        sells = c.execute(
            "SELECT id,ticker,status,fill_price,fill_shares,created_at,reason "
            "FROM paper_orders WHERE account_id=? AND side='SELL' ORDER BY created_at",
            (account_id,),
        ).fetchall()
        sells_by_bucket: dict[str, list] = defaultdict(list)
        for s in sells:
            sells_by_bucket[_scan_bucket(s[5])].append(s)

        rows = []
        for oid, tk, td, cr, notes in exp:
            cause = _cause(notes)
            cosells = sells_by_bucket.get(_scan_bucket(cr), [])
            proceeds = sum((s[3] or 0.0) * (s[4] or 0.0) for s in cosells)
            need = float(td or 0.0)
            # Con encadenado la BUY se llena a min(target, cash_tras_la_SELL): es
            # una entrada REAL (no perdida) siempre que la SELL libere cash. El
            # target se sizeo como cash+proceeds → proceeds suele quedar apenas
            # por debajo del target; igual la entrada se concreta (algo menor).
            recoverable = cause == "cash_insuficiente" and proceeds > 0.0
            fully = recoverable and proceeds >= need > 0
            rows.append({
                "order_id": oid, "ticker": tk, "need": need, "cause": cause,
                "cosell_proceeds": proceeds, "recuperable": recoverable,
                "financiamiento_total": fully,
                "cosell_tickers": [s[1] for s in cosells],
            })

        in_scope = [r for r in rows if r["cause"] == "cash_insuficiente"]
        recoverable = [r for r in in_scope if r["recuperable"]]
        full = [r for r in recoverable if r["financiamiento_total"]]
        agg = {
            "n_expired_total": len(rows),
            "n_cause_cash": len(in_scope),
            "n_cause_limbo": sum(1 for r in rows if r["cause"] == "approved_limbo"),
            "n_cause_noprice": sum(1 for r in rows if r["cause"] == "sin_precio"),
            "n_recuperables_por_encadenado": len(recoverable),
            "n_financiamiento_total": len(full),
            "n_recuperable_parcial": len(recoverable) - len(full),
            "n_cash_sin_financiamiento": len(in_scope) - len(recoverable),
            "dollars_recuperables": sum(r["need"] for r in recoverable),
        }
        ctx = {
            "db": str(db_path), "account_id": account_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return rows, agg, ctx
    finally:
        con.close()


def render(rows, agg, ctx) -> str:
    lines = [
        f"Aprobación encadenada — BUYs expiradas en cuenta {ctx['account_id']}",
        "",
        f"{'ticker':<7} {'need$':>10} {'causa':<16} {'co-SELL$':>10} {'recup?':>7}  co-sells",
    ]
    for r in rows:
        if r["cause"] != "cash_insuficiente":
            tag = "fuera"
        elif r["financiamiento_total"]:
            tag = "SÍ-tot"
        elif r["recuperable"]:
            tag = "SÍ-parc"
        else:
            tag = "—"
        lines.append(
            f"{r['ticker']:<7} {r['need']:>10,.0f} {r['cause']:<16} "
            f"{r['cosell_proceeds']:>10,.0f} {tag:>7}  "
            f"{','.join(r['cosell_tickers']) or '(ninguna)'}"
        )
    lines += [
        "",
        f"Expiradas total: {agg['n_expired_total']}  "
        f"(cash={agg['n_cause_cash']}, limbo={agg['n_cause_limbo']} [T7.2, fuera], "
        f"sin_precio={agg['n_cause_noprice']} [datos, fuera])",
        f"Recuperables por encadenado: {agg['n_recuperables_por_encadenado']}/"
        f"{agg['n_cause_cash']} de las de cash "
        f"(total={agg['n_financiamiento_total']}, parcial={agg['n_recuperable_parcial']}; "
        f"~${agg['dollars_recuperables']:,.0f} de entradas)  ·  "
        f"sin financiamiento (siguen expirando, correcto): "
        f"{agg['n_cash_sin_financiamiento']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Análisis de BUYs expiradas vs encadenado")
    p.add_argument("--db", default=None)
    p.add_argument("--account", type=int, default=1)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    db_path = Path(args.db) if args.db else _HERE.parent / DEFAULT_DB
    if not db_path.exists():
        print(f"db no encontrada: {db_path}", file=sys.stderr)
        return 1

    rows, agg, ctx = run(db_path, args.account)
    if args.json:
        print(json.dumps({"context": ctx, "aggregate": agg, "rows": rows},
                         ensure_ascii=False, indent=2, default=str))
    else:
        print(render(rows, agg, ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
