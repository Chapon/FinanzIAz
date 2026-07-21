"""
Runner del filtro de régimen de mercado — backlog **Tarea 8 (R2)**.

Pre-registro con kill-criteria congelados:
``docs/market_regime_gate_r2_2026-07-20.md``. Requiere el artefacto de señal PIT
(``scripts/precompute_pit_signals.py``, generado en la Tarea 7) y SPY 10y en cache.

    python scripts/run_market_regime_r2.py
    python scripts/run_market_regime_r2.py --json

Qué hace
--------
1. Arma la serie de régimen de SPY (``SPY.close < SMA200``, PIT en D−1).
2. Corre los brazos pre-registrados sobre un **simulador de cartera real**
   (``analysis/portfolio_sim.py``): max_positions=5, capital finito, la entrada que
   llega sin slot se pierde, el cash liberado se reinvierte.
3. Reporta P/L, max DD, exposición y el desglose por ventana de stress.
4. Verifica el **invariante de exits**: con el gate ON ninguna posición que igual se
   abrió cambia su salida. Si falla, es un bug, no un resultado.
5. Aplica el kill-criteria. No cambia ningún flag vivo.

Sin red y sin tocar ``finanzias.db``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import AtrParams  # noqa: E402
from analysis.market_regime import build_regime_series, make_entry_filter  # noqa: E402
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio  # noqa: E402
from analysis.scaleout_replay import CostModel, ScaleOutParams  # noqa: E402
from analysis.walkforward_power import STRESS_REGIMES, regime_for_date  # noqa: E402
from scripts.precompute_pit_signals import parse_universe_file  # noqa: E402
from scripts.run_scaleout_replay_t7 import build_entries, load_bars_and_signals  # noqa: E402

DEFAULT_UNIVERSE = "data/harness_universe_41_10y.txt"

# Brazos pre-registrados (§4). El baseline es el engine de hoy.
ARMS: dict[str, dict] = {
    "B0_baseline":        {"mode": "off"},
    "R2a_hard_gate":      {"mode": "hard"},
    "R2b_half_size":      {"mode": "half"},
    "R2c_confirm_5d":     {"mode": "confirm", "confirm_days": 5},
}
PRIMARY_ARM = "R2a_hard_gate"
BASELINE_ARM = "B0_baseline"

# Kill-criteria (§7) — congelados.
KILL_MIN_PL_PTS = 1.5          # OR: mejora de P/L
KILL_MIN_DD_RELIEF = 0.20      # OR: reduccion relativa de max DD en stress
KILL_MAX_NORMAL_COST = 1.0     # AND: tope de recorte en ventanas normales


def load_spy_bars(period: str = "10y"):
    from data import parquet_cache

    df = parquet_cache.read("SPY", period, "1d", None)
    if df is None or df.empty:
        return None
    df = df.sort_index()
    bars = []
    for ts, row in df.iterrows():
        try:
            o, h, lo, c = (float(row["Open"]), float(row["High"]),
                           float(row["Low"]), float(row["Close"]))
        except (KeyError, TypeError, ValueError):
            continue
        bars.append((ts.strftime("%Y-%m-%d"), o, h, lo, c))
    return bars


def stress_window_metrics(res: PortfolioResult) -> dict:
    """P/L medio y max DD restringidos a cada ventana de régimen."""
    out: dict[str, dict] = {}
    names = [r.name for r in STRESS_REGIMES] + ["bull_normal"]
    for name in names:
        tr = [t for t in res.trades if t.regime == name]
        seg = [(d, v) for d, v in res.equity_curve
               if regime_for_date(d) == name]
        dd = 0.0
        if seg:
            peak = seg[0][1]
            for _, v in seg:
                peak = max(peak, v)
                if peak > 0:
                    dd = max(dd, 1.0 - v / peak)
        out[name] = {
            "n_trades": len(tr),
            "mean_ret_pts": 100.0 * statistics.fmean([t.ret for t in tr]) if tr else 0.0,
            "pnl": sum(t.pnl for t in tr),
            "max_dd": dd,
        }
    return out


def check_exit_invariant(base: PortfolioResult, arm: PortfolioResult) -> tuple[bool, str]:
    """El gate NUNCA toca exits: una posicion abierta en ambos brazos, en el mismo
    ticker y fecha de entrada, debe salir en la misma fecha y con el mismo retorno.
    """
    base_by = {(t.ticker, t.entry_date): t for t in base.trades}
    checked = mismatched = 0
    for t in arm.trades:
        b = base_by.get((t.ticker, t.entry_date))
        if b is None:
            continue
        checked += 1
        if b.exit_date != t.exit_date or abs(b.ret - t.ret) > 1e-9:
            mismatched += 1
    if mismatched:
        return False, f"{mismatched}/{checked} posiciones con salida distinta"
    return True, f"{checked} posiciones compartidas, todas con salida idéntica"


def summarise(name: str, res: PortfolioResult, base: PortfolioResult | None) -> dict:
    out = {
        "arm": name,
        "total_return_pts": res.total_return_pts,
        "final_equity": res.final_equity,
        "max_dd": res.max_dd,
        "n_offered": res.n_offered,
        "n_taken": res.n_taken,
        "n_filtered": res.n_filtered,
        "n_no_slot": res.n_no_slot,
        "exposure": res.exposure_share,
        "by_regime": stress_window_metrics(res),
    }
    if base is None:
        return out

    out["delta_pl_pts"] = res.total_return_pts - base.total_return_pts
    bdd = base.max_dd
    out["dd_relief"] = ((bdd - res.max_dd) / bdd) if bdd > 0 else 0.0

    # Restricciones del kill-criteria, evaluadas por separado.
    breg = stress_window_metrics(base)
    stress_names = [r.name for r in STRESS_REGIMES]
    stress_dd_base = max((breg[n]["max_dd"] for n in stress_names), default=0.0)
    stress_dd_arm = max((out["by_regime"][n]["max_dd"] for n in stress_names), default=0.0)
    out["stress_dd_relief"] = (
        ((stress_dd_base - stress_dd_arm) / stress_dd_base) if stress_dd_base > 0 else 0.0
    )
    out["normal_cost_pts"] = (
        breg["bull_normal"]["mean_ret_pts"] - out["by_regime"]["bull_normal"]["mean_ret_pts"]
    )
    benefit = (out["delta_pl_pts"] >= KILL_MIN_PL_PTS
               or out["stress_dd_relief"] >= KILL_MIN_DD_RELIEF)
    constraint = out["normal_cost_pts"] <= KILL_MAX_NORMAL_COST
    out["passes"] = bool(benefit and constraint)
    ok, detail = check_exit_invariant(base, res)
    out["exit_invariant_ok"] = ok
    out["exit_invariant_detail"] = detail
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Filtro de régimen de mercado (Tarea 8/R2)")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--spacing", type=int, default=20)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--max-positions", type=int, default=5)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    spy = load_spy_bars(args.period)
    if not spy:
        print("SPY sin cache 10y. Traelo con get_historical_data('SPY', period='10y').",
              file=sys.stderr)
        return 1
    series = build_regime_series(spy)
    n_off = sum(1 for x in series.risk_off if x)
    print(f"SPY: {len(spy)} barras ({spy[0][0]} → {spy[-1][0]}) · "
          f"días risk-off: {n_off} ({100*n_off/len(spy):.1f}%)")

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, missing, incomplete = load_bars_and_signals(
        tickers, args.period, args.warmup
    )
    if incomplete or missing:
        print(f"AVISO: {len(incomplete)} incompletos, {len(missing)} sin datos",
              file=sys.stderr)
    if not bars_by:
        print("Sin datos: corré scripts/precompute_pit_signals.py primero.",
              file=sys.stderr)
        return 1

    entries = build_entries(bars_by, sigs_by, spacing=args.spacing, warmup=args.warmup)
    print(f"Tickers: {len(bars_by)} · entradas candidatas: {len(entries)} · "
          f"max_positions={args.max_positions} · capital={args.capital:,.0f}\n")

    common = dict(
        max_positions=args.max_positions, initial_capital=args.capital,
        cap_days=args.cap_days, atr_p=AtrParams(), so_params=ScaleOutParams(),
        costs=CostModel(), regime_of=regime_for_date,
    )
    results: dict[str, PortfolioResult] = {}
    for name, cfg in ARMS.items():
        filt = make_entry_filter(series, mode=cfg["mode"],
                                 confirm_days=cfg.get("confirm_days", 5))
        results[name] = simulate_portfolio(entries, bars_by, sigs_by,
                                           entry_filter=filt, **common)

    base = results[BASELINE_ARM]
    summaries = [summarise(BASELINE_ARM, base, None)]
    for name in ARMS:
        if name != BASELINE_ARM:
            summaries.append(summarise(name, results[name], base))

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_entries": len(entries), "n_tickers": len(bars_by),
        "max_positions": args.max_positions, "capital": args.capital,
        "risk_off_share": n_off / len(spy),
        "kill_criteria": {"min_pl_pts": KILL_MIN_PL_PTS,
                          "min_dd_relief": KILL_MIN_DD_RELIEF,
                          "max_normal_cost_pts": KILL_MAX_NORMAL_COST},
    }
    if args.json:
        print(json.dumps({"context": ctx, "summaries": summaries},
                         ensure_ascii=False, indent=2, default=str))
        return 0

    hdr = (f"{'brazo':<18}{'P/L total':>11}{'Δ P/L':>9}{'max DD':>9}"
           f"{'DD stress':>11}{'alivio':>9}{'tomadas':>9}{'filtr.':>8}"
           f"{'expos.':>8}{'PASS':>6}")
    print(hdr)
    print("-" * len(hdr))
    for s in summaries:
        d = s.get("delta_pl_pts")
        rel = s.get("stress_dd_relief")
        sdd = max((s["by_regime"][r.name]["max_dd"] for r in STRESS_REGIMES), default=0.0)
        print(f"{s['arm']:<18}{s['total_return_pts']:>10.2f}%"
              f"{('—' if d is None else f'{d:+.2f}'):>9}"
              f"{100*s['max_dd']:>8.1f}%{100*sdd:>10.1f}%"
              f"{('—' if rel is None else f'{100*rel:+.1f}%'):>9}"
              f"{s['n_taken']:>9}{s['n_filtered']:>8}"
              f"{100*s['exposure']:>7.0f}%"
              f"{('' if s.get('passes') is None else ('SI' if s['passes'] else 'no')):>6}")

    print("\nPor régimen — retorno medio por trade (pts) / n trades:")
    names = ["bull_normal"] + [r.name for r in STRESS_REGIMES]
    print(f"  {'brazo':<18}" + "".join(f"{n:>22}" for n in names))
    for s in summaries:
        cells = "".join(
            f"{s['by_regime'][n]['mean_ret_pts']:>+15.2f} (n={s['by_regime'][n]['n_trades']:>3})"
            for n in names
        )
        print(f"  {s['arm']:<18}{cells}")

    print("\nCosto en ventanas normales (tope +1.0 pt) e invariante de exits:")
    for s in summaries[1:]:
        print(f"  {s['arm']:<18} costo bull_normal = {s['normal_cost_pts']:+.2f} pts"
              f"  ·  exits: {'OK' if s['exit_invariant_ok'] else 'ROTO'}"
              f" ({s['exit_invariant_detail']})")

    print(f"\nKill-criteria: (Δ P/L ≥ +{KILL_MIN_PL_PTS} pts  O  alivio de DD en stress "
          f"≥ {100*KILL_MIN_DD_RELIEF:.0f}%)  Y  costo en normales ≤ {KILL_MAX_NORMAL_COST} pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
