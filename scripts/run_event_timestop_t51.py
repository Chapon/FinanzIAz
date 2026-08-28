"""
Runner de EVENT-TIMESTOP — **Tarea 51**.

Pre-registro con la regla CONGELADA: ``docs/event_timestop_prereg_t51_2026-08-28.md``.

Qué decide y por qué
--------------------
La **49** midió que priorizar la anomalía en el desempate del día **no es el efecto**: a la tenencia
del engine (``cap_days=250``) el candidato da 0.51% contra 3.23%. Pero el descriptivo de la **45**
reproduce exacto con ``cap_days=20`` (3.71% → 7.92%). **El efecto se da vuelta entero al cambiar de
tenencia**, así que la hipótesis pasa a ser que lo que funcionaba no era *cuándo entra* sino
**cuánto se lo sostiene**.

Y el §0 del pre-registro tuvo que corregir **dos premisas falsas** del enunciado (tarea 57):

* ``cap_days`` y ``time_stop_days`` **no son la misma regla** — el cap duro cierra al llegar a la
  barra N **a todos, ganadores incluidos**; el time stop de la T13 dispara una sola vez y **sólo en
  pérdida**. El +4.21 pp vive en el **cap duro**, que la T13 nunca midió.
* La T13 **no refutó** su brazo: cerró **«sin población»** (0,5% alcanzados contra ≥5%), sobre 5
  slots y 41 tickers.

Por eso las preguntas son **tres, anidadas** (§1): ¿el tope hace algo? ¿es del **evento** o de
**cualquier** posición? ¿hay **dosis-respuesta** en N? Y hay **dos candidatos con jerarquía**: el
condicionado al evento (A) tiene que ganarle al incondicional (B), no sólo al baseline.

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

from analysis.anomaly_signal import AnomalyParams, build_anomaly_entries  # noqa: E402
from analysis.exit_replay import AtrParams  # noqa: E402
from analysis.harness_config import (  # noqa: E402
    HARNESS_FILL_MODE,
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    POPULATION_LIVE_ACCT2,
    REPRO_OK,
    WINDOW_REFRESH_2026_08_09,
    announce,
    artifact_window,
    reproduction_check,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio  # noqa: E402
from analysis.rank_policy import rate_matched_priority  # noqa: E402
from analysis.risk_sizing import cagr  # noqa: E402
from analysis.scaleout_replay import CostModel, ScaleOutParams  # noqa: E402
from analysis.walkforward_power import (  # noqa: E402
    STRESS_REGIMES,
    paired_block_bootstrap,
    regime_for_date,
)
from scripts.precompute_pit_signals import parse_universe_file  # noqa: E402
from scripts.run_anom_profile_t45 import _delta_samples_pooled, per_trade_pts  # noqa: E402
from scripts.run_anomaly_replay_t11b import _pct, load_bars_signals_volume  # noqa: E402
from scripts.run_prio_event_t49 import (  # noqa: E402
    candidates_by_date,
    count_by_date,
    keys_of,
    restrict_to_pool,
)
from scripts.run_rank_neutral_t39 import aligned_daily  # noqa: E402
from scripts.run_ranking_t21 import (  # noqa: E402
    load_bars_signals_scores,
    precompute_realized,
    summarise,
    trade_overlap,
)
from scripts.run_regime_power_t46 import _summarise_samples  # noqa: E402
from scripts.run_stop_value_t37 import (  # noqa: E402
    BudgetExhausted,
    SimCache,
    _prev_day,
    entries_between,
)
from scripts.run_tp_cal_replay_t23 import buy_entries  # noqa: E402

# ── §3 — población y config CONGELADAS ───────────────────────────────────────
BASE_CAP = 250            # la tenencia del engine: sin tope efectivo
EVAL_MODE = "touch"       # la regla que ejecuta el engine (26b)
FILL_MODE = HARNESS_FILL_MODE
LIVE_GATES = True         # los gates de re-entrada del engine vivo (T34)
ANOM_K, ANOM_M = 2.0, 1.5  # el detector congelado de la T11b/45

# ── §2 — brazos ──────────────────────────────────────────────────────────────
GRID_N: tuple[int, ...] = (10, 15, 20, 30, 40, 60)
BASELINE_ARM = "B_base"
UNCOND_PREFIX = "U_"      # CANDIDATO B — el tope a todas
EVENT_PREFIX = "E_"       # CANDIDATO A — el tope sólo al evento
CONTROL_PREFIX = "C_rand_"
CONTROL_SEEDS = 20
CONTROL_SEED_BASE = 60_000
ORACLE_ARM = "ORACULO_cap"
ANTI_ORACLE_ARM = "ANTI_ORACULO_cap"

# ── §6 — kill-criteria CONGELADOS ────────────────────────────────────────────
KILL_MIN_DCAGR = 0.0050       # C1: ≥ +0.50 pp sobre B_base
KILL_DD_TOL = 0.0300          # C3: maxDD ≤ base + 3.00 pp
KILL_CONTROL_PCTILE = 95      # C2: > p95 de las 20 semillas
KILL_A_OVER_B = 0.0050        # C9: A − B ≥ +0.50 pp
UNIMODAL_TOL = 0.0020         # C6: ±0.20 pp no cuenta como cambio de dirección
NEIGHBOUR_SHARE = 0.50        # C6: los vecinos conservan ≥50% del ΔCAGR de N*
KILL_REGIME_TOL_PTS = -1.00   # C8: el IC95% no entero por debajo de −1.00 pt
SENS_MAX_POSITIONS = 5        # C7

# ── §5 — sanity del instrumento ──────────────────────────────────────────────
SANITY_MIN_POPULATION = 0.05   # el umbral de la T13 (§6.3), reusado tal cual
SANITY_MIN_TRADE_DIFF = 0.10   # el tope muerde ≥10% de trades distintos
SANITY_ORACLE_PCTILE = 95
REPRO_BASE_CAGR = 0.0323       # `B1_score` cap 250 — la 49 §0 y la T39
REPRO_ALPHA_CAP20 = 0.0371     # `E_analyze` de la 45 — la 49 §5.2
REPRO_ALPHA_CAP250 = 0.0201    # `A_alpha` — la 49 §0 (cross-check, NO es gate)
REPRO_TOL = 0.0005

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345
REGIME_RESAMPLES = 2000
REGIME_SEED = 777

# §6 — el walk-forward que elige N* (los folds de la T37).
FOLDS: tuple[tuple[str, str, str], ...] = (
    ("2020-08-01", "2021-08-01", "2022-07-31"),
    ("2021-08-01", "2022-08-01", "2023-07-31"),
    ("2022-08-01", "2023-08-01", "2024-07-31"),
    ("2023-08-01", "2024-08-01", "2025-07-31"),
    ("2024-08-01", "2025-08-01", "2026-07-31"),
)

STRESS_NAMES = tuple(r.name for r in STRESS_REGIMES)
POOLED = "stress_POOLED"

_CACHE = SimCache(None, None)


def _sim(tag: str, entries, bars_by, sigs_by, **kw) -> PortfolioResult:
    return _CACHE.run(f"t51|{tag}",
                      lambda: simulate_portfolio(entries, bars_by, sigs_by, **kw))


# ── Brazos (§2) ──────────────────────────────────────────────────────────────


def uncond_name(n: int) -> str:
    return f"{UNCOND_PREFIX}{n}"


def event_name(n: int) -> str:
    return f"{EVENT_PREFIX}{n}"


def control_name(k: int) -> str:
    return f"{CONTROL_PREFIX}{k}"


def cap_for_all(n: int):
    """El tope a **todas** las posiciones — CANDIDATO B."""
    def f(_ticker: str, _date_iso10: str) -> int:
        return n
    return f


def cap_for_keys(keys: set[tuple[str, str]], n: int, base: int = BASE_CAP):
    """El tope **sólo** a las posiciones cuya entrada está en ``keys``.

    Pura: depende de ``(ticker, fecha)`` y del conjunto, no del estado de la
    cartera ni del orden de las llamadas."""
    def f(ticker: str, date_iso10: str) -> int:
        return n if (ticker, date_iso10) in keys else base
    return f


def oracle_cap_keys(cands_by_date: dict[str, list[str]], n_by_date: dict[str, int],
                    realized: dict, *, worst: bool) -> set[tuple[str, str]]:
    """Las claves a capar, **igualadas en tasa**, elegidas por el retorno realizado.

    Mira el futuro a propósito: es el sanity de que el instrumento ve topes buenos
    (capar a las que peor terminan) y malos (capar a las que mejor terminan). Con la
    misma ``n`` por día que el candidato, así el umbral del §5.4 es duro.
    """
    out: set[tuple[str, str]] = set()
    default = 9.9 if worst else -9.9
    for d, n in n_by_date.items():
        pool = cands_by_date.get(d) or []
        if n <= 0 or not pool:
            continue
        ranked = sorted(pool, key=lambda t: (realized.get((t, d), default), t),
                        reverse=not worst)
        out.update((t, d) for t in ranked[:n])
    return out


# ── §5.2 — el sanity de población de la T13 ──────────────────────────────────


def population_share(base_res: PortfolioResult, n: int,
                     keys: set[tuple[str, str]] | None = None) -> float:
    """Fracción de trades del **baseline** que el tope de ``n`` alcanzaría.

    Es el §6.3 de la T13 reusado tal cual: si es menor a ``SANITY_MIN_POPULATION``
    el brazo está **sin poder** y se reporta *«sin población»*, no como NO-SHIP —
    que es exactamente el diagnóstico que la T13 publicó y el enunciado de esta
    tarea leyó al revés (tarea 57).

    ``keys=None`` ⇒ la población del brazo incondicional (todos los trades).
    """
    trades = base_res.trades
    if not trades:
        return 0.0
    hit = [t for t in trades if t.held_days >= n
           and (keys is None or (t.ticker, t.entry_date) in keys)]
    return len(hit) / len(trades)


# ── §4 — dosis-respuesta ─────────────────────────────────────────────────────


def dose_response(deltas: dict[int, float], n_star: int) -> dict:
    """C6: la curva ΔCAGR vs N tiene que ser **unimodal** y sin **pico aislado**.

    Unimodal con tolerancia: un tramo con |Δ| ≤ ``UNIMODAL_TOL`` no cuenta como
    cambio de dirección. Sin pico aislado: los vecinos de ``N*`` en la grilla
    conservan ≥``NEIGHBOUR_SHARE`` del ΔCAGR de ``N*``.
    """
    ns = sorted(deltas)
    seq = [deltas[n] for n in ns]
    dirs = []
    for a, b in zip(seq, seq[1:]):
        d = b - a
        dirs.append(0 if abs(d) <= UNIMODAL_TOL else (1 if d > 0 else -1))
    nz = [d for d in dirs if d != 0]
    changes = sum(1 for a, b in zip(nz, nz[1:]) if a != b)
    unimodal = changes <= 1

    i = ns.index(n_star)
    neigh = [ns[j] for j in (i - 1, i + 1) if 0 <= j < len(ns)]
    peak = deltas[n_star]
    if peak <= 0.0:
        # Sin efecto positivo que sostener no hay nada que llamar dosis-respuesta.
        no_isolated = False
        kept = 0.0
    else:
        kept = min((deltas[m] / peak) for m in neigh) if neigh else 0.0
        no_isolated = bool(neigh) and kept >= NEIGHBOUR_SHARE

    return {
        "n_star": n_star, "deltas": {str(n): deltas[n] for n in ns},
        "directions": dirs, "direction_changes": changes,
        "unimodal": unimodal, "neighbour_kept": kept, "no_isolated_peak": no_isolated,
        "passes": bool(unimodal and no_isolated),
    }


# ── §6 — regla de decisión ───────────────────────────────────────────────────


def evaluate_b(base: dict, cand: dict, boot_base, c6: dict, c8: dict,
               sens: dict | None) -> dict:
    """CANDIDATO B — el tope **incondicional**. C2/C5 no aplican (su tasa es 100%)."""
    dcagr = cand["cagr"] - base["cagr"]
    c1 = bool(dcagr >= KILL_MIN_DCAGR)
    c3 = bool(cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL)
    c4 = bool(boot_base is not None and boot_base.ci_low > 0.0)
    c6_ok = bool(c6["passes"])
    c7 = bool(sens) and bool(sens.get("b_c1")) and bool(sens.get("b_c4"))
    c8_ok = bool(c8["passes"])
    ship = bool(c1 and c3 and c4 and c6_ok and c7 and c8_ok)
    return {"dcagr": dcagr, "c1_dcagr": c1, "c3_maxdd": c3, "c4_boot_base": c4,
            "c6_dose": c6_ok, "c7_sensitivity": c7, "c8_regime": c8_ok, "ship": ship}


def evaluate_a(base: dict, cand: dict, b_cand: dict, controls: list[dict],
               boot_base, boot_ctrl, boot_b, c6: dict, c8: dict,
               sens: dict | None) -> dict:
    """CANDIDATO A — el tope **condicionado al evento**. Todos los de B más C2/C5/C9."""
    ctrl_cagrs = [c["cagr"] for c in controls]
    ctrl_p95 = _pct(ctrl_cagrs, KILL_CONTROL_PCTILE) if ctrl_cagrs else float("nan")

    dcagr = cand["cagr"] - base["cagr"]
    dover_b = cand["cagr"] - b_cand["cagr"]
    c1 = bool(dcagr >= KILL_MIN_DCAGR)
    c2 = bool(ctrl_cagrs and cand["cagr"] > ctrl_p95)
    c3 = bool(cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL)
    c4 = bool(boot_base is not None and boot_base.ci_low > 0.0)
    c5 = bool(boot_ctrl is not None and boot_ctrl.ci_low > 0.0)
    c6_ok = bool(c6["passes"])
    c7 = bool(sens) and bool(sens.get("a_c1")) and bool(sens.get("a_c4"))
    c8_ok = bool(c8["passes"])
    c9 = bool(dover_b >= KILL_A_OVER_B
              and boot_b is not None and boot_b.ci_low > 0.0)
    ship = bool(c1 and c2 and c3 and c4 and c5 and c6_ok and c7 and c8_ok and c9)
    return {"dcagr": dcagr, "dcagr_over_b": dover_b, "control_p95": ctrl_p95,
            "control_median": statistics.median(ctrl_cagrs) if ctrl_cagrs else None,
            "c1_dcagr": c1, "c2_vs_control": c2, "c3_maxdd": c3, "c4_boot_base": c4,
            "c5_boot_control": c5, "c6_dose": c6_ok, "c7_sensitivity": c7,
            "c8_regime": c8_ok, "c9_beats_uncond": c9, "ship": ship}


def outcome_of(a: dict, b: dict, pop: dict, *, sanity_valid: bool) -> str:
    """La prosa del §6, resuelta ex ante para cada desenlace.

    ``sanity_valid`` es **keyword obligatorio** a propósito: el §5 dice que si falla
    un sanity la corrida es INVÁLIDA y **no hay veredicto**, así que un llamador que
    se lo olvide no puede publicar un SHIP sobre una corrida que no se sostiene — el
    molde de la 45, la 47 y la 49, que este runner no tenía.
    """
    if not sanity_valid:
        # Sin población la invalidez no es un misterio de cañería: el oráculo del cap
        # y las semillas del control se quedan sin sobre qué moverse. Decirlo evita
        # mandar a buscar un bug donde lo que falta es el objeto de la regla.
        why = ("" if (pop["b_ok"] or pop["a_ok"]) else
               " La causa está a la vista en el §5.2: sin población, ni el oráculo "
               "del cap ni las semillas del control tienen a quién capar.")
        return ("CORRIDA INVÁLIDA — falló un sanity del §5. No hay veredicto y no se "
                "re-especifica nada (precedente T26)." + why)
    if not pop["b_ok"] and not pop["a_ok"]:
        return ("SIN POBLACIÓN — menos del 5% de los trades del baseline llega al "
                "tope. El brazo está SIN PODER, no refutado (mismo diagnóstico que "
                "la T13, §5.2). No hay veredicto.")
    if a["ship"]:
        return ("SHIP A — el tope condicionado al EVENTO. Ojo con el costo del §7: "
                "el detector no corre en el engine vivo, así que cablearlo pide "
                "construir esa cañería primero.")
    if b["ship"]:
        return ("SHIP B — el tope INCONDICIONAL. No era el evento, era la tenencia: "
                "el condicionado no le gana al incondicional (C9) o no le gana al "
                "control igualado en tasa (C2/C5).")
    if not b["c1_dcagr"] and not a["c1_dcagr"]:
        return ("NO-SHIP los dos — el tope de tenencia no aporta sobre el engine de "
                "hoy. La hipótesis del §1 queda refutada CON PODER, que es lo que la "
                "T13 no pudo hacer.")
    if not b["c6_dose"]:
        return ("NO-SHIP — C6: no hay dosis-respuesta. El efecto vive en un N "
                "aislado, que es la firma del sobreajuste al número que motivó la "
                "tarea, no la de un mecanismo.")
    return "NO-SHIP — no pasa el AND de los criterios del §6."


def evaluate_sanity(summaries: dict, controls: list[dict], trade_diff: float,
                    ctrl_diff_median: float, repro: dict, pop: dict,
                    n_star_e: int) -> dict:
    acc = all(s["accounting_ok"] for s in summaries.values())
    band = sorted(c["cagr"] for c in controls)
    ctrl_p95 = _pct(band, SANITY_ORACLE_PCTILE) if band else float("nan")
    ctrl_median = statistics.median(band) if band else float("nan")
    checks = {
        "accounting": acc,
        "repro_base": bool(repro.get("base_ok")),
        "repro_alpha_cap20": bool(repro.get("alpha20_ok")),
        "oracle_sees_good_caps": bool(band and summaries[ORACLE_ARM]["cagr"] > ctrl_p95),
        "oracle_sees_bad_caps": bool(band and summaries[ANTI_ORACLE_ARM]["cagr"] < ctrl_median),
        "cap_bites": bool(trade_diff >= SANITY_MIN_TRADE_DIFF),
        "control_seeds_effective": bool(ctrl_diff_median >= SANITY_MIN_TRADE_DIFF
                                        and len({round(c["cagr"], 8) for c in controls}) > 1),
    }
    return {"checks": checks, "valid": all(checks.values()),
            "trade_diff": trade_diff, "ctrl_diff_median": ctrl_diff_median,
            "control_p95": ctrl_p95, "control_median": ctrl_median,
            "population": pop, "n_star_event": n_star_e}


# ── §6 — walk-forward que elige N* ───────────────────────────────────────────


def walk_forward(entries, bars_by, sigs_by, common: dict, caps_of: dict,
                 *, tag: str, log=sys.stdout) -> dict:
    """Elige el N de cada familia en el **train** y lo cobra en el **test** siguiente.

    ``caps_of`` es ``{N: cap_days_of}`` — la misma familia en toda la grilla, así
    que la función sirve igual para el brazo incondicional y para el del evento.
    """
    ns = sorted(caps_of)
    picks: list[int] = []
    per_fold: list[dict] = []
    proc_eq = base_eq = float(common["initial_capital"])
    proc_curve: list[tuple[str, float]] = []
    base_curve: list[tuple[str, float]] = []

    for fi, (train_end, test_lo, test_hi) in enumerate(FOLDS, 1):
        train = entries_between(entries, bars_by, None, _prev_day(train_end))
        test = entries_between(entries, bars_by, test_lo, test_hi)
        print(f"    [{tag}] fold {fi}/{len(FOLDS)} — train {len(train)} · "
              f"test {len(test)} …", file=log, flush=True)

        train_cagr = {
            n: cagr(_sim(f"wf|{tag}|{fi}|train|{n}", train, bars_by, sigs_by,
                         cap_days_of=caps_of[n], **common).equity_curve)
            for n in ns
        }
        pick = max(ns, key=lambda n: train_cagr[n])
        picks.append(pick)

        r_proc = _sim(f"wf|{tag}|{fi}|test|{pick}|eq{proc_eq:.6f}", test, bars_by,
                      sigs_by, cap_days_of=caps_of[pick],
                      **{**common, "initial_capital": proc_eq})
        r_base = _sim(f"wf|base|{fi}|test|eq{base_eq:.6f}", test, bars_by, sigs_by,
                      **{**common, "initial_capital": base_eq})
        proc_curve.extend(r_proc.equity_curve)
        base_curve.extend(r_base.equity_curve)
        proc_eq, base_eq = r_proc.final_equity, r_base.final_equity

        per_fold.append({
            "fold": fi, "train_end": train_end, "test": f"{test_lo}..{test_hi}",
            "n_train": len(train), "n_test": len(test), "pick": pick,
            "train_cagr": {str(n): train_cagr[n] for n in ns},
            "oos_cagr_proc": cagr(r_proc.equity_curve),
            "oos_cagr_base": cagr(r_base.equity_curve),
        })

    counts: dict[int, int] = {}
    for p in picks:
        counts[p] = counts.get(p, 0) + 1
    star = max(counts, key=lambda n: (counts[n], -n))
    return {"per_fold": per_fold, "picks": picks, "star": star,
            "agreement": counts[star],
            "oos_cagr_proc": cagr(proc_curve), "oos_cagr_base": cagr(base_curve)}


# ── §6 C8 — régimen con potencia ─────────────────────────────────────────────


def regime_pooled(base_res: PortfolioResult, cand_res: PortfolioResult) -> dict:
    """Δ pts/trade contra el baseline en el **agregado** de las tres ventanas de
    stress, con IC95% por bootstrap (el §4 de la 46, como lo usó la 45)."""
    pb, pc = per_trade_pts(base_res), per_trade_pts(cand_res)
    xs = [v for r in STRESS_NAMES for v in pb.get(r, [])]
    ys = [v for r in STRESS_NAMES for v in pc.get(r, [])]
    if not xs or not ys:
        return {"passes": False, "n_base": len(xs), "n_cand": len(ys),
                "reason": "sin trades en las ventanas de stress"}
    observed = statistics.fmean(ys) - statistics.fmean(xs)
    samples = _delta_samples_pooled(xs, ys, n_resamples=REGIME_RESAMPLES,
                                    seed=REGIME_SEED)
    summ = _summarise_samples(samples, observed)
    ci_high = summ.get("ci_high", observed)
    return {**summ, "n_base": len(xs), "n_cand": len(ys), "pooled": POOLED,
            "passes": bool(ci_high >= KILL_REGIME_TOL_PTS)}


# ── Main ─────────────────────────────────────────────────────────────────────


def _common(max_positions: int, capital: float, **over) -> dict:
    base = dict(
        max_positions=max_positions, initial_capital=capital, cap_days=BASE_CAP,
        atr_p=AtrParams(), so_params=ScaleOutParams(), costs=CostModel(),
        regime_of=regime_for_date, allow_reentry_while_open=False,
        eval_mode=EVAL_MODE, fill_mode=FILL_MODE, live_gates=LIVE_GATES,
    )
    base.update(over)
    return base


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EVENT-TIMESTOP (tarea 51)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--seeds", type=int, default=CONTROL_SEEDS)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--no-walkforward", action="store_true", help="sólo desarrollo")
    p.add_argument("--no-sensitivity", action="store_true", help="sólo desarrollo")
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--budget-seconds", type=float, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    # §3 — la población está CONGELADA. Correr sobre otro universo es cañería, no
    # veredicto; el sanity de reproducción lo marca NO APLICA por su cuenta (T52).
    smoke = bool(args.universe != LIVE_UNIVERSE_FILE or args.no_walkforward
                 or args.no_sensitivity or args.seeds != CONTROL_SEEDS)

    global _CACHE
    _CACHE = SimCache(Path(args.cache_dir) if args.cache_dir else None,
                      args.budget_seconds)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, vol_by, missing, incomplete = load_bars_signals_volume(
        tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.",
              file=sys.stderr)
        return 1
    if missing or incomplete:
        print(f"AVISO: {len(incomplete)} incompletos, {len(missing)} sin datos",
              file=sys.stderr)
    # El score vive en el mismo artefacto PIT que la señal.
    _b, _s, score_by, _m = load_bars_signals_scores(tickers, args.period, args.warmup)

    entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not entries:
        print("Sin entradas BUY.", file=sys.stderr)
        return 1

    # §2 — el evento: el detector congelado, RESTRINGIDO al pool del engine. No
    # agrega candidatos nuevos (eso es lo que la 45 rechazó por C8): sólo cambia
    # cuánto se sostiene lo que el engine ya iba a abrir.
    anom_all = build_anomaly_entries(bars_by, vol_by,
                                     AnomalyParams(k=ANOM_K, m=ANOM_M),
                                     warmup=args.warmup)
    anom_in_pool = restrict_to_pool(anom_all, entries)
    event_keys = keys_of(anom_in_pool, bars_by)
    n_by_date = count_by_date(event_keys)
    cands_by_date = candidates_by_date(entries, bars_by)

    window = artifact_window(bars_by)
    cfg = announce(args.max_positions, args.universe, len(bars_by), window=window,
                   eval_mode=EVAL_MODE, fill_mode=FILL_MODE, live_gates=LIVE_GATES,
                   file=log)
    print(f"Tickers: {len(bars_by)} · entradas `analyze BUY`: {len(entries)}", file=log)
    print(f"Evento A_k{ANOM_K}_m{ANOM_M}: {len(anom_all)} entradas, "
          f"**{len(anom_in_pool)}** dentro del pool del engine "
          f"({len(event_keys)} claves en {len(n_by_date)} días)", file=log)
    print(f"Grilla del tope: N ∈ {list(GRID_N)} contra el baseline cap={BASE_CAP}\n",
          file=log)
    if smoke:
        print("*** SMOKE — la corrida NO puede dictar veredicto ***\n", file=log)

    def b1(t: str, d: str) -> float:
        return float((score_by.get(t) or {}).get(d, 0.0))

    common = _common(args.max_positions, args.capital, rank_score=b1)

    # ── 1. Baseline + la grilla de las dos familias ──────────────────────────
    results: dict[str, PortfolioResult] = {}
    results[BASELINE_ARM] = _sim(f"grid|{BASELINE_ARM}", entries, bars_by, sigs_by,
                                 **common)
    caps_uncond = {n: cap_for_all(n) for n in GRID_N}
    caps_event = {n: cap_for_keys(event_keys, n) for n in GRID_N}
    for n in GRID_N:
        print(f"  grilla N={n} …", file=log, flush=True)
        results[uncond_name(n)] = _sim(f"grid|{uncond_name(n)}", entries, bars_by,
                                       sigs_by, cap_days_of=caps_uncond[n], **common)
        results[event_name(n)] = _sim(f"grid|{event_name(n)}", entries, bars_by,
                                      sigs_by, cap_days_of=caps_event[n], **common)
    summaries = {k: summarise(v) for k, v in results.items()}

    # ── 2. §6 — N* por WALK-FORWARD, no in-sample ────────────────────────────
    if args.no_walkforward:
        star_u = max(GRID_N, key=lambda n: summaries[uncond_name(n)]["cagr"])
        star_e = max(GRID_N, key=lambda n: summaries[event_name(n)]["cagr"])
        wf_u = {"star": star_u, "agreement": 0, "SMOKE": True, "per_fold": []}
        wf_e = {"star": star_e, "agreement": 0, "SMOKE": True, "per_fold": []}
    else:
        print("\n  §6 — walk-forward que elige N* …", file=log, flush=True)
        wf_u = walk_forward(entries, bars_by, sigs_by, common, caps_uncond,
                            tag="U", log=log)
        wf_e = walk_forward(entries, bars_by, sigs_by, common, caps_event,
                            tag="E", log=log)
        star_u, star_e = wf_u["star"], wf_e["star"]
    arm_u, arm_e = uncond_name(star_u), event_name(star_e)
    print(f"\n  N* incondicional = {star_u} ({wf_u['agreement']}/{len(FOLDS)} folds) · "
          f"N* evento = {star_e} ({wf_e['agreement']}/{len(FOLDS)} folds)\n",
          file=log, flush=True)

    # ── 3. §5.2 — el sanity de población de la T13, sobre el N* de cada familia ─
    base_res = results[BASELINE_ARM]
    pop = {
        "b_share": population_share(base_res, star_u),
        "a_share": population_share(base_res, star_e, event_keys),
        "min": SANITY_MIN_POPULATION,
    }
    pop["b_ok"] = bool(pop["b_share"] >= SANITY_MIN_POPULATION)
    pop["a_ok"] = bool(pop["a_share"] >= SANITY_MIN_POPULATION)

    # ── 4. Los 20 controles IGUALADOS EN TASA en el N* del evento ────────────
    ctrl_names: list[str] = []
    for k in range(args.seeds):
        name = control_name(k)
        keys = rate_matched_priority(cands_by_date, n_by_date, CONTROL_SEED_BASE + k)
        print(f"  control {k+1}/{args.seeds} …", file=log, flush=True)
        results[name] = _sim(f"ctrl|{star_e}|{k}", entries, bars_by, sigs_by,
                             cap_days_of=cap_for_keys(keys, star_e), **common)
        summaries[name] = summarise(results[name])
        ctrl_names.append(name)
    controls = [summaries[n] for n in ctrl_names]

    # ── 5. §5.4 — oráculo y anti-oráculo, igualados en tasa ──────────────────
    print("  oráculo / anti-oráculo …", file=log, flush=True)
    realized = precompute_realized(entries, bars_by, sigs_by, common)
    for name, worst in ((ORACLE_ARM, True), (ANTI_ORACLE_ARM, False)):
        keys = oracle_cap_keys(cands_by_date, n_by_date, realized, worst=worst)
        results[name] = _sim(f"oracle|{star_e}|{int(worst)}", entries, bars_by,
                             sigs_by, cap_days_of=cap_for_keys(keys, star_e), **common)
        summaries[name] = summarise(results[name])

    # ── 6. §5.3 — reproducción (ventana + población: tareas 48 y 52) ─────────
    #
    # El 2×2 de atribución del §2 es DESCRIPTIVO y además contiene tres números ya
    # publicados por la 49, así que se lo usa de sanity: dos son gate (§5.3) y el
    # tercero es un cross-check que NO estaba pedido.
    print("  2×2 de atribución + reproducción …", file=log, flush=True)
    grid22: dict[str, float] = {}
    for fondo, rs in (("alpha", None), ("score", b1)):
        for cap in (20, BASE_CAP):
            kw = _common(args.max_positions, args.capital, cap_days=cap)
            if rs is not None:
                kw["rank_score"] = rs
            grid22[f"{fondo}_cap{cap}"] = summarise(
                _sim(f"attr|{fondo}|{cap}", entries, bars_by, sigs_by, **kw))["cagr"]

    pop_run = cfg.population(len(entries))
    repro_specs = {
        "base": (summaries[BASELINE_ARM]["cagr"], REPRO_BASE_CAGR),
        "alpha20": (grid22["alpha_cap20"], REPRO_ALPHA_CAP20),
        "alpha250": (grid22["alpha_cap250"], REPRO_ALPHA_CAP250),   # cross-check
    }
    repro_states = {k: reproduction_check(
        got, exp, tol=REPRO_TOL, current=window,
        measured_on=WINDOW_REFRESH_2026_08_09, population=pop_run,
        measured_over=POPULATION_LIVE_ACCT2) for k, (got, exp) in repro_specs.items()}
    repro = {
        "grid_2x2": grid22,
        "base_ok": repro_states["base"][0] == REPRO_OK,
        "alpha20_ok": repro_states["alpha20"][0] == REPRO_OK,
        "alpha250_ok": repro_states["alpha250"][0] == REPRO_OK,   # NO es gate
        "states": {k: st for k, (st, _) in repro_states.items()},
        "reasons": {k: why for k, (_, why) in repro_states.items()},
    }

    # ── 7. Bootstraps pareados (C4, C5, C9) ──────────────────────────────────
    print("  bootstraps pareados …", file=log, flush=True)
    daily = aligned_daily(results, [BASELINE_ARM, arm_u, arm_e] + ctrl_names)
    ctrl_series = _control_mean_series(daily, ctrl_names)

    def _boot(xs, ys):
        if not xs or not ys:
            return None
        n = min(len(xs), len(ys))
        return paired_block_bootstrap([v for _, v in xs[:n]], [v for _, v in ys[:n]],
                                      block=BOOT_BLOCK, n_resamples=args.resamples,
                                      seed=BOOT_SEED)

    boot_b_base = _boot(daily[BASELINE_ARM], daily[arm_u])
    boot_a_base = _boot(daily[BASELINE_ARM], daily[arm_e])
    boot_a_ctrl = _boot(ctrl_series, daily[arm_e])
    boot_a_over_b = _boot(daily[arm_u], daily[arm_e])

    # ── 8. C6 (dosis-respuesta) y C8 (régimen) ───────────────────────────────
    base_cagr = summaries[BASELINE_ARM]["cagr"]
    d_u = {n: summaries[uncond_name(n)]["cagr"] - base_cagr for n in GRID_N}
    d_e = {n: summaries[event_name(n)]["cagr"] - base_cagr for n in GRID_N}
    c6_u, c6_e = dose_response(d_u, star_u), dose_response(d_e, star_e)
    print("  régimen (C8) …", file=log, flush=True)
    c8_u = regime_pooled(base_res, results[arm_u])
    c8_e = regime_pooled(base_res, results[arm_e])

    # ── 9. C7 — sensibilidad a 5 slots ───────────────────────────────────────
    sens = None
    if not args.no_sensitivity:
        print(f"  C7 — sensibilidad a {SENS_MAX_POSITIONS} slots …", file=log, flush=True)
        s_common = _common(SENS_MAX_POSITIONS, args.capital, rank_score=b1)
        s_res = {
            BASELINE_ARM: _sim(f"sens|{BASELINE_ARM}", entries, bars_by, sigs_by,
                               **s_common),
            arm_u: _sim(f"sens|{arm_u}", entries, bars_by, sigs_by,
                        cap_days_of=caps_uncond[star_u], **s_common),
            arm_e: _sim(f"sens|{arm_e}", entries, bars_by, sigs_by,
                        cap_days_of=caps_event[star_e], **s_common),
        }
        s_sum = {k: summarise(v) for k, v in s_res.items()}
        s_daily = aligned_daily(s_res, [BASELINE_ARM, arm_u, arm_e])
        s_boot_u = _boot(s_daily[BASELINE_ARM], s_daily[arm_u])
        s_boot_e = _boot(s_daily[BASELINE_ARM], s_daily[arm_e])
        sens = {
            "max_positions": SENS_MAX_POSITIONS,
            "base_cagr": s_sum[BASELINE_ARM]["cagr"],
            "u_cagr": s_sum[arm_u]["cagr"], "e_cagr": s_sum[arm_e]["cagr"],
            "b_c1": bool(s_sum[arm_u]["cagr"] - s_sum[BASELINE_ARM]["cagr"]
                         >= KILL_MIN_DCAGR),
            "b_c4": bool(s_boot_u is not None and s_boot_u.ci_low > 0.0),
            "a_c1": bool(s_sum[arm_e]["cagr"] - s_sum[BASELINE_ARM]["cagr"]
                         >= KILL_MIN_DCAGR),
            "a_c4": bool(s_boot_e is not None and s_boot_e.ci_low > 0.0),
        }

    # ── 10. Veredicto ────────────────────────────────────────────────────────
    trade_diff = trade_overlap(base_res, results[arm_e])
    pair_diffs = [trade_overlap(results[ctrl_names[i]], results[ctrl_names[j]])
                  for i in range(len(ctrl_names))
                  for j in range(i + 1, len(ctrl_names))]
    ctrl_diff_median = statistics.median(pair_diffs) if pair_diffs else 0.0

    sanity = evaluate_sanity(summaries, controls, trade_diff, ctrl_diff_median,
                             repro, pop, star_e)
    vb = evaluate_b(summaries[BASELINE_ARM], summaries[arm_u], boot_b_base,
                    c6_u, c8_u, sens)
    va = evaluate_a(summaries[BASELINE_ARM], summaries[arm_e], summaries[arm_u],
                    controls, boot_a_base, boot_a_ctrl, boot_a_over_b,
                    c6_e, c8_e, sens)
    # La población manda sobre el veredicto: sin ella el brazo está sin poder.
    if not pop["b_ok"]:
        vb["ship"] = False
    if not pop["a_ok"]:
        va["ship"] = False
    # §5: un sanity caído invalida la corrida entera, y eso manda sobre los criterios.
    if not sanity["valid"]:
        vb["ship"] = va["ship"] = False
    outcome = outcome_of(va, vb, pop, sanity_valid=sanity["valid"])

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "smoke": smoke, "universe": args.universe, "n_tickers": len(bars_by),
        "max_positions": args.max_positions, "window": str(window),
        "population": str(pop_run), "n_entries": len(entries),
        "n_event_keys": len(event_keys),
        "grid_n": list(GRID_N), "base_cap": BASE_CAP,
        "arm_uncond": arm_u, "arm_event": arm_e,
        "wf_uncond": wf_u, "wf_event": wf_e,
        "summaries": summaries, "controls": ctrl_names,
        "repro": repro, "sanity": sanity,
        "c6_uncond": c6_u, "c6_event": c6_e,
        "c8_uncond": c8_u, "c8_event": c8_e,
        "sensitivity": sens,
        "boot": {
            "b_vs_base": _boot_d(boot_b_base), "a_vs_base": _boot_d(boot_a_base),
            "a_vs_control": _boot_d(boot_a_ctrl), "a_vs_b": _boot_d(boot_a_over_b),
        },
        "verdict_b": vb, "verdict_a": va, "outcome": outcome,
        "cache": {"hits": _CACHE.hits, "misses": _CACHE.misses},
    }

    if args.json:
        print(json.dumps(ctx, indent=2, default=str))
    else:
        _report(ctx)
    return 0


def _control_mean_series(daily: dict, names: list[str]) -> list[tuple[str, float]]:
    """La serie diaria **promedio** de los controles — el nulo pareado del C5.

    Promediar sobre semillas saca el ruido de la realización, que es la lección que
    la T39 dejó en su §4.1 y la 49 reusó."""
    series = [daily[n] for n in names if daily.get(n)]
    if not series:
        return []
    n = min(len(s) for s in series)
    return [(series[0][i][0], statistics.fmean(s[i][1] for s in series))
            for i in range(n)]


def _boot_d(b) -> dict | None:
    if b is None:
        return None
    return {"delta": b.observed, "ci_low": b.ci_low, "ci_high": b.ci_high,
            "p_value": b.p_value}


def _f(x, w=9, p=2, suf="") -> str:
    if x is None:
        return " " * (w - len(suf)) + "—" + suf
    return f"{x:{w}.{p}f}{suf}"


def _crit(v: dict) -> None:
    """Solo los criterios: el dict trae ademas numeros que no son gate."""
    for k, val in v.items():
        if k.startswith("c") and isinstance(val, bool):
            print(f"    [{'OK ' if val else 'FALLA'}] {k}")


def _report(ctx: dict) -> None:
    s, sn = ctx["summaries"], ctx["sanity"]
    print("\n" + "=" * 78)
    print("EVENT-TIMESTOP (tarea 51) — ¿el tope de tenencia, y es del EVENTO?")
    print("=" * 78)
    if ctx["smoke"]:
        print("\n*** SMOKE — la corrida NO puede dictar veredicto ***")

    print(f"\nVentana: {ctx['window']} · población: {ctx['population']}")
    print(f"N* incondicional = {ctx['wf_uncond']['star']} · "
          f"N* evento = {ctx['wf_event']['star']}")

    print("\n  Grilla (ΔCAGR vs el baseline, en pp):")
    print(f"    {'N':>5} {'U_N (todas)':>14} {'E_N (evento)':>14}")
    base = s[BASELINE_ARM]["cagr"]
    for n in ctx["grid_n"]:
        du = 100 * (s[f"U_{n}"]["cagr"] - base)
        de = 100 * (s[f"E_{n}"]["cagr"] - base)
        print(f"    {n:>5} {du:>14.2f} {de:>14.2f}")

    print("\n  Brazos:")
    for name in ["B_base", ctx["arm_uncond"], ctx["arm_event"],
                 "ORACULO_cap", "ANTI_ORACULO_cap"]:
        v = s[name]
        print(f"    {name:<16} CAGR {_f(100*v['cagr'], 7, 2, '%')} · "
              f"Sharpe {_f(v['sharpe'], 5)} · maxDD {_f(100*v['max_dd'], 6, 1, '%')} "
              f"· tomadas {v['n_taken']:>5} · tenencia {v['mean_held_days']:.1f}d")
    band = sorted(s[c]["cagr"] for c in ctx["controls"])
    if band:
        print(f"    {'CONTROL x' + str(len(band)):<16} min {100*band[0]:.2f}% · "
              f"mediana {100*statistics.median(band):.2f}% · "
              f"p95 {100*sn['control_p95']:.2f}%")

    print("\n  §5 — sanity (si alguno falla, la corrida es INVÁLIDA):")
    rp = ctx["repro"]
    for k, ok in sn["checks"].items():
        # Los de reproduccion imprimen su ESTADO, no un booleano: `NO APLICA`
        # (otra poblacion, tarea 52) no es lo mismo que `FALLA` (cambio la
        # caneria), y confundirlos es el defecto que la 52 acaba de arreglar.
        st = {"repro_base": "base", "repro_alpha_cap20": "alpha20"}.get(k)
        label = rp["states"][st] if st else ("OK " if ok else "FALLA")
        print(f"    [{label:<13}] {k}")
    print("    2x2 de atribucion (CAGR): "
          + " . ".join(f"{k} {100*v:.2f}%" for k, v in rp["grid_2x2"].items()))
    print("    cross-check alpha_cap250 (NO es gate): "
          + rp["states"]["alpha250"])
    p = sn["population"]
    print(f"    población del tope — incondicional {100*p['b_share']:.1f}% "
          f"({'OK' if p['b_ok'] else 'SIN POBLACIÓN'}) · "
          f"evento {100*p['a_share']:.1f}% "
          f"({'OK' if p['a_ok'] else 'SIN POBLACIÓN'}) · mínimo {100*p['min']:.0f}%")

    print("\n  §6 — CANDIDATO B (tope incondicional):")
    _crit(ctx["verdict_b"])
    print("\n  §6 — CANDIDATO A (tope condicionado al evento):")
    _crit(ctx["verdict_a"])

    print(f"\n  corrida {'VÁLIDA' if sn['valid'] else 'INVÁLIDA'}")
    print(f"\n  VEREDICTO: {ctx['outcome']}")
    print("=" * 78)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BudgetExhausted as e:
        print(f"\n*** presupuesto agotado en {e} — volvé a correr para seguir ***",
              file=sys.stderr)
        raise SystemExit(3)
