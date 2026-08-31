"""E1a — replay del cap duro de exposición por nombre (anti-MLTX).

Contrafactual (ver `docs/exposure_cap_e1a_2026-07-01.md`): el P/L realizado de
un round-trip escala linealmente con el notional de la compra. Si la compra i
supera `cap_pct` del book (marcado a mercado en el momento de comprar), su P/L
realizado se multiplica por ``s_i = min(1, cap_pct·book_i / notional_i)``. Cash
liberado queda ocioso (conservador). Modelo de primer orden: el cap se evalúa
contra la trayectoria REAL del book (no se recalcula la trayectoria capada).

Read-only sobre un backup limpio (nunca la DB viva). Determinístico.

Uso:
    python scripts/run_exposure_cap_replay.py \
        --db backups/finanzias_2026-07-01_00-59-13_daily.db --account 1
"""

from __future__ import annotations

import argparse
import glob
import os
import sqlite3
from collections import defaultdict, deque

# Nombres de referencia del kill-criteria.
WORST_NAME = "MLTX"
BIG_WINNERS = ("MU", "TSLA", "AAPL", "TJX")


def replay_exposure_cap(orders: list[dict], cap_pct: float, init_capital: float = 0.0) -> dict:
    """Aplica el cap por nombre al P/L realizado, vía FIFO por lote.

    ``orders``: filas ``filled`` con ``ticker``/``side``/``fill_price``/
    ``fill_shares``, **ordenadas por fecha de fill**. ``init_capital`` es el cash
    inicial (denominador base del book). Devuelve el P/L realizado por nombre,
    actual (cap desactivado) y capado, más el book máximo por nombre.
    """
    cash = float(init_capital)
    shares: dict[str, float] = defaultdict(float)
    last_px: dict[str, float] = {}
    lots: dict[str, deque] = defaultdict(deque)  # ticker -> [ [sh, buy_px, scale], ... ]
    actual_pnl: dict[str, float] = defaultdict(float)
    capped_pnl: dict[str, float] = defaultdict(float)
    max_pct: dict[str, float] = defaultdict(float)

    for o in orders:
        t = o["ticker"]
        px = float(o["fill_price"] or 0.0)
        sh = float(o["fill_shares"] or 0.0)
        last_px[t] = px
        if o["side"] == "BUY":
            book = cash + sum(shares[k] * last_px.get(k, 0.0) for k in shares)
            notional = px * sh
            pct = notional / book if book > 0 else 0.0
            max_pct[t] = max(max_pct[t], pct)
            if cap_pct > 0 and book > 0 and notional > cap_pct * book:
                scale = cap_pct * book / notional
            else:
                scale = 1.0
            lots[t].append([sh, px, scale])
            cash -= notional
            shares[t] += sh
        else:  # SELL — consume lotes FIFO
            remaining = sh
            while remaining > 1e-9 and lots[t]:
                lot = lots[t][0]
                take = min(remaining, lot[0])
                gain = (px - lot[1]) * take
                actual_pnl[t] += gain
                capped_pnl[t] += gain * lot[2]
                lot[0] -= take
                remaining -= take
                if lot[0] <= 1e-9:
                    lots[t].popleft()
            cash += px * sh
            shares[t] -= sh

    return {
        "actual_pnl": dict(actual_pnl),
        "capped_pnl": dict(capped_pnl),
        "max_pct": dict(max_pct),
    }


def summarize(res: dict) -> dict:
    """Agrega totales y los focos del kill-criteria a partir de replay_exposure_cap."""
    a, c = res["actual_pnl"], res["capped_pnl"]
    total_a = sum(a.values())
    total_c = sum(c.values())
    big_a = sum(a.get(t, 0.0) for t in BIG_WINNERS)
    big_c = sum(c.get(t, 0.0) for t in BIG_WINNERS)
    worst_a = a.get(WORST_NAME, 0.0)
    worst_c = c.get(WORST_NAME, 0.0)
    return {
        "total_actual": total_a,
        "total_capped": total_c,
        "delta_total": total_c - total_a,
        "worst_actual": worst_a,
        "worst_capped": worst_c,
        "worst_reduction": (1 - worst_c / worst_a) if worst_a else 0.0,
        "big_actual": big_a,
        "big_capped": big_c,
        "big_retained": (big_c / big_a) if big_a else 1.0,
    }


def _load_orders(db: str, account: int) -> list[dict]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    init_cap = float(
        con.execute("SELECT initial_capital FROM paper_accounts WHERE id=?", (account,)).fetchone()[0]
    )
    rows = con.execute(
        "SELECT ticker, side, fill_price, fill_shares, filled_at FROM paper_orders "
        "WHERE account_id=? AND status='filled' AND filled_at IS NOT NULL "
        "ORDER BY filled_at",
        (account,),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows], init_cap


def main() -> None:
    ap = argparse.ArgumentParser(description="E1a exposure-cap replay")
    ap.add_argument("--db", default=None, help="ruta al backup (default: el más nuevo en backups/)")
    ap.add_argument("--account", type=int, default=1)
    ap.add_argument("--caps", default="0.20,0.25,0.33", help="grid de cap_pct, coma-separado")
    args = ap.parse_args()

    db = args.db or sorted(glob.glob("backups/*.db"), key=os.path.getmtime)[-1]
    orders, init_cap = _load_orders(db, args.account)
    caps = [float(x) for x in args.caps.split(",")]

    print(f"db: {db}")
    print(f"account={args.account}  initial_capital=${init_cap:,.0f}  n_filled={len(orders)}\n")

    base = summarize(replay_exposure_cap(orders, 0.0, init_cap))
    print(
        f"P/L realizado actual (sin cap): ${base['total_actual']:,.0f}  "
        f"(peor {WORST_NAME}: ${base['worst_actual']:,.0f} · "
        f"big-4 {'+'.join(BIG_WINNERS)}: ${base['big_actual']:,.0f})\n"
    )

    hdr = f"{'cap':>6} {'ΔP/L':>10} {'total':>10} {'worst_red':>10} {'big_ret':>9}"
    print(hdr)
    print("-" * len(hdr))
    for cap in caps:
        s = summarize(replay_exposure_cap(orders, cap, init_cap))
        d_pts = s["delta_total"] / init_cap * 100
        print(
            f"{cap:>6.0%} ${s['delta_total']:>+8,.0f} ${s['total_capped']:>+8,.0f} "
            f"{s['worst_reduction']:>9.0%} {s['big_retained']:>8.0%}  "
            f"(Δ={d_pts:+.2f} pts)"
        )


if __name__ == "__main__":
    main()
