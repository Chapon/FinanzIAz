"""
Runner de PRIO-EVENT — **Tarea 49**.

Pre-registro con la regla CONGELADA: ``docs/prio_event_prereg_t49_2026-08-20.md``.

La pregunta
-----------
Con **143.096 candidatos `analyze BUY` para 10 slots** (~50:1), la pieza del motor
que más veces se ejecuta es el **desempate del día**. La serie midió seis veces que
la clave que se usa hoy —el ``buy_score``— no tiene alpha, y la **39** cerró NO-SHIP
al reemplazarla por un orden neutro: sacarle la decisión al score no alcanzó.

La **45** abrió otra posibilidad, y es la primera de la serie que **no es un score**:
darle el turno al candidato sobre el que **ocurrió un evento** ese día valía
**+4.21 pp de CAGR** como *descriptivo* — con el propio veredicto declarando que el
número estaba **confundido** con *"cualquier cosa menos alfabético"*.

    ¿Le gana al desempate vivo, y sobre todo le gana a priorizar AL AZAR A LA
    MISMA TASA?

Las tres correcciones al descriptivo de la 45, todas **adversas** al candidato:

1. **Re-ordenación PURA** del pool que el engine ya tiene: sólo pueden priorizarse
   las entradas que son ``analyze BUY`` **y** anomalía (920 de las 1.236). Se le
   saca la parte que agregaba ~316 candidatos nuevos.
2. **``cap_days=250``** (la tenencia del engine), no el 20 heredado del marco de la
   T11b con el que se midió el +4.21 pp. Cierra de paso la tarea 50.
3. **El gate es el control IGUALADO EN TASA** (20 brazos de prioridad aleatoria con
   los mismos días, la misma cantidad por día y el mismo ``buy_score`` de fondo), no
   el baseline. Es la lección de la **T26** aplicada al eje del turno.

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py``/``strategies.py``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.anomaly_signal import AnomalyParams, build_anomaly_entries
from analysis.exit_replay import AtrParams
from analysis.harness_config import (
    HARNESS_FILL_MODE,
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    POPULATION_LIVE_ACCT2,
    REPRO_OK,
    WINDOW_REFRESH_2026_09_01_LIVE,
    SignalStoreGapError,
    StaleArtifactError,
    announce,
    announce_artifacts,
    announce_signal_store,
    artifact_window,
    reproduction_check,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.rank_policy import rate_matched_priority
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    paired_block_bootstrap,
    regime_for_date,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_anom_profile_t45 import (
    merge_entries,
    regime_criterion,
)
from scripts.run_anomaly_replay_t11b import _pct, load_bars_signals_volume
from scripts.run_rank_neutral_t39 import aligned_daily, policy_series
from scripts.run_ranking_t21 import (
    precompute_realized,
    summarise,
    trade_overlap,
)
from scripts.run_tp_cal_replay_t23 import buy_entries

# ── §3 — población y config congeladas ───────────────────────────────────────
CAP_DAYS = 250  # la tenencia del engine (familia T21/T23/T26/T39)
REPRO_CAP_DAYS = 20  # la del marco T11b/T45, sólo para el sanity §5.2
EVAL_MODE = "touch"
FILL_MODE = HARNESS_FILL_MODE
LIVE_GATES = True
ANOM_K, ANOM_M = 2.0, 1.5  # el brazo de decisión de la T11b, congelado

# ── §2 — brazos ──────────────────────────────────────────────────────────────
BASELINE_ARM = "B1_score"
CANDIDATE_ARM = "E_prio_anom"
ALPHA_ARM = "A_alpha"
MERGED_ARM = "E_merged_prio"
CONTROL_PREFIX = "R_rand_"
ORACLE_ARM = "ORACULO_PRIO"
ANTI_ORACLE_ARM = "ANTI_ORACULO_PRIO"
N_SEEDS = 20
CONTROL_SEED_BASE = 60_000
PRIO_BOOST = 10.0  # el score vive en [0,1] ⇒ +10 garantiza la prioridad

# ── §6 — kill-criteria ───────────────────────────────────────────────────────
KILL_MIN_DCAGR = 0.0050  # C1: ≥ +0.50 pp sobre B1_score
KILL_CONTROL_PCTILE = 95  # C2: > p95 de las 20 semillas
KILL_DD_TOL = 0.0300  # C3: maxDD ≤ base + 3.00 pp

# ── §5 — sanity ──────────────────────────────────────────────────────────────
# §5.4' (ENMIENDA 2026-08-20, `docs/prio_event_enmienda_t49_2026-08-20.md`): el
# umbral de +5.00 pp del pre-registro venia de la T21 §5.2, donde el oraculo es de
# POTENCIA COMPLETA (reordena todos los candidatos de todos los dias). El de aca
# esta IGUALADO EN TASA -- mueve 920 turnos sobre 143.096 candidatos --, asi que ese
# umbral no medía el instrumento sino el techo de la intervencion, que es lo que el
# §6 existe para decidir. El reemplazo va contra LA BANDA DE LOS 20 CONTROLES (la
# misma que usa C2), o sea que no se elige: sale de la muestra.
SANITY_ORACLE_PCTILE = 95  # ORACULO_PRIO > p95 de la banda del control
SANITY_MIN_TRADE_DIFF = 0.10  # ≥10% de trades distintos (umbral T21 §5.4)
SANITY_T33_CAGR = (
    0.0081  # docs/fill_lookahead_t33_2026-08-16.md §6  # re-anclado 2026-09-01 (tarea 68), era 0.0197
)
SANITY_T45_ANALYZE = (
    0.0347  # docs/anom_profile_t45_2026-08-20.md §3  # re-anclado 2026-09-01 (tarea 68), era 0.0371
)
SANITY_T45_MERGED_PRIO = 0.0761  # re-anclado 2026-09-01 (tarea 68), era 0.0792
SANITY_TOL = 0.0005  # ±0.05 pp (los publicados van a 2 decimales)

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345


def control_name(k: int) -> str:
    return f"{CONTROL_PREFIX}{k}"


# ── Brazos (§2) ──────────────────────────────────────────────────────────────


def candidates_by_date(entries, bars_by) -> dict[str, list[str]]:
    """``{fecha: [tickers candidatos ese día]}`` — idéntico entre brazos."""
    out: dict[str, list[str]] = {}
    for t, idx in entries:
        out.setdefault(bars_by[t][idx][0], []).append(t)
    return out


def keys_of(entries, bars_by) -> set[tuple[str, str]]:
    return {(t, bars_by[t][idx][0]) for t, idx in entries}


def restrict_to_pool(anom_entries, pool_entries) -> list[tuple[str, int]]:
    """§2 — el candidato es una **re-ordenación pura**: sólo puede priorizar lo que
    el engine ya ofrece.

    Es la corrección al descriptivo de la 45, que corría sobre el pool **unido** y
    por eso mezclaba *"prioriza 1.236"* con *"agrega ~316 candidatos nuevos"*. Acá
    los candidatos nuevos se descartan a propósito: agregarlos es la fuente de
    señal que la 45 rechazó por C8."""
    pool = set(pool_entries)
    return [ti for ti in anom_entries if ti in pool]


def count_by_date(keys: set[tuple[str, str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for _t, d in keys:
        out[d] = out.get(d, 0) + 1
    return out


def make_prio(prio_keys: set[tuple[str, str]], score_by) -> Callable[[str, str], float]:
    """``rank_score`` = ``PRIO_BOOST + score`` si está priorizado, si no ``score``.

    El fondo sigue siendo el ``buy_score`` vivo **en todos los brazos de este
    grupo** —candidato y controles— así que lo único que los separa es **cuáles**
    entradas se priorizan, que es exactamente el eje de la tarea."""

    def rank(ticker: str, date_iso10: str) -> float:
        s = float((score_by.get(ticker) or {}).get(date_iso10, 0.0))
        return (PRIO_BOOST + s) if (ticker, date_iso10) in prio_keys else s

    return rank


def make_binary_prio(prio_keys: set[tuple[str, str]]) -> Callable[[str, str], float]:
    """La prioridad **binaria** con desempate alfabético — la de la 45 (§5.2)."""

    def rank(ticker: str, date_iso10: str) -> float:
        return 1.0 if (ticker, date_iso10) in prio_keys else 0.0

    return rank


def oracle_prio_keys(
    cands_by_date: dict[str, list[str]], n_by_date: dict[str, int], realized: dict, *, best: bool
) -> set[tuple[str, str]]:
    """Prioridad **igualada en tasa** al mejor (o peor) retorno realizado del día.

    Mira el futuro a propósito: es el sanity de que el instrumento ve calidad de
    turno. Igualado en tasa ⇒ tiene exactamente las mismas ``n`` prioridades por
    día que el candidato, así que el umbral del §5.4 es duro."""
    out: set[tuple[str, str]] = set()
    default = -9.9 if best else 9.9
    for d, n in n_by_date.items():
        pool = cands_by_date.get(d) or []
        if n <= 0 or not pool:
            continue
        ranked = sorted(pool, key=lambda t: (realized.get((t, d), default), t), reverse=best)
        out.update((t, d) for t in ranked[:n])
    return out


# ── §6 — regla de decisión ───────────────────────────────────────────────────


def evaluate(
    base: dict, cand: dict, controls: list[dict], boot_base, boot_ctrl, c6: dict, sens: dict | None
) -> dict:
    """El AND de los siete criterios del §6."""
    ctrl_cagrs = [c["cagr"] for c in controls]
    ctrl_p95 = _pct(ctrl_cagrs, KILL_CONTROL_PCTILE) if ctrl_cagrs else float("nan")

    dcagr = cand["cagr"] - base["cagr"]
    c1 = bool(dcagr >= KILL_MIN_DCAGR)
    c2 = bool(ctrl_cagrs and cand["cagr"] > ctrl_p95)
    c3 = bool(cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL)
    c4 = bool(boot_base is not None and boot_base.ci_low > 0.0)
    c5 = bool(boot_ctrl is not None and boot_ctrl.ci_low > 0.0)
    c6_ok = bool(c6["passes"])
    c7 = sens is not None and bool(sens.get("c1")) and bool(sens.get("c2"))

    accounting = base["accounting_ok"] and cand["accounting_ok"]
    ship = bool(accounting and c1 and c2 and c3 and c4 and c5 and c6_ok and c7)

    if ship:
        outcome = (
            "SHIP — se cabla `paper_event_priority_enabled` con default OFF; "
            "prenderlo es decisión de Chapa (§7). Toca decisiones vivas de "
            "ENTRADA."
        )
    elif c1 and c4 and not (c2 and c5):
        outcome = (
            "NO-SHIP — C2/C5: el candidato le gana al desempate vivo pero NO "
            "al control igualado en tasa. O sea que el +4.21 pp de la 45 era "
            "DESORDENAR, no EL EVENTO. Es el desenlace que esta tarea existe "
            "para poder distinguir."
        )
    elif c1 and c2 and c3 and c4 and c5 and c6_ok and not c7:
        outcome = (
            "NO-SHIP — C7: el efecto no sobrevive a 5 slots. Y si además se "
            "ENCOGE, es evidencia contra el mecanismo declarado en el §3 "
            "(el turno debería decidir MÁS cuanto peor el ratio de selección)."
        )
    elif not c6_ok:
        outcome = (
            "NO-SHIP — C6: el IC95% del Δ contra el control en el agregado de "
            "stress está entero del lado malo de una tolerancia detectable."
        )
    else:
        outcome = "NO-SHIP — no pasa el AND de los siete criterios."

    return {
        "dcagr": dcagr,
        "control_p95": ctrl_p95,
        "control_median": (
            statistics.fmean(sorted(ctrl_cagrs)[len(ctrl_cagrs) // 2 : len(ctrl_cagrs) // 2 + 1])
            if ctrl_cagrs
            else None
        ),
        "c1_dcagr": c1,
        "c2_vs_control": c2,
        "c3_maxdd": c3,
        "c4_boot_base": c4,
        "c5_boot_control": c5,
        "c6_regime": c6_ok,
        "c7_sensitivity": c7,
        "ship": ship,
        "outcome": outcome,
    }


def evaluate_sanity(
    summaries: dict, controls: list[dict], trade_diff: float, ctrl_diff_median: float, repro: dict
) -> dict:
    acc = all(s["accounting_ok"] for s in summaries.values())
    # §5.4' — contra la banda del control, no contra el baseline (ver ENMIENDA).
    band = sorted(c["cagr"] for c in controls)
    ctrl_p95 = _pct(band, SANITY_ORACLE_PCTILE) if band else float("nan")
    ctrl_median = statistics.median(band) if band else float("nan")
    oracle_ok = bool(band and summaries[ORACLE_ARM]["cagr"] > ctrl_p95)
    anti_ok = bool(band and summaries[ANTI_ORACLE_ARM]["cagr"] < ctrl_median)
    bite_ok = bool(trade_diff >= SANITY_MIN_TRADE_DIFF)
    seeds_ok = bool(
        ctrl_diff_median >= SANITY_MIN_TRADE_DIFF and len({round(c["cagr"], 8) for c in controls}) > 1
    )
    checks: dict[str, Any] = {
        "accounting": acc,
        "repro_t45": bool(repro.get("t45_ok")),
        "repro_t33": bool(repro.get("t33_ok")),
        "oracle_sees_good_turns": oracle_ok,
        "oracle_sees_bad_turns": anti_ok,
        "priority_bites": bite_ok,
        "control_seeds_effective": seeds_ok,
    }
    return {
        "checks": checks,
        "valid": all(checks.values()),
        "trade_diff": trade_diff,
        "ctrl_diff_median": ctrl_diff_median,
        "control_p95": ctrl_p95,
        "control_median": ctrl_median,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def _common(max_positions: int, capital: float, cap_days: int, **over) -> dict:
    base: dict[str, Any] = dict(
        max_positions=max_positions,
        initial_capital=capital,
        cap_days=cap_days,
        atr_p=AtrParams(),
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        eval_mode=EVAL_MODE,
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
    )
    base.update(over)
    return base


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="PRIO-EVENT — Tarea 49")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--sens-max-positions", type=int, default=5)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--seeds", type=int, default=N_SEEDS)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--no-sensitivity", action="store_true")
    p.add_argument("--no-repro", action="store_true", help="sólo para desarrollo")
    p.add_argument(
        "--allow-stale-artifacts",
        action="store_true",
        help="no abortar si el cohorte de artefactos está desalineado (T30) NI si el "
        "store de señales PIT está corto (T86) — declararlo en el pre-registro",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, vol_by, _missing, _incomplete = load_bars_signals_volume(
        tickers, args.period, args.warmup
    )
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    # El score vive en el mismo artefacto PIT que la señal.
    from scripts.run_ranking_t21 import load_bars_signals_scores

    _b, _s, score_by, _m = load_bars_signals_scores(tickers, args.period, args.warmup)

    entries = buy_entries(bars_by, sigs_by, args.warmup)
    anom_all = build_anomaly_entries(bars_by, vol_by, AnomalyParams(k=ANOM_K, m=ANOM_M), warmup=args.warmup)
    # §2 — el candidato es una RE-ORDENACIÓN PURA: sólo lo que el engine ya ofrece.
    anom_in_pool = restrict_to_pool(anom_all, entries)
    prio_keys = keys_of(anom_in_pool, bars_by)
    n_by_date = count_by_date(prio_keys)
    cands_by_date = candidates_by_date(entries, bars_by)

    # T30 — frescura del cohorte, ANTES de pagar la corrida (tarea 76). La ventana
    # que declara `artifact_window` es min(starts)..max(ends), así que un solo
    # artefacto desalineado la corre sin que se note. Falla ruidoso (política T22).
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts, file=log)
        announce_signal_store(
            bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts, file=log
        )
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3

    cfg = announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=artifact_window(bars_by),
        eval_mode=EVAL_MODE,
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
        file=log,
    )
    print(f"Tickers: {len(bars_by)} · entradas `analyze BUY`: {len(entries)}", file=log)
    print(
        f"Anomalía A_k{ANOM_K}_m{ANOM_M}: {len(anom_all)} entradas, de las cuales "
        f"**{len(anom_in_pool)}** ya son candidatas del engine "
        f"({len(anom_all) - len(anom_in_pool)} quedan afuera del candidato: son "
        f"pool nuevo, que es lo que la 45 rechazó por C8)",
        file=log,
    )
    print(f"Días con prioridad: {len(n_by_date)}\n", file=log)

    common = _common(args.max_positions, args.capital, CAP_DAYS)

    def run(rank, **over):
        return simulate_portfolio(entries, bars_by, sigs_by, **{**common, **over}, rank_score=rank)

    realized = precompute_realized(entries, bars_by, sigs_by, common)
    print(f"Retornos realizados para los oráculos: {len(realized)}", file=log)

    def b1(t: str, d: str) -> float:
        return float((score_by.get(t) or {}).get(d, 0.0))

    results: dict[str, PortfolioResult] = {
        BASELINE_ARM: run(b1),
        CANDIDATE_ARM: run(make_prio(prio_keys, score_by)),
        ALPHA_ARM: run(None),
        ORACLE_ARM: run(make_prio(oracle_prio_keys(cands_by_date, n_by_date, realized, best=True), score_by)),
        ANTI_ORACLE_ARM: run(
            make_prio(oracle_prio_keys(cands_by_date, n_by_date, realized, best=False), score_by)
        ),
    }
    for k in range(args.seeds):
        keys = rate_matched_priority(cands_by_date, n_by_date, CONTROL_SEED_BASE + k)
        results[control_name(k)] = run(make_prio(keys, score_by))

    # Descriptivo: el brazo de la 45 (pool UNIDO), con la config del veredicto.
    merged = merge_entries(entries, anom_all, bars_by)
    results[MERGED_ARM] = simulate_portfolio(
        merged, bars_by, sigs_by, **common, rank_score=make_prio(keys_of(anom_all, bars_by), score_by)
    )

    summaries = {n: summarise(r) for n, r in results.items()}
    ctrl_names = [control_name(k) for k in range(args.seeds)]
    controls = [summaries[n] for n in ctrl_names]

    # C4 / C5 — bootstrap pareado contra el baseline y contra la política control.
    daily = aligned_daily(results, [BASELINE_ARM, CANDIDATE_ARM, *ctrl_names])
    boot_base = paired_block_bootstrap(
        [r for _, r in daily[BASELINE_ARM]],
        [r for _, r in daily[CANDIDATE_ARM]],
        block=BOOT_BLOCK,
        n_resamples=args.resamples,
        seed=BOOT_SEED,
    )
    ctrl_series = policy_series(daily, ctrl_names)
    boot_ctrl = paired_block_bootstrap(
        [r for _, r in ctrl_series],
        [r for _, r in daily[CANDIDATE_ARM]],
        block=BOOT_BLOCK,
        n_resamples=args.resamples,
        seed=BOOT_SEED,
    )

    # C6 — régimen con potencia, contra el control igualado en tasa.
    control_pts: dict[str, list[float]] = {}
    for n in ctrl_names:
        for t in results[n].trades:
            control_pts.setdefault(t.regime, []).append(100.0 * t.ret)
    c6 = regime_criterion(control_pts, results[CANDIDATE_ARM], n_resamples=args.resamples, seed=BOOT_SEED)

    # §5.6 / §5.7 — el turno muerde y las semillas son efectivas.
    trade_diff = trade_overlap(results[BASELINE_ARM], results[CANDIDATE_ARM])
    pair_diffs = [
        trade_overlap(results[ctrl_names[i]], results[ctrl_names[j]])
        for i in range(len(ctrl_names))
        for j in range(i + 1, len(ctrl_names))
    ]
    ctrl_diff_median = statistics.median(pair_diffs) if pair_diffs else 0.0

    # ── C7 — sensibilidad a 5 slots ──────────────────────────────────────────
    sens: dict[str, Any] | None = None
    if not args.no_sensitivity:
        s_common = _common(args.sens_max_positions, args.capital, CAP_DAYS)

        def s_run(rank):
            return simulate_portfolio(entries, bars_by, sigs_by, **s_common, rank_score=rank)

        s_base = summarise(s_run(b1))
        s_cand = summarise(s_run(make_prio(prio_keys, score_by)))
        s_ctrl = [
            summarise(
                s_run(
                    make_prio(
                        rate_matched_priority(cands_by_date, n_by_date, CONTROL_SEED_BASE + k), score_by
                    )
                )
            )
            for k in range(args.seeds)
        ]
        s_p95 = _pct([c["cagr"] for c in s_ctrl], KILL_CONTROL_PCTILE)
        sens = {
            "max_positions": args.sens_max_positions,
            "base_cagr": s_base["cagr"],
            "cand_cagr": s_cand["cagr"],
            "control_p95": s_p95,
            "dcagr": s_cand["cagr"] - s_base["cagr"],
            "c1": bool((s_cand["cagr"] - s_base["cagr"]) >= KILL_MIN_DCAGR),
            "c2": bool(s_cand["cagr"] > s_p95),
        }

    # ── §5.2 / §5.3 — las dos reproducciones ─────────────────────────────────
    repro: dict = {}
    if args.no_repro:
        repro = {"t45_ok": True, "t33_ok": True, "skipped": True}
    else:
        r_common = _common(args.max_positions, args.capital, REPRO_CAP_DAYS)
        r_analyze = summarise(simulate_portfolio(entries, bars_by, sigs_by, **r_common))
        r_merged = summarise(
            simulate_portfolio(
                merged, bars_by, sigs_by, **r_common, rank_score=make_binary_prio(keys_of(anom_all, bars_by))
            )
        )
        t33 = summarise(
            simulate_portfolio(
                entries,
                bars_by,
                sigs_by,
                **_common(args.max_positions, args.capital, CAP_DAYS, eval_mode="close", live_gates=False),
                rank_score=b1,
            )
        )
        # Tareas 48 y 52 — las tres anclas pasan por el helper multi-estado en vez
        # de por un `abs() <= tol` de dos estados: la ventana de los artefactos es
        # RODANTE y la población puede no ser la de las anclas, y ninguna de las
        # dos cosas es evidencia de que cambió la cañería.
        checks: dict[str, Any] = {
            "t45_analyze": (r_analyze["cagr"], SANITY_T45_ANALYZE),
            "t45_merged_prio": (r_merged["cagr"], SANITY_T45_MERGED_PRIO),
            "t33": (t33["cagr"], SANITY_T33_CAGR),
        }
        states: dict[str, Any] = {
            k: reproduction_check(
                got,
                exp,
                tol=SANITY_TOL,
                current=artifact_window(bars_by),
                measured_on=WINDOW_REFRESH_2026_09_01_LIVE,
                population=cfg.population(len(entries)),
                measured_over=POPULATION_LIVE_ACCT2,
            )
            for k, (got, exp) in checks.items()
        }
        repro = {
            "t45_analyze": r_analyze["cagr"],
            "t45_merged_prio": r_merged["cagr"],
            "t45_ok": all(states[k][0] == REPRO_OK for k in ("t45_analyze", "t45_merged_prio")),
            "t45_state": " / ".join(states[k][0] for k in ("t45_analyze", "t45_merged_prio")),
            "t33_cagr": t33["cagr"],
            "t33_ok": states["t33"][0] == REPRO_OK,
            "t33_state": states["t33"][0],
            "reasons": {k: why for k, (_, why) in states.items()},
        }
        # T71: los "esperado" salen de la CONSTANTE, no de un literal. Cuando la 68
        # re-ancló estos tres números, el print siguió diciendo los viejos y una
        # corrida imprimía `E_analyze 3.47% (esperado 3.71%) · OK` — el runner se
        # contradecía a sí mismo y el OK se leía como un bug de cañería.
        print(
            f"Reproducción 45 (cap_days=20, pool unido, prioridad binaria): "
            f"E_analyze {100 * r_analyze['cagr']:.2f}% (esperado {100 * SANITY_T45_ANALYZE:.2f}%) · "
            f"E_merged_prio {100 * r_merged['cagr']:.2f}% "
            f"(esperado {100 * SANITY_T45_MERGED_PRIO:.2f}%) · "
            f"{repro['t45_state']}",
            file=log,
        )
        print(
            f"Reproducción T33 (close/sin gates): {100 * t33['cagr']:.2f}% "
            f"(esperado {100 * SANITY_T33_CAGR:.2f}%) · {repro['t33_state']}",
            file=log,
        )
        for nombre, (st, why) in states.items():
            if st != REPRO_OK:
                print(f"  → {nombre}: {why}", file=log)
        print("", file=log)

    sanity = evaluate_sanity(summaries, controls, trade_diff, ctrl_diff_median, repro)
    verdict = evaluate(
        summaries[BASELINE_ARM], summaries[CANDIDATE_ARM], controls, boot_base, boot_ctrl, c6, sens
    )
    if not sanity["valid"]:
        verdict["ship"] = False
        verdict["outcome"] = (
            "CORRIDA INVÁLIDA — falló un sanity del §5. No hay "
            "veredicto y no se re-especifica nada (precedente T26)."
        )

    ctx: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries": len(entries),
        "n_anom_all": len(anom_all),
        "n_anom_in_pool": len(anom_in_pool),
        "n_prio_days": len(n_by_date),
        "max_positions": args.max_positions,
        "seeds": args.seeds,
        "boot_base": [boot_base.ci_low, boot_base.ci_high, boot_base.p_value],
        "boot_ctrl": [boot_ctrl.ci_low, boot_ctrl.ci_high, boot_ctrl.p_value],
        "regime_criterion": c6,
        "sensitivity": sens,
        "repro": repro,
        "sanity": sanity,
        "verdict": verdict,
        "control_cagrs": sorted(c["cagr"] for c in controls),
    }
    if args.json:
        print(json.dumps({"context": ctx, "summaries": summaries}, ensure_ascii=False, indent=2, default=str))
        return 0
    _report(summaries, ctrl_names, ctx)
    return 0


def _f(x, w=9, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries: dict, ctrl_names: list[str], ctx: dict) -> None:
    vd, c6 = ctx["verdict"], ctx["regime_criterion"]
    cc = ctx["control_cagrs"]
    hdr = f"{'brazo':<20}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'tomad':>7}{'tenencia':>10}"
    print(hdr)
    print("-" * len(hdr))
    for n in (BASELINE_ARM, CANDIDATE_ARM, ALPHA_ARM, MERGED_ARM, ORACLE_ARM, ANTI_ORACLE_ARM):
        s = summaries[n]
        tag = {BASELINE_ARM: " BASE", CANDIDATE_ARM: " *CAND"}.get(n, "")
        print(
            f"{n:<20}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9, 2)}"
            f"{_f(s['max_dd'], 9, 1, '%')}{s['n_taken']:>7}"
            f"{s['mean_held_days']:>10.1f}{tag}"
        )
    print(
        f"\nCONTROL igualado en tasa ({len(cc)} semillas): "
        f"min {_f(cc[0], 0, 2, '%')} · mediana {_f(cc[len(cc) // 2], 0, 2, '%')} · "
        f"p95 {_f(vd['control_p95'], 0, 2, '%')} · max {_f(cc[-1], 0, 2, '%')}"
    )
    print(
        f"  → el candidato da {_f(summaries[CANDIDATE_ARM]['cagr'], 0, 2, '%')} "
        f"({'ARRIBA' if vd['c2_vs_control'] else 'DENTRO'} de la banda)"
    )

    print(
        f"\nΔCAGR vs base {100 * vd['dcagr']:+.2f} pp · bootstrap pareado vs BASE "
        f"IC95% [{100 * ctx['boot_base'][0]:+.2f}, {100 * ctx['boot_base'][1]:+.2f}] pp "
        f"p={ctx['boot_base'][2]:.3f}"
    )
    print(
        f"                               bootstrap pareado vs CONTROL "
        f"IC95% [{100 * ctx['boot_ctrl'][0]:+.2f}, {100 * ctx['boot_ctrl'][1]:+.2f}] pp "
        f"p={ctx['boot_ctrl'][2]:.3f}"
    )

    print(
        f"\nC6 — régimen · tolerancia {c6['tolerance_pts']:.2f} pts "
        f"(material {c6['material_pts']:.2f}, detectable {_f(c6['detectable_pts'], 0, 2)})"
    )
    wh = f"  {'ventana':<18}{'n cand':>7}{'σ':>7}{'detect':>8}{'Δ vs control':>14}{'IC95%':>20}"
    print(wh)
    print("  " + "-" * (len(wh) - 2))
    for name, w in c6["windows"].items():
        st = w["stability"]
        ci = f"[{st['ci_low']:+.2f}, {st['ci_high']:+.2f}]" if st else "—"
        star = "  ← GATE" if name == "stress_POOLED" else ""
        print(
            f"  {name:<18}{w['n_cand']:>7}{w['sd_pts']:>7.2f}"
            f"{_f(w['detectable'], 8, 2)}{w['delta_pts']:>+14.2f}{ci:>20}{star}"
        )

    sn = ctx["sensitivity"]
    if sn:
        print(
            f"\nC7 — a {sn['max_positions']} slots: base "
            f"{_f(sn['base_cagr'], 0, 2, '%')} · candidato {_f(sn['cand_cagr'], 0, 2, '%')} "
            f"(Δ {100 * sn['dcagr']:+.2f} pp, p95 control "
            f"{_f(sn['control_p95'], 0, 2, '%')}) · C1 "
            f"{'PASA' if sn['c1'] else 'FALLA'} · C2 {'PASA' if sn['c2'] else 'FALLA'}"
        )

    sa = ctx["sanity"]
    print("\nSanity (§5):")
    for k, v in sa["checks"].items():
        print(f"  {k:<26} {'OK' if v else 'FALLA'}")
    print(
        f"  turno muerde {100 * sa['trade_diff']:.1f}% · semillas del control "
        f"{100 * sa['ctrl_diff_median']:.1f}%"
    )
    print(f"  corrida {'VÁLIDA' if sa['valid'] else 'INVÁLIDA'}")

    print("\nCriterios (§6):")
    for k in (
        "c1_dcagr",
        "c2_vs_control",
        "c3_maxdd",
        "c4_boot_base",
        "c5_boot_control",
        "c6_regime",
        "c7_sensitivity",
    ):
        print(f"  {k:<18} {'PASA' if vd[k] else 'FALLA'}")
    print(f"\n  VEREDICTO: {'SHIP' if vd['ship'] else 'NO-SHIP'}")
    print(f"  {vd['outcome']}")


if __name__ == "__main__":
    raise SystemExit(main())
