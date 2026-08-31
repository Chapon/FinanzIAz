"""
Runner de STOP-PRICE-REDECIDE — **Tarea 47**.

Pre-registro con la regla CONGELADA:
``docs/stop_price_redecide_prereg_t47_2026-08-19.md``.

Qué re-decide y por qué
-----------------------
La **26b** comparó las dos reglas de la barrera ATR —decidida al **close diario** vs
al **toque intradía** (la viva)— y midió a 10 slots **+3.39 pp de CAGR**, **−4.88 pp de
maxDD** y bootstrap **[+0.03, +6.30] p=0.024**. Pasó C1-C4 y C6 y cerró **NO-SHIP por
C5 solo**. La **46** midió después que ese C5 tenía **5,1% de potencia** — o sea α.

Esta tarea la vuelve a decidir con un criterio que discrimina. **Reusa intactos**
población, brazos, múltiplos, sanity y C1/C2/C3/C4/C6 de la 26b; lo único que cambia es:

* **C5′** — la tolerancia **se computa** (``detectable_mean_effect``), el gate va sobre el
  **agregado de las tres ventanas de stress** y falla sólo si el **IC95% está entero** del
  lado malo. Las ventanas individuales son descriptivo obligatorio.
* **C7 (nuevo)** — la sensibilidad a 5 slots pasa a **gate duro**. La 26b ya la midió y
  **falla ahí** (C3 con IC [−0.40, +8.88]): se declara sabiendo que empuja a NO-SHIP.
* **``live_gates=True``** — los dos brazos disparan stop a tasas muy distintas (19,9% vs
  13,4%), así que los gates de re-entrada **no son un nivel común** y no pueden darse por
  cancelados (criterio de la T33 aplicado al revés que en la T21).

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py``.
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

from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    POPULATION_LIVE_ACCT2,
    REPRO_OK,
    WINDOW_REFRESH_2026_08_09,
    announce,
    artifact_window,
    reproduction_check,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    BULL_NORMAL,
    STRESS_REGIMES,
    block_delta_sign_stability,
    detectable_mean_effect,
    paired_block_bootstrap,
    regime_for_date,
    regime_window_returns,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_rank_neutral_t39 import aligned_daily
from scripts.run_regime_power_t46 import _delta_samples, _summarise_samples
from scripts.run_stop_cal_replay_t26 import summarise
from scripts.run_stop_price_replay_t26b import (
    BASELINE_ARM,
    CANDIDATE_ARM,
    CAP_DAYS,
    KILL_DD_TOL,
    KILL_MIN_CONSISTENT,
    KILL_MIN_DCAGR,
    KILL_SHARPE_TOL,
    build_arms,
    consistency_across_mults,
    evaluate_sanity,
)
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

FILL_MODE = "decision"
LIVE_GATES = True

# §4 — C5′. La tolerancia MATERIAL se declara acá; la efectiva es el máximo entre
# ésta y lo detectable, que sale de la muestra.
TOL_MATERIAL_PTS = 1.00
STRESS_NAMES = tuple(r.name for r in STRESS_REGIMES)
REGIMES = (BULL_NORMAL, *STRESS_NAMES)

# §5.4 — el sanity de reproducción: los números publicados por la 26b, sin gates.
REPRO_EXPECTED = {"close_2.0": 0.0780, "touch_2.0": 0.0441}
REPRO_TOL = 0.0005

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345


# ── C5′ — el criterio de régimen con potencia ────────────────────────────────


def per_trade_pts(res: PortfolioResult) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {r: [] for r in REGIMES}
    for t in res.trades:
        out.setdefault(t.regime, []).append(100.0 * t.ret)
    return out


def regime_criterion(base: PortfolioResult, cand: PortfolioResult, *, n_resamples: int, seed: int) -> dict:
    """C5′ (§4): tolerancia computada + gate sobre el AGREGADO de stress con IC.

    Falla **sólo** si el IC95% del Δ del agregado está **enteramente por debajo de
    −tol**. Rechazar por el punto estimado con el IC cruzando cero es exactamente lo
    que la 46 midió que no tiene potencia.
    """
    pb, pc = per_trade_pts(base), per_trade_pts(cand)
    pooled_b = [v for r in STRESS_NAMES for v in pb.get(r, [])]
    pooled_c = [v for r in STRESS_NAMES for v in pc.get(r, [])]

    windows: dict[str, dict] = {}
    for r in (*REGIMES, "stress_POOLED"):
        xs = pooled_b if r == "stress_POOLED" else pb.get(r, [])
        ys = pooled_c if r == "stress_POOLED" else pc.get(r, [])
        n = len(xs)
        sd = statistics.stdev(xs) if n > 1 else 0.0
        delta = (statistics.fmean(ys) if ys else 0.0) - (statistics.fmean(xs) if xs else 0.0)
        stab = None
        if xs and ys:
            stab = _summarise_samples(_delta_samples(xs, ys, n_resamples=n_resamples, seed=seed), delta)
        windows[r] = {
            "n_base": n,
            "n_cand": len(ys),
            "sd_pts": sd,
            "delta_pts": delta,
            "detectable": detectable_mean_effect(sd, n) if n > 1 else None,
            "stability": stab,
        }

    pooled = windows["stress_POOLED"]
    det = pooled["detectable"]
    usable_det = det if (det is not None and math.isfinite(det)) else 0.0
    tol = max(TOL_MATERIAL_PTS, usable_det)
    ci_high = pooled["stability"]["ci_high"] if pooled["stability"] else None
    # Pasa salvo que la evidencia entera esté del lado malo.
    passes = not (ci_high is not None and ci_high < -tol)
    return {
        "tolerance_pts": tol,
        "material_pts": TOL_MATERIAL_PTS,
        "detectable_pts": det,
        "pooled_delta_pts": pooled["delta_pts"],
        "pooled_ci_high": ci_high,
        "pooled_ci_low": (pooled["stability"]["ci_low"] if pooled["stability"] else None),
        "passes": passes,
        "windows": windows,
    }


# ── §6 — regla de decisión ───────────────────────────────────────────────────


def evaluate(summaries: dict, c5: dict, boot, sens: dict | None) -> dict:
    base, cand = summaries[BASELINE_ARM], summaries[CANDIDATE_ARM]
    b_sh = base["sharpe"] if base["sharpe"] is not None else -1e9
    c_sh = cand["sharpe"] if cand["sharpe"] is not None else -1e9
    n_consistent, mult_deltas = consistency_across_mults(summaries)

    c1 = (cand["cagr"] - base["cagr"]) >= KILL_MIN_DCAGR
    c2 = cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL
    c3 = boot is not None and boot.ci_low > 0.0
    c4 = c_sh >= b_sh - KILL_SHARPE_TOL
    c5_ok = bool(c5["passes"])
    c6 = n_consistent >= KILL_MIN_CONSISTENT
    c7 = bool(sens) and bool(sens.get("c1")) and bool(sens.get("c3"))

    accounting = base["accounting_ok"] and cand["accounting_ok"]
    ship = bool(accounting and c1 and c2 and c3 and c4 and c5_ok and c6 and c7)

    if ship:
        outcome = (
            "SHIP — se cabla `paper_atr_confirm_at_close` con default OFF; "
            "prenderlo es decisión de Chapa (§7)."
        )
    elif c1 and c2 and c3 and c4 and c5_ok and c6 and not c7:
        outcome = (
            "NO-SHIP — C7: el efecto no sobrevive a 5 slots. Está declarado ex "
            "ante que un efecto que sólo existe con 10 slots es FRÁGIL, y una "
            "regla de salida frágil no se cabla en la cuenta viva."
        )
    elif not c5_ok:
        outcome = (
            "NO-SHIP — C5′: el IC95% del Δ en el agregado de stress está entero "
            "del lado malo de una tolerancia detectable. Este rechazo SÍ "
            "significa algo (a diferencia del C5 de la 26b)."
        )
    else:
        outcome = "NO-SHIP — no pasa el AND de los siete criterios."

    return {
        "dcagr": cand["cagr"] - base["cagr"],
        "dd_delta": cand["max_dd"] - base["max_dd"],
        "sharpe_delta": c_sh - b_sh,
        "n_consistent": n_consistent,
        "mult_deltas": mult_deltas,
        "c1_cagr": c1,
        "c2_maxdd": c2,
        "c3_boot": c3,
        "c4_sharpe": c4,
        "c5_regime": c5_ok,
        "c6_consistency": c6,
        "c7_sensitivity": c7,
        "ship": ship,
        "outcome": outcome,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="STOP-PRICE-REDECIDE — Tarea 47")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--sens-max-positions", type=int, default=5)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument(
        "--no-sensitivity",
        action="store_true",
        help="saltea la corrida a 5 slots (C7 queda sin evaluar ⇒ NO-SHIP)",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)
    entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not entries:
        print("Sin entradas BUY.", file=sys.stderr)
        return 1

    cfg = announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=artifact_window(bars_by),
        eval_mode="touch",
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
        file=log,
    )
    print(f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)}", file=log)
    print(f"BASELINE = {BASELINE_ARM} (la regla viva) · candidato = {CANDIDATE_ARM}\n", file=log)

    common = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        live_gates=LIVE_GATES,
    )
    arms = build_arms(FILL_MODE)
    results: dict[str, PortfolioResult] = {}
    for i, (n, kw) in enumerate(arms.items(), 1):
        print(f"  [{args.max_positions} slots] {i}/{len(arms)} {n} …", file=log, flush=True)
        results[n] = simulate_portfolio(entries, bars_by, sigs_by, **kw, **common)
    summaries = {n: summarise(r) for n, r in results.items()}

    daily = aligned_daily(results, [BASELINE_ARM, CANDIDATE_ARM])
    boot = paired_block_bootstrap(
        [r for _, r in daily[BASELINE_ARM]],
        [r for _, r in daily[CANDIDATE_ARM]],
        block=BOOT_BLOCK,
        n_resamples=args.resamples,
        seed=BOOT_SEED,
    )
    c5 = regime_criterion(
        results[BASELINE_ARM], results[CANDIDATE_ARM], n_resamples=args.resamples, seed=BOOT_SEED
    )

    # Descriptivo #2 (§4): la versión de CARTERA, pareada. No es el gate.
    port = {}
    for r in (*REGIMES, "stress_POOLED"):

        def _in(dt: str, _r=r) -> bool:
            reg = regime_for_date(dt)
            return reg in STRESS_NAMES if _r == "stress_POOLED" else reg == _r

        port[r] = block_delta_sign_stability(
            [v for dt, v in daily[BASELINE_ARM] if _in(dt)],
            [v for dt, v in daily[CANDIDATE_ARM] if _in(dt)],
            block=BOOT_BLOCK,
            n_resamples=args.resamples,
            seed=BOOT_SEED,
        )
    port_levels = {n: regime_window_returns(daily[n]) for n in (BASELINE_ARM, CANDIDATE_ARM)}

    # C7 — sensibilidad a 5 slots (los dos brazos de decisión).
    sens = None
    if not args.no_sensitivity:
        print(f"  [{args.sens_max_positions} slots] sensibilidad …", file=log, flush=True)
        s_common = dict(common, max_positions=args.sens_max_positions)
        s_res = {
            n: simulate_portfolio(entries, bars_by, sigs_by, **arms[n], **s_common)
            for n in (BASELINE_ARM, CANDIDATE_ARM)
        }
        s_sum = {n: summarise(r) for n, r in s_res.items()}
        s_daily = aligned_daily(s_res, [BASELINE_ARM, CANDIDATE_ARM])
        s_boot = paired_block_bootstrap(
            [r for _, r in s_daily[BASELINE_ARM]],
            [r for _, r in s_daily[CANDIDATE_ARM]],
            block=BOOT_BLOCK,
            n_resamples=args.resamples,
            seed=BOOT_SEED,
        )
        sens = {
            "max_positions": args.sens_max_positions,
            "base_cagr": s_sum[BASELINE_ARM]["cagr"],
            "cand_cagr": s_sum[CANDIDATE_ARM]["cagr"],
            "dcagr": s_sum[CANDIDATE_ARM]["cagr"] - s_sum[BASELINE_ARM]["cagr"],
            "ci_low": s_boot.ci_low,
            "ci_high": s_boot.ci_high,
            "p": s_boot.p_value,
            "c1": (s_sum[CANDIDATE_ARM]["cagr"] - s_sum[BASELINE_ARM]["cagr"]) >= KILL_MIN_DCAGR,
            "c3": s_boot.ci_low > 0.0,
        }

    # §5.4 — reproducción de la 26b: los mismos brazos SIN gates.
    print("  reproducción de la 26b (sin gates) …", file=log, flush=True)
    repro_common = dict(common, live_gates=False)
    repro = {}
    for n in (BASELINE_ARM, CANDIDATE_ARM):
        r = simulate_portfolio(entries, bars_by, sigs_by, **arms[n], **repro_common)
        repro[n] = summarise(r)["cagr"]
    # Tarea 48: consciente de la ventana rodante de los artefactos. Tarea 52:
    # y de la población — las anclas de la 26b se midieron sobre el universo vivo.
    win = artifact_window(bars_by)
    pop = cfg.population(len(entries))
    repro_checks = {
        n: reproduction_check(
            repro[n],
            REPRO_EXPECTED[n],
            tol=REPRO_TOL,
            current=win,
            measured_on=WINDOW_REFRESH_2026_08_09,
            population=pop,
            measured_over=POPULATION_LIVE_ACCT2,
        )
        for n in repro
    }
    repro_ok = all(st == REPRO_OK for st, _ in repro_checks.values())

    sanity = evaluate_sanity(summaries, results)
    sanity["repro"] = repro
    sanity["repro_ok"] = repro_ok
    sanity["repro_states"] = {n: st for n, (st, _) in repro_checks.items()}
    sanity["repro_reasons"] = {n: why for n, (_, why) in repro_checks.items()}
    sanity["all_ok"] = bool(sanity["all_ok"] and repro_ok)

    verdict = evaluate(summaries, c5, boot, sens)
    if not sanity["all_ok"]:
        verdict["ship"] = False
        verdict["outcome"] = (
            "CORRIDA INVÁLIDA — falla un sanity del §5; no hay "
            "veredicto. No se re-especifica nada para salvarla."
        )

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries": len(entries),
        "max_positions": args.max_positions,
        "cap_days": args.cap_days,
        "fill_mode": FILL_MODE,
        "live_gates": LIVE_GATES,
        "verdict": verdict,
        "sanity": sanity,
        "c5": c5,
        "sensitivity": sens,
        "portfolio_delta": port,
        "portfolio_levels": port_levels,
        "boot": {
            "observed": boot.observed,
            "ci_low": boot.ci_low,
            "ci_high": boot.ci_high,
            "p_value": boot.p_value,
        },
    }
    if args.json:
        print(json.dumps({"context": ctx, "summaries": summaries}, ensure_ascii=False, indent=2, default=str))
        return 0

    _report(summaries, ctx, verdict, sanity, boot, c5)
    return 0


def _f(x, w=9, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries, ctx, verdict, sanity, boot, c5):
    hdr = f"{'brazo':<18}{'CAGR':>10}{'Sharpe':>9}{'maxDD':>9}{'tomad':>8}"
    print(hdr)
    print("-" * len(hdr))
    for n, s in summaries.items():
        tag = {BASELINE_ARM: "BASE (la regla viva)", CANDIDATE_ARM: "*CANDIDATO"}.get(n, "")
        print(
            f"{n:<18}{_f(s['cagr'], 10, 2, '%')}{_f(s['sharpe'], 9, 2)}"
            f"{_f(s['max_dd'], 9, 1, '%')}{s['n_taken']:>8}  {tag}"
        )

    print("\nSanity (§5):")
    print(f"  [{'OK' if sanity['accounting'] else 'FALLA'}] contabilidad")
    print(
        f"  [{'OK' if sanity['oracle_quality_ok'] else 'FALLA'}] el oráculo le gana al "
        f"control IGUALADO en tasa: +{100 * sanity['oracle_vs_random_cagr']:.2f}pp de CAGR"
    )
    print(
        f"  [{'OK' if sanity['rule_bites'] else 'FALLA'}] la regla muerde: "
        f"{100 * sanity['trade_diff_share']:.1f}% de trades distintos"
    )
    rp = sanity["repro"]
    print(
        f"  [{'/'.join(sorted(set(sanity.get('repro_states', {}).values()))) or 'FALLA'}]"
        f" reproduce la 26b sin gates: "
        + " · ".join(f"{n} {100 * v:.2f}% (esp. {100 * REPRO_EXPECTED[n]:.2f}%)" for n, v in rp.items())
    )

    det_pts = c5["detectable_pts"]
    det_txt = "—" if det_pts is None else f"{det_pts:.2f}"
    print(
        f"\nC5′ — régimen CON POTENCIA (§4). Tolerancia efectiva = "
        f"{c5['tolerance_pts']:.2f} pts "
        f"(material {c5['material_pts']:.2f} · detectable {det_txt})"
    )
    hdr2 = f"{'ventana':<20}{'n':>6}{'σ':>8}{'detect.':>10}{'Δ pts':>9}{'IC95%':>20}"
    print(hdr2)
    print("-" * len(hdr2))
    for r, w in c5["windows"].items():
        st = w["stability"]
        ci = "—" if st is None else f"[{st['ci_low']:+.2f}, {st['ci_high']:+.2f}]"
        det = "—" if w["detectable"] is None else f"±{w['detectable']:.2f}"
        star = "  ← GATE" if r == "stress_POOLED" else ""
        print(f"{r:<20}{w['n_base']:>6}{w['sd_pts']:>8.2f}{det:>10}{w['delta_pts']:>+9.2f}{ci:>20}{star}")
    print("  Las ventanas individuales son DESCRIPTIVO: no pueden producir un rechazo.")

    print("\nΔ a nivel CARTERA por ventana (segundo descriptivo, pareado — NO es gate):")
    for r, st in ctx["portfolio_delta"].items():
        if st["delta"] is None:
            continue
        print(
            f"  {r:<20} Δ {100 * st['delta']:>+8.2f}%  "
            f"[{100 * st['ci_low']:+.1f}%, {100 * st['ci_high']:+.1f}%]  "
            f"P(signo) {100 * st['p_same_sign']:.0f}%"
        )

    print(
        f"\nΔCAGR {_f(verdict['dcagr'], 0, 2, '%')} · ΔmaxDD {_f(verdict['dd_delta'], 0, 2, '%')}"
        f" · ΔSharpe {verdict['sharpe_delta']:+.3f}"
    )
    print(
        f"Bootstrap pareado: {100 * boot.observed:+.2f}pp · IC95% "
        f"[{100 * boot.ci_low:+.2f}, {100 * boot.ci_high:+.2f}]pp · p={boot.p_value:.3f}"
    )
    if ctx["sensitivity"]:
        s = ctx["sensitivity"]
        print(
            f"Sensibilidad a {s['max_positions']} slots: ΔCAGR {100 * s['dcagr']:+.2f}pp · "
            f"IC95% [{100 * s['ci_low']:+.2f}, {100 * s['ci_high']:+.2f}]pp"
        )
    print(f"Consistencia a través del múltiplo: {verdict['n_consistent']}/5")

    print("\nRegla de decisión (§6):")
    for k, label in [
        ("c1_cagr", "C1 ΔCAGR ≥ +0.50pp"),
        ("c2_maxdd", "C2 maxDD ≤ base + 2.00pp"),
        ("c3_boot", "C3 IC95% inferior > 0"),
        ("c4_sharpe", "C4 Sharpe ≥ base − 0.05"),
        ("c5_regime", "C5′ régimen con potencia (agregado de stress, IC)"),
        ("c6_consistency", "C6 consistencia ≥ 3/5 múltiplos"),
        ("c7_sensitivity", "C7 C1 y C3 aguantan a 5 slots"),
    ]:
        print(f"  [{'PASA' if verdict[k] else 'FALLA'}] {label}")
    print(f"\n  VEREDICTO: {verdict['outcome']}")


if __name__ == "__main__":
    raise SystemExit(main())
