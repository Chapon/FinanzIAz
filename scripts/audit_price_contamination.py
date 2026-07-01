"""
Auditoría de precios contaminados (backlog E5).

Barre la DB viva por órdenes ``filled`` cuyo ``fill_price`` difiera del close
diario cacheado en la fecha del fill por más de una banda (default 50%). Es la
misma higiene que ``scripts/run_atr_stop_recalib.partition_atr_events`` y el
guard prospectivo de ``data/yahoo_finance`` (``is_price_out_of_band``), aplicada
retroactivamente a lo ya ejecutado.

Motivación: el ciclo **KLAC** 2026-06-01/05 se abrió y cerró a ~$1.940 cuando el
precio real era ~$194 (~10× por basura de Yahoo). Ese notional inflado contamina
el peso en el portfolio, el DD, el ADV y hasta la muestra de salidas ATR (A1).

    # Detectar (read-only, no toca nada):
    python scripts/audit_price_contamination.py [--db finanzias.db] [--band 0.5] [--json]

    # Remediar (VOID del round-trip contaminado + revertir su efecto de caja):
    python scripts/audit_price_contamination.py --apply --yes

``--apply`` solo anula round-trips **cerrados** (el ticker no tiene posición
abierta): marca las órdenes ``status='voided'`` y revierte su efecto neto de caja
en la cuenta, para que Métricas y los harness midan sobre datos limpios. Hace un
backup de la DB en ``backups/`` antes de escribir. Si un ticker contaminado tiene
posición abierta, lo reporta y NO lo toca (requiere manejo manual).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from data.yahoo_finance import is_price_out_of_band  # noqa: E402

DEFAULT_DB = "finanzias.db"
DEFAULT_BAND = 0.5


@dataclass
class ContamOrder:
    """Una orden filled cuyo precio quedó fuera de banda vs el histórico."""

    order_id: int
    account_id: int
    ticker: str
    side: str
    fill_price: float
    fill_shares: float
    commission: float
    filled_at: str
    reason: str
    ref_close: float
    deviation: float  # |fill/ref − 1|, fracción


def _load_closes_by_date(con: sqlite3.Connection, ticker: str) -> dict[str, float]:
    """Mapa día→close del frame diario cacheado más fresco (o {} si no hay)."""
    row = con.execute(
        "SELECT data_json FROM historical_data_cache "
        "WHERE ticker = ? AND interval = '1d' ORDER BY fetched_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row:
        return {}
    try:
        d = json.loads(row[0])
        cols = d["columns"]
        if "Close" not in cols:
            return {}
        ci = cols.index("Close")
        out: dict[str, float] = {}
        for ts, vals in zip(d["index"], d["data"]):
            day = str(ts)[:10]
            close = vals[ci]
            if close is not None and close > 0:
                out[day] = float(close)
        return out
    except Exception:
        return {}


def _close_on_or_before(closes: dict[str, float], day: str) -> float | None:
    """Close en ``day`` o el más reciente anterior — ancla de escala del día."""
    keys = sorted(k for k in closes if k <= day)
    return closes[keys[-1]] if keys else None


def find_contaminated(
    con: sqlite3.Connection, *, band: float = DEFAULT_BAND, account_id: int | None = None
) -> list[ContamOrder]:
    """Órdenes filled con precio fuera de banda vs el close cacheado del día."""
    q = (
        "SELECT id, account_id, ticker, side, fill_price, fill_shares, "
        "COALESCE(commission_paid, 0), filled_at, COALESCE(reason, '') "
        "FROM paper_orders WHERE status = 'filled' AND fill_price IS NOT NULL"
    )
    params: list = []
    if account_id is not None:
        q += " AND account_id = ?"
        params.append(account_id)
    q += " ORDER BY ticker, filled_at"

    closes_cache: dict[str, dict[str, float]] = {}
    out: list[ContamOrder] = []
    for oid, acc, tk, side, fp, fs, comm, fat, reason in con.execute(q, params):
        if tk not in closes_cache:
            closes_cache[tk] = _load_closes_by_date(con, tk)
        ref = _close_on_or_before(closes_cache[tk], str(fat)[:10])
        if ref is None:
            continue  # sin referencia → fail-open (no podemos juzgar la escala)
        if is_price_out_of_band(fp, ref, band):
            out.append(
                ContamOrder(
                    order_id=int(oid),
                    account_id=int(acc),
                    ticker=str(tk),
                    side=str(side),
                    fill_price=float(fp),
                    fill_shares=float(fs or 0.0),
                    commission=float(comm or 0.0),
                    filled_at=str(fat),
                    reason=str(reason),
                    ref_close=float(ref),
                    deviation=abs(float(fp) / float(ref) - 1.0),
                )
            )
    return out


def _has_open_position(con: sqlite3.Connection, account_id: int, ticker: str) -> bool:
    row = con.execute(
        "SELECT COALESCE(SUM(shares), 0) FROM paper_positions "
        "WHERE account_id = ? AND ticker = ?",
        (account_id, ticker),
    ).fetchone()
    return bool(row and row[0] and row[0] > 1e-9)


def _net_cash_effect(orders: list[ContamOrder]) -> float:
    """Efecto neto que estas órdenes tuvieron sobre la caja de la cuenta.

    BUY bajó la caja en (notional + comisión); SELL la subió en (notional −
    comisión). Revertir el round-trip = restar este neto de ``cash``.
    """
    net = 0.0
    for o in orders:
        notional = o.fill_price * o.fill_shares
        if o.side == "BUY":
            net -= notional + o.commission
        else:  # SELL
            net += notional - o.commission
    return net


def apply_void(
    con: sqlite3.Connection, orders: list[ContamOrder]
) -> tuple[list[ContamOrder], list[ContamOrder]]:
    """Anula los round-trips **cerrados** contaminados y revierte su caja.

    Devuelve (voided, skipped). ``skipped`` = órdenes de tickers con posición
    abierta (no se tocan: requieren manejo manual). No commitea — el caller
    decide (permite dry-run con rollback).
    """
    voided: list[ContamOrder] = []
    skipped: list[ContamOrder] = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for o in orders:
        if _has_open_position(con, o.account_id, o.ticker):
            skipped.append(o)
        else:
            voided.append(o)

    # Agrupar por cuenta para revertir la caja una vez por cuenta.
    by_acct: dict[int, list[ContamOrder]] = {}
    for o in voided:
        by_acct.setdefault(o.account_id, []).append(o)
    for acct_id, acc_orders in by_acct.items():
        net = _net_cash_effect(acc_orders)
        con.execute(
            "UPDATE paper_accounts SET cash = cash - ? WHERE id = ?", (net, acct_id)
        )
        for o in acc_orders:
            note = (
                f"\n[E5 audit {stamp}] anulada: precio {o.fill_price:.2f} fuera de "
                f"banda vs close {o.ref_close:.2f} ({o.deviation:+.0%}); caja revertida."
            )
            con.execute(
                "UPDATE paper_orders SET status = 'voided', "
                "notes = COALESCE(notes, '') || ? WHERE id = ?",
                (note, o.order_id),
            )
    return voided, skipped


def _backup_db(db_path: Path) -> Path:
    backups = _HERE.parent / "backups"
    backups.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = backups / f"{db_path.stem}_pre_e5_{stamp}.db"
    shutil.copy2(db_path, dest)
    return dest


def _print_report(orders: list[ContamOrder], band: float) -> None:
    if not orders:
        print(f"✓ DB limpia: ningún fill fuera de banda (>{band:.0%} vs close del día).")
        return
    print(f"⚠ {len(orders)} orden(es) contaminada(s) (>{band:.0%} vs close del día):\n")
    for o in orders:
        notional = o.fill_price * o.fill_shares
        print(
            f"  #{o.order_id} acct={o.account_id} {o.side:4s} {o.ticker:6s} "
            f"{o.fill_shares:g}×{o.fill_price:.2f} = ${notional:,.0f}  "
            f"(close {o.filled_at[:10]} ≈ ${o.ref_close:.2f}, desvío {o.deviation:+.0%})"
        )
        if o.reason:
            print(f"       reason: {o.reason[:70]}")


def run(
    db_path: Path, *, band: float, account_id: int | None, apply: bool, yes: bool, as_json: bool
) -> int:
    con = sqlite3.connect(str(db_path))
    try:
        orders = find_contaminated(con, band=band, account_id=account_id)

        if as_json:
            payload = {
                "db": str(db_path),
                "band": band,
                "contaminated": [asdict(o) for o in orders],
            }
            print(json.dumps(payload, indent=2, default=str))
        else:
            _print_report(orders, band)

        if not apply or not orders:
            return 0

        # Dry-run del efecto para mostrarlo antes de escribir.
        net = _net_cash_effect([o for o in orders])
        if not yes:
            print(
                f"\n(dry-run) --apply revertiría la caja en {-net:+.2f} y marcaría "
                f"{len(orders)} orden(es) como 'voided'. Reejecutá con --yes para aplicar."
            )
            return 0

        backup = _backup_db(db_path)
        print(f"\nBackup: {backup}")
        voided, skipped = apply_void(con, orders)
        con.commit()
        print(f"✓ Anuladas {len(voided)} orden(es); caja revertida.")
        for o in voided:
            print(f"    voided #{o.order_id} {o.side} {o.ticker}")
        if skipped:
            print(
                f"⚠ {len(skipped)} orden(es) NO tocadas (posición abierta, manejo manual):"
            )
            for o in skipped:
                print(f"    skip  #{o.order_id} {o.side} {o.ticker}")
        return 0
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Auditoría de precios contaminados (E5).")
    ap.add_argument("--db", default=DEFAULT_DB, help="Ruta a la DB (default finanzias.db).")
    ap.add_argument("--band", type=float, default=DEFAULT_BAND, help="Banda relativa (default 0.5).")
    ap.add_argument("--account", type=int, default=None, help="Filtrar por account_id.")
    ap.add_argument("--apply", action="store_true", help="Anular round-trips contaminados.")
    ap.add_argument("--yes", action="store_true", help="Confirmar la escritura (con --apply).")
    ap.add_argument("--json", action="store_true", help="Salida JSON.")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: no existe la DB {db_path}", file=sys.stderr)
        return 2
    return run(
        db_path,
        band=args.band,
        account_id=args.account,
        apply=args.apply,
        yes=args.yes,
        as_json=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
