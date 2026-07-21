"""
Runner del replay de scale-out + trailing — backlog **Tarea 7**.

Pre-registro con kill-criteria congelados: ``docs/scaleout_trailing_t7_2026-07-20.md``.
Requiere el artefacto de señal PIT (``scripts/precompute_pit_signals.py``).

    python scripts/precompute_pit_signals.py            # una vez, ~2 h
    python scripts/run_scaleout_replay_t7.py            # segundos
    python scripts/run_scaleout_replay_t7.py --json

Qué hace
--------
1. Arma la grilla de entradas PIT: barras donde la señal precomputada dice **BUY**,
   espaciadas ``--spacing`` (default 20 = el cap, para que las ventanas no se
   solapen y el CPCV sea legítimo).
2. Corre cada brazo pre-registrado sobre las mismas entradas (comparación pareada).
3. Reporta ΔP/L en puntos, DD ratio sobre la curva compuesta, payoff ratio, win
   rate, MAE/MFE y el desglose por régimen.
4. Robustez estilo E4: **PBO (CSCV)** sobre la matriz de retornos por brazo y
   **DSR** contabilizando todos los brazos como intentos.
5. Aplica el kill-criteria y dice PASS/FAIL por brazo. No cambia ningún flag vivo.

Sin red y sin tocar ``finanzias.db``: lee Parquet + los JSON de señal.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import AtrParams, Bar, max_drawdown  # noqa: E402
from analysis.scaleout_replay import (  # noqa: E402
    CostModel,
    CycleResult,
    ScaleOutParams,
    replay_cycle,
)
from analysis.walkforward_power import (  # noqa: E402
    _sharpe,
    _skew_kurt,
    deflated_sharpe_ratio,
    pbo_cscv,
    regime_for_date,
)
from scripts.precompute_pit_signals import _load_existing, _out_path, parse_universe_file  # noqa: E402

DEFAULT_UNIVERSE = "data/harness_universe_41_10y.txt"

# ── Brazos pre-registrados (doc §4 + enmienda 2) ─────────────────────────────
# Eje único: qué fracción vende el flip de señal. 1.0 = engine de hoy.
# Los brazos B mueven además el trailing del remanente (stop inicial fijo en 2.0).
ARMS: dict[str, tuple[ScaleOutParams, AtrParams]] = {
    "B0_baseline_full_exit": (ScaleOutParams(sell_fraction=1.0), AtrParams()),
    "A50_scaleout_50":       (ScaleOutParams(sell_fraction=0.5), AtrParams()),
    "B_trail_2.5":           (ScaleOutParams(sell_fraction=0.5), AtrParams(trail_mult=2.5)),
    "B_trail_3.0":           (ScaleOutParams(sell_fraction=0.5), AtrParams(trail_mult=3.0)),
    "C_A4_levels_rule":      (ScaleOutParams(sell_fraction=0.0), AtrParams()),
    "A33_scaleout_33":       (ScaleOutParams(sell_fraction=0.33), AtrParams()),
    "A67_scaleout_67":       (ScaleOutParams(sell_fraction=0.67), AtrParams()),
}
PRIMARY_ARM = "A50_scaleout_50"
BASELINE_ARM = "B0_baseline_full_exit"
# Brazos que cuentan como "intentos" para el DSR (todos menos el baseline).
N_TRIALS = len(ARMS) - 1

# Kill-criteria (doc §6) — congelados.
KILL_MIN_DELTA_PTS = 1.5
KILL_MAX_DD_RATIO = 1.5
KILL_MAX_PBO = 0.5


def load_bars_and_signals(tickers: list[str], period: str, warmup: int):
    """{ticker: [Bar]} + {ticker: {iso10: signal}}. Saltea lo que no esté completo."""
    from data import parquet_cache

    bars_by: dict[str, list[Bar]] = {}
    sigs_by: dict[str, dict] = {}
    missing: list[str] = []
    incomplete: list[str] = []
    for t in tickers:
        blob = _load_existing(_out_path(t, period, warmup))
        if not blob:
            missing.append(t)
            continue
        if not blob.get("complete"):
            incomplete.append(t)
            continue
        df = parquet_cache.read(t, period, "1d", None)
        if df is None or df.empty:
            missing.append(t)
            continue
        df = df.sort_index()
        bars: list[Bar] = []
        for ts, row in df.iterrows():
            try:
                o, h, lo, c = (float(row["Open"]), float(row["High"]),
                               float(row["Low"]), float(row["Close"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in (o, h, lo, c)) or c <= 0:
                continue
            bars.append((ts.strftime("%Y-%m-%d"), o, h, lo, c))
        if not bars:
            missing.append(t)
            continue
        bars_by[t] = bars
        sigs_by[t] = {d: v[0] for d, v in (blob.get("signals") or {}).items() if v[0]}
    return bars_by, sigs_by, missing, incomplete


def build_entries(bars_by: dict, sigs_by: dict, *, spacing: int, warmup: int):
    """Entradas PIT: barras con señal BUY, espaciadas ``spacing`` por ticker.

    El espaciado se cuenta desde la **última entrada aceptada**, no desde la grilla
    fija, para que las ventanas de ``cap_days`` no se solapen nunca (requisito de
    independencia del CPCV).
    """
    out: list[tuple[str, int]] = []
    for t, bars in bars_by.items():
        sigs = sigs_by.get(t) or {}
        last = -10**9
        for i in range(warmup, len(bars) - 1):
            if i - last < spacing:
                continue
            if sigs.get(bars[i][0]) == "BUY":
                out.append((t, i))
                last = i
    out.sort(key=lambda x: (bars_by[x[0]][x[1]][0], x[0]))  # cronológico
    return out


def run_arm(entries, bars_by, sigs_by, params, atr_p, *, cap_days, costs, notional):
    """Corre un brazo sobre todas las entradas. Devuelve [CycleResult] alineado."""
    results: list[CycleResult] = []
    for ticker, idx in entries:
        bars = bars_by[ticker]
        res = replay_cycle(
            bars, idx, sigs_by.get(ticker) or {},
            params=params, atr_p=atr_p, cap_days=cap_days,
            costs=costs, notional=notional,
            regime=regime_for_date(bars[idx][0]),
        )
        if res is None:
            continue
        res.ticker = ticker
        results.append(res)
    return results


def composite_curve(results: list[CycleResult]) -> list[tuple[str, float]]:
    """Curva compuesta equal-weight: media diaria del valor normalizado de las
    posiciones abiertas ese día, encadenada cronológicamente.

    Cada ciclo aporta su valor relativo al costo de entrada. Es un proxy de cartera
    (una posición por entrada, equal-notional) que permite un max DD comparable
    entre brazos, ya que todos comparten exactamente las mismas entradas.
    """
    by_date: dict[str, list[float]] = {}
    for r in results:
        if r.entry_cost <= 0:
            continue
        for d, v in r.daily_value:
            by_date.setdefault(d, []).append(v / r.entry_cost)
    if not by_date:
        return []
    curve: list[tuple[str, float]] = []
    equity = 1.0
    prev: float | None = None
    for d in sorted(by_date):
        m = statistics.fmean(by_date[d])
        if prev is not None and prev > 0:
            equity *= m / prev
        curve.append((d, equity))
        prev = m
    return curve


def summarise(name: str, results: list[CycleResult], base: list[CycleResult] | None):
    rets = [r.ret for r in results]
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x < 0]
    curve = composite_curve(results)
    dd = max_drawdown(curve)
    out = {
        "arm": name,
        "n": len(results),
        "mean_ret_pts": 100.0 * statistics.fmean(rets) if rets else 0.0,
        "median_ret_pts": 100.0 * statistics.median(rets) if rets else 0.0,
        "win_rate": 100.0 * len(wins) / len(rets) if rets else 0.0,
        "avg_win_pts": 100.0 * statistics.fmean(wins) if wins else 0.0,
        "avg_loss_pts": 100.0 * statistics.fmean(losses) if losses else 0.0,
        "payoff": (statistics.fmean(wins) / abs(statistics.fmean(losses)))
                  if wins and losses else float("nan"),
        "max_dd": dd,
        "sharpe": _sharpe(rets),
        "mean_held_days": statistics.fmean([r.held_days for r in results]) if results else 0.0,
        "median_mae_pts": 100.0 * statistics.median([r.mae for r in results]) if results else 0.0,
        "median_mfe_pts": 100.0 * statistics.median([r.mfe for r in results]) if results else 0.0,
        "exit_mix": {},
    }
    mix: dict[str, int] = {}
    for r in results:
        mix[r.exit_reasons] = mix.get(r.exit_reasons, 0) + 1
    out["exit_mix"] = dict(sorted(mix.items(), key=lambda kv: -kv[1])[:6])

    if base is not None:
        base_rets = [r.ret for r in base]
        out["delta_pts"] = out["mean_ret_pts"] - 100.0 * statistics.fmean(base_rets)
        base_dd = max_drawdown(composite_curve(base))
        out["dd_ratio"] = (dd / base_dd) if base_dd > 0 else (1.0 if dd == 0 else float("inf"))
        # por régimen
        per_reg: dict[str, float] = {}
        by_reg_base: dict[str, list[float]] = {}
        by_reg_arm: dict[str, list[float]] = {}
        for r in base:
            by_reg_base.setdefault(r.regime, []).append(r.ret)
        for r in results:
            by_reg_arm.setdefault(r.regime, []).append(r.ret)
        for reg in sorted(set(by_reg_base) | set(by_reg_arm)):
            b = by_reg_base.get(reg) or []
            a = by_reg_arm.get(reg) or []
            if b and a:
                per_reg[reg] = 100.0 * (statistics.fmean(a) - statistics.fmean(b))
        out["delta_by_regime"] = per_reg
        out["passes"] = bool(
            out["delta_pts"] >= KILL_MIN_DELTA_PTS and out["dd_ratio"] <= KILL_MAX_DD_RATIO
        )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay scale-out + trailing (Tarea 7)")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--spacing", type=int, default=20)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--notional", type=float, default=10_000.0)
    p.add_argument("--commission", type=float, default=0.001)
    p.add_argument("--slippage", type=float, default=0.0005)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, missing, incomplete = load_bars_and_signals(
        tickers, args.period, args.warmup
    )
    if incomplete:
        print(f"AVISO: {len(incomplete)} tickers con señal PIT incompleta "
              f"(se excluyen): {', '.join(incomplete[:8])}"
              f"{'...' if len(incomplete) > 8 else ''}", file=sys.stderr)
    if missing:
        print(f"AVISO: {len(missing)} tickers sin datos: "
              f"{', '.join(missing[:8])}{'...' if len(missing) > 8 else ''}",
              file=sys.stderr)
    if not bars_by:
        print("Sin datos: corré scripts/precompute_pit_signals.py primero.",
              file=sys.stderr)
        return 1

    entries = build_entries(bars_by, sigs_by, spacing=args.spacing, warmup=args.warmup)
    costs = CostModel(commission=args.commission, slippage=args.slippage)
    print(f"Tickers: {len(bars_by)} · entradas BUY point-in-time: {len(entries)} "
          f"(spacing {args.spacing}, cap {args.cap_days}d)")

    per_arm: dict[str, list[CycleResult]] = {}
    for name, (params, atr_p) in ARMS.items():
        per_arm[name] = run_arm(entries, bars_by, sigs_by, params, atr_p,
                                cap_days=args.cap_days, costs=costs,
                                notional=args.notional)

    base = per_arm[BASELINE_ARM]
    summaries = [summarise(BASELINE_ARM, base, None)]
    for name in ARMS:
        if name == BASELINE_ARM:
            continue
        summaries.append(summarise(name, per_arm[name], base))

    # ── Robustez: PBO (CSCV) + DSR sobre los mismos retornos pareados ─────────
    perf_matrix = {name: [r.ret for r in res] for name, res in per_arm.items()}
    lens = {len(v) for v in perf_matrix.values()}
    pbo = pbo_cscv(perf_matrix) if len(lens) == 1 else None
    trial_sharpes = [_sharpe(perf_matrix[n]) for n in ARMS if n != BASELINE_ARM]
    best_name = max((n for n in ARMS if n != BASELINE_ARM),
                    key=lambda n: _sharpe(perf_matrix[n]))
    sk, ku = _skew_kurt(perf_matrix[best_name])
    dsr = deflated_sharpe_ratio(
        trial_sharpes, n_obs=len(perf_matrix[best_name]),
        selected=_sharpe(perf_matrix[best_name]), skew=sk, kurtosis=ku,
    )

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by), "n_entries": len(entries),
        "spacing": args.spacing, "cap_days": args.cap_days,
        "costs": {"commission": args.commission, "slippage": args.slippage},
        "n_trials_dsr": N_TRIALS,
        "kill_criteria": {"min_delta_pts": KILL_MIN_DELTA_PTS,
                          "max_dd_ratio": KILL_MAX_DD_RATIO,
                          "max_pbo": KILL_MAX_PBO},
    }
    if args.json:
        print(json.dumps({
            "context": ctx, "summaries": summaries,
            "pbo": pbo.__dict__ if pbo else None, "dsr": dsr.__dict__,
            "best_by_sharpe": best_name,
        }, ensure_ascii=False, indent=2, default=str))
        return 0

    print()
    hdr = (f"{'brazo':<24}{'n':>5}{'ret medio':>11}{'Δ pts':>8}{'win%':>7}"
           f"{'payoff':>8}{'DD':>7}{'ratio':>7}{'días':>6}{'PASS':>6}")
    print(hdr)
    print("-" * len(hdr))
    for s in summaries:
        d = s.get("delta_pts")
        r = s.get("dd_ratio")
        print(f"{s['arm']:<24}{s['n']:>5}{s['mean_ret_pts']:>10.2f}%"
              f"{('—' if d is None else f'{d:+.2f}'):>8}"
              f"{s['win_rate']:>6.1f}%{s['payoff']:>8.2f}"
              f"{100*s['max_dd']:>6.1f}%"
              f"{('—' if r is None else f'{r:.2f}'):>7}"
              f"{s['mean_held_days']:>6.1f}"
              f"{('' if s.get('passes') is None else ('SI' if s['passes'] else 'no')):>6}")

    print("\nΔ por régimen (pts vs baseline):")
    for s in summaries[1:]:
        reg = s.get("delta_by_regime") or {}
        cells = "  ".join(f"{k}={v:+.2f}" for k, v in reg.items())
        print(f"  {s['arm']:<24} {cells}")

    print("\nMezcla de salidas (top):")
    for s in summaries:
        print(f"  {s['arm']:<24} {s['exit_mix']}")

    print(f"\nPBO (CSCV): {pbo.pbo:.3f}" if pbo else "\nPBO: n/d")
    if pbo and pbo.best_is_counts:
        top = sorted(pbo.best_is_counts.items(), key=lambda kv: -kv[1])[:3]
        print(f"  mejor in-sample más veces: {top}")
    print(f"DSR: mejor por Sharpe = {best_name} · SR={dsr.observed_sharpe:.4f} · "
          f"SR0={dsr.expected_max_sharpe:.4f} · DSR={dsr.deflated_sharpe:.4f} "
          f"({dsr.n_trials} intentos, n={dsr.n_obs})")
    print(f"\nKill-criteria: Δ ≥ +{KILL_MIN_DELTA_PTS} pts · DD ratio ≤ "
          f"{KILL_MAX_DD_RATIO} · PBO ≤ {KILL_MAX_PBO} · DSR > 0 · "
          f"el signo no puede depender de un solo régimen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
