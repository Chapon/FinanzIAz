"""
Recalibración / continuidad de los stops ATR — backlog A1.

Replay de los ciclos que en la realidad salieron por un exit ATR (``reason``
empieza con ``atr_``), re-evaluados bajo variantes de parámetro con **fills
modelados** (gap/touch), para responder: ¿los stops ATR (mult 2.0) agregan
valor, y a qué múltiplo? Contrafactual + kill-criteria pre-registrados en
``docs/atr_stop_recalib_2026-06-30.md``.

    python scripts/run_atr_stop_recalib.py [--db PATH] [--account 1]
        [--cap-days 20] [--detail] [--json]

Higiene de datos: se excluyen ciclos con precio corrupto (fill que difiere del
close del cache en el día del exit por > ``--contam-tol``, default 0.5) — p.ej.
KLAC 2026-06-05 (~10× por precio basura de Yahoo). Se reportan aparte.

Kill criteria (upfront): se shipea la variante que mejore el ΔP/L total
≥ +2 pts (% sobre capital inicial) sin empeorar el max DD ajustado > 1.5×.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import (
    AtrParams,
    ReplayReport,
    SellEvent,
    SimExit,
    _idx_on_or_after,
    build_report,
    replay_atr_recalib,
)
from scripts.baseline_metrics import load_snapshots
from scripts.run_exit_replay_t61 import (
    build_sell_events,
    make_bar_loader,
)

DEFAULT_DB = "finanzias.db"

# Variantes: stop igual o más laxo que el baseline (ver doc — el contrafactual
# solo es honesto para mult ≥ baseline o sin stops).
VARIANTS: list[tuple[str, AtrParams]] = [
    ("baseline_2.0", AtrParams(stop_mult=2.0)),
    ("no_stops", AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False)),
    ("mult_2.5", AtrParams(stop_mult=2.5)),
    ("mult_3.0", AtrParams(stop_mult=3.0)),
]


def _close_on_sell_day(ev: SellEvent, bars) -> float | None:
    if not bars:
        return None
    d_idx = _idx_on_or_after(bars, ev.sell_date)
    if d_idx >= len(bars) or bars[d_idx][0] != ev.sell_date:
        return None
    return bars[d_idx][4]


def partition_atr_events(
    events: list[SellEvent], bar_loader, contam_tol: float
) -> tuple[list[SellEvent], list[tuple[SellEvent, str]]]:
    """Separa los exits ATR limpios de los contaminados/sin-datos.

    Contaminado = el fill real difiere del close del cache en el día del exit
    por > ``contam_tol`` (split / precio basura no conciliado).
    """
    clean: list[SellEvent] = []
    excluded: list[tuple[SellEvent, str]] = []
    for ev in events:
        if not (ev.reason or "").startswith("atr_"):
            continue
        bars = bar_loader(ev.ticker)
        close = _close_on_sell_day(ev, bars)
        if close is None or close <= 0:
            excluded.append((ev, "sin barra del día del exit"))
            continue
        dev = abs(ev.sell_price / close - 1.0)
        if dev > contam_tol:
            excluded.append((ev, f"precio corrupto (fill/close−1={dev:+.1%})"))
            continue
        clean.append(ev)
    return clean, excluded


def run(db_path: Path, account_id: int, cap_days: int, contam_tol: float):
    con = sqlite3.connect(str(db_path))
    try:
        all_events = build_sell_events(con, account_id)
        bar_loader = make_bar_loader(con)
        clean, excluded = partition_atr_events(all_events, bar_loader, contam_tol)

        snaps = load_snapshots(con, account_id)
        real_curve = [(s.snapshot_at.strftime("%Y-%m-%d"), s.total_equity) for s in snaps]
        cap_row = con.execute(
            "SELECT initial_capital FROM paper_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        initial_capital = float(cap_row[0]) if cap_row else 50_000.0

        reports: list[ReplayReport] = []
        sims_by_variant: dict[str, list[SimExit]] = {}
        for label, atr_p in VARIANTS:
            sims: list[SimExit] = []
            for ev in clean:
                bars = bar_loader(ev.ticker)
                sim = replay_atr_recalib(ev, bars, cap_days=cap_days, atr_p=atr_p)
                if sim is None:  # sin día de continuación; cuenta como real (sin cambio)
                    sim = SimExit(
                        event=ev,
                        modified=False,
                        exit_date=ev.sell_date,
                        exit_price=ev.sell_price,
                        exit_reason=ev.reason,
                        pnl_sim=ev.pnl_real,
                    )
                sims.append(sim)
            rep = build_report(
                label, sims, real_curve, initial_capital=initial_capital, bar_loader=bar_loader
            )
            reports.append(rep)
            sims_by_variant[label] = sims

        ctx = {
            "db": str(db_path),
            "account_id": account_id,
            "n_atr_exits_total": sum(1 for e in all_events if (e.reason or "").startswith("atr_")),
            "n_clean": len(clean),
            "n_excluded": len(excluded),
            "excluded": [(e.ticker, e.sell_date, why) for e, why in excluded],
            "initial_capital": initial_capital,
            "cap_days": cap_days,
            "contam_tol": contam_tol,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return reports, sims_by_variant, ctx
    finally:
        con.close()


def render(reports, sims_by_variant, ctx, detail: bool) -> str:
    lines = [
        f"Recalibración stops ATR — {ctx['n_atr_exits_total']} exits ATR "
        f"({ctx['n_clean']} limpios, {ctx['n_excluded']} excluidos) · "
        f"cap {ctx['cap_days']}d · capital {ctx['initial_capital']:,.0f}",
        "",
    ]
    if ctx["excluded"]:
        lines.append("Excluidos por higiene de datos:")
        for tk, sd, why in ctx["excluded"]:
            lines.append(f"  - {tk} {sd}: {why}")
        lines.append("")
    lines.append(
        f"{'variante':<14} {'mod':>4} {'ΔP/L $':>10} {'ΔP/L pts':>9} "
        f"{'DD real':>8} {'DD sim':>8} {'ratio':>6} {'PASS':>5}"
    )
    cap = ctx["initial_capital"]
    for r in reports:
        lines.append(
            f"{r.variant:<14} {r.n_modified:>4} {r.pnl_delta_total:>+10.2f} "
            f"{r.pnl_delta_pts:>+9.2f} {100 * r.max_dd_real:>7.2f}% "
            f"{100 * r.max_dd_sim:>7.2f}% {r.dd_ratio:>6.2f} "
            f"{'✅' if r.passes_kill_criteria else '—':>5}"
        )
        if r.exits_by_reason:
            lines.append(f"{'':<14}   exits: {r.exits_by_reason}")
        # Sensibilidad: ΔP/L pts sacando el ciclo de mayor |aporte| (leave-one-out).
        # Con n chico, si el veredicto depende de 1 ciclo no es robusto.
        deltas = [s.pnl_delta for s in sims_by_variant[r.variant]]
        if len(deltas) > 1 and cap > 0:
            top = max(deltas, key=abs)
            loo_pts = 100.0 * (sum(deltas) - top) / cap
            tk = max(sims_by_variant[r.variant], key=lambda s: abs(s.pnl_delta)).event.ticker
            lines.append(f"{'':<14}   sensib: sin {tk} (±mayor) ΔP/L = {loo_pts:+.2f} pts")
    lines.append("")
    lines.append("Kill criteria: ΔP/L ≥ +2.00 pts y DD ratio ≤ 1.50")

    if detail:
        for label, sims in sims_by_variant.items():
            lines.append("")
            lines.append(f"── {label} (por ciclo) ──")
            for s in sims:
                ev = s.event
                lines.append(
                    f"  {ev.ticker:5} sell={ev.sell_date} fill={ev.sell_price:8.2f} "
                    f"→ exit={s.exit_date} @ {s.exit_price:8.2f} ({s.exit_reason:16}) "
                    f"ΔP/L={s.pnl_delta:+8.2f}"
                )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Recalibración de stops ATR (A1)")
    p.add_argument("--db", default=None)
    p.add_argument("--account", type=int, default=1)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--contam-tol", type=float, default=0.5)
    p.add_argument("--detail", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    db_path = Path(args.db) if args.db else _HERE.parent / DEFAULT_DB
    if not db_path.exists():
        print(f"db no encontrada: {db_path}", file=sys.stderr)
        return 1

    reports, sims_by_variant, ctx = run(db_path, args.account, args.cap_days, args.contam_tol)

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
        print(render(reports, sims_by_variant, ctx, args.detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
