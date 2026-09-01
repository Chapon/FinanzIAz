"""
Runner de ANOM-PROFILE — **Tarea 45**.

Pre-registro con la regla CONGELADA: ``docs/anom_profile_prereg_t45_2026-08-20.md``.

Qué re-decide y por qué
-----------------------
La **T11b** midió que el detector de ruptura de momentum **tiene alpha real** (le gana
al azar time-matched con holgura, sobrevive LOTO, PBO 0.476) y cerró **NO-SHIP por un
solo criterio**: su §6.5 de robustez de régimen, que le rechazaba el brazo por
``bear_2022`` −2.01 pts/trade con **n=20**. Después:

* la **38** midió que ese perfil **no es una propiedad de la señal sino del universo de
  41 tickers**: en la población viva ``bear_2022`` pasa a **+0.46** y ``covid_2020`` de
  +1.71 a **−0.92** — dos de las tres ventanas de stress cambian de signo, y no por
  modelar la regla del engine (eso deja el perfil intacto) sino por la **población**;
* la **46** midió que con esos ``n`` el criterio **rechaza al nivel del azar**: el
  efecto detectable al 80% de potencia es ±1.85 a ±4.73 pts contra un umbral de 0.00.

Esta tarea la vuelve a decidir con criterios que discriminan. **Reusa intactos** el
detector, la grilla de 9 brazos, el simulador, el contrafactual Monte Carlo y los
criterios **C1, C2, C3, C4 y C6** de la T11b. Lo que cambia:

* **C5′** — la tolerancia **se computa** (``detectable_mean_effect``), el gate va sobre
  el **agregado de las tres ventanas de stress** y **contra el control time-matched**,
  no contra cero (comparar el nivel de un bear contra cero mide el **mercado**, no la
  señal — lección de la 46 §3). Falla sólo si el **IC95% está entero** del lado malo.
  Las ventanas individuales son descriptivo obligatorio.
* **C7 (nuevo)** — sensibilidad a 5 slots como gate duro (precedente de la 47).
* **C8 (nuevo)** — **additividad sobre el engine**: la pregunta que el ship plantea y
  que la T11b **nunca hizo**. Su contrafactual era *entrar al azar*, y nadie opera
  contra eso: el engine ya tiene una fuente de candidatos y los slots son 10.
* **El brazo NO se re-selecciona** — queda congelado en ``A_k2.0_m1.5``, que eligió la
  regla de la T11b sobre la población **vieja** ⇒ sobre la viva es fuera de muestra.
* **El MC se matchea al candidato**, no al primario. La T11b comparaba un brazo de 466
  entradas contra un control de 357: ~30% más de exposición del lado del candidato.

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py``/``strategies.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.anomaly_signal import AnomalyParams, build_anomaly_entries
from analysis.exit_replay import AtrParams
from analysis.harness_config import (
    HARNESS_FILL_MODE,
    LEGACY_FILL_MODE,
    LEGACY_MAX_POSITIONS,
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    POPULATION_LEGACY_41,
    POPULATION_LIVE_ACCT2,
    REPRO_OK,
    WINDOW_REFRESH_2026_09_01_LEGACY,
    WINDOW_REFRESH_2026_09_01_LIVE,
    ArtifactPopulation,
    announce,
    artifact_window,
    reproduction_check,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import cagr, precompute_oracle_returns
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    BULL_NORMAL,
    STRESS_REGIMES,
    _sharpe,
    _skew_kurt,
    deflated_sharpe_ratio,
    detectable_mean_effect,
    paired_block_bootstrap,
    pbo_cscv,
    regime_for_date,
    regime_window_returns,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_anomaly_replay_t11b import (
    CANDIDATE_ARMS,
    KILL_DD_MULT,
    KILL_MAX_PBO,
    KILL_MIN_DCAGR,
    KILL_MIN_DSR,
    KILL_RANDOM_PCTILE,
    _median,
    _month,
    _pct,
    aligned_returns,
    load_bars_signals_volume,
    operable_entries,
    random_baseline,
    summarise,
)
from scripts.run_rank_neutral_t39 import aligned_daily
from scripts.run_regime_power_t46 import _summarise_samples
from scripts.run_tp_cal_replay_t23 import buy_entries

# ── Config CONGELADA (§3) ────────────────────────────────────────────────────

CANDIDATE_ARM = "A_k2.0_m1.5"  # §0.4 — congelado, NO se re-selecciona
ORACLE_ARM = "V_oracle_entry"
EVAL_MODE = "touch"  # la regla que ejecuta el engine (26b)
FILL_MODE = HARNESS_FILL_MODE  # el fill honesto (T33)
LIVE_GATES = True  # los gates de re-entrada del engine (T34)
CAP_DAYS = 20
SENS_MAX_POSITIONS = 5  # §6 C7

# Población B (§2) — el marco vivo.
ANALYZE_ARM = "E_analyze"
COMBINED_ARM = "E_analyze+anom"
COMBINED_PRIO_ARM = "E_analyze+anom_PRIO"

# §4 — C5′. La tolerancia MATERIAL se declara acá (el MISMO valor que congeló la
# 47, no re-elegido para esta población); la efectiva es el máximo entre ésta y lo
# detectable, que sale de la muestra del candidato.
TOL_MATERIAL_PTS = 1.00
STRESS_NAMES = tuple(r.name for r in STRESS_REGIMES)
REGIMES = (BULL_NORMAL, *STRESS_NAMES)
POOLED = "stress_POOLED"

# §6 — C8.
KILL_MIN_DCAGR_C8 = 0.005  # +0.50 pp
BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345

# §5 — sanity.
SANITY_ORACLE_MIN_DCAGR = 0.20  # el oráculo despega ≥ +20 pp sobre el candidato
REPRO_LIVE_CAGR = (
    0.0917  # `U_ungated` de la 38, mismos artefactos  # re-anclado 2026-09-01 (tarea 68), era 0.0923
)
REPRO_LEGACY_UNIVERSE = "data/harness_universe_41_10y.txt"
REPRO_LEGACY_CAGR = 0.1251  # ver §5.3(b)  # re-anclado 2026-09-01 (tarea 68), era 0.1277 (medido 2026-08-20)
REPRO_LEGACY_SHARPE = (
    1.20  # la T11b publicó 12.89%/1.24: es la tarea 48  # re-anclado 2026-09-01 (tarea 68), era 1.22
)
REPRO_TOL = 0.0005
REPRO_SHARPE_TOL = 0.02


# ── C5′ — el criterio de régimen con potencia (§4) ───────────────────────────


def per_trade_pts(res: PortfolioResult) -> dict[str, list[float]]:
    """Retorno por trade en **pts**, agrupado por régimen."""
    out: dict[str, list[float]] = {r: [] for r in REGIMES}
    for t in res.trades:
        out.setdefault(t.regime, []).append(100.0 * t.ret)
    return out


def _delta_samples_pooled(
    xs: list[float], ys: list[float], *, n_resamples: int, seed: int, chunk: int = 64
) -> list[float]:
    """Bootstrap de la diferencia de medias ``mean(ys) − mean(xs)``, por tandas.

    Misma mecánica que ``run_regime_power_t46._delta_samples`` —remuestreo
    **independiente** de cada lado, porque los brazos no comparten trades— pero
    calculada en tandas de ``chunk`` resamples. Hace falta porque acá ``xs`` es el
    **control**: los trades de las K=500 carteras del Monte Carlo agrupados, o sea
    ~10⁵ elementos, y la versión de la 46 arma una matriz ``(n_resamples × len(xs))``
    que no entra en memoria.

    No pretende ser bit-idéntica a la de la 46 (el orden de consumo del RNG cambia);
    no hay ningún número publicado que reproducir por esta vía.
    """
    import numpy as np

    a = np.asarray(xs, dtype=float)
    b = np.asarray(ys, dtype=float)
    if a.size == 0 or b.size == 0:
        return []
    rng = np.random.default_rng(seed)
    out: list[float] = []
    left = n_resamples
    while left > 0:
        k = min(chunk, left)
        ia = rng.integers(0, a.size, size=(k, a.size))
        ib = rng.integers(0, b.size, size=(k, b.size))
        out.extend((b[ib].mean(axis=1) - a[ia].mean(axis=1)).tolist())
        left -= k
    return out


def regime_criterion(
    control_pts: dict[str, list[float]], cand: PortfolioResult, *, n_resamples: int, seed: int
) -> dict:
    """C5′ (§4): tolerancia computada + gate sobre el AGREGADO de stress, con IC,
    y **contra el control time-matched** (no contra cero).

    Falla **sólo** si el IC95% del Δ del agregado está **enteramente por debajo de
    −tol**. Rechazar por el punto estimado con el IC cruzando cero es exactamente lo
    que la 46 midió que no tiene potencia; y rechazar por el **nivel** contra cero
    mide el mercado de esa ventana, no la política (46 §3).
    """
    pc = per_trade_pts(cand)
    pooled_b = [v for r in STRESS_NAMES for v in (control_pts.get(r) or [])]
    pooled_c = [v for r in STRESS_NAMES for v in pc.get(r, [])]

    windows: dict[str, dict] = {}
    for r in (*REGIMES, POOLED):
        xs = pooled_b if r == POOLED else (control_pts.get(r) or [])
        ys = pooled_c if r == POOLED else pc.get(r, [])
        # La tolerancia se computa sobre la muestra del CANDIDATO (§4.1): es su n
        # el que limita lo que se puede resolver, no el del control.
        n = len(ys)
        sd = statistics.stdev(ys) if n > 1 else 0.0
        delta = (statistics.fmean(ys) if ys else 0.0) - (statistics.fmean(xs) if xs else 0.0)
        stab = None
        if xs and ys:
            stab = _summarise_samples(
                _delta_samples_pooled(xs, ys, n_resamples=n_resamples, seed=seed), delta
            )
        windows[r] = {
            "n_cand": n,
            "n_control": len(xs),
            "sd_pts": sd,
            "delta_pts": delta,
            "mean_cand": (statistics.fmean(ys) if ys else None),
            "mean_control": (statistics.fmean(xs) if xs else None),
            "detectable": detectable_mean_effect(sd, n) if n > 1 else None,
            "stability": stab,
        }

    pooled = windows[POOLED]
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


# ── Población B (§2) — additividad sobre el engine ───────────────────────────


def merge_entries(
    analyze: list[tuple[str, int]], anom: list[tuple[str, int]], bars_by
) -> list[tuple[str, int]]:
    """Unión **deduplicada** de las dos fuentes, en orden cronológico.

    Una entrada que las dos fuentes proponen el mismo día para el mismo ticker es
    **una sola** entrada: ``portfolio_sim`` la tomaría una vez de todos modos
    (``allow_reentry_while_open=False``), pero dejarla duplicada ensuciaría el
    conteo de candidatos ofrecidos."""
    out = sorted(set(analyze) | set(anom))
    out.sort(key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]))
    return out


def make_prio_rank(anom_keys: set[tuple[str, str]]):
    """``rank_score`` que le da el slot al candidato de anomalía en su día.

    Sólo cambia **el orden del empate del día**, no el conjunto de candidatos —
    que es lo que lo hace interpretable como *"¿la señal aporta cuando consigue
    slot?"* y no como una política distinta."""

    def rank(ticker: str, date_iso10: str) -> float:
        return 1.0 if (ticker, date_iso10) in anom_keys else 0.0

    return rank


def trade_diff_share(base: PortfolioResult, cand: PortfolioResult) -> float:
    """Fracción de trades que difieren entre los dos brazos (clave ticker+fecha).

    **No es un sanity** (§5): que la fuente nueva gane o no gane slots es un
    **resultado**, y es la mitad de la respuesta de C8. La 38 pagó una corrida
    entera por confundir las dos cosas."""
    kb = {(t.ticker, t.entry_date) for t in base.trades}
    kc = {(t.ticker, t.entry_date) for t in cand.trades}
    union = kb | kc
    return (len(union - (kb & kc)) / len(union)) if union else 0.0


# ── §6 — regla de decisión ───────────────────────────────────────────────────


def evaluate(
    cand_sum: dict, rb: dict, dsr, pbo, c5: dict, loto: dict | None, sens: dict | None, c8: dict | None
) -> dict:
    """El AND de los ocho criterios del §6."""
    sh = cand_sum["sharpe"] if cand_sum["sharpe"] is not None else -1e9

    c1 = bool(cand_sum["cagr"] > rb["cagr_p95"] and sh > rb["sharpe_p95"])
    c2 = bool((cand_sum["cagr"] - rb["cagr_median"]) >= KILL_MIN_DCAGR)
    c3 = bool(cand_sum["max_dd"] <= KILL_DD_MULT * rb["maxdd_median"])
    c4 = bool(
        dsr is not None and dsr.deflated_sharpe > KILL_MIN_DSR and pbo is not None and pbo.pbo < KILL_MAX_PBO
    )
    c5_ok = bool(c5["passes"])
    c6 = bool(loto is not None and loto["survives"])
    c7 = sens is not None and bool(sens.get("c1")) and bool(sens.get("c2"))
    c8_ok = c8 is not None and bool(c8.get("c8_cagr")) and bool(c8.get("c8_boot"))

    ship = bool(c1 and c2 and c3 and c4 and c5_ok and c6 and c7 and c8_ok)

    if ship:
        outcome = (
            "SHIP — se cabla `paper_anomaly_entries_enabled` con default OFF; "
            "prenderlo es decisión de Chapa (§7). Toca decisiones vivas de "
            "ENTRADA."
        )
    elif c1 and c2 and c3 and c4 and c5_ok and c6 and c7 and not c8_ok:
        outcome = (
            "NO-SHIP — C8: la señal no le aporta a la fuente de candidatos que "
            "el engine ya tiene. Hay que leer el descriptivo priorizado para "
            "decir si es que NO APORTA o que NUNCA CONSIGUE SLOT (§6)."
        )
    elif c1 and c2 and c3 and c4 and c5_ok and c6 and not c7:
        outcome = (
            "NO-SHIP — C7: el efecto no sobrevive a 5 slots. Está declarado ex "
            "ante que un efecto que sólo existe con 10 slots es FRÁGIL."
        )
    elif not c5_ok:
        outcome = (
            "NO-SHIP — C5′: el IC95% del Δ contra el control en el agregado de "
            "stress está entero del lado malo de una tolerancia detectable. "
            "Este rechazo SÍ significa algo (a diferencia del §6.5 de la T11b)."
        )
    else:
        outcome = "NO-SHIP — no pasa el AND de los ocho criterios."

    return {
        "c1_vs_random": c1,
        "c2_dcagr": c2,
        "c3_maxdd": c3,
        "c4_dsr_pbo": c4,
        "c5_regime": c5_ok,
        "c6_loto": c6,
        "c7_sensitivity": c7,
        "c8_additive": c8_ok,
        "ship": ship,
        "outcome": outcome,
    }


# ── Sanity (§5) ──────────────────────────────────────────────────────────────


def evaluate_sanity(
    results: dict[str, PortfolioResult], cand_sum: dict, oracle_sum: dict, repro: dict
) -> dict:
    acc = all(summarise(r)["accounting_ok"] for r in results.values())
    oracle_gap = (oracle_sum["cagr"] - cand_sum["cagr"]) if oracle_sum["cagr"] is not None else None
    oracle_ok = bool(oracle_gap is not None and oracle_gap >= SANITY_ORACLE_MIN_DCAGR)
    live_ok = bool(repro.get("live_ok"))
    legacy_ok = bool(repro.get("legacy_ok")) if repro.get("legacy_ran") else None
    checks: dict[str, Any] = {
        "accounting": acc,
        "oracle_takes_off": oracle_ok,
        "repro_live": live_ok,
        "repro_legacy": legacy_ok,
    }
    valid = bool(acc and oracle_ok and live_ok and (legacy_ok is not False))
    return {
        "checks": checks,
        "oracle_gap": oracle_gap,
        "valid": valid,
        "legacy_skipped": not repro.get("legacy_ran"),
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def _common(max_positions: int, capital: float, cap_days: int) -> dict:
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
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
    )


def _mc(
    run, bars_by, entries, operable_by_month, *, k_random: int, seed: int, collect: dict | None = None
) -> dict:
    """Monte Carlo time-matched **al candidato** (§0, último párrafo)."""
    count_by_month: dict[str, int] = {}
    for ti in entries:
        key = _month(bars_by, ti)
        count_by_month[key] = count_by_month.get(key, 0) + 1
    dist = random_baseline(
        run, bars_by, count_by_month, operable_by_month, k_random=k_random, seed0=seed, regime_pts=collect
    )
    return {
        "cagr_p95": _pct(dist["cagr"], KILL_RANDOM_PCTILE),
        "cagr_median": _median(dist["cagr"]),
        "sharpe_p95": _pct(dist["sharpe"], KILL_RANDOM_PCTILE),
        "sharpe_median": _median(dist["sharpe"]),
        "maxdd_median": _median(dist["max_dd"]),
        "k": k_random,
    }


def _loto(run, entries, random_median_cagr: float) -> dict | None:
    """§6.6 de la T11b, intacto: sacar el ticker de mayor aporte al P/L."""
    res = run(entries)
    if not res.trades:
        return None
    pnl_by: dict[str, float] = {}
    for t in res.trades:
        pnl_by[t.ticker] = pnl_by.get(t.ticker, 0.0) + t.pnl
    dropped = max(pnl_by, key=lambda k: pnl_by[k])
    cg = cagr(run([ti for ti in entries if ti[0] != dropped]).equity_curve)
    return {"dropped": dropped, "cagr_without": cg, "survives": cg > random_median_cagr}


def _repro_legacy(period: str, warmup: int, cap_days: int, capital: float, log, current_window=None) -> dict:
    """§5.3(b): la config publicada de la T11b sobre los artefactos de HOY."""
    tickers = parse_universe_file(_HERE.parent / REPRO_LEGACY_UNIVERSE)
    bars_by, sigs_by, vol_by, _missing, _inc = load_bars_signals_volume(tickers, period, warmup)
    if not bars_by:
        return {"ran": False, "reason": "sin artefactos del universo legacy"}
    k, m = CANDIDATE_ARMS[CANDIDATE_ARM]
    entries = build_anomaly_entries(bars_by, vol_by, AnomalyParams(k=k, m=m), warmup=warmup)
    res = simulate_portfolio(
        entries,
        bars_by,
        sigs_by,
        max_positions=LEGACY_MAX_POSITIONS,
        initial_capital=capital,
        cap_days=cap_days,
        atr_p=AtrParams(),
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        eval_mode="close",
        fill_mode=LEGACY_FILL_MODE,
        live_gates=False,
    )
    s = summarise(res)
    # Tarea 48 — multi-estado: la ventana de los artefactos es RODANTE, así que un
    # desajuste puede venir de la cañería o de un refresh, y hay que distinguirlo.
    # Tarea 52 — este brazo corre sobre el universo LEGACY a propósito (es la config
    # publicada de la T11b), así que su ancla declara esa población y no la viva.
    state, reason = reproduction_check(
        s["cagr"],
        REPRO_LEGACY_CAGR,
        tol=REPRO_TOL,
        current=artifact_window(bars_by),
        measured_on=WINDOW_REFRESH_2026_09_01_LEGACY,
        population=ArtifactPopulation(REPRO_LEGACY_UNIVERSE, len(bars_by), len(entries)),
        measured_over=POPULATION_LEGACY_41,
    )
    sharpe_ok = s["sharpe"] is not None and abs(s["sharpe"] - REPRO_LEGACY_SHARPE) <= REPRO_SHARPE_TOL
    ok = state == REPRO_OK and sharpe_ok
    print(
        f"Reproducción legacy (41t/5sl/resting/close): CAGR {100 * s['cagr']:.2f}% "
        f"(esperado {100 * REPRO_LEGACY_CAGR:.2f}%) · Sharpe {s['sharpe']:.2f} "
        f"(esperado {REPRO_LEGACY_SHARPE:.2f}) · {state}",
        file=log,
    )
    if state != REPRO_OK:
        print(f"  → {reason}", file=log)
    return {
        "ran": True,
        "ok": ok,
        "state": state,
        "reason": reason,
        "cagr": s["cagr"],
        "sharpe": s["sharpe"],
        "n_entries": len(entries),
        "n_taken": s["n_taken"],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ANOM-PROFILE — Tarea 45")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--sens-max-positions", type=int, default=SENS_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--k-random", type=int, default=500)
    p.add_argument("--seed", type=int, default=BOOT_SEED)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument(
        "--no-sensitivity", action="store_true", help="saltea la corrida a 5 slots (C7 sin evaluar ⇒ NO-SHIP)"
    )
    p.add_argument(
        "--no-additivity", action="store_true", help="saltea la población B (C8 sin evaluar ⇒ NO-SHIP)"
    )
    p.add_argument(
        "--no-repro-legacy", action="store_true", help="saltea el sanity §5.3(b) — sólo para desarrollo"
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, vol_by, missing, incomplete = load_bars_signals_volume(
        tickers, args.period, args.warmup
    )
    if not bars_by:
        print("Sin datos: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if incomplete or missing:
        print(f"AVISO: {len(incomplete)} incompletos, {len(missing)} sin datos", file=sys.stderr)

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

    # ── Población A: el marco de la T11b ─────────────────────────────────────
    entries_by: dict[str, Any] = {
        name: build_anomaly_entries(bars_by, vol_by, AnomalyParams(k=k, m=m), warmup=args.warmup)
        for name, (k, m) in CANDIDATE_ARMS.items()
    }
    cand_entries = entries_by[CANDIDATE_ARM]
    if not cand_entries:
        print("El candidato no produjo entradas.", file=sys.stderr)
        return 1
    print(
        f"Tickers: {len(bars_by)} · CANDIDATO {CANDIDATE_ARM} (congelado): {len(cand_entries)} entradas",
        file=log,
    )

    common = _common(args.max_positions, args.capital, args.cap_days)

    def run(entries, **over):
        return simulate_portfolio(entries, bars_by, sigs_by, **{**common, **over})

    results: dict[str, PortfolioResult] = {n: run(e) for n, e in entries_by.items()}
    summaries = {n: summarise(results[n]) for n in CANDIDATE_ARMS}
    cand_sum = summaries[CANDIDATE_ARM]

    # Contrafactual: MC time-matched AL CANDIDATO, con el control por régimen (C5′).
    operable = operable_entries(bars_by, args.warmup)
    operable_by_month: dict[str, list[tuple[str, int]]] = {}
    for ti in operable:
        operable_by_month.setdefault(_month(bars_by, ti), []).append(ti)
    control_pts: dict[str, list[float]] = {}
    rb = _mc(
        run,
        bars_by,
        cand_entries,
        operable_by_month,
        k_random=args.k_random,
        seed=args.seed,
        collect=control_pts,
    )

    # Oráculo (sanity §5.2), dimensionado al candidato.
    oracle_ret = precompute_oracle_returns(
        operable,
        bars_by,
        sigs_by,
        so_params=ScaleOutParams(),
        atr_p=AtrParams(),
        cap_days=args.cap_days,
        costs=CostModel(),
        fill_mode=FILL_MODE,
        eval_mode=EVAL_MODE,
    )
    scored = [(ti, oracle_ret.get((ti[0], bars_by[ti[0]][ti[1]][0]))) for ti in operable]
    # Nombre nuevo: al re-bindear, el tipo declarado sigue siendo `float | None`
    # aunque el filtro ya saco los None.
    scored_ok = [(ti, r) for ti, r in scored if r is not None]
    scored_ok.sort(key=lambda x: x[1], reverse=True)
    oracle_entries = sorted(
        (ti for ti, _ in scored_ok[: len(cand_entries)]),
        key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]),
    )
    results[ORACLE_ARM] = run(oracle_entries)
    oracle_sum = summarise(results[ORACLE_ARM])

    # C4 — DSR/PBO sobre los 9 brazos (los mismos 9 intentos de la T11b).
    arms = list(CANDIDATE_ARMS)
    rets = aligned_returns(results, arms)
    T = len(next(iter(rets.values()))) if rets else 0
    pbo = pbo_cscv({a: rets[a] for a in arms}, n_splits=10) if T >= 10 else None
    dsr = None
    if T >= 2:
        sk, ku = _skew_kurt(rets[CANDIDATE_ARM])
        dsr = deflated_sharpe_ratio(
            [_sharpe(rets[a]) for a in arms],
            n_obs=T,
            selected=_sharpe(rets[CANDIDATE_ARM]),
            skew=sk,
            kurtosis=ku,
        )

    # C5′ y C6.
    c5 = regime_criterion(control_pts, results[CANDIDATE_ARM], n_resamples=args.resamples, seed=args.seed)
    loto = _loto(run, cand_entries, rb["cagr_median"])

    # Descriptivo: qué brazo habría re-seleccionado la regla de la T11b (§6).
    def passes_local(s: dict) -> bool:
        sh = s["sharpe"] if s["sharpe"] is not None else -1e9
        return bool(
            s["accounting_ok"]
            and s["cagr"] > rb["cagr_p95"]
            and sh > rb["sharpe_p95"]
            and s["max_dd"] <= KILL_DD_MULT * rb["maxdd_median"]
            and (s["cagr"] - rb["cagr_median"]) >= KILL_MIN_DCAGR
        )

    eligibles = [a for a in arms if passes_local(summaries[a])]
    ranked = sorted(
        arms,
        key=lambda a: summaries[a]["sharpe"] if summaries[a]["sharpe"] is not None else -1e9,
        reverse=True,
    )
    would_reselect = next((a for a in ranked if a in eligibles), None)

    # Descriptivo de cartera por ventana de régimen (§4, segundo descriptivo).
    daily_cand = aligned_daily(results, [CANDIDATE_ARM])[CANDIDATE_ARM]
    regime_portfolio = regime_window_returns(daily_cand)

    # ── C7 — sensibilidad a 5 slots ──────────────────────────────────────────
    sens: dict[str, Any] | None = None
    if not args.no_sensitivity:
        s_common = _common(args.sens_max_positions, args.capital, args.cap_days)

        def s_run(entries, **over):
            return simulate_portfolio(entries, bars_by, sigs_by, **{**s_common, **over})

        s_sum = summarise(s_run(cand_entries))
        s_rb = _mc(s_run, bars_by, cand_entries, operable_by_month, k_random=args.k_random, seed=args.seed)
        s_sh = s_sum["sharpe"] if s_sum["sharpe"] is not None else -1e9
        sens = {
            "max_positions": args.sens_max_positions,
            "cagr": s_sum["cagr"],
            "sharpe": s_sum["sharpe"],
            "random": s_rb,
            "c1": bool(s_sum["cagr"] > s_rb["cagr_p95"] and s_sh > s_rb["sharpe_p95"]),
            "c2": bool((s_sum["cagr"] - s_rb["cagr_median"]) >= KILL_MIN_DCAGR),
        }

    # ── C8 — additividad sobre el engine (población B) ───────────────────────
    c8: dict[str, Any] | None = None
    if not args.no_additivity:
        analyze = buy_entries(bars_by, sigs_by, args.warmup)
        merged = merge_entries(analyze, cand_entries, bars_by)
        anom_keys = {(t, bars_by[t][i][0]) for t, i in cand_entries}
        b_res: dict[str, Any] = {
            ANALYZE_ARM: run(analyze),
            COMBINED_ARM: run(merged),
            COMBINED_PRIO_ARM: run(merged, rank_score=make_prio_rank(anom_keys)),
        }
        b_sum = {n: summarise(r) for n, r in b_res.items()}
        results.update(b_res)
        daily = aligned_daily(b_res, [ANALYZE_ARM, COMBINED_ARM])
        boot = paired_block_bootstrap(
            [r for _, r in daily[ANALYZE_ARM]],
            [r for _, r in daily[COMBINED_ARM]],
            block=BOOT_BLOCK,
            n_resamples=args.resamples,
            seed=args.seed,
        )
        d_prio = aligned_daily(b_res, [ANALYZE_ARM, COMBINED_PRIO_ARM])
        boot_prio = paired_block_bootstrap(
            [r for _, r in d_prio[ANALYZE_ARM]],
            [r for _, r in d_prio[COMBINED_PRIO_ARM]],
            block=BOOT_BLOCK,
            n_resamples=args.resamples,
            seed=args.seed,
        )
        dcagr = b_sum[COMBINED_ARM]["cagr"] - b_sum[ANALYZE_ARM]["cagr"]
        c8 = {
            "n_analyze": len(analyze),
            "n_merged": len(merged),
            "summaries": b_sum,
            "dcagr": dcagr,
            "dcagr_prio": b_sum[COMBINED_PRIO_ARM]["cagr"] - b_sum[ANALYZE_ARM]["cagr"],
            "boot_ci": [boot.ci_low, boot.ci_high],
            "boot_p": boot.p_value,
            "boot_prio_ci": [boot_prio.ci_low, boot_prio.ci_high],
            "trade_diff": trade_diff_share(b_res[ANALYZE_ARM], b_res[COMBINED_ARM]),
            "trade_diff_prio": trade_diff_share(b_res[ANALYZE_ARM], b_res[COMBINED_PRIO_ARM]),
            "c8_cagr": bool(dcagr >= KILL_MIN_DCAGR_C8),
            "c8_boot": bool(boot.ci_low > 0.0),
        }

    # ── Sanity + veredicto ───────────────────────────────────────────────────
    window = artifact_window(bars_by)
    live_state, live_reason = reproduction_check(
        cand_sum["cagr"],
        REPRO_LIVE_CAGR,
        tol=REPRO_TOL,
        current=window,
        measured_on=WINDOW_REFRESH_2026_09_01_LIVE,
        population=cfg.population(len(cand_entries)),
        measured_over=POPULATION_LIVE_ACCT2,
    )
    repro: dict = {
        "live_cagr": cand_sum["cagr"],
        "live_ok": live_state == REPRO_OK,
        "live_state": live_state,
        "live_reason": live_reason,
        "live_expected": REPRO_LIVE_CAGR,
        "window": str(window),
    }
    if args.no_repro_legacy:
        repro["legacy_ran"] = False
    else:
        leg = _repro_legacy(args.period, args.warmup, args.cap_days, args.capital, log, current_window=window)
        repro["legacy_ran"] = bool(leg.get("ran"))
        repro["legacy_ok"] = bool(leg.get("ok"))
        repro["legacy"] = leg

    sanity = evaluate_sanity(results, cand_sum, oracle_sum, repro)
    verdict = evaluate(cand_sum, rb, dsr, pbo, c5, loto, sens, c8)
    if not sanity["valid"]:
        verdict["ship"] = False
        verdict["outcome"] = (
            "CORRIDA INVÁLIDA — falló un sanity del §5. No hay "
            "veredicto y no se re-especifica nada (precedente T26)."
        )

    ctx: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries_candidate": len(cand_entries),
        "candidate": CANDIDATE_ARM,
        "max_positions": args.max_positions,
        "eval_mode": EVAL_MODE,
        "fill_mode": FILL_MODE,
        "live_gates": LIVE_GATES,
        "random_baseline": rb,
        "would_reselect": would_reselect,
        "pbo": (pbo.pbo if pbo else None),
        "dsr": (dsr.deflated_sharpe if dsr else None),
        "dsr_obs": T,
        "loto": loto,
        "sensitivity": sens,
        "additivity": c8,
        "regime_criterion": c5,
        "regime_portfolio": regime_portfolio,
        "repro": repro,
        "sanity": sanity,
        "verdict": verdict,
    }

    if args.json:
        print(
            json.dumps(
                {"context": ctx, "summaries": summaries, "oracle": oracle_sum},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    _report(summaries, oracle_sum, ctx)
    return 0


def _f(x, w=8, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries: dict, oracle_sum: dict, ctx: dict) -> None:
    rb, c5 = ctx["random_baseline"], ctx["regime_criterion"]
    print(
        f"\nAzar time-matched AL CANDIDATO (K={rb['k']}): CAGR mediana "
        f"{_f(rb['cagr_median'], 0, 2, '%')} · p95 {_f(rb['cagr_p95'], 0, 2, '%')} | "
        f"Sharpe mediana {rb['sharpe_median']:.2f} · p95 {rb['sharpe_p95']:.2f} | "
        f"maxDD mediana {_f(rb['maxdd_median'], 0, 1, '%')}\n"
    )

    hdr = f"{'brazo':<14}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'tomad':>7}{'ofrec':>7}"
    print(hdr)
    print("-" * len(hdr))
    for n, s in summaries.items():
        mark = " *CAND" if n == ctx["candidate"] else ""
        print(
            f"{n:<14}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9, 2)}"
            f"{_f(s['max_dd'], 9, 1, '%')}{s['n_taken']:>7}{s['n_offered']:>7}{mark}"
        )
    o = oracle_sum
    print(
        f"{'V_oracle_entry':<14}{_f(o['cagr'], 9, 2, '%')}{_f(o['sharpe'], 9, 2)}"
        f"{_f(o['max_dd'], 9, 1, '%')}{o['n_taken']:>7}{o['n_offered']:>7}  sanity"
    )
    if ctx["would_reselect"] and ctx["would_reselect"] != ctx["candidate"]:
        print(
            f"\n  OJO: la regla de la T11b re-seleccionaría {ctx['would_reselect']} "
            f"sobre esta población. El candidato NO cambia (§0.4) — es un hallazgo "
            f"de inestabilidad del criterio de selección."
        )

    print(
        f"\nC5′ — régimen con potencia · tolerancia {c5['tolerance_pts']:.2f} pts "
        f"(material {c5['material_pts']:.2f}, detectable "
        f"{_f(c5['detectable_pts'], 0, 2)})"
    )
    wh = f"  {'ventana':<18}{'n cand':>7}{'σ':>7}{'detect':>8}{'Δ vs azar':>11}{'IC95%':>20}{'P(signo)':>10}"
    print(wh)
    print("  " + "-" * (len(wh) - 2))
    for name, w in c5["windows"].items():
        st = w["stability"]
        ci = f"[{st['ci_low']:+.2f}, {st['ci_high']:+.2f}]" if st else "—"
        ps = f"{100 * st['p_same_sign']:.0f}%" if st else "—"
        star = "  ← GATE" if name == POOLED else ""
        print(
            f"  {name:<18}{w['n_cand']:>7}{w['sd_pts']:>7.2f}"
            f"{_f(w['detectable'], 8, 2)}{w['delta_pts']:>+11.2f}{ci:>20}{ps:>10}{star}"
        )
    print(
        f"  → C5′ {'PASA' if c5['passes'] else 'FALLA'}. Las ventanas individuales "
        f"son descriptivo: NO pueden producir un rechazo (§4.3)."
    )
    print(
        f"  Cartera por ventana (2º descriptivo): "
        f"{ {k: f'{100 * v:+.2f}%' for k, v in ctx['regime_portfolio'].items()} }"
    )

    print(
        f"\nSelección múltiple (9 brazos, T={ctx['dsr_obs']} obs): "
        f"PBO={_f(ctx['pbo'], 0, 3)} · DSR={_f(ctx['dsr'], 0, 3)}"
    )
    lo = ctx["loto"]
    if lo:
        print(
            f"LOTO (sacando {lo['dropped']}): CAGR {_f(lo['cagr_without'], 0, 2, '%')} "
            f"→ edge {'sobrevive' if lo['survives'] else 'SE CAE'}"
        )

    sn = ctx["sensitivity"]
    if sn:
        print(
            f"\nC7 — a {sn['max_positions']} slots: CAGR {_f(sn['cagr'], 0, 2, '%')} "
            f"(p95 azar {_f(sn['random']['cagr_p95'], 0, 2, '%')}, mediana "
            f"{_f(sn['random']['cagr_median'], 0, 2, '%')}) · "
            f"C1 {'PASA' if sn['c1'] else 'FALLA'} · "
            f"C2 {'PASA' if sn['c2'] else 'FALLA'}"
        )

    c8 = ctx["additivity"]
    if c8:
        print(
            f"\nC8 — additividad sobre el engine ({c8['n_analyze']} entradas "
            f"`analyze BUY` + {ctx['n_entries_candidate']} de anomalía = "
            f"{c8['n_merged']} tras deduplicar):"
        )
        h8 = f"  {'brazo':<22}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'tomad':>7}"
        print(h8)
        print("  " + "-" * (len(h8) - 2))
        for n, s in c8["summaries"].items():
            print(
                f"  {n:<22}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9, 2)}"
                f"{_f(s['max_dd'], 9, 1, '%')}{s['n_taken']:>7}"
            )
        print(
            f"  ΔCAGR {100 * c8['dcagr']:+.2f} pp · bootstrap pareado IC95% "
            f"[{100 * c8['boot_ci'][0]:+.2f}, {100 * c8['boot_ci'][1]:+.2f}] pp "
            f"p={c8['boot_p']:.3f} · trades distintos {100 * c8['trade_diff']:.1f}%"
        )
        print(
            f"  DESCRIPTIVO priorizado: ΔCAGR {100 * c8['dcagr_prio']:+.2f} pp · IC95% "
            f"[{100 * c8['boot_prio_ci'][0]:+.2f}, {100 * c8['boot_prio_ci'][1]:+.2f}] pp "
            f"· trades distintos {100 * c8['trade_diff_prio']:.1f}% "
            f"(NO es gate — distingue 'no aporta' de 'no consigue slot')"
        )

    sa, vd = ctx["sanity"], ctx["verdict"]
    print("\nSanity (§5):")
    for k, v in sa["checks"].items():
        print(f"  {k:<20} {'—' if v is None else ('OK' if v else 'FALLA')}")
    print(
        f"  oráculo despega +{100 * (sa['oracle_gap'] or 0):.2f} pp "
        f"(mínimo +{100 * SANITY_ORACLE_MIN_DCAGR:.0f})"
    )
    print(f"  corrida {'VÁLIDA' if sa['valid'] else 'INVÁLIDA'}")

    print("\nCriterios (§6):")
    for k in (
        "c1_vs_random",
        "c2_dcagr",
        "c3_maxdd",
        "c4_dsr_pbo",
        "c5_regime",
        "c6_loto",
        "c7_sensitivity",
        "c8_additive",
    ):
        print(f"  {k:<18} {'PASA' if vd[k] else 'FALLA'}")
    print(f"\n  VEREDICTO: {'SHIP' if vd['ship'] else 'NO-SHIP'}")
    print(f"  {vd['outcome']}")


if __name__ == "__main__":
    raise SystemExit(main())
