"""
Runner de TRAIL-ARM — **Tarea 54**.

Pre-registro CONGELADO: ``docs/trail_arm_prereg_t54_2026-08-28.md``
Enmienda 1 (antes de correr): ``docs/trail_arm_enmienda_t54_2026-08-28.md``
Enmienda 2 (tras el smoke de cañería, antes de la corrida): ``docs/trail_arm_enmienda2_t54_2026-08-28.md``

Qué decide y por qué
--------------------
Desde el 2026-08-27 la cuenta 2 corre ``soff_t2.0`` — stop duro **apagado**, trailing
en 2.0×ATR. En ese brazo el **36,5%** de los trades tiene un HWM que nunca supera
``entrada + 1×ATR``, así que el trailing **nunca se arma** y esas posiciones quedan
con una sola barrera. La pregunta es si el umbral de armado
(``trail_min_excess_atrs``, 1.0 en vivo) está bien puesto.

El §0 del pre-registro tuvo que corregir **tres premisas** (tarea 61):

* el agujero **ya no es hipotético** — es la política de salida de hoy;
* la brecha de retorno del §7 de la 37 es **en buena parte mecánica**: el excedente
  máximo sobre la entrada es el **techo** del retorno posible, así que no prueba que
  el trailing hubiera salvado nada;
* bajar el umbral **reintroduce un stop duro por la ventana** (con ``trail_mult=2.0``
  el nivel queda por debajo de la entrada para la población que no arma), y eso es
  justo el brazo que la 37 apagó. **Predicción declarada: los umbrales bajos pierden.**

La grilla sale de la **distribución medida** (regla de la tarea 58,
``scripts/measure_trail_arm_t54.py``), no de una intuición, y la población que manda
es la **diferencial** —los trades que cambian de comportamiento—, no la acumulada.

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py``/``strategies.py``/``gates.py``.
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

from analysis.exit_replay import AtrParams
from analysis.harness_config import (
    HARNESS_FILL_MODE,
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    POPULATION_LIVE_ACCT2,
    REPRO_OK,
    WINDOW_REFRESH_2026_08_09,
    announce,
    announce_grid,
    artifact_window,
    reproduction_check,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import cagr
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    paired_block_bootstrap,
    regime_for_date,
)
from scripts.measure_trail_arm_t54 import trade_excess_atrs
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_event_timestop_t51 import (
    _prev_day,
    dose_response,
    entries_between,
    regime_pooled,
)
from scripts.run_rank_neutral_t39 import aligned_daily
from scripts.run_ranking_t21 import summarise, trade_overlap
from scripts.run_stop_cal_replay_t26 import NO_STOP
from scripts.run_stop_value_t37 import CacheDirBusy, SimCache
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

# ── Config congelada (§3) ────────────────────────────────────────────────────

EVAL_MODE = "touch"
FILL_MODE = HARNESS_FILL_MODE          # "decision" (T33)
LIVE_GATES = True
BASE_CAP = 250

# El brazo VIVO desde el 2026-08-27 — el baseline de esta tarea, que NO es el
# `s2.0_t2.0` con el que corrió toda la serie anterior.
LIVE_TRAIL_MULT = 2.0
BASE_K = 1.0
GRID_K: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.5)

BASELINE_ARM = "base_k1.00"
ORACLE_ARM = "ORACULO_arm"
ANTI_ORACLE_ARM = "ANTI_ORACULO_arm"

# ── Umbrales del §6 (CONGELADOS) ─────────────────────────────────────────────

KILL_MIN_DCAGR = 0.0050        # C1: +0.50 pp
KILL_MAX_DD_WORSE = 0.0300     # C3: +3.00 pp
KILL_REGIME_TOL_PTS = -1.00    # C8 (vía regime_pooled de la 51)
SENS_MAX_POSITIONS = 5         # C7

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345

# ── Sanity (§5, con la enmienda 1) ───────────────────────────────────────────

SANITY_MIN_POPULATION = 0.05   # §5.3 — el umbral de la T13, sobre la DIFERENCIAL
SANITY_MIN_TRADE_DIFF = 0.10   # §5.5 — el umbral muerde
ORACLE_MIN_SPREAD = 0.0100     # §5.4 (enmienda): oráculo − anti ≥ +1.00 pp

# §5.2 — reproducción. El brazo vivo ya reprodujo los dos dígitos de la T37 §7.7
# en la medición previa (9.17% / 28.2%), antes de congelar el pre-registro.
REPRO_BASE_CAGR = 0.0917
REPRO_TOL = 0.0005
# La fracción que nunca arma con el umbral vivo (T37 §7: 36,5%). No es un CAGR, así
# que va con su propia tolerancia y NO pasa por `reproduction_check`.
REPRO_NEVER_ARMED = 0.365
REPRO_NEVER_ARMED_TOL = 0.005

FOLDS: tuple[tuple[str, str, str], ...] = (
    ("2020-08-01", "2021-08-01", "2022-07-31"),
    ("2021-08-01", "2022-08-01", "2023-07-31"),
    ("2022-08-01", "2023-08-01", "2024-07-31"),
    ("2023-08-01", "2024-08-01", "2025-07-31"),
    ("2024-08-01", "2025-08-01", "2026-07-31"),
)

_CACHE = SimCache(None, None)


def _sim(tag: str, entries, bars_by, sigs_by, **kw) -> PortfolioResult:
    return _CACHE.run(f"t54|{tag}",
                      lambda: simulate_portfolio(entries, bars_by, sigs_by, **kw))


# ── Brazos (§2) ──────────────────────────────────────────────────────────────


def arm_name(k: float) -> str:
    return f"k{k:.2f}"


def thr_for_all(k: float):
    """El umbral de armado a **todas** las posiciones — el candidato, que es
    incondicional (por eso la enmienda 1 retira el control igualado en tasa)."""
    def f(_ticker: str, _date_iso10: str) -> float:
        return k
    return f


def thr_for_keys(keys: set[tuple[str, str]], k: float, base: float = BASE_K):
    """El umbral **sólo** a las posiciones cuya entrada está en ``keys``.

    Pura: depende de ``(ticker, fecha)`` y del conjunto, no del estado de la cartera
    ni del orden de las llamadas. Es lo que usan el oráculo y el anti-oráculo."""
    def f(ticker: str, date_iso10: str) -> float:
        return k if (ticker, date_iso10) in keys else base
    return f


# ── §5.3 — población DIFERENCIAL (la que un brazo puede mover) ───────────────


def excess_by_key(base_res: PortfolioResult, bars_by: dict) -> dict:
    """``{(ticker, fecha_entrada): excedente máximo sobre la entrada, en ATRs}``."""
    return {(r["ticker"], r["entry"]): r["excess_atrs"]
            for r in trade_excess_atrs(base_res, bars_by)}


def differential_keys(excess: dict, k: float, base: float = BASE_K) -> set:
    """Las claves que **cambian de comportamiento** al mover el umbral a ``k``.

    Bajarlo sólo toca a los trades con excedente en ``(k, base]``: los de arriba ya
    armaban el trailing y los de abajo siguen sin armarlo. Subirlo toca a los de
    ``(base, k]``, que **dejan** de armarlo. La acumulada sobrestima —es el error
    que la 51 pagó por el otro eje— y por eso el §5.3 se lee sobre ésta."""
    lo, hi = min(k, base), max(k, base)
    if k == base:
        return set()
    return {key for key, m in excess.items() if lo < m <= hi}


def population_share(excess: dict, k: float, base: float = BASE_K) -> float:
    return (len(differential_keys(excess, k, base)) / len(excess)) if excess else 0.0


# ── §5.4 con la ENMIENDA 2 — el oráculo, dentro de lo que el brazo puede tocar ─


def oracle_arm_keys(diff_keys: set, base_res: PortfolioResult, *,
                    worst: bool) -> set:
    """La mitad **peor** (o **mejor**) de la población que el brazo puede cambiar.

    La enmienda 2 existe porque elegir entre **todos** los candidatos —el molde de
    la 51— daba un anti-oráculo idéntico al baseline: el excedente es el techo del
    retorno (§0.2), así que "los que mejor terminan" son casi exactamente los que el
    umbral **no puede tocar**. Un oráculo que no puede moverse no acota nada.

    Los dos brazos quedan **igualados en tasa por construcción**: ``⌊|D|/2⌋``.
    Mira el futuro a propósito — es el instrumento, no un candidato.
    """
    rets = {(t.ticker, t.entry_date): t.ret for t in base_res.trades}
    pool = sorted(diff_keys, key=lambda k: (rets.get(k, 0.0), k), reverse=not worst)
    return set(pool[:len(pool) // 2])


# ── §6 — walk-forward que elige k* ───────────────────────────────────────────


def walk_forward(entries, bars_by, sigs_by, common: dict, ks: list[float],
                 *, log=sys.stdout) -> dict:
    """Elige el umbral en el **train** y lo cobra en el **test** siguiente.

    ``ks`` es la grilla **que pasó el §5.3**: la lección de la 58 es mirar la
    población **antes** que el acuerdo entre folds, porque un acuerdo perfecto sobre
    un brazo que casi no se ejecuta no es evidencia de nada.
    """
    picks: list[float] = []
    per_fold: list[dict] = []
    proc_eq = base_eq = float(common["initial_capital"])
    proc_curve: list[tuple[str, float]] = []
    base_curve: list[tuple[str, float]] = []

    for fi, (train_end, test_lo, test_hi) in enumerate(FOLDS, 1):
        train = entries_between(entries, bars_by, None, _prev_day(train_end))
        test = entries_between(entries, bars_by, test_lo, test_hi)
        print(f"    fold {fi}/{len(FOLDS)} — train {len(train)} · test {len(test)} …",
              file=log, flush=True)

        train_cagr = {
            k: cagr(_sim(f"wf|{fi}|train|{k:.2f}", train, bars_by, sigs_by,
                         trail_min_excess_of=thr_for_all(k), **common).equity_curve)
            for k in ks
        }
        pick = max(ks, key=lambda k: train_cagr[k])
        picks.append(pick)

        r_proc = _sim(f"wf|{fi}|test|{pick:.2f}|eq{proc_eq:.6f}", test, bars_by,
                      sigs_by, trail_min_excess_of=thr_for_all(pick),
                      **{**common, "initial_capital": proc_eq})
        r_base = _sim(f"wf|base|{fi}|test|eq{base_eq:.6f}", test, bars_by, sigs_by,
                      **{**common, "initial_capital": base_eq})
        proc_curve.extend(r_proc.equity_curve)
        base_curve.extend(r_base.equity_curve)
        proc_eq, base_eq = r_proc.final_equity, r_base.final_equity

        per_fold.append({
            "fold": fi, "train_end": train_end, "test": f"{test_lo}..{test_hi}",
            "n_train": len(train), "n_test": len(test), "pick": pick,
            "train_cagr": {f"{k:.2f}": train_cagr[k] for k in ks},
            "oos_cagr_proc": cagr(r_proc.equity_curve),
            "oos_cagr_base": cagr(r_base.equity_curve),
        })

    counts: dict[float, int] = {}
    for p in picks:
        counts[p] = counts.get(p, 0) + 1
    star = max(counts, key=lambda k: (counts[k], -k))
    return {"per_fold": per_fold, "picks": picks, "star": star,
            "agreement": counts[star],
            "oos_cagr_proc": cagr(proc_curve), "oos_cagr_base": cagr(base_curve)}


# ── C9 — que mueva el RESULTADO, no la etiqueta ──────────────────────────────


def exit_mix(res: PortfolioResult) -> dict:
    """Mezcla de motivos de salida. Descriptivo, y la mitad del C9."""
    out: dict[str, int] = {}
    for t in res.trades:
        motivo = (t.exit_reason or "?").split(" ")[0].split("@")[0].strip()
        out[motivo] = out.get(motivo, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def changed_exits(base_res: PortfolioResult, cand_res: PortfolioResult,
                  keys: set) -> dict:
    """Cuántos trades **cambian de salida** de verdad — descriptivo, NO gate.

    Cambiar el *estado de armado* del trailing no es cambiar la salida: un trailing
    armado sólo importa si llega a **disparar**. El smoke de cañería lo mostró con
    el anti-oráculo, que quedó idéntico al baseline dígito por dígito. Así que la
    población del §5.3 —los trades que cruzan el umbral— es una **cota superior** de
    lo que un brazo mueve, y este número dice cuánto de esa cota se realiza.
    """
    b = {(t.ticker, t.entry_date): (t.exit_date, t.exit_reason)
         for t in base_res.trades}
    c = {(t.ticker, t.entry_date): (t.exit_date, t.exit_reason)
         for t in cand_res.trades}
    comunes = [k for k in b if k in c]
    if not comunes:
        return {"n_common": 0, "n_changed": 0, "share": 0.0,
                "n_changed_in_diff_pop": 0}
    cambiados = [k for k in comunes if b[k] != c[k]]
    return {
        "n_common": len(comunes), "n_changed": len(cambiados),
        "share": len(cambiados) / len(comunes),
        "n_changed_in_diff_pop": sum(1 for k in cambiados if k in keys),
    }


def differential_return(base_res: PortfolioResult, cand_res: PortfolioResult,
                        keys: set) -> dict:
    """Retorno medio, **pareado por clave**, de los trades que el brazo cambia.

    C9: si el umbral sólo cambia *quién firma la salida* sin mejorar el retorno de
    esa población, el brazo movió la etiqueta y no el resultado.
    """
    b = {(t.ticker, t.entry_date): 100.0 * t.ret for t in base_res.trades}
    c = {(t.ticker, t.entry_date): 100.0 * t.ret for t in cand_res.trades}
    comunes = [k for k in keys if k in b and k in c]
    if not comunes:
        return {"n_common": 0, "base_pts": 0.0, "cand_pts": 0.0, "delta_pts": 0.0}
    xb = statistics.fmean(b[k] for k in comunes)
    xc = statistics.fmean(c[k] for k in comunes)
    return {"n_common": len(comunes), "base_pts": xb, "cand_pts": xc,
            "delta_pts": xc - xb}


# ── §6 — la regla de decisión ────────────────────────────────────────────────


def evaluate(base: dict, cand: dict, boot, c6: dict, c8: dict, sens: dict | None,
             diff_ret: dict) -> dict:
    dcagr = cand["cagr"] - base["cagr"]
    c1 = bool(dcagr >= KILL_MIN_DCAGR)
    c3 = bool(cand["max_dd"] <= base["max_dd"] + KILL_MAX_DD_WORSE)
    c4 = bool(boot is not None and boot.ci_low > 0.0)
    c6_ok = bool(c6.get("passes"))
    c7 = bool(sens is not None and sens.get("c1") and sens.get("c4"))
    c8_ok = bool(c8.get("passes"))
    # C9: mueve el resultado, no la etiqueta.
    c9 = bool(c1 and diff_ret["n_common"] > 0 and diff_ret["delta_pts"] > 0.0)
    ship = bool(c1 and c3 and c4 and c6_ok and c7 and c8_ok and c9)
    return {"dcagr": dcagr, "c1_dcagr": c1, "c3_maxdd": c3, "c4_boot_base": c4,
            "c6_dose": c6_ok, "c7_sensitivity": c7, "c8_regime": c8_ok,
            "c9_moves_the_result": c9, "ship": ship}


def evaluate_sanity(summaries: dict, trade_diff: float, repro: dict,
                    pop: dict, k_star: float) -> dict:
    acc = all(s["accounting_ok"] for s in summaries.values())
    orac = summaries[ORACLE_ARM]["cagr"]
    anti = summaries[ANTI_ORACLE_ARM]["cagr"]
    cand = summaries[arm_name(k_star)]["cagr"]
    checks = {
        "accounting": acc,
        "repro_base": bool(repro.get("base_ok")),
        "repro_never_armed": bool(repro.get("never_armed_ok")),
        # §5.4 con la enmienda 1: sin controles, el contraste es oráculo vs anti.
        "oracle_beats_anti_oracle": bool(orac - anti >= ORACLE_MIN_SPREAD),
        "candidate_inside_the_oracle_range": bool(anti <= cand <= orac),
        "threshold_bites": bool(trade_diff >= SANITY_MIN_TRADE_DIFF),
    }
    return {"checks": checks, "valid": all(checks.values()),
            "trade_diff": trade_diff, "oracle_cagr": orac, "anti_oracle_cagr": anti,
            "population": pop, "k_star": k_star}


def outcome_of(v: dict, pop: dict, *, sanity_valid: bool) -> str:
    """La prosa del §6, resuelta ex ante. ``sanity_valid`` es **keyword
    obligatorio** — la guarda que la tarea 60 tuvo que agregarle al runner de la 51
    después de escribirlo."""
    if not sanity_valid:
        return ("CORRIDA INVÁLIDA — falló un sanity del §5. No hay veredicto y no se "
                "re-especifica nada (precedente T26).")
    if not pop["ok"]:
        return ("SIN POBLACIÓN — el umbral elegido cambia menos del 5% de los trades. "
                "El brazo está SIN PODER, no refutado (T13, §5.3). No hay veredicto.")
    if v["ship"]:
        return ("SHIP — el umbral de armado del trailing se mueve a k*. El ship es el "
                "MECANISMO y apagado (§7): `paper_atr_trail_min_excess_atrs` con "
                "default 1.0, en una tarea propia.")
    if not v["c1_dcagr"]:
        return ("NO-SHIP — C1: mover el umbral de armado no paga sobre la política "
                "que corre hoy. El 1.0 vivo NO está mal puesto, y eso es información "
                "útil sobre una salida que está en producción.")
    if not v["c9_moves_the_result"]:
        return ("NO-SHIP — C9: el umbral mueve el MOTIVO de salida, no el resultado. "
                "Cambia quién firma la salida sin mejorar el retorno de los trades "
                "que efectivamente toca.")
    if not v["c4_boot_base"]:
        return ("NO-SHIP — C4: la ventaja no sobrevive al bootstrap pareado contra el "
                "baseline; el intervalo cruza el cero.")
    if not v["c6_dose"]:
        return ("NO-SHIP — C6: no hay dosis-respuesta. El efecto vive en un umbral "
                "aislado, que es la firma del sobreajuste, no la de un mecanismo.")
    return "NO-SHIP — no pasa el AND de los criterios del §6."


# ── Main ─────────────────────────────────────────────────────────────────────


def _common(max_positions: int, capital: float, **over) -> dict:
    base = dict(
        max_positions=max_positions, initial_capital=capital, cap_days=BASE_CAP,
        atr_p=AtrParams(stop_mult=NO_STOP, trail_mult=LIVE_TRAIL_MULT,
                        trail_min_excess_atrs=BASE_K),
        so_params=ScaleOutParams(), costs=CostModel(),
        regime_of=regime_for_date, allow_reentry_while_open=False,
        eval_mode=EVAL_MODE, fill_mode=FILL_MODE, live_gates=LIVE_GATES,
    )
    base.update(over)
    return base


def _boot_d(b) -> dict | None:
    if b is None:
        return None
    return {"delta": b.observed, "ci_low": b.ci_low, "ci_high": b.ci_high,
            "p_value": b.p_value}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TRAIL-ARM (tarea 54)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--no-walkforward", action="store_true", help="sólo desarrollo")
    p.add_argument("--no-sensitivity", action="store_true", help="sólo desarrollo")
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--budget-seconds", type=float, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    smoke = bool(args.universe != LIVE_UNIVERSE_FILE or args.no_walkforward
                 or args.no_sensitivity)

    global _CACHE
    try:
        _CACHE = SimCache(Path(args.cache_dir) if args.cache_dir else None,
                          args.budget_seconds)
    except CacheDirBusy as exc:
        # Tarea 59: morir temprano y con el culpable nombrado. Seguir seria
        # mezclarse con la otra corrida en el cache y en el artefacto, y eso
        # despues no se detecta.
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 2

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, _missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.",
              file=sys.stderr)
        return 1
    entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not entries:
        print("Sin entradas BUY.", file=sys.stderr)
        return 1

    window = artifact_window(bars_by)
    cfg = announce(args.max_positions, args.universe, len(bars_by), window=window,
                   eval_mode=EVAL_MODE, fill_mode=FILL_MODE, live_gates=LIVE_GATES,
                   file=log)
    print(f"Tickers: {len(bars_by)} · entradas `analyze BUY`: {len(entries)}", file=log)
    print(f"BASELINE = el brazo VIVO desde 2026-08-27: stop duro OFF + trail "
          f"{LIVE_TRAIL_MULT}×ATR, armado en {BASE_K}×ATR", file=log)
    print(f"Grilla del umbral: k ∈ {list(GRID_K)}\n", file=log)
    if smoke:
        print("*** SMOKE — la corrida NO puede dictar veredicto ***\n", file=log)

    common = _common(args.max_positions, args.capital)

    # ── 1. Baseline + la población de la grilla (T58, ANTES de los brazos) ────
    results: dict[str, PortfolioResult] = {}
    results[BASELINE_ARM] = _sim(f"grid|{BASELINE_ARM}", entries, bars_by, sigs_by,
                                 **common)
    base_res = results[BASELINE_ARM]
    excess = excess_by_key(base_res, bars_by)
    grid_pop = announce_grid(list(excess.values()), GRID_K,
                             label="excedente máximo sobre la entrada (en ATRs)",
                             file=log)
    # La acumulada que imprime `announce_grid` es informativa; la que MANDA es la
    # diferencial (§5.3 + enmienda del pre-registro).
    diff_share = {k: population_share(excess, k) for k in GRID_K}
    print("Población DIFERENCIAL — trades que cambian de comportamiento vs "
          f"k={BASE_K:.2f}:", file=log)
    print(f"  {'k':>6} {'cambian':>9} {'población':>11}", file=log)
    for k in GRID_K:
        marca = "" if diff_share[k] >= SANITY_MIN_POPULATION else "  <- sin población"
        print(f"  {k:>6.2f} {round(diff_share[k] * len(excess)):>9} "
              f"{100 * diff_share[k]:>10.2f}%{marca}", file=log)
    print("", file=log)

    viables = [k for k in GRID_K if diff_share[k] >= SANITY_MIN_POPULATION]
    if not viables:
        print("Ningún brazo con población: no hay nada que medir.", file=sys.stderr)
        viables = list(GRID_K)

    # ── 2. La grilla ─────────────────────────────────────────────────────────
    for k in GRID_K:
        print(f"  grilla k={k:.2f} …", file=log, flush=True)
        results[arm_name(k)] = _sim(f"grid|{arm_name(k)}", entries, bars_by, sigs_by,
                                    trail_min_excess_of=thr_for_all(k), **common)
    summaries = {n: summarise(r) for n, r in results.items()}

    # ── 3. k* por WALK-FORWARD sobre la grilla CON POBLACIÓN ─────────────────
    if args.no_walkforward:
        star = max(viables, key=lambda k: summaries[arm_name(k)]["cagr"])
        wf = {"star": star, "agreement": 0, "SMOKE": True, "per_fold": [],
              "picks": []}
    else:
        print("\n  §6 — walk-forward que elige k* …", file=log, flush=True)
        wf = walk_forward(entries, bars_by, sigs_by, common, viables, log=log)
        star = wf["star"]
    arm = arm_name(star)
    print(f"\n  k* = {star:.2f} ({wf['agreement']}/{len(FOLDS)} folds) · "
          f"población diferencial {100 * diff_share[star]:.2f}%\n", file=log)

    pop = {"share": diff_share[star], "min": SANITY_MIN_POPULATION,
           "ok": bool(diff_share[star] >= SANITY_MIN_POPULATION),
           "by_k": {f"{k:.2f}": diff_share[k] for k in GRID_K}}

    # ── 4. Oráculo y anti-oráculo, igualados en tasa (§5.4 + enmienda) ───────
    print("  oráculo / anti-oráculo …", file=log, flush=True)
    keys_star = differential_keys(excess, star)
    for name, worst in ((ORACLE_ARM, True), (ANTI_ORACLE_ARM, False)):
        keys = oracle_arm_keys(keys_star, base_res, worst=worst)
        results[name] = _sim(f"oracle2|{star:.2f}|{int(worst)}", entries, bars_by,
                             sigs_by, trail_min_excess_of=thr_for_keys(keys, star),
                             **common)
        summaries[name] = summarise(results[name])

    # ── 5. §5.2 — reproducción (ventana + población: 48 y 52) ────────────────
    pop_run = cfg.population(len(entries))
    st_base, why_base = reproduction_check(
        summaries[BASELINE_ARM]["cagr"], REPRO_BASE_CAGR, tol=REPRO_TOL,
        current=window, measured_on=WINDOW_REFRESH_2026_08_09,
        population=pop_run, measured_over=POPULATION_LIVE_ACCT2)
    never_armed = sum(1 for m in excess.values() if m <= BASE_K) / len(excess)
    repro = {
        "base_state": st_base, "base_why": why_base,
        "base_ok": st_base == REPRO_OK,
        "never_armed": never_armed,
        "never_armed_expected": REPRO_NEVER_ARMED,
        "never_armed_ok": bool(abs(never_armed - REPRO_NEVER_ARMED)
                               <= REPRO_NEVER_ARMED_TOL),
    }

    # ── 6. Bootstrap pareado (C4) ────────────────────────────────────────────
    print("  bootstrap pareado …", file=log, flush=True)
    daily = aligned_daily(results, [BASELINE_ARM, arm])

    def _boot(xs, ys):
        if not xs or not ys:
            return None
        n = min(len(xs), len(ys))
        return paired_block_bootstrap([v for _, v in xs[:n]], [v for _, v in ys[:n]],
                                      block=BOOT_BLOCK, n_resamples=args.resamples,
                                      seed=BOOT_SEED)

    boot = _boot(daily[BASELINE_ARM], daily[arm])

    # ── 7. C6 (dosis-respuesta) y C8 (régimen) ───────────────────────────────
    base_cagr = summaries[BASELINE_ARM]["cagr"]
    deltas = {k: summaries[arm_name(k)]["cagr"] - base_cagr for k in GRID_K}
    c6 = dose_response(deltas, star)
    print("  régimen (C8) …", file=log, flush=True)
    c8 = regime_pooled(base_res, results[arm])

    # ── 8. C9 — el resultado, no la etiqueta ─────────────────────────────────
    diff_ret = differential_return(base_res, results[arm], keys_star)
    realized_change = changed_exits(base_res, results[arm], keys_star)
    mixes = {n: exit_mix(results[n]) for n in (BASELINE_ARM, arm)}

    # ── 9. C7 — sensibilidad a 5 slots ───────────────────────────────────────
    sens = None
    if not args.no_sensitivity:
        print(f"  C7 — sensibilidad a {SENS_MAX_POSITIONS} slots …", file=log,
              flush=True)
        s_common = _common(SENS_MAX_POSITIONS, args.capital)
        s_res = {
            BASELINE_ARM: _sim(f"sens|{BASELINE_ARM}", entries, bars_by, sigs_by,
                               **s_common),
            arm: _sim(f"sens|{arm}", entries, bars_by, sigs_by,
                      trail_min_excess_of=thr_for_all(star), **s_common),
        }
        s_sum = {n: summarise(r) for n, r in s_res.items()}
        s_daily = aligned_daily(s_res, [BASELINE_ARM, arm])
        s_boot = _boot(s_daily[BASELINE_ARM], s_daily[arm])
        sens = {
            "max_positions": SENS_MAX_POSITIONS,
            "base_cagr": s_sum[BASELINE_ARM]["cagr"], "cand_cagr": s_sum[arm]["cagr"],
            "c1": bool(s_sum[arm]["cagr"] - s_sum[BASELINE_ARM]["cagr"]
                       >= KILL_MIN_DCAGR),
            "c4": bool(s_boot is not None and s_boot.ci_low > 0.0),
        }

    # ── 10. Veredicto ────────────────────────────────────────────────────────
    trade_diff = trade_overlap(base_res, results[arm])
    sanity = evaluate_sanity(summaries, trade_diff, repro, pop, star)
    v = evaluate(summaries[BASELINE_ARM], summaries[arm], boot, c6, c8, sens,
                 diff_ret)
    if not pop["ok"] or not sanity["valid"]:
        v["ship"] = False
    outcome = outcome_of(v, pop, sanity_valid=sanity["valid"])

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "smoke": smoke, "universe": args.universe, "n_tickers": len(bars_by),
        "max_positions": args.max_positions, "window": str(window),
        "population": str(pop_run), "n_entries": len(entries),
        "grid_k": list(GRID_K), "base_k": BASE_K, "viables": viables,
        "arm": arm, "k_star": star, "wf": wf,
        "summaries": summaries, "repro": repro, "sanity": sanity,
        "grid_population": {
            "cumulative": [{"value": a.value, "n_hit": a.n_hit, "share": a.share,
                            "inert": a.inert, "underpowered": a.underpowered}
                           for a in grid_pop.arms],
            "differential": {f"{k:.2f}": diff_share[k] for k in GRID_K},
            "warnings": grid_pop.warnings(),
        },
        "c6_dose": c6, "c8_regime": c8, "sensitivity": sens,
        "boot_vs_base": _boot_d(boot),
        "diff_return": diff_ret, "exit_mix": mixes,
        "changed_exits": realized_change,
        "verdict": v, "outcome": outcome,
        "cache": {"hits": _CACHE.hits, "misses": _CACHE.misses},
    }

    if args.json:
        print(json.dumps(ctx, indent=2, default=str))
    else:
        _report(ctx)
    return 0


def _crit(v: dict) -> None:
    for k, val in v.items():
        if k.startswith("c") and isinstance(val, bool):
            print(f"    [{'OK ' if val else 'FALLA'}] {k}")


def _report(ctx: dict) -> None:
    s, sn = ctx["summaries"], ctx["sanity"]
    print("\n" + "=" * 78)
    print("TRAIL-ARM (tarea 54) — ¿el umbral de ARMADO del trailing está bien puesto?")
    print("=" * 78)
    if ctx["smoke"]:
        print("\n*** SMOKE — la corrida NO puede dictar veredicto ***")

    print(f"\nVentana: {ctx['window']} · población: {ctx['population']}")
    print(f"k* = {ctx['k_star']:.2f} ({ctx['wf']['agreement']}/{len(FOLDS)} folds)")

    print("\n  Grilla (ΔCAGR vs el brazo vivo, en pp):")
    base = s[BASELINE_ARM]["cagr"]
    print(f"    {'k':>6} {'ΔCAGR':>10} {'población dif.':>16}")
    for k in ctx["grid_k"]:
        d = 100 * (s[arm_name(k)]["cagr"] - base)
        share = ctx["grid_population"]["differential"][f"{k:.2f}"]
        print(f"    {k:>6.2f} {d:>10.2f} {100 * share:>15.2f}%")

    print("\n  Brazos:")
    for name in [BASELINE_ARM, ctx["arm"], ORACLE_ARM, ANTI_ORACLE_ARM]:
        v = s[name]
        print(f"    {name:<18} CAGR {100 * v['cagr']:>7.2f}% · "
              f"Sharpe {v['sharpe']:>5.2f} · maxDD {100 * v['max_dd']:>6.1f}% · "
              f"tomadas {v['n_taken']:>5} · tenencia {v['mean_held_days']:.1f}d")

    print("\n  §5 — sanity (si alguno falla, la corrida es INVÁLIDA):")
    for k, ok in sn["checks"].items():
        print(f"    [{'OK ' if ok else 'FALLA'}] {k}")
    rp = ctx["repro"]
    print(f"    reproducción base: {rp['base_state']} · nunca arma "
          f"{100 * rp['never_armed']:.2f}% (esperado "
          f"{100 * rp['never_armed_expected']:.1f}%)")
    print(f"    población diferencial del k*: {100 * sn['population']['share']:.2f}% "
          f"(mínimo {100 * sn['population']['min']:.0f}%)")

    ce = ctx["changed_exits"]
    print(f"\n  Salidas que CAMBIAN de verdad: {ce['n_changed']} de "
          f"{ce['n_common']} trades comunes ({100 * ce['share']:.2f}%) · "
          f"{ce['n_changed_in_diff_pop']} dentro de la población del §5.3 "
          f"(descriptivo, no gate)")

    dr = ctx["diff_return"]
    print(f"\n  C9 — los {dr['n_common']} trades que el brazo cambia: "
          f"{dr['base_pts']:.2f} → {dr['cand_pts']:.2f} pts "
          f"(Δ {dr['delta_pts']:+.2f})")
    for name, mix in ctx["exit_mix"].items():
        top = " · ".join(f"{m} {n}" for m, n in list(mix.items())[:4])
        print(f"    {name:<18} {top}")

    print("\n  §6 — criterios:")
    _crit(ctx["verdict"])
    print(f"\n  corrida {'VÁLIDA' if sn['valid'] else 'INVÁLIDA'}")
    print(f"\n  VEREDICTO: {ctx['outcome']}")
    print("=" * 78)


if __name__ == "__main__":
    raise SystemExit(main())
