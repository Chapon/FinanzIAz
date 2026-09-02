"""
REGIME-POWER — **Tarea 46**: ¿el criterio de robustez de régimen de la serie
distingue crash-risk de ruido de muestra?

Por qué existe
--------------
El criterio de régimen —C5 en 26b/34/37, §6.5 en T11b— exige **signo estable en las
cuatro ventanas** y se evalúa sobre el retorno medio **por trade** dentro de cada una.
Ese criterio **mató a las tres tareas más prometedoras de la serie**: la 26b (−0.15 pts
en 2018Q4), la 34 (−1.18) y la T11b (−2.01 en `bear_2022`), que era el único brazo con
alpha medido.

La T38 midió cuántos trades hay realmente en esas ventanas —**10-63**— y mostró que al
triplicar la muestra **dos de tres signos se dan vuelta**. Este script contesta la
pregunta que sigue, que es de **potencia**, no de umbral:

  1. ¿Qué efecto por trade es siquiera **detectable** con esos ``n``?
  2. ¿Cuánto aguanta el **signo** de cada ventana si se remuestrea la propia muestra?
  3. ¿La versión de **cartera** del criterio (``regime_window_returns``, la que ya usan
     la T38 y la T39) es más estable que la de **por trade**?

No decide ningún flag y no toca el motor: es análisis sobre datos ya medidos. Lo que
produce es **el criterio que las tareas siguientes van a pre-registrar** — empezando por
la 37, que hoy tiene el criterio viejo congelado.

Poblaciones
-----------
* ``anomaly`` — entradas del detector de ruptura (T11b/T38), señal ``A_k2.0_m1.5``.
* ``analyze`` — eventos ``analyze BUY`` PIT (la población de 26b/34/T39).

Sin red, sin tocar ``finanzias.db``.
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

from analysis.anomaly_signal import AnomalyParams, build_anomaly_entries
from analysis.exit_replay import AtrParams
from analysis.harness_config import (
    HARNESS_FILL_MODE,
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    StaleArtifactError,
    announce,
    announce_artifacts,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.rank_policy import neutral_rank
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    BULL_NORMAL,
    STRESS_REGIMES,
    achieved_power_mean,
    block_delta_sign_stability,
    block_sign_stability,
    detectable_mean_effect,
    regime_for_date,
    regime_window_returns,
    sign_stability,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_rank_neutral_t39 import aligned_daily

EVAL_MODE = "touch"
LIVE_GATES = True
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345
BOOT_BLOCK = 20

# Los umbrales de régimen que la serie usó, para contrastarlos contra lo detectable.
PUBLISHED_TOLERANCE_PTS = 0.05  # C5 de 26b/34: Δ ≥ −0.05 pts por trade
# Los rechazos que ese criterio produjo (pts por trade), para re-leerlos.
PUBLISHED_REJECTIONS = {
    "26b · close_2.0 en 2018Q4": -0.15,
    "26b · close_2.0 en bear_2022": -0.08,
    "34 · touch_off en 2018Q4": -1.18,
    "T11b · A_k2.0_m1.5 en bear_2022": -2.01,
}

REGIMES = [BULL_NORMAL] + [r.name for r in STRESS_REGIMES]
# Candidato de reemplazo: las tres ventanas de stress agregadas en una sola, que
# es la forma más barata de recuperar potencia sin cambiar de métrica.
STRESS_POOLED = "stress_POOLED"


def _common(max_positions: int, cap_days: int, capital: float) -> dict:
    return dict(
        max_positions=max_positions,
        initial_capital=capital,
        cap_days=cap_days,
        atr_p=AtrParams(),
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        eval_mode=EVAL_MODE,
        fill_mode=HARNESS_FILL_MODE,
        live_gates=LIVE_GATES,
    )


def per_trade_by_regime(res: PortfolioResult) -> dict[str, list[float]]:
    """Retornos **por trade** agrupados por régimen, en pts (×100)."""
    out: dict[str, list[float]] = {r: [] for r in REGIMES}
    for t in res.trades:
        out.setdefault(t.regime, []).append(100.0 * t.ret)
    return out


def analyse(res_a: PortfolioResult, res_b: PortfolioResult, *, n_resamples: int, seed: int) -> dict:
    """Las tres lecturas del mismo eje, para poder compararlas de frente."""
    pt_a = per_trade_by_regime(res_a)
    pt_b = per_trade_by_regime(res_b)
    daily = aligned_daily({"a": res_a, "b": res_b}, ["a", "b"])
    port_a = regime_window_returns(daily["a"])
    port_b = regime_window_returns(daily["b"])

    stress_names = [r.name for r in STRESS_REGIMES]
    pt_a[STRESS_POOLED] = [v for r in stress_names for v in pt_a.get(r, [])]
    pt_b[STRESS_POOLED] = [v for r in stress_names for v in pt_b.get(r, [])]

    out: dict[str, dict] = {}
    for r in [*REGIMES, STRESS_POOLED]:
        xs, ys = pt_a.get(r, []), pt_b.get(r, [])
        n = len(xs)
        sd = statistics.stdev(xs) if n > 1 else 0.0
        mean = statistics.fmean(xs) if xs else 0.0
        d = (mean / sd) if sd > 0 else 0.0
        # (A) el signo del brazo, que es lo que exige §6.5 de T11b
        stab_arm = sign_stability(xs, n_resamples=n_resamples, seed=seed)
        # (B) la diferencia de medias entre brazos, que es lo que exige C5 de 26b/34
        delta = (statistics.fmean(ys) if ys else 0.0) - mean
        stab_delta = None
        if xs and ys:
            samples = _delta_samples(xs, ys, n_resamples=n_resamples, seed=seed)
            stab_delta = _summarise_samples(samples, delta)

        # (C) la versión de CARTERA, que es la que usan T38/T39
        # `_in_window` captura `r` del loop pero se invoca en las dos lineas
        # siguientes, dentro de la misma iteracion, y no se guarda: el
        # late-binding que B023 advierte no puede darse aca.
        def _in_window(dt: str) -> bool:
            reg = regime_for_date(dt)
            return reg in stress_names if r == STRESS_POOLED else reg == r  # noqa: B023

        daily_r = [v for dt, v in daily["a"] if _in_window(dt)]
        daily_r_b = [v for dt, v in daily["b"] if _in_window(dt)]
        stab_port = block_sign_stability(daily_r, block=BOOT_BLOCK, n_resamples=n_resamples, seed=seed)
        # (D) y lo que un criterio de régimen REALMENTE evalúa: el Δ entre brazos
        # dentro de la ventana. El nivel de (C) habla del mercado, no de la política.
        stab_port_delta = block_delta_sign_stability(
            daily_r, daily_r_b, block=BOOT_BLOCK, n_resamples=n_resamples, seed=seed
        )
        port_a_r = sum(port_a.get(x, 0.0) for x in stress_names) if r == STRESS_POOLED else port_a.get(r, 0.0)
        port_b_r = sum(port_b.get(x, 0.0) for x in stress_names) if r == STRESS_POOLED else port_b.get(r, 0.0)
        out[r] = {
            "n_trades": n,
            "mean_pts": mean,
            "sd_pts": sd,
            "cohens_d": d,
            "detectable_at_80": detectable_mean_effect(sd, n) if n > 1 else None,
            "power_for_tolerance": (
                achieved_power_mean(PUBLISHED_TOLERANCE_PTS / sd, n) if sd > 0 and n > 1 else 0.0
            ),
            "power_for_observed": achieved_power_mean(d, n) if n > 1 else 0.0,
            "arm_sign": stab_arm,
            "delta_pts": delta,
            "delta_sign": stab_delta,
            "portfolio_ret_a": port_a_r,
            "portfolio_ret_b": port_b_r,
            "portfolio_sign": stab_port,
            "portfolio_delta_sign": stab_port_delta,
        }
    return out


def _delta_samples(xs: list[float], ys: list[float], *, n_resamples: int, seed: int) -> list[float]:
    """Distribución bootstrap de la **diferencia de medias** entre dos brazos.

    Los brazos no comparten trades (cambian cuáles se toman), así que la
    diferencia **no es pareada trade a trade**: se remuestrea cada brazo por
    separado y se resta.
    """
    import numpy as np

    a = np.asarray(xs, dtype=float)
    b = np.asarray(ys, dtype=float)
    rng = np.random.default_rng(seed)
    ia = rng.integers(0, a.size, size=(n_resamples, a.size))
    ib = rng.integers(0, b.size, size=(n_resamples, b.size))
    return list(b[ib].mean(axis=1) - a[ia].mean(axis=1))


def _summarise_samples(samples: list[float], observed: float) -> dict:
    """IC95% + fracción de resamples que conserva el signo de lo observado."""
    import numpy as np

    arr = np.asarray(samples, dtype=float)
    same = float(np.mean(np.sign(arr) == np.sign(observed))) if observed != 0 else 0.5
    return {
        "n": int(arr.size),
        "mean": observed,
        "ci_low": float(np.percentile(arr, 2.5)),
        "ci_high": float(np.percentile(arr, 97.5)),
        "p_same_sign": same,
    }


# ── Poblaciones ──────────────────────────────────────────────────────────────


def population_anomaly(universe: str, period: str, warmup: int, common: dict):
    """Entradas del detector de ruptura (T11b/T38). Contraste: con gate de régimen."""
    from analysis.market_regime import build_regime_series, make_entry_filter
    from scripts.run_anomaly_replay_t11b import load_bars_signals_volume
    from scripts.run_market_regime_r2 import load_spy_bars

    tickers = parse_universe_file(_HERE.parent / universe)
    bars_by, sigs_by, vol_by, _m, _i = load_bars_signals_volume(tickers, period, warmup)
    entries = build_anomaly_entries(bars_by, vol_by, AnomalyParams(k=2.0, m=1.5), warmup=warmup)
    series = build_regime_series(load_spy_bars(period) or [])
    a = simulate_portfolio(entries, bars_by, sigs_by, **common)
    # Contraste = ``G_hard``, no ``G_half``: el criterio C5 de 26b/34 mide la
    # DIFERENCIA de medias entre brazos, y ``half`` toma exactamente los mismos
    # trades (sólo los achica), así que su Δ por trade es 0 por construcción — el
    # mismo motivo por el que el sanity de la T38 no podía verlo.
    b = simulate_portfolio(
        entries, bars_by, sigs_by, entry_filter=make_entry_filter(series, mode="hard"), **common
    )
    return (
        a,
        b,
        {"n_tickers": len(bars_by), "n_entries": len(entries), "arm_a": "U_ungated", "arm_b": "G_hard"},
    )


def population_analyze(universe: str, period: str, warmup: int, common: dict):
    """Eventos ``analyze BUY`` PIT (26b/34/T39). Contraste: ranking aleatorio rotado."""
    from scripts.run_ranking_t21 import load_bars_signals_scores
    from scripts.run_tp_cal_replay_t23 import buy_entries

    tickers = parse_universe_file(_HERE.parent / universe)
    bars_by, sigs_by, score_by, _missing = load_bars_signals_scores(tickers, period, warmup)
    entries = buy_entries(bars_by, sigs_by, warmup)
    a = simulate_portfolio(
        entries,
        bars_by,
        sigs_by,
        rank_score=lambda t, d: float((score_by.get(t) or {}).get(d, 0.0)),
        **common,
    )
    b = simulate_portfolio(
        entries, bars_by, sigs_by, rank_score=lambda t, d: neutral_rank(12345, d, t), **common
    )
    return (
        a,
        b,
        {"n_tickers": len(bars_by), "n_entries": len(entries), "arm_a": "B1_score", "arm_b": "N_rot_0"},
    )


POPULATIONS = {"anomaly": population_anomaly, "analyze": population_analyze}


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="REGIME-POWER — Tarea 46")
    p.add_argument("--population", choices=sorted(POPULATIONS), default="anomaly")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--seed", type=int, default=BOOT_SEED)
    p.add_argument(
        "--allow-stale-artifacts",
        action="store_true",
        help="no abortar si el cohorte de artefactos está desalineado (T30)",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    cap_days = args.cap_days if args.population == "anomaly" else 250
    common = _common(args.max_positions, cap_days, args.capital)
    # T30 — frescura del cohorte, ANTES de pagar la corrida (tarea 76). La ventana
    # que declara `artifact_window` es min(starts)..max(ends), así que un solo
    # artefacto desalineado la corre sin que se note. Falla ruidoso (política T22).
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts, file=log)
    except StaleArtifactError as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3

    announce(
        args.max_positions,
        args.universe,
        0,
        eval_mode=EVAL_MODE,
        fill_mode=HARNESS_FILL_MODE,
        live_gates=LIVE_GATES,
        file=log,
    )
    print(f"Población: {args.population} · cap_days={cap_days}\n", file=log)

    res_a, res_b, meta = POPULATIONS[args.population](args.universe, args.period, args.warmup, common)
    print(
        f"{meta['n_tickers']} tickers · {meta['n_entries']} entradas · "
        f"brazos {meta['arm_a']} vs {meta['arm_b']}\n",
        file=log,
    )

    stats = analyse(res_a, res_b, n_resamples=args.resamples, seed=args.seed)
    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "population": args.population,
        "cap_days": cap_days,
        "max_positions": args.max_positions,
        "eval_mode": EVAL_MODE,
        "live_gates": LIVE_GATES,
        "resamples": args.resamples,
        "published_tolerance_pts": PUBLISHED_TOLERANCE_PTS,
        "published_rejections": PUBLISHED_REJECTIONS,
        **meta,
    }

    if args.json:
        print(json.dumps({"context": ctx, "regimes": stats}, ensure_ascii=False, indent=2, default=str))
        return 0

    _report(stats, ctx)
    return 0


def _report(stats: dict, ctx: dict):
    print("POR TRADE — lo que evalúa el criterio de régimen de la serie")
    hdr = f"{'régimen':<20}{'n':>5}{'media':>9}{'σ':>9}{'detectable':>12}{'pot(obs)':>10}{'P(signo)':>10}"
    print(hdr)
    print("-" * len(hdr))
    for r, s in stats.items():
        det = s["detectable_at_80"]
        ps = s["arm_sign"]["p_same_sign"]
        print(
            f"{r:<20}{s['n_trades']:>5}{s['mean_pts']:>+9.2f}{s['sd_pts']:>9.2f}"
            f"{('—' if det is None else f'±{det:.2f}'):>12}"
            f"{100 * s['power_for_observed']:>9.0f}%"
            f"{('—' if ps is None else f'{100 * ps:.0f}%'):>10}"
        )

    print(
        "\n  'detectable' = efecto medio más chico que se distingue de 0 con ese n y "
        "esa σ,\n  al 80% de potencia y α=0.05. 'P(signo)' = fracción de resamples "
        "que conserva el\n  signo de la media observada — si ronda 50%, el criterio "
        "tira una moneda."
    )

    print(
        f"\n  El umbral que la serie usó (C5 de 26b/34) es ±{PUBLISHED_TOLERANCE_PTS:.2f} "
        f"pts por trade.\n  Potencia para detectarlo con los n de arriba:"
    )
    for r, s in stats.items():
        print(f"    {r:<20} {100 * s['power_for_tolerance']:>5.1f}%")

    print("\nDIFERENCIA ENTRE BRAZOS — lo que evalúa C5 (26b/34)")
    hdr2 = f"{'régimen':<20}{'Δ pts':>10}{'IC95%':>22}{'P(signo)':>10}"
    print(hdr2)
    print("-" * len(hdr2))
    for r, s in stats.items():
        ds = s["delta_sign"]
        if ds is None:
            print(f"{r:<20}{'—':>10}{'—':>22}{'—':>10}")
            continue
        ci = f"[{ds['ci_low']:+.2f}, {ds['ci_high']:+.2f}]"
        print(f"{r:<20}{s['delta_pts']:>+10.2f}{ci:>22}{100 * ds['p_same_sign']:>9.0f}%")

    print("\nA NIVEL CARTERA — la versión que usan la T38 y la T39")
    hdr3 = f"{'régimen':<20}{'ret':>10}{'IC95%':>24}{'P(signo)':>10}{'días':>7}"
    print(hdr3)
    print("-" * len(hdr3))
    for r, s in stats.items():
        ps_ = s["portfolio_sign"]
        lo, hi, pss = ps_["ci_low"], ps_["ci_high"], ps_["p_same_sign"]
        print(
            f"{r:<20}{100 * s['portfolio_ret_a']:>+9.2f}%"
            f"{('—' if lo is None else f'[{100 * lo:+.1f}%, {100 * hi:+.1f}%]'):>24}"
            f"{('—' if pss is None else f'{100 * pss:.0f}%'):>10}{ps_['n']:>7}"
        )

    print("\nΔ ENTRE BRAZOS a nivel CARTERA — lo que un criterio de régimen realmente evalúa")
    hdr4 = f"{'régimen':<20}{'Δ ret':>10}{'IC95%':>24}{'P(signo)':>10}"
    print(hdr4)
    print("-" * len(hdr4))
    for r, s in stats.items():
        pd_ = s["portfolio_delta_sign"]
        if pd_["delta"] is None:
            print(f"{r:<20}{'—':>10}{'—':>24}{'—':>10}")
            continue
        ci = f"[{100 * pd_['ci_low']:+.1f}%, {100 * pd_['ci_high']:+.1f}%]"
        print(f"{r:<20}{100 * pd_['delta']:>+9.2f}%{ci:>24}{100 * pd_['p_same_sign']:>9.0f}%")

    print("\nLos rechazos que ese criterio produjo, contra lo detectable:")
    for label, delta in PUBLISHED_REJECTIONS.items():
        print(f"  {label:<38} Δ = {delta:+.2f} pts")


if __name__ == "__main__":
    raise SystemExit(main())
