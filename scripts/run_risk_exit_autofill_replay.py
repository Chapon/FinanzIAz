"""
Runner — validación del auto-fill de risk-exits en cuenta manual (tarea ① N3/A2).

Pregunta: en una cuenta **manual**, ¿conviene ejecutar los risk-exits
(``atr_*`` / ``vol_trim``) al toque (como en auto) en vez de encolarlos como
orden pendiente que requiere aprobación y puede **expirar** sin ejecutarse?

Contrafactual (kill-criteria pre-registrado, BACKLOG tarea ①):
    comparar "stop pending que puede expirar" vs "auto-fill del risk-exit".
    Se shipea si el auto-fill **no empeora** el P/L y **reduce** la exposición
    a la cola de pérdidas (DD).

Modelo de las dos políticas sobre cada risk-exit real (FIFO sobre la DB):

  * **AUTO-FILL (la feature):** el stop se ejecuta en el scan que dispara. Es
    *exactamente* lo que ocurrió en la historia capturada — los 6 risk-exits
    reales se aprobaron a segundos/minutos del trigger (delay ≈ 0), así que el
    fill real ES el fill del auto-fill. ``pnl_auto = pnl_real``.

  * **PENDING-EXPIRA (el agujero que tapa la feature):** el stop queda pending,
    no se aprueba y ``reconcile_account`` lo marca ``expired`` a las 24h; la
    posición sigue abierta SIN stop efectivo. Peor caso acotado: rida hasta el
    cap (20 días hábiles) y salga al close. Se modela reusando
    ``exit_replay.replay_event`` con el ATR neutralizado (mult enormes, trail
    off) para que NINGÚN stop dispare en la simulación — la posición ride al cap.

Métricas (idénticas en espíritu al harness T6.1):
  * ΔP/L (auto − expira), en $ y en puntos (% del capital inicial).
  * DD de la curva de equity real (= auto, el stop salió) vs la ajustada por el
    ride del contrafactual (``adjusted_equity_curve`` + ``max_drawdown``).
  * Peor excursión adversa por evento (cuánto más cae la posición debajo del
    fill del stop) = la cola de pérdidas que el auto-fill evita.

Uso:
    python scripts/run_risk_exit_autofill_replay.py [--db PATH] [--account 1]
        [--cap-days 20] [--json]

Read-only sobre un backup limpio (ver skill finanzias-conventions). No escribe
la DB.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import (  # noqa: E402
    AtrParams,
    SellEvent,
    SimExit,
    adjusted_equity_curve,
    max_drawdown,
    replay_event,
)
from scripts.baseline_metrics import load_snapshots  # noqa: E402
from scripts.run_exit_replay_t61 import (  # noqa: E402
    build_sell_events,
    make_bar_loader,
)

DEFAULT_DB = "finanzias.db"

# ATR neutralizado: ningún stop/tp/trail dispara en la sim → la posición ride
# al cap (modela el stop que NUNCA se ejecuta porque el pending expira).
_NO_ATR = AtrParams(period=14, stop_mult=1e9, tp_mult=1e9, trail_enabled=False)


def is_risk_exit(reason: str | None) -> bool:
    r = reason or ""
    return r.startswith("atr_") or r.startswith("vol_trim")


@dataclass
class RiskExitReplay:
    event: SellEvent
    expire_sim: SimExit | None          # None ⇒ sin barras / demasiado reciente
    worst_excursion: float = 0.0        # peor MTM $ debajo del fill del stop
    approval_delay_h: float | None = None


def _approval_delays(con: sqlite3.Connection, account_id: int) -> dict[int, float]:
    """Horas entre created_at y filled_at por order_id (evidencia del delay≈0)."""
    out: dict[int, float] = {}
    for oid, cr, fl in con.execute(
        "SELECT id, created_at, filled_at FROM paper_orders "
        "WHERE account_id = ? AND side = 'SELL' AND status = 'filled'",
        (account_id,),
    ):
        try:
            d = (datetime.fromisoformat(fl) - datetime.fromisoformat(cr)).total_seconds() / 3600.0
            out[int(oid)] = d
        except (TypeError, ValueError):
            continue
    return out


def run(db_path: Path, account_id: int, cap_days: int):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        all_events = build_sell_events(con, account_id)
        risk_events = [e for e in all_events if is_risk_exit(e.reason)]
        bar_loader = make_bar_loader(con)
        delays = _approval_delays(con, account_id)

        snaps = load_snapshots(con, account_id)
        real_curve = [(s.snapshot_at.strftime("%Y-%m-%d"), s.total_equity) for s in snaps]
        cap_row = con.execute(
            "SELECT initial_capital FROM paper_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        initial_capital = float(cap_row[0]) if cap_row else 50_000.0

        replays: list[RiskExitReplay] = []
        for ev in risk_events:
            bars = bar_loader(ev.ticker)
            sim = None
            worst = 0.0
            if bars:
                sim = replay_event(
                    ev, bars, scheduled_exit_idx=None, cap_days=cap_days, atr_p=_NO_ATR
                )
                if sim is not None and sim.daily_delta:
                    worst = min((d for _, d in sim.daily_delta), default=0.0)
            replays.append(
                RiskExitReplay(
                    event=ev,
                    expire_sim=sim,
                    worst_excursion=worst,
                    approval_delay_h=delays.get(ev.order_id),
                )
            )

        # Agregados.
        modeled = [r for r in replays if r.expire_sim is not None]
        pnl_auto = sum(r.event.pnl_real for r in replays)              # auto = real
        pnl_expire = sum(
            (r.expire_sim.pnl_sim if r.expire_sim is not None else r.event.pnl_real)
            for r in replays
        )
        delta = pnl_auto - pnl_expire                                  # >0 ⇒ auto mejor
        delta_pts = 100.0 * delta / initial_capital if initial_capital > 0 else 0.0

        # DD: curva real (auto, el stop salió) vs ajustada por el ride del expire.
        expire_sims = [r.expire_sim for r in modeled if r.expire_sim is not None]
        dd_auto = max_drawdown(real_curve)
        adj = adjusted_equity_curve(real_curve, expire_sims)
        dd_expire = max_drawdown(adj)
        dd_ratio = (dd_expire / dd_auto) if dd_auto > 0 else (1.0 if dd_expire == 0 else float("inf"))

        worst_total = sum(r.worst_excursion for r in replays)

        # Kill-criteria: auto NO empeora P/L (Δ ≥ 0) y reduce la cola de DD
        # (la curva del expire tiene DD ≥ la de auto, y hay excursión adversa).
        no_worse_pnl = delta >= 0.0
        reduces_dd = dd_expire >= dd_auto and worst_total < 0.0
        passes = no_worse_pnl and reduces_dd

        ctx = {
            "db": str(db_path),
            "account_id": account_id,
            "n_sell_events": len(all_events),
            "n_risk_exits": len(risk_events),
            "n_modeled": len(modeled),
            "initial_capital": initial_capital,
            "cap_days": cap_days,
            "max_approval_delay_h": max((d for d in delays.values()), default=None),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        agg = {
            "pnl_auto": pnl_auto,
            "pnl_expire_worstcase": pnl_expire,
            "pnl_delta_auto_minus_expire": delta,
            "pnl_delta_pts": delta_pts,
            "dd_auto": dd_auto,
            "dd_expire_worstcase": dd_expire,
            "dd_ratio_expire_over_auto": dd_ratio,
            "worst_adverse_excursion_total": worst_total,
            "no_worse_pnl": no_worse_pnl,
            "reduces_dd_tail": reduces_dd,
            "passes_kill_criteria": passes,
        }
        return replays, agg, ctx
    finally:
        con.close()


def render(replays: list[RiskExitReplay], agg: dict, ctx: dict) -> str:
    lines = [
        f"Risk-exit auto-fill replay — cuenta {ctx['account_id']} · "
        f"{ctx['n_risk_exits']} risk-exits de {ctx['n_sell_events']} SELLs · "
        f"cap {ctx['cap_days']}d · capital {ctx['initial_capital']:,.0f}",
        f"Delay máx de aprobación de SELLs reales: "
        f"{ctx['max_approval_delay_h']:.2f}h  (auto-fill ≈ fills reales)"
        if ctx["max_approval_delay_h"] is not None else "",
        "",
        f"{'ticker':<8} {'reason':<10} {'pnl_auto$':>11} {'pnl_expire$':>12} "
        f"{'Δ(auto-exp)$':>13} {'peor exc.$':>11} {'delay h':>8}",
    ]
    for r in replays:
        ev = r.event
        reason_short = (ev.reason or "")[:9]
        pnl_exp = r.expire_sim.pnl_sim if r.expire_sim is not None else ev.pnl_real
        delay = f"{r.approval_delay_h:.2f}" if r.approval_delay_h is not None else "—"
        lines.append(
            f"{ev.ticker:<8} {reason_short:<10} {ev.pnl_real:>+11.2f} "
            f"{pnl_exp:>+12.2f} {(ev.pnl_real - pnl_exp):>+13.2f} "
            f"{r.worst_excursion:>+11.2f} {delay:>8}"
        )
    lines += [
        "",
        f"TOTAL  pnl_auto={agg['pnl_auto']:+.2f}  "
        f"pnl_expire(worst)={agg['pnl_expire_worstcase']:+.2f}  "
        f"Δ={agg['pnl_delta_auto_minus_expire']:+.2f} ({agg['pnl_delta_pts']:+.2f} pts)",
        f"DD auto={100*agg['dd_auto']:.2f}%  DD expire(worst)={100*agg['dd_expire_worstcase']:.2f}%  "
        f"ratio={agg['dd_ratio_expire_over_auto']:.2f}",
        f"Cola de pérdidas evitada (peor excursión total): "
        f"{agg['worst_adverse_excursion_total']:+.2f}",
        "",
        f"Kill-criteria — no empeora P/L: {'✅' if agg['no_worse_pnl'] else '—'}  ·  "
        f"reduce cola de DD: {'✅' if agg['reduces_dd_tail'] else '—'}  ·  "
        f"VEREDICTO: {'SHIP ✅' if agg['passes_kill_criteria'] else 'NO-SHIP —'}",
    ]
    return "\n".join(x for x in lines if x is not None)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay auto-fill de risk-exits (tarea ①)")
    p.add_argument("--db", default=None)
    p.add_argument("--account", type=int, default=1)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    db_path = Path(args.db) if args.db else _HERE.parent / DEFAULT_DB
    if not db_path.exists():
        print(f"db no encontrada: {db_path}", file=sys.stderr)
        return 1

    replays, agg, ctx = run(db_path, args.account, args.cap_days)
    if args.json:
        print(json.dumps({"context": ctx, "aggregate": agg}, ensure_ascii=False,
                         indent=2, default=str))
    else:
        print(render(replays, agg, ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
