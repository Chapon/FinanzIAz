"""
Runner de RANK-NEUTRAL — **Tarea 39**.

Pre-registro con la regla CONGELADA: ``docs/rank_neutral_prereg_t39_2026-08-19.md``.

Qué hace (fiel al pre-registro)
-------------------------------
1. **El candidato es la POLÍTICA, no una semilla** (§4.1). "Orden aleatorio rotado"
   se instancia con **20** semillas; C1/C3 se leen sobre la mediana, C2 sobre el
   mínimo y el bootstrap se paira contra la **serie diaria promedio de las 20**.
   La semilla que se cablearía quedó declarada **antes** de correr: ``12345``.
2. **Bracket de persistencia** (§4.2): el ``buy_score`` es persistente y el orden
   rotado no, así que entra la familia ``P_fix`` (20 permutaciones **fijas**) como
   nulo pareado en persistencia. El alfabético de la T21 fue *una sola realización*
   de esa familia — por eso su +3.10 pp era suerte. Diagnóstico, NO promovible.
3. **Config honesta**: ``eval_mode="touch"`` (26b) + ``fill_mode="decision"`` (T33)
   + ``live_gates=True`` (T34). La T21 no tenía ninguno de los tres.
4. **Seis criterios en AND** (§6) con cada caso partido resuelto ex ante, y siete
   sanity (§5) — incluido el de **reproducción** de la línea publicada por la T33
   (``B1_score`` = 1.97% en su config), que valida población y cañería.

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py``/``strategies.py``.
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
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.rank_policy import fixed_rank, neutral_rank
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    BULL_NORMAL,
    STRESS_REGIMES,
    _sharpe,
    _skew_kurt,
    deflated_sharpe_ratio,
    paired_block_bootstrap,
    pbo_cscv,
    regime_for_date,
    regime_window_returns,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_ranking_t21 import (
    load_bars_signals_scores,
    precompute_realized,
    summarise,
    trade_overlap,
)
from scripts.run_tp_cal_replay_t23 import buy_entries

# ── §3 — población y config congeladas ───────────────────────────────────────
CAP_DAYS = 250  # lección T13 §2 (el engine no tiene tope de tenencia)
EVAL_MODE = "touch"  # la regla que ejecuta el engine (26b)
LIVE_GATES = True  # gates de re-entrada del engine vivo (T34)

# ── §2 — brazos ──────────────────────────────────────────────────────────────
BASELINE_ARM = "B1_score"
INVERTED_ARM = "I_inverted"
ORACLE_ARM = "ORACULO"
ANTI_ORACLE_ARM = "ANTI_ORACULO"
ROT_PREFIX = "N_rot_"
FIX_PREFIX = "P_fix_"
N_SEEDS = 20
ROT_SEED_BASE = 12345  # §2: la semilla que se cablearía es ésta (k=0)
FIX_SEED_BASE = 54321

# ── §6 — regla de decisión congelada ─────────────────────────────────────────
KILL_MIN_DCAGR = 0.0050  # C1: mediana(N_rot) − B1 ≥ +0.50pp (umbral de T21 C1)
KILL_DD_TOL = 0.0300  # C3: mediana maxDD ≤ base + 3.00pp (umbral de T21 C2)
KILL_REGIME_TOL = -0.0050  # C5: ≥ −0.50pp de retorno de cartera por régimen (T38 C2)

# ── §5 — sanity del instrumento ──────────────────────────────────────────────
SANITY_ORACLE_EDGE = 0.0500  # ORACULO ≥ B1 + 5.00pp (umbral de T21 §5.2)
SANITY_MIN_TRADE_DIFF = 0.10  # ≥10% de trades distintos (umbral de T21 §5.4)
SANITY_T33_CAGR = 0.0197  # docs/fill_lookahead_t33_2026-08-16.md §6
SANITY_T33_TOL = 0.0005  # ±0.05pp (el publicado va a 2 decimales)

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345


# ── Brazos ───────────────────────────────────────────────────────────────────


def rot_name(k: int) -> str:
    return f"{ROT_PREFIX}{k}"


def fix_name(k: int) -> str:
    return f"{FIX_PREFIX}{k}"


def build_arms(score_by, realized, *, n_seeds: int = N_SEEDS) -> dict:
    """Los ``rank_score`` de cada brazo del §2. Mayor entra primero."""

    def b1(t: str, d: str) -> float:
        return float((score_by.get(t) or {}).get(d, 0.0))

    def inverted(t: str, d: str) -> float:
        return -float((score_by.get(t) or {}).get(d, 0.0))

    arms: dict[str, object] = {
        BASELINE_ARM: b1,
        INVERTED_ARM: inverted,
        ORACLE_ARM: (lambda t, d: realized.get((t, d), -9.9)),
        ANTI_ORACLE_ARM: (lambda t, d: -realized.get((t, d), 9.9)),
    }
    for k in range(n_seeds):
        # Cierre por default-arg: cada brazo se queda con SU semilla. La función
        # es pura, así que el valor no depende del orden de las llamadas (§5.7).
        arms[rot_name(k)] = lambda t, d, _s=ROT_SEED_BASE + k: neutral_rank(_s, d, t)
        arms[fix_name(k)] = lambda t, d, _s=FIX_SEED_BASE + k: fixed_rank(_s, t)
    return arms


# ── Series diarias ───────────────────────────────────────────────────────────


def aligned_daily(results: dict[str, PortfolioResult], arms: list[str]) -> dict[str, list[tuple[str, float]]]:
    """``{brazo: [(fecha, retorno_diario)]}`` sobre el calendario **unión**.

    Misma mecánica que ``run_tp_cal_replay_t23.aligned_returns`` (forward-fill de
    la equity y mismo guard de ``filled[i-1] > 0``), pero conservando la fecha —
    que es lo que necesita el retorno por ventana de régimen del C5. El test
    ``test_aligned_daily_coincide_con_aligned_returns`` fija esa equivalencia.
    """
    eq_by: dict[str, dict[str, float]] = {}
    cal: set[str] = set()
    for name in arms:
        d = {dt: v for dt, v in results[name].equity_curve}
        eq_by[name] = d
        cal |= set(d)
    dates = sorted(cal)
    out: dict[str, list[tuple[str, float]]] = {}
    for name in arms:
        d = eq_by[name]
        last = results[name].initial_capital
        filled: list[float] = []
        for dt in dates:
            if dt in d:
                last = d[dt]
            filled.append(last)
        out[name] = [
            (dates[i], filled[i] / filled[i - 1] - 1.0) for i in range(1, len(filled)) if filled[i - 1] > 0
        ]
    return out


def policy_series(daily: dict[str, list[tuple[str, float]]], names: list[str]) -> list[tuple[str, float]]:
    """Serie diaria **promedio de las semillas** — el retorno esperado de la política (§4.1).

    Promediar sobre semillas saca el ruido de la realización, que es exactamente
    lo que hundió a C3 en la T21 (allá el Δ mezclaba el déficit del score con la
    suerte del alfabético).
    """
    if not names:
        return []
    series = [daily[n] for n in names]
    n = min(len(s) for s in series)
    out: list[tuple[str, float]] = []
    for i in range(n):
        out.append((series[0][i][0], statistics.fmean(s[i][1] for s in series)))
    return out


# ── §4.2 — dónde cae el score dentro del bracket de persistencia ─────────────


def _ranks(vals: list[float]) -> list[float]:
    """Rangos con promedio en los empates (los scores empatan seguido)."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    out = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def rank_autocorr(key, by_date: dict[str, list[str]], lag: int = 1) -> float | None:
    """Autocorrelación de rango a ``lag`` ruedas de una clave de orden (Spearman medio).

    Ubica una política dentro del bracket del §4.2: el orden rotado da ~0 (rota
    todos los días), el fijo da 1.0 (no rota nunca) y el ``buy_score`` cae en
    algún lugar del medio — que es el número que dice cuánto se parece el
    baseline a cada punta del bracket.

    ``lag`` importa porque el mecanismo que el bracket mide es la **concentración
    del book**, y eso se juega al **horizonte de tenencia**, no a un día: una
    clave con autocorrelación diaria alta pero que se desarma en una semana no
    concentra nada. Extrapolar el lag-1 como si fuera AR(1) sería un supuesto, así
    que se mide directo.
    """
    from analysis.walkforward_power import pearson

    dates = sorted(by_date)
    rhos: list[float] = []
    # strict=False obligado: son pares con LAG, asi que los largos difieren por
    # `lag` a proposito (y por eso tampoco sirve pairwise, que asume lag=1).
    for prev, cur in zip(dates, dates[lag:], strict=False):
        common = sorted(set(by_date[prev]) & set(by_date[cur]))
        if len(common) < 3:
            continue
        a = _ranks([float(key(t, prev)) for t in common])
        b = _ranks([float(key(t, cur)) for t in common])
        r = pearson(a, b)
        if r is not None:
            rhos.append(r)
    return statistics.fmean(rhos) if rhos else None


def buy_candidates_by_date(bars_by, sigs_by, warmup: int) -> dict[str, list[str]]:
    """``{fecha: [tickers con analyze BUY ese día]}`` — el pool que compite por slot."""
    out: dict[str, list[str]] = {}
    for t, bars in bars_by.items():
        sig = sigs_by.get(t) or {}
        for idx in range(warmup, len(bars) - 1):
            d = bars[idx][0]
            if sig.get(d) == "BUY":
                out.setdefault(d, []).append(t)
    return out


# ── §6 — regla de decisión ───────────────────────────────────────────────────


def evaluate(base: dict, seeds: list[dict], boot, regime_delta: dict, sens: dict | None) -> dict:
    """AND de los seis criterios, con cada caso partido del §6 resuelto ex ante."""
    cagrs = sorted(s["cagr"] for s in seeds)
    med_cagr = statistics.median(cagrs)
    med_dd = statistics.median(s["max_dd"] for s in seeds)
    n_win = sum(1 for c in cagrs if c > base["cagr"])

    c1 = (med_cagr - base["cagr"]) >= KILL_MIN_DCAGR
    c2 = bool(cagrs) and n_win == len(cagrs)
    c3 = med_dd <= base["max_dd"] + KILL_DD_TOL
    c4 = boot is not None and boot.ci_low > 0.0
    c5 = bool(regime_delta) and all(d >= KILL_REGIME_TOL for d in regime_delta.values())
    c6 = sens is not None and bool(sens.get("c1_sign")) and bool(sens.get("c2"))

    accounting = base["accounting_ok"] and all(s["accounting_ok"] for s in seeds)
    ship = bool(accounting and c1 and c2 and c3 and c4 and c5 and c6)

    if ship:
        outcome = (
            "SHIP — el ranking pasa a orden aleatorio rotado "
            f"(`paper_ranking_mode=neutral_random`, semilla {ROT_SEED_BASE})."
        )
    elif c1 and not c3:
        outcome = (
            "NO-SHIP — caso partido resuelto ex ante (§6): la política rinde "
            "más pero el drawdown se deteriora por encima de la tolerancia "
            "declarada. Se reporta cuánto drawdown compra el score."
        )
    elif c1 and not c2:
        outcome = (
            f"NO-SHIP — C2 falla: ganan {n_win}/{len(cagrs)} semillas. Se cablea "
            "UNA semilla elegida a ciegas, así que si el resultado depende de "
            "cuál toca no hay política validada. La fracción queda como lead "
            "para un pre-registro propio."
        )
    elif c1 and c2 and c3 and not c4:
        outcome = (
            "NO-SHIP — el bootstrap pareado no clarea el 95%. Precedente directo "
            "y del mismo harness: es lo que le pasó al alfabético en la T21."
        )
    elif c1 and c2 and c3 and c4 and not c5:
        outcome = (
            "NO-SHIP — C5: la política cuesta retorno de cartera en al menos un "
            "régimen por encima de la tolerancia declarada."
        )
    elif c1 and c2 and c3 and c4 and c5 and not c6:
        outcome = (
            "NO-SHIP — C6: el resultado no sobrevive a 5 slots, donde el ranking "
            "debería decidir MÁS (peor ratio de selección), no menos."
        )
    elif not c1:
        outcome = (
            "NO-SHIP — el déficit del score no alcanza el umbral con la config "
            "honesta y los gates puestos. El ranking queda como está y el "
            "hallazgo se documenta como caducidad parcial de la sexta medición."
        )
    else:
        outcome = "NO-SHIP — no pasa el AND de los seis criterios."

    return {
        "median_cagr": med_cagr,
        "min_cagr": cagrs[0] if cagrs else None,
        "max_cagr": cagrs[-1] if cagrs else None,
        "median_max_dd": med_dd,
        "dcagr": med_cagr - base["cagr"],
        "dd_delta": med_dd - base["max_dd"],
        "n_win": n_win,
        "n_seeds": len(cagrs),
        "c1_cagr": c1,
        "c2_all_seeds": c2,
        "c3_maxdd": c3,
        "c4_bootstrap": c4,
        "c5_regime": c5,
        "c6_sensitivity": c6,
        "ship": ship,
        "outcome": outcome,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def _simulate(entries, bars_by, sigs_by, arms, common, *, log, label) -> dict:
    out: dict[str, PortfolioResult] = {}
    for i, (name, fn) in enumerate(arms.items(), 1):
        print(f"  [{label}] {i}/{len(arms)} {name} …", file=log, flush=True)
        out[name] = simulate_portfolio(entries, bars_by, sigs_by, atr_p=AtrParams(), rank_score=fn, **common)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="RANK-NEUTRAL — Tarea 39")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--sens-max-positions", type=int, default=5)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--seeds", type=int, default=N_SEEDS)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument(
        "--no-sensitivity",
        action="store_true",
        help="saltea la corrida a 5 slots (C6 queda sin evaluar ⇒ NO-SHIP)",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, score_by, missing = load_bars_signals_scores(tickers, args.period, args.warmup)
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
        eval_mode=EVAL_MODE,
        fill_mode=HARNESS_FILL_MODE,
        live_gates=LIVE_GATES,
        file=log,
    )
    print(
        f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)} · "
        f"semillas por familia: {args.seeds}\n",
        file=log,
    )

    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        eval_mode=EVAL_MODE,
        fill_mode=HARNESS_FILL_MODE,
        live_gates=LIVE_GATES,
    )
    realized = precompute_realized(entries, bars_by, sigs_by, common)
    print(f"Retornos realizados para el oráculo: {len(realized)}\n", file=log)

    arms = build_arms(score_by, realized, n_seeds=args.seeds)
    results = _simulate(entries, bars_by, sigs_by, arms, common, log=log, label=f"{args.max_positions} slots")
    summaries = {n: summarise(r) for n, r in results.items()}
    rot_names = [rot_name(k) for k in range(args.seeds)]
    fix_names = [fix_name(k) for k in range(args.seeds)]

    # §4.1 — la serie diaria de la política = promedio de las semillas.
    daily = aligned_daily(results, [BASELINE_ARM, *rot_names])
    pol = policy_series(daily, rot_names)
    base_daily = daily[BASELINE_ARM]
    boot = paired_block_bootstrap(
        [r for _, r in base_daily],
        [r for _, r in pol],
        block=BOOT_BLOCK,
        n_resamples=args.resamples,
        seed=BOOT_SEED,
    )

    # C5 — retorno de CARTERA por ventana de régimen (no por trade).
    reg_base = regime_window_returns(base_daily)
    reg_pol = regime_window_returns(pol)
    regime_delta = {k: reg_pol[k] - reg_base[k] for k in reg_base}

    # C6 — sensibilidad a 5 slots sobre los brazos de decisión.
    sens: dict[str, Any] | None = None
    if not args.no_sensitivity:
        sens_common = dict(common, max_positions=args.sens_max_positions)
        sens_arms = {n: arms[n] for n in [BASELINE_ARM, *rot_names]}
        sens_res = _simulate(
            entries,
            bars_by,
            sigs_by,
            sens_arms,
            sens_common,
            log=log,
            label=f"{args.sens_max_positions} slots",
        )
        sens_sum = {n: summarise(r) for n, r in sens_res.items()}
        s_base = sens_sum[BASELINE_ARM]["cagr"]
        s_cagrs = sorted(sens_sum[n]["cagr"] for n in rot_names)
        sens = {
            "max_positions": args.sens_max_positions,
            "base_cagr": s_base,
            "median_cagr": statistics.median(s_cagrs),
            "min_cagr": s_cagrs[0],
            "max_cagr": s_cagrs[-1],
            "n_win": sum(1 for c in s_cagrs if c > s_base),
            "c1_sign": (statistics.median(s_cagrs) - s_base) > 0.0,
            "c2": all(c > s_base for c in s_cagrs),
        }

    # §5.2 — sanity de reproducción: la línea publicada por la T33 para el baseline.
    repro_common = dict(common, eval_mode="close", live_gates=False)
    repro = simulate_portfolio(
        entries, bars_by, sigs_by, atr_p=AtrParams(), rank_score=arms[BASELINE_ARM], **repro_common
    )
    repro_cagr = summarise(repro)["cagr"]
    # Tarea 48: el chequeo sabe sobre qué VENTANA se midió su referencia, así que
    # un refresh de artefactos ya no se reporta como "cambió la cañería".
    # Tarea 52: y sobre qué POBLACIÓN, así que correrlo sobre otro universo tampoco.
    repro_state, repro_reason = reproduction_check(
        repro_cagr,
        SANITY_T33_CAGR,
        tol=SANITY_T33_TOL,
        current=artifact_window(bars_by),
        measured_on=WINDOW_REFRESH_2026_08_09,
        population=cfg.population(len(entries)),
        measured_over=POPULATION_LIVE_ACCT2,
    )

    # §5 — sanity del instrumento.
    diff_share = trade_overlap(results[BASELINE_ARM], results[rot_name(0)])
    pair_diffs = [
        trade_overlap(results[rot_names[i]], results[rot_names[j]])
        for i in range(len(rot_names))
        for j in range(i + 1, len(rot_names))
    ]
    seed_cagrs = [summaries[n]["cagr"] for n in rot_names]
    sanity: dict[str, Any] = {
        "accounting": all(summaries[n]["accounting_ok"] for n in results),
        "repro_cagr": repro_cagr,
        "repro_state": repro_state,
        "repro_reason": repro_reason,
        "repro_ok": repro_state == REPRO_OK,
        "oracle_edge": summaries[ORACLE_ARM]["cagr"] - summaries[BASELINE_ARM]["cagr"],
        "oracle_ok": (summaries[ORACLE_ARM]["cagr"] >= summaries[BASELINE_ARM]["cagr"] + SANITY_ORACLE_EDGE),
        "anti_oracle_ok": summaries[ANTI_ORACLE_ARM]["cagr"] <= summaries[BASELINE_ARM]["cagr"],
        "trade_diff_share": diff_share,
        "ranking_bites": diff_share >= SANITY_MIN_TRADE_DIFF,
        "seed_pair_diff": statistics.median(pair_diffs) if pair_diffs else 0.0,
        "seeds_effective": (
            bool(pair_diffs)
            and statistics.median(pair_diffs) >= SANITY_MIN_TRADE_DIFF
            and len(set(seed_cagrs)) == len(seed_cagrs)
        ),
    }
    sanity["all_ok"] = bool(
        sanity["accounting"]
        and sanity["repro_ok"]
        and sanity["oracle_ok"]
        and sanity["anti_oracle_ok"]
        and sanity["ranking_bites"]
        and sanity["seeds_effective"]
    )

    verdict = evaluate(summaries[BASELINE_ARM], [summaries[n] for n in rot_names], boot, regime_delta, sens)
    if not sanity["all_ok"]:
        verdict["ship"] = False
        verdict["outcome"] = (
            "CORRIDA INVÁLIDA — falla un sanity del §5; no hay veredicto "
            "(el instrumento no está validado). No se re-especifica nada."
        )

    fix_cagrs = sorted(summaries[n]["cagr"] for n in fix_names)
    rot_cagrs = sorted(seed_cagrs)

    # §4.2 — descriptivo: dónde cae el score entre las dos puntas del bracket.
    pool = buy_candidates_by_date(bars_by, sigs_by, args.warmup)
    persistence: dict[str, Any] = {
        BASELINE_ARM: rank_autocorr(arms[BASELINE_ARM], pool),
        rot_name(0): rank_autocorr(arms[rot_name(0)], pool),
        fix_name(0): rank_autocorr(arms[fix_name(0)], pool),
    }
    # A qué horizonte se desarma el orden del score: es lo que decide si la punta
    # relevante del bracket es la fija o la rotada.
    persistence_lags: dict[str, Any] = {
        f"lag_{k}": rank_autocorr(arms[BASELINE_ARM], pool, lag=k)
        # El 8 es la tenencia media del baseline: es el lag que decide cuál punta
        # del bracket aplica, porque la concentración se juega a ese horizonte.
        for k in (1, 2, 5, 8, 20, 60, 250)
    }

    # Descriptivos (NO son gate — §6): DSR/PBO sobre los brazos no-intercambiables.
    real_arms = [BASELINE_ARM, rot_name(0), fix_name(0), INVERTED_ARM]
    d_all = aligned_daily(results, real_arms)
    rets_all = {c: [r for _, r in d_all[c]] for c in real_arms}
    T = len(next(iter(rets_all.values()))) if rets_all else 0
    pbo = pbo_cscv(rets_all, n_splits=10) if T >= 10 else None
    dsr = None
    if T >= 2:
        sk, ku = _skew_kurt(rets_all[rot_name(0)])
        dsr = deflated_sharpe_ratio(
            [_sharpe(rets_all[c]) for c in real_arms],
            n_obs=T,
            selected=_sharpe(rets_all[rot_name(0)]),
            skew=sk,
            kurtosis=ku,
        )

    ctx: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries": len(entries),
        "max_positions": args.max_positions,
        "cap_days": args.cap_days,
        "eval_mode": EVAL_MODE,
        "fill_mode": HARNESS_FILL_MODE,
        "live_gates": LIVE_GATES,
        "n_seeds": args.seeds,
        "shipped_seed": ROT_SEED_BASE,
        "sanity": sanity,
        "verdict": verdict,
        "bootstrap": vars(boot),
        "rot_cagr": {"min": rot_cagrs[0], "median": statistics.median(rot_cagrs), "max": rot_cagrs[-1]},
        "fix_cagr": {"min": fix_cagrs[0], "median": statistics.median(fix_cagrs), "max": fix_cagrs[-1]},
        "regime_base": reg_base,
        "regime_policy": reg_pol,
        "regime_delta": regime_delta,
        "sensitivity": sens,
        "persistence": persistence,
        "persistence_lags": persistence_lags,
        "dsr": (dsr.deflated_sharpe if dsr else None),
        "pbo": (pbo.pbo if pbo else None),
        "dsr_obs": T,
    }

    if args.json:
        print(json.dumps({"context": ctx, "summaries": summaries}, ensure_ascii=False, indent=2, default=str))
        return 0

    _report(summaries, ctx, verdict, sanity, boot, rot_cagrs, fix_cagrs, dsr, pbo, T)
    return 0


def _f(x, w=9, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries, ctx, verdict, sanity, boot, rot_cagrs, fix_cagrs, dsr, pbo, T):
    hdr = f"{'brazo':<16}{'CAGR':>10}{'Sharpe':>9}{'maxDD':>9}{'tomad':>8}{'días':>7}"
    print(hdr)
    print("-" * len(hdr))
    for n, tag in [
        (BASELINE_ARM, "BASE (lo vivo)"),
        (INVERTED_ARM, "diagnóstico"),
        (ORACLE_ARM, "sanity"),
        (ANTI_ORACLE_ARM, "sanity"),
    ]:
        s = summaries[n]
        print(
            f"{n:<16}{_f(s['cagr'], 10, 2, '%')}{_f(s['sharpe'], 9, 2)}{_f(s['max_dd'], 9, 1, '%')}"
            f"{s['n_taken']:>8}{s['mean_held_days']:>7.1f}  {tag}"
        )
    print(
        f"{'N_rot ×' + str(ctx['n_seeds']):<16}{_f(ctx['rot_cagr']['median'], 10, 2, '%')}"
        f"{'':>9}{_f(verdict['median_max_dd'], 9, 1, '%')}{'':>8}{'':>7}  "
        f"*CANDIDATO (la política) [{100 * rot_cagrs[0]:.2f}%, {100 * rot_cagrs[-1]:.2f}%]"
    )
    print(
        f"{'P_fix ×' + str(ctx['n_seeds']):<16}{_f(ctx['fix_cagr']['median'], 10, 2, '%')}"
        f"{'':>9}{'':>9}{'':>8}{'':>7}  nulo persistente "
        f"[{100 * fix_cagrs[0]:.2f}%, {100 * fix_cagrs[-1]:.2f}%]"
    )

    print("\nSanity del instrumento (§5):")
    print(f"  [{'OK' if sanity['accounting'] else 'FALLA'}] contabilidad")
    print(
        f"  [{sanity.get('repro_state', 'FALLA')}] reproduce la línea de la T33: "
        f"{100 * sanity['repro_cagr']:.2f}% (esperado {100 * SANITY_T33_CAGR:.2f}% "
        f"± {100 * SANITY_T33_TOL:.2f}pp)"
    )
    print(
        f"  [{'OK' if sanity['oracle_ok'] else 'FALLA'}] el oráculo despega: "
        f"+{100 * sanity['oracle_edge']:.2f}pp sobre el baseline (mín +5.00pp)"
    )
    print(f"  [{'OK' if sanity['anti_oracle_ok'] else 'FALLA'}] el anti-oráculo hunde")
    print(
        f"  [{'OK' if sanity['ranking_bites'] else 'FALLA'}] el ranking muerde: "
        f"{100 * sanity['trade_diff_share']:.1f}% de trades distintos (mín 10%)"
    )
    print(
        f"  [{'OK' if sanity['seeds_effective'] else 'FALLA'}] las semillas mueven: "
        f"{100 * sanity['seed_pair_diff']:.1f}% de trades distintos entre semillas (mediana)"
    )

    pers = ctx.get("persistence") or {}
    if pers:

        def _p(x):
            return "n/d" if x is None else f"{x:+.3f}"

        print(
            f"\nBracket de persistencia (§4.2, autocorrelación de rango día a día): "
            f"score {_p(pers.get(BASELINE_ARM))} · rotado {_p(pers.get(rot_name(0)))} "
            f"· fijo {_p(pers.get(fix_name(0)))}"
        )
        lags = ctx.get("persistence_lags") or {}
        if lags:
            print(
                "  el orden del score a k ruedas: "
                + " · ".join(f"lag {k.split('_')[1]} {_p(v)}" for k, v in lags.items())
            )

    print("\nRetorno de CARTERA por ventana de régimen (§6 C5, cash = 0):")
    for r in [BULL_NORMAL] + [x.name for x in STRESS_REGIMES]:
        print(
            f"  {r:<20} base {100 * ctx['regime_base'][r]:>+8.2f}% · "
            f"política {100 * ctx['regime_policy'][r]:>+8.2f}% · "
            f"Δ {100 * ctx['regime_delta'][r]:>+7.2f}pp"
        )

    print(
        f"\nΔCAGR (mediana) {_f(verdict['dcagr'], 0, 2, '%')} · "
        f"ΔmaxDD {_f(verdict['dd_delta'], 0, 2, '%')} · "
        f"semillas que ganan: {verdict['n_win']}/{verdict['n_seeds']}"
    )
    print(
        f"Bootstrap pareado (serie promedio de las semillas): ΔCAGR obs "
        f"{100 * boot.observed:+.2f}pp · IC95% [{100 * boot.ci_low:+.2f}, "
        f"{100 * boot.ci_high:+.2f}]pp · p={boot.p_value:.3f} "
        f"(bloques {boot.block}, {boot.n_resamples} resamples, T={boot.n_obs})"
    )
    if ctx["sensitivity"]:
        s = ctx["sensitivity"]
        print(
            f"Sensibilidad a {s['max_positions']} slots: base {100 * s['base_cagr']:.2f}% · "
            f"mediana {100 * s['median_cagr']:.2f}% [{100 * s['min_cagr']:.2f}%, "
            f"{100 * s['max_cagr']:.2f}%] · ganan {s['n_win']}/{ctx['n_seeds']}"
        )

    print("\nRegla de decisión (§6):")
    for k, label in [
        ("c1_cagr", "C1 ΔCAGR mediana ≥ +0.50pp"),
        ("c2_all_seeds", "C2 las 20 semillas le ganan al baseline"),
        ("c3_maxdd", "C3 maxDD mediana ≤ base + 3.00pp  ← riesgo"),
        ("c4_bootstrap", "C4 IC95% inferior > 0"),
        ("c5_regime", "C5 retorno de cartera por régimen ≥ −0.50pp"),
        ("c6_sensitivity", "C6 el signo de C1 y el de C2 aguantan a 5 slots"),
    ]:
        print(f"  [{'PASA' if verdict[k] else 'FALLA'}] {label}")
    head = f"DSR = {dsr.deflated_sharpe:.3f}" if dsr else "DSR = n/d"
    tail = f"· PBO = {pbo.pbo:.3f}" if pbo else "· PBO = n/d"
    print(f"\nDescriptivos (NO son gate): {head} {tail} (T={T} obs)")
    print(f"\n  VEREDICTO: {verdict['outcome']}")


if __name__ == "__main__":
    raise SystemExit(main())
