"""
Runner del replay del múltiplo del stop ATR — Tarea 34 (STOP-LOOSEN).

Pre-registro con criterios CONGELADOS: ``docs/stop_loosen_prereg_t34_2026-08-18.md``.
Sale del lead del §3 de la 26b (``docs/stop_price_t26b_2026-08-16.md``), que quedó
desbloqueado cuando la T33 invirtió el default de ``fill_mode`` al honesto.

La pregunta
-----------
Bajo ``touch`` —la regla que el engine ejecuta— la 26b midió ``touch_3.0`` en 9.92%
de CAGR contra 4.41% de ``touch_2.0``, el múltiplo **vivo**. O sea **aflojar**, la
dirección opuesta a la que la T26 quiso cablear. Era un lead y no un resultado por
tres razones: el máximo caía en el **borde** de la rejilla, a 5 slots la curva se
desordena, y el lead salió de la **misma muestra** sobre la que se lo evaluaría.

Qué hace (y qué agrega sobre la 26b, que re-correr no agregaría nada: el harness es
determinista)
-------------------------------------------------------------------------------
1. **Rejilla extendida** a 3.5 y ``off`` — lo único que distingue un óptimo interior
   de una monotonía. Es el criterio **C6**.
2. **Walk-forward de la SELECCIÓN** (§6): 5 folds anclados con embargo, equity OOS
   encadenada. Se valida el **procedimiento que elige** el múltiplo, no un múltiplo
   elegido después de ver la respuesta. Es **C1** y **C7**.
3. **Los gates de re-entrada del engine modelados** (``live_gates``, el sexto desvío
   que destapó esta tarea): Gate 5 bloquearía 21-36% de las entradas que el harness
   toma, con gradiente monótono en el múltiplo ⇒ **no se cancela** entre brazos.
   El veredicto se dicta con los gates **ON**; la rejilla con gates OFF se reporta
   al lado para cuantificar el desvío.

El candidato **no está hardcodeado**: sale del walk-forward. Nombrar ``touch_3.0``
sería elegir el ganador de la corrida de la 26b sobre la misma muestra, que es justo
el defecto que la tarea existe para no cometer.

Sin red, sin tocar ``finanzias.db``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import (
    AtrParams,
    max_drawdown,
)
from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    StaleArtifactError,
    announce,
    announce_artifacts,
    artifact_window,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import cagr
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    STRESS_REGIMES,
    paired_block_bootstrap,
    regime_for_date,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_ranking_t21 import trade_overlap
from scripts.run_stop_cal_replay_t26 import (
    NO_STOP,
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

# §5 — la rejilla extendida. El orden importa para leer la forma de la curva (C6).
MULTS: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, NO_STOP)
LIVE_MULT = 2.0
LOOSE_EDGE = (3.5, NO_STOP)  # C6 — el extremo suelto de la rejilla

BASELINE_ARM = "touch_2.0"
ORACLE_ARM = "ORACULO_STOP"
RANDOM_KEEP_ARM = "AZAR_MISMA_TASA"
DIAG_TRAIL_MULT = 2.0  # diagnóstico de desacople (descriptivo, no decide)

# §8 — criterios congelados.
KILL_MIN_DCAGR_OOS = 0.0100  # C1 — ≥ +1.00 pp fuera de muestra
KILL_DD_TOL = 0.0100  # C2 — maxDD ≤ base + 1.00 pp (in-sample Y OOS)
KILL_MIN_DSHARPE = 0.05  # C4 — mejora real, no sólo no-degradación
KILL_REGIME_TOL = 0.05  # C5
KILL_MIN_FOLD_AGREEMENT = 4  # C7 — mismo múltiplo en ≥4 de 5 folds

# §7 — sanity del instrumento, contra el CONTROL IGUALADO (no contra el baseline).
SANITY_ORACLE_VS_RANDOM_CAGR = 0.0150
SANITY_ORACLE_VS_RANDOM_DD = 0.0500
# §7.5 ENMENDADO (docs/stop_loosen_enmienda_t34_2026-08-18.md): el umbral original
# —una banda sobre la fracción de "elegibles" bloqueada— conflacionaba dos cantidades
# y por eso invalidó la primera corrida. El check correcto es el mismo que la 26b usó
# en su §5.3, con el mismo umbral y el mismo helper: la regla tiene que MORDER, o sea
# cambiar la composición de la cartera. El gate no cambia la exposición (con selección
# ~55:1 el slot bloqueado se lo lleva el siguiente candidato), cambia quién entra.
SANITY_MIN_TRADE_DIFF = 0.10

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345

# §6 — walk-forward congelado: 5 folds anclados, embargo de 365 días corridos.
FOLDS: tuple[tuple[str, str, str], ...] = (
    # (train_end_exclusive, test_start, test_end)
    ("2020-08-01", "2021-08-01", "2022-07-31"),
    ("2021-08-01", "2022-08-01", "2023-07-31"),
    ("2022-08-01", "2023-08-01", "2024-07-31"),
    ("2023-08-01", "2024-08-01", "2025-07-31"),
    ("2024-08-01", "2025-08-01", "2026-07-31"),
)


def arm_name(mult: float, mode: str = "touch") -> str:
    return f"{mode}_off" if mult >= NO_STOP else f"{mode}_{mult:.1f}"


def build_arms(*, live_gates: bool = True, fill_mode: str = "decision") -> dict[str, dict]:
    """{nombre: kwargs propios} — rejilla 7×2 + los dos brazos de sanity."""
    arms: dict[str, dict] = {}
    for mode in ("touch", "close"):
        for m in MULTS:
            arms[arm_name(m, mode)] = {
                "atr_p": AtrParams(stop_mult=m),
                "eval_mode": mode,
                "fill_mode": fill_mode,
                "live_gates": live_gates,
            }
    base_p = AtrParams(stop_mult=LIVE_MULT)
    # Los dos de sanity corren en el modo del BASELINE (``touch``), que es la regla
    # viva: se valida el instrumento donde se dicta el veredicto.
    common: dict[str, Any] = {
        "atr_p": base_p,
        "eval_mode": "touch",
        "fill_mode": fill_mode,
        "live_gates": live_gates,
    }
    arms[ORACLE_ARM] = {**common, "stop_filter": _oracle_stop_filter}
    arms[RANDOM_KEEP_ARM] = {**common, "stop_filter": random_stop_filter(RANDOM_KEEP_PROB)}
    return arms


def entry_date_of(bars_by: dict, ticker: str, idx: int) -> str:
    return bars_by[ticker][idx][0]


def entries_between(entries, bars_by, lo: str | None, hi: str | None):
    """Entradas con ``lo ≤ entry_date ≤ hi`` (cualquiera de los dos puede ser None)."""
    out = []
    for tk, idx in entries:
        bars = bars_by.get(tk)
        if not bars or idx >= len(bars):
            continue
        d = bars[idx][0]
        if lo is not None and d < lo:
            continue
        if hi is not None and d > hi:
            continue
        out.append((tk, idx))
    return out


def regime_trade_breakdown(res: PortfolioResult) -> dict:
    out: dict[str, dict] = {}
    for name in ["bull_normal"] + [r.name for r in STRESS_REGIMES]:
        tr = [t for t in res.trades if t.regime == name]
        out[name] = {
            "n": len(tr),
            "mean_ret_pts": 100.0 * statistics.fmean([t.ret for t in tr]) if tr else 0.0,
        }
    return out


# ── §6 — walk-forward de la selección ────────────────────────────────────────


def walk_forward(entries, bars_by, sigs_by, common: dict) -> dict:
    """Elige el múltiplo en cada train y lo cobra en el test siguiente.

    Devuelve la selección por fold, la equity OOS **encadenada** del procedimiento y
    la del baseline fijo, y el múltiplo ``M*`` que sale por mayoría.
    """
    picks: list[float] = []
    per_fold: list[dict] = []
    proc_curve: list[tuple[str, float]] = []
    base_curve: list[tuple[str, float]] = []
    proc_eq = base_eq = float(common["initial_capital"])

    for train_end, test_lo, test_hi in FOLDS:
        train = entries_between(entries, bars_by, None, _prev_day(train_end))
        test = entries_between(entries, bars_by, test_lo, test_hi)

        # 1. Selección: el múltiplo con mayor CAGR en el train. Una sola métrica.
        train_cagr: dict[float, float] = {}
        for m in MULTS:
            r = simulate_portfolio(
                train,
                bars_by,
                sigs_by,
                atr_p=AtrParams(stop_mult=m),
                eval_mode="touch",
                fill_mode="decision",
                live_gates=True,
                **common,
            )
            train_cagr[m] = cagr(r.equity_curve)
        pick = max(MULTS, key=lambda m: train_cagr[m])
        picks.append(pick)

        # 2. Se cobra en el test, con la equity que viene del bloque anterior.
        r_proc = simulate_portfolio(
            test,
            bars_by,
            sigs_by,
            atr_p=AtrParams(stop_mult=pick),
            eval_mode="touch",
            fill_mode="decision",
            live_gates=True,
            **{**common, "initial_capital": proc_eq},
        )
        r_base = simulate_portfolio(
            test,
            bars_by,
            sigs_by,
            atr_p=AtrParams(stop_mult=LIVE_MULT),
            eval_mode="touch",
            fill_mode="decision",
            live_gates=True,
            **{**common, "initial_capital": base_eq},
        )

        proc_curve.extend(r_proc.equity_curve)
        base_curve.extend(r_base.equity_curve)
        proc_eq, base_eq = r_proc.final_equity, r_base.final_equity

        per_fold.append(
            {
                "train_end": train_end,
                "test": f"{test_lo}..{test_hi}",
                "n_train": len(train),
                "n_test": len(test),
                "pick": arm_name(pick),
                "train_cagr": {arm_name(m): train_cagr[m] for m in MULTS},
                "oos_cagr_proc": cagr(r_proc.equity_curve),
                "oos_cagr_base": cagr(r_base.equity_curve),
            }
        )

    counts = {m: picks.count(m) for m in set(picks)}
    m_star = max(counts, key=lambda m: (counts[m], -m))
    return {
        "per_fold": per_fold,
        "picks": [arm_name(m) for m in picks],
        "m_star": m_star,
        "agreement": counts[m_star],
        "proc": {"cagr": cagr(proc_curve), "max_dd": max_drawdown(proc_curve), "final_equity": proc_eq},
        "base": {"cagr": cagr(base_curve), "max_dd": max_drawdown(base_curve), "final_equity": base_eq},
    }


def _prev_day(iso10: str) -> str:
    return date.fromordinal(date.fromisoformat(iso10).toordinal() - 1).isoformat()


# ── §7 — sanity ──────────────────────────────────────────────────────────────


def evaluate_sanity(summaries: dict, results: dict, base_off: PortfolioResult) -> dict:
    orc, rnd = summaries[ORACLE_ARM], summaries[RANDOM_KEEP_ARM]
    d_cagr = orc["cagr"] - rnd["cagr"]
    d_dd = orc["max_dd"] - rnd["max_dd"]

    base = results[BASELINE_ARM]
    # §7.5 enmendado: cableado + la regla muerde (composición), no una banda de share.
    wired = base.n_gate5_blocked > 0 and base_off.n_gate5_blocked == 0
    diff = trade_overlap(base, base_off)

    # §7.4 pide la monotonía en **los dos** modos, no sólo en el que dicta.
    monotone = True
    for mode in ("touch", "close"):
        shares = [summaries[arm_name(m, mode)]["stop_share"] for m in MULTS]
        monotone = monotone and all(a >= b - 1e-12 for a, b in pairwise(shares))

    checks: dict[str, Any] = {
        "accounting": all(s["accounting_ok"] for s in summaries.values()),
        "oracle_vs_random_cagr": d_cagr >= SANITY_ORACLE_VS_RANDOM_CAGR,
        "oracle_vs_random_dd": d_dd <= -SANITY_ORACLE_VS_RANDOM_DD,
        "off_arm_fires_nothing": summaries[arm_name(NO_STOP)]["stop_share"] == 0.0,
        "stop_share_monotone": monotone,
        "gates_wired": wired,
        "gates_bite_composition": diff >= SANITY_MIN_TRADE_DIFF,
    }
    return {
        **checks,
        "all_ok": all(checks.values()),
        "d_cagr": d_cagr,
        "d_dd": d_dd,
        "trade_diff": diff,
        "n_gate5_blocked": base.n_gate5_blocked,
        "n_taken": base.n_taken,
    }


# ── §8 — los ocho criterios ──────────────────────────────────────────────────


def evaluate(summaries: dict, summaries_5: dict, regimes: dict, boot, wf: dict) -> dict:
    m_star = wf["m_star"]
    cand = arm_name(m_star)
    base_s, cand_s = summaries[BASELINE_ARM], summaries[cand]

    c1 = wf["proc"]["cagr"] - wf["base"]["cagr"]
    c2_is = cand_s["max_dd"] - base_s["max_dd"]
    c2_oos = wf["proc"]["max_dd"] - wf["base"]["max_dd"]
    c4 = (cand_s["sharpe"] or 0.0) - (base_s["sharpe"] or 0.0)
    c5: dict[str, Any] = {
        k: regimes[cand][k]["mean_ret_pts"] - regimes[BASELINE_ARM][k]["mean_ret_pts"]
        for k in regimes[BASELINE_ARM]
    }
    best_touch = max(MULTS, key=lambda m: summaries[arm_name(m)]["cagr"])
    c8a = summaries_5[cand]["cagr"] - summaries_5[BASELINE_ARM]["cagr"]
    c8b = summaries[arm_name(m_star, "close")]["cagr"] - summaries[arm_name(LIVE_MULT, "close")]["cagr"]

    crit: dict[str, Any] = {
        "C1_dcagr_oos": (c1, c1 >= KILL_MIN_DCAGR_OOS),
        "C2_maxdd": ((c2_is, c2_oos), c2_is <= KILL_DD_TOL and c2_oos <= KILL_DD_TOL),
        "C3_bootstrap": (boot.ci_low, boot.ci_low > 0),
        "C4_dsharpe": (c4, c4 >= KILL_MIN_DSHARPE),
        "C5_regime": (c5, all(v >= -KILL_REGIME_TOL for v in c5.values())),
        "C6_interior_max": (arm_name(best_touch), best_touch not in LOOSE_EDGE),
        "C7_fold_agreement": (wf["agreement"], wf["agreement"] >= KILL_MIN_FOLD_AGREEMENT),
        "C8_specification": ((c8a, c8b), c8a >= 0 and c8b >= 0),
    }
    ship = all(ok for _, ok in crit.values())

    if ship:
        outcome = (
            f"SHIP — se cabla atr_stop_mult = {m_star:.1f} en la cuenta viva 2. "
            f"Es un cambio de politica de salida EN VIVO (y afloja tambien el trailing)."
        )
    elif not crit["C6_interior_max"][1]:
        outcome = (
            f"NO-SHIP por C6 — el maximo cae en el BORDE suelto ({arm_name(best_touch)}). "
            f"Lo que dice la corrida no es 'aflojar a M*' sino 'el stop ATR no aporta', "
            f"que es otra afirmacion y NO se cabla desde aca: abre tarea propia."
        )
    elif not crit["C7_fold_agreement"][1]:
        outcome = (
            f"NO-SHIP por C7 — el multiplo baila entre folds ({wf['picks']}). "
            f"No hay parametro que cablear; el lead de la 26b §3 queda cerrado como RUIDO."
        )
    elif m_star == LIVE_MULT:
        outcome = (
            "NO-SHIP — el walk-forward elige el multiplo VIVO (2.0). Resultado POSITIVO: "
            "el multiplo esta bien puesto y el lead de la 26b era in-sample."
        )
    else:
        failed = [k for k, (_, ok) in crit.items() if not ok]
        outcome = f"NO-SHIP — falla {', '.join(failed)}. atr_stop_mult queda en 2.0."

    return {"ship": ship, "outcome": outcome, "candidate": cand, "m_star": m_star, "criteria": crit}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay del multiplo del stop ATR (Tarea 34)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    # El veredicto se dicta con el fill honesto (§4). El legacy queda accesible por
    # la regresión de la T33 —ningún runner puede no poder elegirlo— pero bajo
    # ``touch``, que es donde se dicta, los dos fill coinciden y el flag no muerde.
    p.add_argument(
        "--fill-mode",
        choices=("decision", "resting"),
        default="decision",
        help="'resting' es el legacy look-ahead; bajo touch da idéntico",
    )
    p.add_argument(
        "--no-walk-forward",
        action="store_true",
        help="saltea el walk-forward (§6) — deja la corrida SIN veredicto",
    )
    p.add_argument(
        "--allow-stale-artifacts",
        action="store_true",
        help="no abortar si el cohorte de artefactos está desalineado (T30)",
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

    # T30 — frescura del cohorte, ANTES de pagar la corrida (tarea 76). La ventana
    # que declara `artifact_window` es min(starts)..max(ends), así que un solo
    # artefacto desalineado la corre sin que se note. Falla ruidoso (política T22).
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts)
    except StaleArtifactError as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3

    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=artifact_window(bars_by),
        eval_mode="touch",
        fill_mode=args.fill_mode,
        live_gates=True,
    )
    print(f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)}")
    print(
        f"BASELINE = {BASELINE_ARM} (regla, múltiplo y gates vivos) · "
        f"el candidato lo elige el walk-forward, NO está hardcodeado\n"
    )

    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
    )

    arms = build_arms(live_gates=True, fill_mode=args.fill_mode)
    results = {n: simulate_portfolio(entries, bars_by, sigs_by, **kw, **common) for n, kw in arms.items()}
    summaries = {n: summarise(r) for n, r in results.items()}

    # Descriptivo: la misma rejilla ``touch`` SIN los gates, para cuantificar el sexto
    # desvío contra lo que midieron los harness publicados. No dicta nada.
    gates_off_res: dict[str, Any] = {
        arm_name(m): simulate_portfolio(
            entries,
            bars_by,
            sigs_by,
            atr_p=AtrParams(stop_mult=m),
            eval_mode="touch",
            fill_mode=args.fill_mode,
            live_gates=False,
            **common,
        )
        for m in MULTS
    }
    gates_off = {n: summarise(r) for n, r in gates_off_res.items()}
    base_off_res = gates_off_res[BASELINE_ARM]

    # Sensibilidad a 5 slots (C8a).
    common5 = {**common, "max_positions": 5}
    summaries_5: dict[str, Any] = {
        n: summarise(simulate_portfolio(entries, bars_by, sigs_by, **arms[n], **common5))
        for n in [BASELINE_ARM] + [arm_name(m) for m in MULTS]
    }

    wf: dict[str, Any] = (
        {
            "m_star": LIVE_MULT,
            "agreement": 0,
            "picks": [],
            "per_fold": [],
            "proc": {"cagr": 0.0, "max_dd": 0.0},
            "base": {"cagr": 0.0, "max_dd": 0.0},
        }
        if args.no_walk_forward
        else walk_forward(entries, bars_by, sigs_by, common)
    )

    cand = arm_name(float(wf["m_star"]))  # `wf` es heterogeneo; m_star ya es float
    regimes = {n: regime_trade_breakdown(results[n]) for n in (BASELINE_ARM, cand)}
    rets = aligned_returns(results, [BASELINE_ARM, cand])
    boot = paired_block_bootstrap(
        rets[BASELINE_ARM], rets[cand], block=BOOT_BLOCK, n_resamples=args.resamples, seed=BOOT_SEED
    )

    # Diagnóstico descriptivo del desacople stop/trailing (§5). No entra en criterios.
    diag = summarise(
        simulate_portfolio(
            entries,
            bars_by,
            sigs_by,
            atr_p=AtrParams(stop_mult=wf["m_star"], trail_mult=DIAG_TRAIL_MULT),
            eval_mode="touch",
            fill_mode="decision",
            live_gates=True,
            **common,
        )
    )

    sanity = evaluate_sanity(summaries, results, base_off_res)
    verdict = evaluate(summaries, summaries_5, regimes, boot, wf)
    if not sanity["all_ok"]:
        verdict["ship"] = False
        verdict["outcome"] = (
            "CORRIDA INVÁLIDA — falla un sanity del §7; no hay veredicto (el instrumento no está validado)."
        )
    if args.no_walk_forward:
        verdict["ship"] = False
        verdict["outcome"] = "SIN VEREDICTO — se salteó el walk-forward (§6), que es C1 y C7."

    ctx: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries": len(entries),
        "max_positions": args.max_positions,
        "cap_days": args.cap_days,
        "universe": args.universe,
        "verdict": verdict,
        "sanity": sanity,
        "walk_forward": wf,
        "diag_stop_only": diag,
        "boot": {
            "observed": boot.observed,
            "ci_low": boot.ci_low,
            "ci_high": boot.ci_high,
            "p_value": boot.p_value,
        },
    }
    if args.json:
        print(
            json.dumps(
                {
                    "context": ctx,
                    "summaries": summaries,
                    "summaries_5": summaries_5,
                    "gates_off": gates_off,
                    "regimes": regimes,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    _report(summaries, summaries_5, gates_off, regimes, verdict, sanity, boot, wf, diag, results)
    return 0


def _f(x, w=8, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries, summaries_5, gates_off, regimes, verdict, sanity, boot, wf, diag, results):
    print("── Rejilla `touch` (regla viva) con los gates de re-entrada MODELADOS ──")
    hdr = (
        f"{'brazo':<14}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'%stop':>8}"
        f"{'%trail':>8}{'%tp':>7}{'tomad':>8}{'G5 bloq':>9}"
    )
    print(hdr)
    for m in MULTS:
        n = arm_name(m)
        s = summaries[n]
        mark = "  <-- BASELINE (vivo)" if m == LIVE_MULT else ""
        print(
            f"{n:<14}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9)}{_f(s['max_dd'], 9, 1, '%')}"
            f"{_f(s['stop_share'], 8, 1, '%')}{_f(s['exit_mix'].get('atr_trail', 0), 8, 1, '%')}"
            f"{_f(s['exit_mix'].get('atr_tp', 0), 7, 0, '%')}{s['n_taken']:>8}"
            f"{results[n].n_gate5_blocked:>9}{mark}"
        )

    print("\n── La misma rejilla SIN los gates (lo que miden los harness publicados) ──")
    print(f"{'brazo':<14}{'CAGR c/gates':>14}{'CAGR s/gates':>14}{'delta':>10}")
    for m in MULTS:
        n = arm_name(m)
        d = summaries[n]["cagr"] - gates_off[n]["cagr"]
        print(
            f"{n:<14}{_f(summaries[n]['cagr'], 14, 2, '%')}{_f(gates_off[n]['cagr'], 14, 2, '%')}"
            f"{_f(d, 10, 2, '%')}"
        )

    print("\n── Rejilla `close` (cota INFERIOR de disparo — C8b) ──")
    print(f"{'brazo':<14}{'CAGR':>9}{'maxDD':>9}")
    for m in MULTS:
        n = arm_name(m, "close")
        print(f"{n:<14}{_f(summaries[n]['cagr'], 9, 2, '%')}{_f(summaries[n]['max_dd'], 9, 1, '%')}")

    if wf["per_fold"]:
        print("\n── §6 Walk-forward de la selección ──")
        print(f"{'fold':<24}{'n_train':>9}{'n_test':>8}{'elige':>12}{'OOS proc':>10}{'OOS base':>10}")
        for f in wf["per_fold"]:
            print(
                f"{f['test']:<24}{f['n_train']:>9}{f['n_test']:>8}{f['pick']:>12}"
                f"{_f(f['oos_cagr_proc'], 10, 2, '%')}{_f(f['oos_cagr_base'], 10, 2, '%')}"
            )
        print(
            f"\nSelecciones: {wf['picks']}  ⇒  M* = {arm_name(wf['m_star'])} "
            f"({wf['agreement']}/{len(FOLDS)} folds)"
        )
        print(
            f"Cadena OOS — procedimiento: CAGR {_f(wf['proc']['cagr'], 0, 2, '%')} · "
            f"maxDD {_f(wf['proc']['max_dd'], 0, 1, '%')}   |   "
            f"baseline fijo 2.0: CAGR {_f(wf['base']['cagr'], 0, 2, '%')} · "
            f"maxDD {_f(wf['base']['max_dd'], 0, 1, '%')}"
        )

    print("\n── §7 Sanity del instrumento ──")
    for k in (
        "accounting",
        "oracle_vs_random_cagr",
        "oracle_vs_random_dd",
        "off_arm_fires_nothing",
        "stop_share_monotone",
        "gates_wired",
        "gates_bite_composition",
    ):
        print(f"  {'OK ' if sanity[k] else 'FALLA'}  {k}")
    print(
        f"  (oráculo vs azar: ΔCAGR {_f(sanity['d_cagr'], 0, 2, '%')} · "
        f"ΔmaxDD {_f(sanity['d_dd'], 0, 2, '%')} · Gate 5 bloqueó "
        f"{sanity['n_gate5_blocked']} candidatos contra {sanity['n_taken']} trades "
        f"tomados · trades que difieren vs sin gates: "
        f"{_f(sanity['trade_diff'], 0, 1, '%')})"
    )

    print("\n── §8 Criterios (AND de los ocho) ──")
    for k, (val, ok) in verdict["criteria"].items():
        print(f"  {'PASA ' if ok else 'FALLA'}  {k:<20} {val}")
    print(
        f"\nDiagnóstico descriptivo (desacople stop/trailing, NO decide): "
        f"stop {verdict['m_star']:.1f} con trail {DIAG_TRAIL_MULT} ⇒ "
        f"CAGR {_f(diag['cagr'], 0, 2, '%')}"
    )
    print(
        f"\nbootstrap pareado: IC95% [{_f(boot.ci_low, 0, 4)}, {_f(boot.ci_high, 0, 4)}] p={boot.p_value:.3f}"
    )
    print(f"\nVEREDICTO: {verdict['outcome']}")


if __name__ == "__main__":
    raise SystemExit(main())
