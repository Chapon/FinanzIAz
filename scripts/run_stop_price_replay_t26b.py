"""
Runner del replay de "contra qué precio se decide la barrera" — Tarea 26b (STOP-PRICE).

Pre-registro con criterios CONGELADOS: ``docs/stop_price_prereg_t26b_2026-08-14.md``.
Sale de la T26 (`docs/stop_cal_t26_2026-08-13.md` §4) y del desvío que la T32 dejó
declarado en ``analysis/harness_config.py``.

La pregunta
-----------
Los cinco harness de salida de la serie deciden la barrera ATR contra el **close
diario**; el engine vivo la decide contra el **precio corriente intradía**
(``get_bulk_prices``, scan ~15 min). Son dos reglas distintas, no dos calibraciones.

Qué hace
--------
1. Rejilla **2 modos × 5 múltiplos**: ``{close, touch} × {1.0, 1.5, 2.0, 2.5, 3.0}``.
   **BASELINE = ``touch_2.0``** (la regla viva), **candidato = ``close_2.0``**.
2. Aplica los 6 criterios de §6, con C6 = consistencia del signo a través del
   múltiplo (≥3 de 5), el análogo de la dosis-respuesta de la T26 en esta rejilla.
3. **Sanity corregido con la lección de la T26:** el oráculo se compara contra el
   **control igualado en tasa** (``AZAR_MISMA_TASA``), NO contra el baseline — que
   fue exactamente el error que invalidó aquella corrida.
4. Reporta la curva por múltiplo en los dos modos: la segunda pregunta (descriptiva,
   **no decide**) es si sobrevive bajo ``touch`` la monotonía "más ajustado gana".

Ninguno de los dos modos **es** producción: la acotan (``close`` es la cota inferior
de frecuencia de disparo, ``touch`` la superior). Sin red, sin tocar ``finanzias.db``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import AtrParams
from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    announce,
    artifact_window,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    STRESS_REGIMES,
    paired_block_bootstrap,
    regime_for_date,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_ranking_t21 import trade_overlap
from scripts.run_stop_cal_replay_t26 import (
    RANDOM_KEEP_PROB,
    _oracle_stop_filter,
    random_stop_filter,
    summarise,
)
from scripts.run_tp_cal_replay_t23 import (
    aligned_returns,
    buy_entries,
    load_bars_signals,
)

CAP_DAYS = 250

# §4 — la rejilla. El orden importa para la lectura de la curva.
MULTS: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5, 3.0)
MODES: tuple[str, ...] = ("touch", "close")
LIVE_MULT = 2.0

BASELINE_ARM = "touch_2.0"  # la regla que el engine ejecuta HOY
CANDIDATE_ARM = "close_2.0"  # aislar el efecto de la regla, múltiplo vivo fijo

ORACLE_ARM = "ORACULO_STOP"
RANDOM_KEEP_ARM = "AZAR_MISMA_TASA"

# §6 — criterios congelados.
KILL_MIN_DCAGR = 0.0050  # C1
KILL_DD_TOL = 0.0200  # C2
KILL_SHARPE_TOL = 0.05  # C4
KILL_REGIME_TOL = 0.05  # C5
KILL_MIN_CONSISTENT = 3  # C6 — ≥3 de los 5 múltiplos con Δ ≥ 0

# §5 — sanity del instrumento, contra el CONTROL IGUALADO (no contra el baseline).
SANITY_ORACLE_VS_RANDOM_CAGR = 0.0150  # ≥ +1.50pp
SANITY_ORACLE_VS_RANDOM_DD = 0.0500  # maxDD ≤ azar − 5.00pp
SANITY_MIN_TRADE_DIFF = 0.10

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345


def arm_name(mode: str, mult: float) -> str:
    return f"{mode}_{mult:.1f}"


def build_arms(fill_mode: str = "decision") -> dict[str, dict]:
    """{nombre: kwargs propios del brazo} — rejilla + los dos de sanity.

    ``fill_mode="decision"`` en **todos** los brazos: el fill legacy (``resting``)
    llena la barrera en el **nivel** también cuando la decisión fue al close, que
    es un precio mejor que el close y anterior a la información que decidió. Ese
    look-ahead vale **+5.01 pp de CAGR** para ``close_2.0`` (§3 del veredicto) y
    sesga la comparación entera a favor del candidato. Se deja el legacy accesible
    (``--fill-mode resting``) sólo para reproducir la corrida invalidada.
    """
    arms: dict[str, dict] = {}
    for mode in MODES:
        for m in MULTS:
            arms[arm_name(mode, m)] = {
                "atr_p": AtrParams(stop_mult=m),
                "eval_mode": mode,
                "fill_mode": fill_mode,
            }
    base_p = AtrParams(stop_mult=LIVE_MULT)
    # Los dos de sanity corren en el modo del BASELINE (``touch``), que es la regla
    # viva: se valida el instrumento donde se dicta el veredicto.
    arms[ORACLE_ARM] = {
        "atr_p": base_p,
        "eval_mode": "touch",
        "fill_mode": fill_mode,
        "stop_filter": _oracle_stop_filter,
    }
    arms[RANDOM_KEEP_ARM] = {
        "atr_p": base_p,
        "eval_mode": "touch",
        "fill_mode": fill_mode,
        "stop_filter": random_stop_filter(RANDOM_KEEP_PROB),
    }
    return arms


def regime_trade_breakdown(res: PortfolioResult) -> dict:
    out: dict[str, dict] = {}
    for name in ["bull_normal"] + [r.name for r in STRESS_REGIMES]:
        tr = [t for t in res.trades if t.regime == name]
        out[name] = {
            "n": len(tr),
            "mean_ret_pts": 100.0 * statistics.fmean([t.ret for t in tr]) if tr else 0.0,
        }
    return out


# ── Sanity (§5) ──────────────────────────────────────────────────────────────


def evaluate_sanity(summaries: dict, results: dict) -> dict:
    orac, azar = summaries[ORACLE_ARM], summaries[RANDOM_KEEP_ARM]
    diff = trade_overlap(results[BASELINE_ARM], results[CANDIDATE_ARM])
    s = {
        "accounting": all(summaries[n]["accounting_ok"] for n in results),
        "oracle_vs_random_cagr": orac["cagr"] - azar["cagr"],
        "oracle_vs_random_dd": orac["max_dd"] - azar["max_dd"],
        "trade_diff_share": diff,
        "rule_bites": diff >= SANITY_MIN_TRADE_DIFF,
    }
    s["oracle_quality_ok"] = bool(
        s["oracle_vs_random_cagr"] >= SANITY_ORACLE_VS_RANDOM_CAGR
        and s["oracle_vs_random_dd"] <= -SANITY_ORACLE_VS_RANDOM_DD
    )
    s["all_ok"] = bool(s["accounting"] and s["oracle_quality_ok"] and s["rule_bites"])
    return s


# ── Regla de decisión (§6) ───────────────────────────────────────────────────


def consistency_across_mults(summaries: dict) -> tuple[int, dict[float, float]]:
    """C6 — en cuántos múltiplos ``close`` no rinde menos que ``touch``."""
    deltas = {
        m: summaries[arm_name("close", m)]["cagr"] - summaries[arm_name("touch", m)]["cagr"] for m in MULTS
    }
    return sum(1 for d in deltas.values() if d >= 0.0), deltas


def evaluate(summaries: dict, regimes: dict, boot) -> dict:
    base, cand = summaries[BASELINE_ARM], summaries[CANDIDATE_ARM]
    b_sh = base["sharpe"] if base["sharpe"] is not None else -1e9
    c_sh = cand["sharpe"] if cand["sharpe"] is not None else -1e9

    reg_delta: dict[str, float] = {}
    reg_ok = True
    for r, v in regimes[CANDIDATE_ARM].items():
        d = v["mean_ret_pts"] - regimes[BASELINE_ARM][r]["mean_ret_pts"]
        reg_delta[r] = d
        if d < -KILL_REGIME_TOL:
            reg_ok = False

    n_consistent, mult_deltas = consistency_across_mults(summaries)
    c1 = (cand["cagr"] - base["cagr"]) >= KILL_MIN_DCAGR
    c2 = cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL
    c3 = boot is not None and boot.ci_low > 0.0
    c4 = c_sh >= b_sh - KILL_SHARPE_TOL
    c5 = reg_ok
    c6 = n_consistent >= KILL_MIN_CONSISTENT
    return {
        "dcagr": cand["cagr"] - base["cagr"],
        "dd_delta": cand["max_dd"] - base["max_dd"],
        "sharpe_delta": c_sh - b_sh,
        "regime_delta": reg_delta,
        "n_consistent": n_consistent,
        "mult_deltas": mult_deltas,
        "c1_cagr": c1,
        "c2_maxdd": c2,
        "c3_boot": c3,
        "c4_sharpe": c4,
        "c5_regime": c5,
        "c6_consistency": c6,
        "ship": bool(c1 and c2 and c3 and c4 and c5 and c6),
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay del precio de evaluación (Tarea 26b)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument(
        "--fill-mode",
        choices=("decision", "resting"),
        default="decision",
        help="'resting' reproduce la corrida invalidada por look-ahead",
    )
    # Enabler de la Tarea 47 (§3 de su pre-registro). Default OFF = la corrida
    # publicada. Acá NO es un nivel común: los dos brazos de decisión disparan stop
    # a tasas muy distintas (19,9% vs 13,4%), así que la exposición a Gate 5 difiere.
    p.add_argument(
        "--live-gates",
        action="store_true",
        help="modela los gates de re-entrada del engine vivo (Gate 5 anti-whipsaw / 5b anti-churn, Tarea 34)",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)

    entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not entries:
        print("Sin entradas BUY — nada que evaluar.", file=sys.stderr)
        return 1
    # El banner declara la regla del BASELINE (``touch``, la viva); la rejilla corre
    # los dos modos, y eso lo dice la línea de abajo.
    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=artifact_window(bars_by),
        eval_mode="touch",
        fill_mode=args.fill_mode,
        live_gates=args.live_gates,
    )
    print(f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)}")
    print(
        f"BASELINE = {BASELINE_ARM} (la regla viva) · candidato = {CANDIDATE_ARM} "
        f"· la rejilla corre los DOS modos de evaluación"
    )
    print(
        f"fill_mode = {args.fill_mode}"
        + (
            "  <-- LEGACY: llena la barrera en el NIVEL aunque haya decidido al close "
            "(look-ahead, corrida invalidada)"
            if args.fill_mode == "resting"
            else "  (la barrera se llena al precio que tomó la decisión)"
        )
        + "\n"
    )

    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        live_gates=args.live_gates,
    )
    arms = build_arms(args.fill_mode)
    results = {n: simulate_portfolio(entries, bars_by, sigs_by, **kw, **common) for n, kw in arms.items()}
    summaries = {n: summarise(r) for n, r in results.items()}
    regimes = {n: regime_trade_breakdown(results[n]) for n in (BASELINE_ARM, CANDIDATE_ARM)}

    rets = aligned_returns(results, [BASELINE_ARM, CANDIDATE_ARM])
    boot = paired_block_bootstrap(
        rets[BASELINE_ARM], rets[CANDIDATE_ARM], block=BOOT_BLOCK, n_resamples=args.resamples, seed=BOOT_SEED
    )

    sanity = evaluate_sanity(summaries, results)
    verdict = evaluate(summaries, regimes, boot)
    if not sanity["all_ok"]:
        verdict["ship"] = False
        verdict["outcome"] = (
            "CORRIDA INVÁLIDA — falla un sanity del §5; no hay veredicto (el instrumento no está validado)."
        )

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries": len(entries),
        "max_positions": args.max_positions,
        "cap_days": args.cap_days,
        "universe": args.universe,
        "live_gates": args.live_gates,
        "verdict": verdict,
        "sanity": sanity,
        "boot": {
            "observed": boot.observed,
            "ci_low": boot.ci_low,
            "ci_high": boot.ci_high,
            "p_value": boot.p_value,
            "block": boot.block,
            "n_resamples": boot.n_resamples,
        },
    }
    if args.json:
        print(
            json.dumps(
                {"context": ctx, "summaries": summaries, "regimes": regimes},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    _report(summaries, regimes, verdict, sanity, boot)
    return 0


def _f(x, w=8, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries, regimes, verdict, sanity, boot):
    hdr = f"{'brazo':<18}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'%stop':>8}{'%trail':>8}{'%tp':>7}{'tomad':>7}"
    print(hdr)
    print("-" * len(hdr))
    for mode in MODES:
        for m in MULTS:
            n = arm_name(mode, m)
            s = summaries[n]
            mark = "BASE" if n == BASELINE_ARM else "*cand" if n == CANDIDATE_ARM else ""
            print(
                f"{n:<18}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9, 2)}"
                f"{_f(s['max_dd'], 9, 1, '%')}{_f(s['stop_share'], 8, 1, '%')}"
                f"{_f(s['exit_mix'].get('atr_trail', 0), 8, 1, '%')}"
                f"{_f(s['exit_mix'].get('atr_tp', 0), 7, 0, '%')}{s['n_taken']:>7}  {mark}"
            )
        print()
    for n in (ORACLE_ARM, RANDOM_KEEP_ARM):
        s = summaries[n]
        print(
            f"{n:<18}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9, 2)}"
            f"{_f(s['max_dd'], 9, 1, '%')}{_f(s['stop_share'], 8, 1, '%')}"
            f"{_f(s['exit_mix'].get('atr_trail', 0), 8, 1, '%')}"
            f"{_f(s['exit_mix'].get('atr_tp', 0), 7, 0, '%')}{s['n_taken']:>7}  sanity"
        )

    print("\nΔCAGR (close − touch) por múltiplo — §7, DESCRIPTIVO (no decide):")
    for m, d in verdict["mult_deltas"].items():
        print(
            f"  {m:.1f}×ATR  Δ {_f(d, 8, 2, '%')}   "
            f"touch {_f(summaries[arm_name('touch', m)]['cagr'], 8, 2, '%')} · "
            f"close {_f(summaries[arm_name('close', m)]['cagr'], 8, 2, '%')}"
        )

    print("\nPor régimen — ret medio por trade (pts), Δ candidato vs baseline:")
    for r in regimes[CANDIDATE_ARM]:
        b = regimes[BASELINE_ARM][r]["mean_ret_pts"]
        c = regimes[CANDIDATE_ARM][r]["mean_ret_pts"]
        print(f"  {r:<18} base {b:>+6.2f} · cand {c:>+6.2f} · Δ {verdict['regime_delta'][r]:>+6.2f}")

    print(
        f"\nΔCAGR {_f(verdict['dcagr'], 0, 2, '%')} · ΔmaxDD {_f(verdict['dd_delta'], 0, 2, '%')} · "
        f"ΔSharpe {verdict['sharpe_delta']:+.3f}"
    )
    print(
        f"Bootstrap pareado (bloques {boot.block}d, {boot.n_resamples} resamples): "
        f"IC95% [{_f(boot.ci_low, 0, 2, '%')}, {_f(boot.ci_high, 0, 2, '%')}] · p={boot.p_value:.3f}"
    )

    print("\nSanity del instrumento (§5) — contra el CONTROL IGUALADO, no el baseline:")
    print(f"  [{'OK  ' if sanity['accounting'] else 'FALLA'}] contabilidad")
    print(
        f"  [{'OK  ' if sanity['oracle_quality_ok'] else 'FALLA'}] el harness ve calidad de "
        f"salida: oráculo vs azar ΔCAGR {_f(sanity['oracle_vs_random_cagr'], 0, 2, '%')} "
        f"(≥+1.50pp) · ΔmaxDD {_f(sanity['oracle_vs_random_dd'], 0, 2, '%')} (≤−5.00pp)"
    )
    print(
        f"  [{'OK  ' if sanity['rule_bites'] else 'FALLA'}] la regla muerde "
        f"({sanity['trade_diff_share'] * 100:.1f}% ≥ 10%)"
    )

    print("\nCriterios (§6):")
    for k, label in [
        ("c1_cagr", "C1 ΔCAGR ≥ +0.50pp"),
        ("c2_maxdd", "C2 maxDD ≤ base + 2.00pp"),
        ("c3_boot", "C3 bootstrap pareado IC95% inf > 0"),
        ("c4_sharpe", "C4 Sharpe ≥ base − 0.05"),
        ("c5_regime", "C5 régimen robusto"),
        ("c6_consistency", f"C6 consistencia {verdict['n_consistent']}/5 múltiplos"),
    ]:
        print(f"  [{'PASA ' if verdict[k] else 'FALLA'}] {label}")
    if verdict.get("outcome"):
        print(f"\n  {verdict['outcome']}")
    print(f"\n  VEREDICTO: {'SHIP (confirmar al close)' if verdict['ship'] else 'NO-SHIP'}")


if __name__ == "__main__":
    raise SystemExit(main())
