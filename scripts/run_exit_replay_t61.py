"""
Runner T6.1 — exit replay sobre los ciclos reales (roadmap v3, Sprint 6).

Corre desde la raíz del repo (Windows, o sandbox con un backup de la DB):

    python scripts/run_exit_replay_t61.py [--db PATH] [--account 1]
        [--cap-days 20] [--json] [--out docs/exit_replay_t61_YYYY-MM-DD.md]

Variantes (ver analysis/exit_replay.py):
    a) confirm_next_scan  — SELL de señal ejecuta al scan siguiente
    b) score_threshold    — skip SELLs de señal con score ≥ 0.25
    c) min_holding_2 / 3  — SELL de señal diferido hasta edad ≥ 2/3 días hábiles

Kill criteria (upfront): ship si ΔP/L ≥ +2 pts (% capital inicial) y
max DD ajustado ≤ 1.5× el real. ATR params se leen de settings si está
disponible config.settings_manager; sino defaults del engine (14/2.0/4.0/trail).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import (
    AtrParams,
    Bar,
    ReplayReport,
    SellEvent,
    build_report,
    simulate_variant,
)
from scripts.baseline_metrics import fifo_match, load_fills, load_snapshots

DEFAULT_DB = "finanzias.db"


def _atr_params_from_settings() -> AtrParams:
    try:
        from config.settings_manager import settings  # type: ignore

        return AtrParams(
            period=max(2, int(settings.get("atr_period", 14))),
            stop_mult=max(0.0, float(settings.get("atr_stop_mult", 2.0))),
            tp_mult=max(0.0, float(settings.get("atr_tp_mult", 4.0))),
            trail_enabled=bool(settings.get("atr_trail_enabled", True)),
        )
    except Exception:
        return AtrParams()


def make_bar_loader(con: sqlite3.Connection):
    """bar_loader(ticker) -> list[Bar] desde historical_data_cache (sin pandas)."""
    cache: dict[str, list[Bar] | None] = {}

    def load(ticker: str) -> list[Bar] | None:
        if ticker in cache:
            return cache[ticker]
        row = con.execute(
            "SELECT data_json FROM historical_data_cache "
            "WHERE ticker = ? AND interval = '1d' "
            "ORDER BY fetched_at DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        bars: list[Bar] | None = None
        if row and row[0]:
            try:
                d = json.loads(row[0])
                names = [c[0] if isinstance(c, list) else c for c in d["columns"]]
                io_, ih, il, ic = (names.index(k) for k in ("Open", "High", "Low", "Close"))
                tmp: list[Bar] = []
                for ts, vals in zip(d["index"], d["data"], strict=False):
                    o, h, l, c = vals[io_], vals[ih], vals[il], vals[ic]
                    if None in (o, h, l, c) or float(c) <= 0:
                        continue
                    tmp.append((str(ts)[:10], float(o), float(h), float(l), float(c)))
                tmp.sort()
                bars = tmp or None
            except Exception:
                bars = None
        cache[ticker] = bars
        return bars

    return load


def build_sell_events(con: sqlite3.Connection, account_id: int) -> list[SellEvent]:
    """SELL fills reales + contexto FIFO (avg_cost, entry) + reason/score."""
    fills = load_fills(con, account_id)
    trades, _ = fifo_match(fills)
    sell_fills = [f for f in sorted(fills, key=lambda x: x.filled_at) if f.side == "SELL"]
    if len(trades) != len(sell_fills):
        raise RuntimeError(f"FIFO mismatch: {len(trades)} trades vs {len(sell_fills)} SELL fills")

    # reason/score por order_id
    meta: dict[str, Any] = {
        int(r[0]): (r[1], r[2])
        for r in con.execute(
            "SELECT id, reason, signal_score FROM paper_orders "
            "WHERE account_id = ? AND side = 'SELL' AND status = 'filled'",
            (account_id,),
        )
    }

    events: list[SellEvent] = []
    # strict=True: el cuerpo ya levanta RuntimeError si el orden FIFO no calza,
    # asi que un largo distinto tambien tiene que gritar en vez de truncar.
    for f, t in zip(sell_fills, trades, strict=True):
        if t.ticker != f.ticker:
            raise RuntimeError(f"FIFO order mismatch: {t.ticker} != {f.ticker}")
        reason, score = meta.get(f.order_id, ("", None))
        avg_cost = t.cost_basis / t.shares if t.shares > 0 else 0.0
        events.append(
            SellEvent(
                order_id=f.order_id,
                ticker=f.ticker,
                sell_date=f.filled_at.strftime("%Y-%m-%d"),
                sell_price=f.price,
                reason=reason or "",
                signal_score=float(score) if score is not None else None,
                shares=t.shares,
                avg_cost=avg_cost,
                entry_date=t.open_date.strftime("%Y-%m-%d"),
                # seed del HWM: aproximamos el fill del BUY con el costo por share
                # (incluye fees: diferencia ~bps, irrelevante para el trail)
                entry_price=avg_cost,
                sell_commission=f.commission,
                sell_slippage=f.slippage,
            )
        )
    return events


VARIANTS: list[tuple[str, str, dict]] = [
    ("a_confirm_next_scan", "confirm_next_scan", {}),
    ("b_score_threshold_025", "score_threshold", {"sell_threshold": 0.25}),
    ("c_min_holding_2d", "min_holding", {"min_holding_days": 2}),
    ("c_min_holding_3d", "min_holding", {"min_holding_days": 3}),
]


def run(db_path: Path, account_id: int, cap_days: int) -> tuple[list[ReplayReport], dict]:
    con = sqlite3.connect(str(db_path))
    try:
        events = build_sell_events(con, account_id)
        bar_loader = make_bar_loader(con)
        snaps = load_snapshots(con, account_id)
        real_curve = [(s.snapshot_at.strftime("%Y-%m-%d"), s.total_equity) for s in snaps]
        cap_row = con.execute(
            "SELECT initial_capital FROM paper_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        initial_capital = float(cap_row[0]) if cap_row else 50_000.0
        atr_p = _atr_params_from_settings()

        reports: list[ReplayReport] = []
        for label, variant, kw in VARIANTS:
            sims = simulate_variant(events, bar_loader, variant, cap_days=cap_days, atr_p=atr_p, **kw)
            rep = build_report(
                variant, sims, real_curve, initial_capital=initial_capital, bar_loader=bar_loader
            )
            rep.variant = label
            reports.append(rep)

        ctx: dict[str, Any] = {
            "db": str(db_path),
            "account_id": account_id,
            "n_sell_events": len(events),
            "n_signal_sells": sum(1 for e in events if e.is_signal_sell),
            "initial_capital": initial_capital,
            "cap_days": cap_days,
            "atr_params": vars(atr_p) if not hasattr(atr_p, "__dict__") else atr_p.__dict__,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return reports, ctx
    finally:
        con.close()


def _fmt_pct(x, d=2):
    return "—" if x is None else f"{100 * x:+.{d}f}%"


def render_table(reports: list[ReplayReport], ctx: dict) -> str:
    lines = [
        f"T6.1 exit replay — {ctx['n_sell_events']} SELLs "
        f"({ctx['n_signal_sells']} por señal) · cap {ctx['cap_days']}d · "
        f"capital {ctx['initial_capital']:,.0f}",
        "",
        f"{'variante':<24} {'mod':>4} {'ΔP/L $':>10} {'ΔP/L pts':>9} "
        f"{'DD real':>8} {'DD sim':>8} {'ratio':>6} {'extra ret':>10} "
        f"{'capture':>8} {'PASS':>5}",
    ]
    for r in reports:
        lines.append(
            f"{r.variant:<24} {r.n_modified:>4} {r.pnl_delta_total:>+10.2f} "
            f"{r.pnl_delta_pts:>+9.2f} {100 * r.max_dd_real:>7.2f}% "
            f"{100 * r.max_dd_sim:>7.2f}% {r.dd_ratio:>6.2f} "
            f"{_fmt_pct(r.median_extra_return):>10} "
            f"{_fmt_pct(r.capture_ratio_median, 0):>8} "
            f"{'✅' if r.passes_kill_criteria else '—':>5}"
        )
        if r.exits_by_reason:
            lines.append(f"{'':<24}   exits: {r.exits_by_reason}")
    lines.append("")
    lines.append("Kill criteria: ΔP/L ≥ +2.00 pts y DD ratio ≤ 1.50")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="T6.1 exit replay harness")
    p.add_argument("--db", default=None)
    p.add_argument("--account", type=int, default=1)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--json", action="store_true", help="dump JSON a stdout")
    args = p.parse_args(argv)

    db_path = Path(args.db) if args.db else _HERE.parent / DEFAULT_DB
    if not db_path.exists():
        print(f"db no encontrada: {db_path}", file=sys.stderr)
        return 1

    reports, ctx = run(db_path, args.account, args.cap_days)

    if args.json:
        print(
            json.dumps(
                {"context": ctx, "reports": [r.to_dict() for r in reports]},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    else:
        print(render_table(reports, ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
