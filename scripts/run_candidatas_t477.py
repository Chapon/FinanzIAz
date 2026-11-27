"""CANDIDATAS-DE-LA-REJILLA-T170 (tarea 477) — ¿alguna celda de salida le gana a la viva?

Pre-registro congelado ANTES de escribir esto: ``docs/candidatas_rejilla_prereg_t477_2026-11-27.md``
(``78d2d60``). La 472 encontró que, con el IC fuera de muestra que congeló el §7 de la T170,
cuatro celdas de la rejilla stop × trailing le ganan a la salida viva (``soff_t2.0``) con el
intervalo entero positivo. La regla congelada les abre un pre-registro con gate de
multiplicidad, y éste es su runner.

Qué decide (§4), sobre Δ = celda − viva, en el **marco primario** (orden y costo del vivo):

M1  p ajustado por Romano-Wolf sobre las 14 celdas            < 0,05
D1  ΔCAGR fuera de muestra (cinco folds encadenados)          ≥ +1,00 pp
D2  folds ganados                                             ≥ 4 de 5
D3  cola por trade, muestra completa: Δ(peor) y Δ(p1)         ≥ −2,00 pp
D5  caída máxima, muestra completa y fuera de muestra         ≤ viva +1,00 pp
C9  ruina gradual a 2,60%/50% y 0,47%/70%, peor de 3 semillas ≥ 0

**La familia son las 14 celdas**, no las cuatro que marcó la 472, y **el marco que decide es el
que nadie miró**: el orden de candidatos del vivo (la 473) y su costo (la 468). El alfabético se
corre con ``--orden alfabetico`` y se reporta: tiene que reproducir la tabla de la 472.

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py`` ni ninguna perilla viva: si alguna
celda pasa, **nada se cablea** y decide Chapa.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.harness_config import (
    COSTO_HARNESS,
    COSTO_VIVO,
    COSTOS_DEL_RUNNER,
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    SignalStoreGapError,
    StaleArtifactError,
    announce,
    announce_artifacts,
    announce_signal_store,
    artifact_window,
    costo_del_runner,
)
from analysis.orden_del_dia import ORDEN_ALFABETICO, ORDEN_VIVO, ORDENES, rank_del_orden
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import cagr
from analysis.ruin_injection import DECIDING_SHAPE, bars_digest, inject_ruin, ticker_years
from analysis.ruin_injection import seeds as ruin_seeds
from analysis.scaleout_replay import ScaleOutParams
from analysis.walkforward_power import RomanoWolfResult, regime_for_date, romano_wolf_stepdown
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_exit_policy_t170 import (
    BOOT_BLOCK,
    BOOT_RESAMPLES,
    BOOT_SEED,
    CHALLENGER_CELL,
    D1_MIN_DCAGR_OOS,
    D2_MIN_FOLDS,
    D3_TAIL_TOL_PTS,
    D5_DD_TOL,
    POLICY_ARM,
    POLICY_CELL,
    arm_fingerprint,
)
from scripts.run_rank_neutral_t39 import aligned_daily
from scripts.run_ranking_t21 import load_bars_signals_scores
from scripts.run_stop_cal_replay_t26 import (
    NO_STOP,
    RANDOM_KEEP_PROB,
    _oracle_stop_filter,
    random_stop_filter,
    summarise,
)
from scripts.run_stop_value_t37 import (
    C9_POINTS,
    CAP_DAYS,
    EVAL_MODE,
    FILL_MODE,
    FOLDS,
    LIVE_GATES,
    ORACLE_ARM,
    RANDOM_KEEP_ARM,
    REPRO_TOL,
    SANITY_ORACLE_VS_RANDOM_CAGR,
    SANITY_ORACLE_VS_RANDOM_DD,
    SimCache,
    arm_name,
    arm_params,
    entries_between,
    grid_cells,
    max_drawdown,
    tail_stats,
)
from scripts.run_tp_cal_replay_t23 import buy_entries

# ── §3 — la familia (CONGELADA): las 14 celdas de la rejilla menos la viva ───
FAMILIA: tuple[tuple[float, float], ...] = tuple(c for c in grid_cells() if c != POLICY_CELL)

# ── §4 — umbrales (CONGELADOS) ───────────────────────────────────────────────
M1_ALPHA = 0.05  # p ajustado por Romano-Wolf < 0,05
C9_MIN_DCAGR = 0.0  # ΔCAGR con ruina ≥ 0 en la peor semilla, en los dos puntos

# ── §5 — anclas de reproducción ──────────────────────────────────────────────
# 3. Marco primario: la 473 (orden y costo del vivo, sin régimen) — 9,75% con 2.325 tomados.
ANCLA_PRIMARIA_CAGR = 0.0975
ANCLA_PRIMARIA_TOMADOS = 2325
# 4. Marco secundario: el ΔCAGR fuera de muestra de cada celda con el orden alfabético, la
# tabla de la 472 (`docs/exit_policy_t170_2026-09-10.md` §3 y la re-lectura de la 469 §3).
ANCLA_472: dict[str, dict[str, float]] = {
    COSTO_HARNESS: {
        "s2.0_t2.0": 0.0176,
        "s2.0_t3.0": 0.0315,
        "s2.0_toff": 0.0106,
        "s3.0_t2.0": -0.0141,
        "s3.0_t3.0": 0.0192,
        "s3.0_toff": 0.0154,
        "s4.0_t2.0": -0.0008,
        "s4.0_t3.0": 0.0320,
        "s4.0_toff": 0.0375,
        "s6.0_t2.0": 0.0008,
        "s6.0_t3.0": 0.0257,
        "s6.0_toff": 0.0364,
        "soff_t3.0": 0.0258,
        "soff_toff": 0.0375,
    },
    COSTO_VIVO: {
        "s2.0_t2.0": 0.0211,
        "s2.0_t3.0": 0.0140,
        "s2.0_toff": 0.0194,
        "s3.0_t2.0": -0.0154,
        "s3.0_t3.0": 0.0341,
        "s3.0_toff": 0.0154,
        "s4.0_t2.0": -0.0035,
        "s4.0_t3.0": 0.0368,
        "s4.0_toff": 0.0414,
        "s6.0_t2.0": 0.0036,
        "s6.0_t3.0": 0.0279,
        "s6.0_toff": 0.0400,
        "soff_t3.0": 0.0280,
        "soff_toff": 0.0416,
    },
}
# Las anclas de la T170 para la viva con el orden alfabético (las de `repro_targets_del_costo`).
ANCLA_T170_VIVA = {COSTO_HARNESS: 0.0878, COSTO_VIVO: 0.1372}

_CACHE = SimCache(None, None)


def _sim(tag: str, entries, bars_by, sigs_by, **kw) -> PortfolioResult:
    """Una simulación por el cache. El orden y el costo van en el ``tag`` (el ``run_tag``):
    ``arm_fingerprint`` no los mira, y un cache que los ignore devolvería el marco equivocado."""
    huella = arm_fingerprint(kw)
    return _CACHE.run(f"{tag}|{huella}", lambda: simulate_portfolio(entries, bars_by, sigs_by, **kw))


def run_tag_de(window, n_tickers: int, n_entries: int, args) -> str:
    """La clave de la corrida: población, config, **orden** y **costo**."""
    return (
        f"t477|{window}|u{args.universe}|n{n_tickers}|e{n_entries}|mp{args.max_positions}"
        f"|cap{args.cap_days}|cap${args.capital:.2f}|{EVAL_MODE}|{FILL_MODE}|g{int(LIVE_GATES)}"
        f"|orden={args.orden}|costo={args.costo}"
    )


# ── Fuera de muestra: las 15 curvas encadenadas ──────────────────────────────


def curvas_oos(entries, bars_by, sigs_by, common: dict, *, tag: str, log=sys.stdout) -> dict[str, dict]:
    """``{celda: {"curve", "folds"}}`` de las 15 celdas: los cinco folds de test encadenados,
    con el equity compuesto entre folds, como en la T170 (``grid_descriptive``)."""
    tests = [entries_between(entries, bars_by, lo, hi) for _, lo, hi in FOLDS]
    out: dict[str, dict] = {}
    for cell in (POLICY_CELL, *FAMILIA):
        name = arm_name(*cell)
        print(f"    OOS {name} …", file=log, flush=True)
        eq = float(common["initial_capital"])
        curve: list[tuple[str, float]] = []
        folds: list[float] = []
        for fi, test in enumerate(tests, 1):
            r = _sim(
                f"wf{fi}|test|{name}|eq{eq:.6f}|{tag}",
                test,
                bars_by,
                sigs_by,
                **arm_params(*cell),
                **{**common, "initial_capital": eq},
            )
            curve.extend(r.equity_curve)
            folds.append(cagr(r.equity_curve))
            eq = r.final_equity
        out[name] = {"curve": curve, "folds": folds}
    return out


def m1_romano_wolf(curvas: dict[str, dict], capital: float, *, resamples: int) -> RomanoWolfResult:
    """M1: Romano-Wolf sobre **las 14 a la vez**, con los mismos índices para las 15 series."""
    nombres = [arm_name(*c) for c in FAMILIA]
    res = {n: SimpleNamespace(equity_curve=curvas[n]["curve"], initial_capital=capital) for n in curvas}
    daily = aligned_daily(res, [POLICY_ARM, *nombres])
    return romano_wolf_stepdown(
        [r for _, r in daily[POLICY_ARM]],
        {n: [r for _, r in daily[n]] for n in nombres},
        block=BOOT_BLOCK,
        n_resamples=resamples,
        seed=BOOT_SEED,
    )


# ── C9: la ruina inyectada, con la viva como base ────────────────────────────


def ruina_c9(entries, bars_by, sigs_by, common: dict, *, tag: str, log=sys.stdout) -> dict:
    """C9 de la T37 con **la viva** como base (el ``ruin_sweep`` de la T37 la tiene fija en
    ``s2.0_t2.0``). Cada mundo se genera una vez por (tasa, profundidad, semilla) y lo ven las
    15 celdas: la comparación sigue siendo pareada. El determinismo del mundo (§5.6) se verifica
    re-inyectando con la misma terna."""
    por_celda: dict[str, dict[str, dict]] = {arm_name(*c): {} for c in FAMILIA}
    digests_ok = True
    for rate, depth in C9_POINTS:
        key = f"d{depth:.2f}_r{rate:.4f}"
        deltas: dict[str, list[float]] = {n: [] for n in por_celda}
        for sd in ruin_seeds():
            wtag = f"{DECIDING_SHAPE}|d{depth:.4f}|r{rate:.6f}|s{sd}"
            world, _events = inject_ruin(bars_by, rate=rate, depth=depth, shape=DECIDING_SHAPE, seed=sd)
            again, _ = inject_ruin(bars_by, rate=rate, depth=depth, shape=DECIDING_SHAPE, seed=sd)
            digests_ok = digests_ok and bars_digest(again) == bars_digest(world)
            base = _sim(
                f"ruin|{wtag}|{POLICY_ARM}|{tag}",
                entries,
                world,
                sigs_by,
                **arm_params(*POLICY_CELL),
                **common,
            )
            base_cagr = cagr(base.equity_curve)
            for cell in FAMILIA:
                n = arm_name(*cell)
                r = _sim(f"ruin|{wtag}|{n}|{tag}", entries, world, sigs_by, **arm_params(*cell), **common)
                deltas[n].append(cagr(r.equity_curve) - base_cagr)
        for n, ds in deltas.items():
            por_celda[n][key] = {
                "rate": rate,
                "depth": depth,
                "dcagr_worst": min(ds),
                "dcagr_mean": statistics.fmean(ds),
            }
        print(f"    ruina d={depth:.0%} r={rate:.2%} lista", file=log, flush=True)
    return {"celdas": por_celda, "digests_ok": digests_ok}


# ── §4 — la regla de decisión ────────────────────────────────────────────────


def evaluar_celda(
    *,
    p_adj: float,
    dcagr_oos: float,
    folds: int,
    d_worst: float,
    d_p1: float,
    ddd_is: float,
    ddd_oos: float,
    c9_worst: list[float],
) -> dict:
    """Las seis del §4. Pasa sólo con todas; ``None`` en cualquiera ⇒ no se pudo medir."""
    crit = {
        "M1": p_adj < M1_ALPHA,
        "D1": dcagr_oos >= D1_MIN_DCAGR_OOS,
        "D2": folds >= D2_MIN_FOLDS,
        "D3": d_worst >= -D3_TAIL_TOL_PTS and d_p1 >= -D3_TAIL_TOL_PTS,
        "D5": ddd_is <= D5_DD_TOL and ddd_oos <= D5_DD_TOL,
        "C9": len(c9_worst) == len(C9_POINTS) and all(d >= C9_MIN_DCAGR for d in c9_worst),
    }
    medible = p_adj == p_adj and len(c9_worst) == len(C9_POINTS)
    return {**crit, "medible": medible, "pasa": medible and all(crit.values())}


def evaluar_sanity(summaries: dict, *, orden: str, costo: str, curvas: dict, digests_ok: bool) -> dict:
    """§5: si falla alguno, la corrida es INVÁLIDA y no hay veredicto."""
    orc, rnd = summaries[ORACLE_ARM], summaries[RANDOM_KEEP_ARM]
    viva = summaries[POLICY_ARM]
    s: dict[str, Any] = {
        "contabilidad": all(v["accounting_ok"] for v in summaries.values()),
        "oraculo_cagr": orc["cagr"] - rnd["cagr"],
        "oraculo_dd": orc["max_dd"] - rnd["max_dd"],
        "digests_ok": digests_ok,
    }
    s["oraculo_ok"] = (
        s["oraculo_cagr"] >= SANITY_ORACLE_VS_RANDOM_CAGR and s["oraculo_dd"] <= -SANITY_ORACLE_VS_RANDOM_DD
    )
    # §5.5 — el control mecánico: la barrera `off` no dispara nunca.
    mecanico = {}
    for st, tr in grid_cells():
        mix = summaries[arm_name(st, tr)]["exit_mix"]
        ok = (st < NO_STOP or mix.get("atr_stop", 0.0) == 0.0) and (
            tr < NO_STOP or mix.get("atr_trail", 0.0) == 0.0
        )
        mecanico[arm_name(st, tr)] = ok
    s["mecanico_ok"] = all(mecanico.values())
    # §5.3 / §5.4 — la reproducción, según el marco.
    if orden == ORDEN_VIVO and costo == COSTO_VIVO:
        s["repro"] = {
            "viva_cagr": (
                viva["cagr"],
                ANCLA_PRIMARIA_CAGR,
                abs(viva["cagr"] - ANCLA_PRIMARIA_CAGR) <= REPRO_TOL,
            ),
            "viva_tomados": (
                viva["n_taken"],
                ANCLA_PRIMARIA_TOMADOS,
                viva["n_taken"] == ANCLA_PRIMARIA_TOMADOS,
            ),
        }
    elif orden == ORDEN_ALFABETICO:
        esperado = ANCLA_472[costo]
        cagr_l = cagr(curvas[POLICY_ARM]["curve"])
        s["repro"] = {
            "viva_cagr": (
                viva["cagr"],
                ANCLA_T170_VIVA[costo],
                abs(viva["cagr"] - ANCLA_T170_VIVA[costo]) <= REPRO_TOL,
            )
        }
        for n, e in esperado.items():
            d = cagr(curvas[n]["curve"]) - cagr_l
            s["repro"][f"oos_{n}"] = (d, e, abs(d - e) <= REPRO_TOL)
    else:
        s["repro"] = {}  # el orden del vivo al costo del harness no tiene ancla: se reporta
    s["repro_ok"] = all(ok for *_, ok in s["repro"].values()) if s["repro"] else None
    s["all_ok"] = bool(
        s["contabilidad"] and s["oraculo_ok"] and s["mecanico_ok"] and s["digests_ok"] and s["repro_ok"]
    )
    return s


# ── Reporte ──────────────────────────────────────────────────────────────────


def _report(celdas: dict, sanity: dict, *, orden: str, costo: str, primario: bool, log=sys.stdout) -> None:
    print(f"\n§5 — Sanity del instrumento (orden {orden}, costo {costo}):", file=log)
    print(f"  [{'OK' if sanity['contabilidad'] else 'FALLA'}] contabilidad", file=log)
    print(
        f"  [{'OK' if sanity['oraculo_ok'] else 'FALLA'}] oráculo vs control igualado: "
        f"ΔCAGR {100 * sanity['oraculo_cagr']:+.2f} pp, ΔmaxDD {100 * sanity['oraculo_dd']:+.2f} pp",
        file=log,
    )
    print(f"  [{'OK' if sanity['mecanico_ok'] else 'FALLA'}] la barrera `off` no dispara", file=log)
    print(f"  [{'OK' if sanity['digests_ok'] else 'FALLA'}] la ruina es determinista", file=log)
    for k, (actual, esperado, ok) in sanity["repro"].items():
        print(f"  [{'OK' if ok else 'FALLA'}] reproduce {k}: {actual:.4f} (esp. {esperado:.4f})", file=log)

    hdr = f"{'celda':<11}{'ΔCAGR':>8}{'p':>7}{'p RW':>7}{'folds':>6}{'Δpeor':>7}{'Δp1':>7}{'ΔDD in':>8}{'ΔDD oos':>8}{'C9 a':>7}{'C9 b':>7}  criterios"
    print("\n§4 — Las 14 celdas contra la viva (Δ en pp; C9 = peor semilla en cada punto):", file=log)
    print(hdr, file=log)
    print("-" * len(hdr), file=log)
    for n, v in sorted(celdas.items(), key=lambda kv: -kv[1]["dcagr_oos"]):
        fallan = [k for k in ("M1", "D1", "D2", "D3", "D5", "C9") if not v["eval"][k]]
        marca = "PASA" if v["eval"]["pasa"] else "falla " + ",".join(fallan)
        c9 = v["c9_worst"]
        print(
            f"{n:<11}{100 * v['dcagr_oos']:>+8.2f}{v['p_raw']:>7.3f}{v['p_adj']:>7.3f}{v['folds']:>4}/5"
            f"{v['d_worst']:>+7.2f}{v['d_p1']:>+7.2f}{100 * v['ddd_is']:>+8.2f}{100 * v['ddd_oos']:>+8.2f}"
            f"{100 * c9[0]:>+7.2f}{100 * c9[1]:>+7.2f}  {marca}",
            file=log,
        )

    print("\n" + "=" * 78, file=log)
    if not sanity["all_ok"]:
        print("VEREDICTO: CORRIDA INVÁLIDA — falla un sanity del §5; no hay veredicto.", file=log)
    elif not primario:
        print("MARCO SECUNDARIO — se reporta, no decide (§2).", file=log)
    else:
        pasan = [n for n, v in celdas.items() if v["eval"]["pasa"]]
        if pasan:
            print(
                f"VEREDICTO: PASAN {', '.join(sorted(pasan))} — nada se cablea; decide Chapa (§4).", file=log
            )
        else:
            print(
                "VEREDICTO: NINGUNA PASA — la salida viva queda, y la rejilla queda cerrada (§4).", file=log
            )
    print("=" * 78, file=log)


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CANDIDATAS-DE-LA-REJILLA-T170 (tarea 477)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--allow-stale-artifacts", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--orden", choices=ORDENES, default=ORDEN_VIVO, help="el marco primario es el del vivo")
    p.add_argument(
        "--costo", choices=COSTOS_DEL_RUNNER, default=COSTO_VIVO, help="el marco primario es el del vivo"
    )
    args = p.parse_args(argv)
    primario = args.orden == ORDEN_VIVO and args.costo == COSTO_VIVO

    log = sys.stderr if args.json else sys.stdout
    global _CACHE
    _CACHE = SimCache(Path(args.cache_dir) if args.cache_dir else None, None)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, score_by, missing = load_bars_signals_scores(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)
    entries = buy_entries(bars_by, sigs_by, args.warmup)
    window = artifact_window(bars_by)
    _cm = costo_del_runner(args.costo)
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts, file=log)
        announce_signal_store(
            bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts, file=log
        )
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3
    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=window,
        eval_mode=EVAL_MODE,
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
        costo_por_lado=_cm.commission + _cm.slippage,
        orden_del_vivo=args.orden == ORDEN_VIVO,
        file=log,
    )
    print(
        f"Tickers: {len(bars_by)} · entradas: {len(entries)} · ticker-años: {ticker_years(bars_by):.0f} · "
        f"orden {args.orden} · costo {args.costo} · {'MARCO PRIMARIO' if primario else 'marco secundario'}\n",
        file=log,
    )

    tag = run_tag_de(window, len(bars_by), len(entries), args)
    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        so_params=ScaleOutParams(),
        costs=_cm,
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        rank_score=rank_del_orden(args.orden, score_by),
    )

    # 1. Muestra completa: las 15 y los dos de sanity (montados donde el stop actúa, como la T170).
    arms: dict[str, dict] = {arm_name(*c): arm_params(*c) for c in grid_cells()}
    sanity_kw = {**arm_params(*CHALLENGER_CELL)}
    arms[ORACLE_ARM] = {**sanity_kw, "stop_filter": _oracle_stop_filter}
    arms[RANDOM_KEEP_ARM] = {**sanity_kw, "stop_filter": random_stop_filter(RANDOM_KEEP_PROB)}
    results: dict[str, PortfolioResult] = {}
    for i, (n, kw) in enumerate(arms.items(), 1):
        print(f"  muestra completa {i}/{len(arms)} {n} …", file=log, flush=True)
        results[n] = _sim(f"full|{n}|{tag}", entries, bars_by, sigs_by, **kw, **common)
    summaries = {n: summarise(r) for n, r in results.items()}
    tails = {n: tail_stats(r) for n, r in results.items()}

    # 2. Fuera de muestra, M1 y C9.
    print("\nFuera de muestra …", file=log, flush=True)
    curvas = curvas_oos(entries, bars_by, sigs_by, common, tag=tag, log=log)
    rw = m1_romano_wolf(curvas, args.capital, resamples=args.resamples)
    print("\nC9 — ruina inyectada …", file=log, flush=True)
    ruina = ruina_c9(entries, bars_by, sigs_by, common, tag=tag, log=log)

    # 3. Cada celda contra la viva.
    viva_c = curvas[POLICY_ARM]
    celdas: dict[str, dict] = {}
    for cell in FAMILIA:
        n = arm_name(*cell)
        c = curvas[n]
        v: dict[str, Any] = {
            "dcagr_oos": cagr(c["curve"]) - cagr(viva_c["curve"]),
            "folds": sum(1 for a, b in zip(c["folds"], viva_c["folds"], strict=True) if a - b > 0.0),
            "p_raw": rw.p_raw[n],
            "p_adj": rw.p_adjusted[n],
            "d_worst": tails[n]["worst"] - tails[POLICY_ARM]["worst"],
            "d_p1": tails[n]["p1"] - tails[POLICY_ARM]["p1"],
            "ddd_is": summaries[n]["max_dd"] - summaries[POLICY_ARM]["max_dd"],
            "ddd_oos": max_drawdown(c["curve"]) - max_drawdown(viva_c["curve"]),
            "c9_worst": [ruina["celdas"][n][k]["dcagr_worst"] for k in sorted(ruina["celdas"][n])],
        }
        v["eval"] = evaluar_celda(
            p_adj=v["p_adj"],
            dcagr_oos=v["dcagr_oos"],
            folds=v["folds"],
            d_worst=v["d_worst"],
            d_p1=v["d_p1"],
            ddd_is=v["ddd_is"],
            ddd_oos=v["ddd_oos"],
            c9_worst=v["c9_worst"],
        )
        celdas[n] = v

    sanity = evaluar_sanity(
        summaries, orden=args.orden, costo=args.costo, curvas=curvas, digests_ok=ruina["digests_ok"]
    )
    _report(celdas, sanity, orden=args.orden, costo=args.costo, primario=primario, log=log)

    if args.json:
        print(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "window": str(window),
                    "orden": args.orden,
                    "costo": args.costo,
                    "primario": primario,
                    "viva": {
                        k: v for k, v in summaries[POLICY_ARM].items() if not isinstance(v, (list, dict))
                    },
                    "sanity": sanity,
                    "celdas": celdas,
                    "ruina": ruina["celdas"],
                },
                indent=2,
                default=str,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
