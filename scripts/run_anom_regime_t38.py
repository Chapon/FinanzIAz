"""
Runner de ANOM-REGIME — **Tarea 38**.

Pre-registro con la regla CONGELADA: ``docs/anom_regime_prereg_t38_2026-08-19.md``.

La pregunta
-----------
T11b midió que el detector de ruptura de momentum **tiene alpha real** (le gana al
azar con holgura, sobrevive LOTO, PBO 0.476) y que **falla sólo por régimen**:
``bear_2022`` −2.01 pts/trade y ``2018Q4`` −0.30 contra ``bull_normal`` +1.57. Es el
crash-risk documentado del momentum. **¿Condicionar la señal al régimen —con el mismo
detector que la cuenta ya usa (T20)— convierte ese edge en uno robusto?**

Qué hace (fiel al pre-registro)
-------------------------------
1. **La señal queda FIJA** en ``A_k2.0_m1.5`` (el brazo de decisión de T11b) para todos
   los brazos: el eje de esta tarea es el **gate**, no la calibración del detector.
2. Brazos: ``U_ungated`` (baseline) vs **``G_half``** (candidato primario: reusa
   *exactamente* el overlay de T20, factor 0.50 en risk-off, ya cableado y **activo**
   en la cuenta viva) + tres secundarios descriptivos (``G_hard``, ``G_confirm``,
   ``G_scale25``) que **no pueden reemplazar al primario después de ver los números**.
3. **C2 es el criterio que hace el trabajo** y se mide a nivel **CARTERA por ventana de
   régimen** (``regime_window_returns``), no por trade: un gate que deja de operar en
   el bear tiene ~cero trades ahí, así que el Δ por trade es vacío y **pasaría el
   criterio sin hacer nada**. C1 sólo pide ≥ 0 porque el gate no existe para agregar
   retorno, existe para sacar el crash-risk.
4. Config honesta: ``eval_mode="touch"`` + ``fill_mode="decision"`` + ``live_gates=True``
   + universo y slots de la cuenta viva. **T11b no tenía ninguno de los cinco.**

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py``/``strategies.py``.
"""

from __future__ import annotations

import argparse
import json
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
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    StaleArtifactError,
    announce,
    announce_artifacts,
    artifact_window,
)
from analysis.market_regime import build_regime_series, make_entry_filter
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import precompute_oracle_returns
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    BULL_NORMAL,
    STRESS_REGIMES,
    paired_block_bootstrap,
    pbo_cscv,
    regime_for_date,
    regime_window_returns,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_anomaly_replay_t11b import (
    _median,
    _month,
    _pct,
    load_bars_signals_volume,
    operable_entries,
    random_baseline,
    regime_trade_breakdown,
    summarise,
)
from scripts.run_market_regime_r2 import load_spy_bars
from scripts.run_rank_neutral_t39 import aligned_daily

# ── §2/§3 — señal, brazos y config congelados ────────────────────────────────
SIGNAL_K = 2.0  # A_k2.0_m1.5: el brazo de DECISIÓN de T11b, no su primario
SIGNAL_M = 1.5
CAP_DAYS = 20  # el horizonte que T11b pre-registró para esta señal
EVAL_MODE = "touch"
LIVE_GATES = True

BASELINE_ARM = "U_ungated"
CANDIDATE_ARM = "G_half"  # §2: primario declarado por un motivo ajeno al resultado
ORACLE_ARM = "V_oracle_entry"
GATE_ARMS: dict[str, dict] = {
    BASELINE_ARM: {"mode": "off"},
    CANDIDATE_ARM: {"mode": "half"},
    "G_hard": {"mode": "hard"},
    "G_confirm": {"mode": "confirm", "confirm_days": 5},
    "G_scale25": {"mode": "scale", "factor": 0.25},
}

# ── §6 — regla de decisión congelada ─────────────────────────────────────────
KILL_MIN_DCAGR = 0.0  # C1: no puede COSTAR retorno (≥ 0.00 pp)
KILL_REGIME_TOL = -0.0050  # C2: ≥ −0.50 pp de retorno de cartera por régimen
KILL_BOOT_FLOOR = -0.005  # C5: IC95% inferior > −0.005
KILL_MAX_PBO = 0.5  # C6
C2_STRICT_REGIMES = ("stress_bear_2022", "stress_2018q4")  # donde T11b sangraba

# ── §5 — sanity del instrumento ──────────────────────────────────────────────
SANITY_ORACLE_EDGE = 0.2000  # oráculo ≥ baseline + 20.00 pp
SANITY_MIN_TRADE_DIFF = 0.10  # el gate muerde: ≥10% de trades distintos…
SANITY_MIN_CAPITAL_DIFF = 0.10  # …o ≥10% del capital desplegado
SANITY_RANDOM_PCTILE = 95

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345


# ── Métricas propias de esta tarea ───────────────────────────────────────────


def deployed_capital(res: PortfolioResult) -> float:
    """Capital efectivamente desplegado (suma de lo invertido en cada trade).

    Es la segunda mitad del sanity §5.4: un gate que **achica** el tamaño sin
    cambiar qué tickets se toman no movería el solapamiento de trades, pero sí
    esto. Con ``G_half`` (factor 0.50) es justamente el canal principal.
    """
    return sum(t.invested for t in res.trades)


def gate_bites(base: PortfolioResult, cand: PortfolioResult) -> dict:
    """§5.4 — el gate muerde por trades **o** por capital desplegado.

    El criterio es **el congelado** y se aplica tal cual. Pero se reporta al lado un
    descriptivo que mide lo que la frase *quiere* decir, porque las dos métricas del
    §5.4 son estructuralmente insensibles a un gate que **achica** en vez de
    bloquear: el simulador **redespliega el cash liberado** en la próxima entrada, así
    que la suma de lo invertido a 10 años puede quedar casi igual aunque el gate haya
    mordido en cada risk-off. Es la lección de la T34 §7.5 —verificar que la métrica
    del sanity mida lo que la frase dice— aplicada antes de correr, no después.
    """
    sa = {(t.ticker, t.entry_date) for t in base.trades}
    sb = {(t.ticker, t.entry_date) for t in cand.trades}
    union = sa | sb
    trade_diff = (len(union - (sa & sb)) / len(union)) if union else 0.0
    cap_a, cap_b = deployed_capital(base), deployed_capital(cand)
    cap_diff = abs(cap_b - cap_a) / cap_a if cap_a > 0 else 0.0
    scaled = [t for t in cand.trades if t.size_factor < 1.0]
    scaled_share = len(scaled) / len(cand.trades) if cand.trades else 0.0
    scaled_capital = (sum(t.invested for t in scaled) / cap_b) if cap_b > 0 else 0.0
    return {
        "trade_diff": trade_diff,
        "capital_diff": cap_diff,
        # Descriptivos (NO son el criterio): qué fracción de las entradas del
        # candidato cayó en risk-off y por lo tanto entró achicada.
        "scaled_trade_share": scaled_share,
        "scaled_capital_share": scaled_capital,
        "ok": (trade_diff >= SANITY_MIN_TRADE_DIFF or cap_diff >= SANITY_MIN_CAPITAL_DIFF),
    }


def regime_trade_counts(res: PortfolioResult) -> dict[str, int]:
    """``n_trades`` por régimen — **descriptivo, no criterio** (§4 del pre-registro).

    Va al lado del retorno para que se vea si un brazo pasó porque le fue bien o
    porque **no jugó**.
    """
    out = {BULL_NORMAL: 0}
    for r in STRESS_REGIMES:
        out[r.name] = 0
    for t in res.trades:
        out[t.regime] = out.get(t.regime, 0) + 1
    return out


# ── §6 — regla de decisión ───────────────────────────────────────────────────


def evaluate(
    base: dict,
    cand: dict,
    reg_base: dict,
    reg_cand: dict,
    boot,
    rb: dict,
    pbo_val: float | None,
    sens: dict | None,
) -> dict:
    """AND de los siete criterios, con cada caso partido del §6 resuelto ex ante."""
    b_sh = base["sharpe"] if base["sharpe"] is not None else -1e9
    c_sh = cand["sharpe"] if cand["sharpe"] is not None else -1e9
    reg_delta = {k: reg_cand[k] - reg_base[k] for k in reg_base}

    c1 = (cand["cagr"] - base["cagr"]) >= KILL_MIN_DCAGR
    c2_tol = all(d >= KILL_REGIME_TOL for d in reg_delta.values())
    c2_strict = all(reg_delta.get(r, 0.0) > 0.0 for r in C2_STRICT_REGIMES)
    c2 = c2_tol and c2_strict
    c3 = cand["max_dd"] <= base["max_dd"]
    c4 = c_sh >= b_sh and c_sh > rb["sharpe_p95"]
    c5 = boot is not None and boot.ci_low > KILL_BOOT_FLOOR
    c6 = pbo_val is not None and pbo_val < KILL_MAX_PBO
    c7 = sens is not None and bool(sens.get("c1_sign")) and bool(sens.get("c2_bear"))

    accounting = base["accounting_ok"] and cand["accounting_ok"]
    ship = bool(accounting and c1 and c2 and c3 and c4 and c5 and c6 and c7)

    if ship:
        outcome = (
            "SHIP — el detector entra como fuente de leads con el overlay de "
            "régimen de T20 aplicado, APAGADO detrás de un flag hasta que "
            "Chapa lo prenda (§7)."
        )
    elif c1 and not c2:
        outcome = (
            "NO-SHIP — C2: el gate no arregla el bear, que era el ÚNICO motivo "
            "por el que T11b no shipeó. Si no lo arregla, no sirve para nada."
        )
    elif c2 and not c1:
        outcome = (
            "NO-SHIP — C2 pasa y C1 falla: el gate arregla el bear pero cuesta "
            "retorno agregado. Se reporta CUÁNTO: es el precio del seguro, y con "
            "el número se puede volver con otro factor en un pre-registro propio."
        )
    else:
        outcome = "NO-SHIP — no pasa el AND de los siete criterios."

    return {
        "dcagr": cand["cagr"] - base["cagr"],
        "dd_delta": cand["max_dd"] - base["max_dd"],
        "sharpe_delta": c_sh - b_sh,
        "regime_delta": reg_delta,
        "c1_cagr": c1,
        "c2_regime": c2,
        "c2_tolerance": c2_tol,
        "c2_strict": c2_strict,
        "c3_maxdd": c3,
        "c4_sharpe": c4,
        "c5_bootstrap": c5,
        "c6_pbo": c6,
        "c7_sensitivity": c7,
        "ship": ship,
        "outcome": outcome,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ANOM-REGIME — Tarea 38")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--sens-max-positions", type=int, default=5)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--k-random", type=int, default=500)
    p.add_argument("--seed", type=int, default=BOOT_SEED)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument(
        "--no-sensitivity",
        action="store_true",
        help="saltea la corrida a 5 slots (C7 queda sin evaluar ⇒ NO-SHIP)",
    )
    p.add_argument(
        "--allow-stale-artifacts",
        action="store_true",
        help="no abortar si el cohorte de artefactos está desalineado (T30)",
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

    spy = load_spy_bars(args.period)
    if not spy:
        print("SPY sin cache 10y. Traelo con get_historical_data('SPY', period='10y').", file=sys.stderr)
        return 1
    series = build_regime_series(spy)
    n_off = sum(1 for f in series.risk_off if f)

    entries = build_anomaly_entries(
        bars_by, vol_by, AnomalyParams(k=SIGNAL_K, m=SIGNAL_M), warmup=args.warmup
    )
    if not entries:
        print("El detector no produjo entradas.", file=sys.stderr)
        return 1

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
        len(bars_by),
        window=artifact_window(bars_by),
        eval_mode=EVAL_MODE,
        fill_mode=HARNESS_FILL_MODE,
        live_gates=LIVE_GATES,
        file=log,
    )
    print(
        f"Señal FIJA A_k{SIGNAL_K}_m{SIGNAL_M} (brazo de decisión de T11b) · "
        f"{len(entries)} entradas · {len(bars_by)} tickers",
        file=log,
    )
    print(
        f"SPY: {len(spy)} barras ({spy[0][0]} → {spy[-1][0]}) · "
        f"risk-off en {100 * n_off / len(spy):.1f}% de las ruedas\n",
        file=log,
    )

    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        atr_p=AtrParams(),
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        eval_mode=EVAL_MODE,
        fill_mode=HARNESS_FILL_MODE,
        live_gates=LIVE_GATES,
    )

    def run_gate(cfg: dict, entries_, **over) -> PortfolioResult:
        filt = make_entry_filter(
            series, mode=cfg["mode"], confirm_days=cfg.get("confirm_days", 5), factor=cfg.get("factor", 0.5)
        )
        return simulate_portfolio(entries_, bars_by, sigs_by, entry_filter=filt, **dict(common, **over))

    results: dict[str, PortfolioResult] = {}
    for name, cfg in GATE_ARMS.items():
        print(f"  [{args.max_positions} slots] {name} …", file=log, flush=True)
        results[name] = run_gate(cfg, entries)
    summaries = {n: summarise(r) for n, r in results.items()}

    # §5.3 — el baseline tiene que reproducir el edge: Monte Carlo time-matched.
    print(f"  Monte Carlo time-matched (K={args.k_random}) …", file=log, flush=True)
    operable = operable_entries(bars_by, args.warmup)
    operable_by_month: dict[str, list[tuple[str, int]]] = {}
    for ti in operable:
        operable_by_month.setdefault(_month(bars_by, ti), []).append(ti)
    count_by_month: dict[str, int] = {}
    for ti in entries:
        key = _month(bars_by, ti)
        count_by_month[key] = count_by_month.get(key, 0) + 1

    def run_plain(entries_) -> PortfolioResult:
        return simulate_portfolio(entries_, bars_by, sigs_by, **common)

    rand_dist = random_baseline(
        run_plain, bars_by, count_by_month, operable_by_month, k_random=args.k_random, seed0=args.seed
    )
    rb: dict[str, Any] = {
        "cagr_p95": _pct(rand_dist["cagr"], SANITY_RANDOM_PCTILE),
        "cagr_median": _median(rand_dist["cagr"]),
        "sharpe_p95": _pct(rand_dist["sharpe"], SANITY_RANDOM_PCTILE),
        "sharpe_median": _median(rand_dist["sharpe"]),
        "maxdd_median": _median(rand_dist["max_dd"]),
        "k": args.k_random,
    }

    # §5.2 — oráculo de entrada (mira el futuro): valida que el instrumento vea
    # calidad de ENTRADA, que es el eje sobre el que actúa el gate.
    print("  Oráculo de entrada …", file=log, flush=True)
    oracle_ret = precompute_oracle_returns(
        operable,
        bars_by,
        sigs_by,
        atr_p=AtrParams(),
        so_params=ScaleOutParams(),
        cap_days=args.cap_days,
        costs=CostModel(),
        # El oráculo puntúa con la MISMA mecánica de salida que los brazos que
        # valida — las dos mitades, fill (T33) y decisión (26b, tarea 44).
        eval_mode=EVAL_MODE,
        fill_mode=HARNESS_FILL_MODE,
    )
    op_scored = [(ti, oracle_ret.get((ti[0], bars_by[ti[0]][ti[1]][0]))) for ti in operable]
    # Nombre nuevo: al re-bindear, el tipo declarado sigue siendo `float | None`
    # aunque el filtro ya saco los None, y el sort queda sin clave ordenable.
    scored = [(ti, r) for ti, r in op_scored if r is not None]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = sorted(
        (ti for ti, _ in scored[: len(entries)]),
        key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]),
    )
    results[ORACLE_ARM] = run_plain(top)
    summaries[ORACLE_ARM] = summarise(results[ORACLE_ARM])

    # §4 — retorno de CARTERA por ventana de régimen (el núcleo del C2).
    daily = aligned_daily(results, [BASELINE_ARM] + [n for n in GATE_ARMS if n != BASELINE_ARM])
    reg_by = {n: regime_window_returns(daily[n]) for n in daily}
    n_trades_by = {n: regime_trade_counts(results[n]) for n in GATE_ARMS}
    # Descriptivo (NO es criterio): la métrica POR TRADE con la que T11b midió su
    # fallo de régimen. Va al lado de la de cartera para que se pueda comparar con
    # el veredicto publicado — son dos métricas distintas, no dos configs.
    per_trade_by = {n: regime_trade_breakdown(results[n]) for n in GATE_ARMS}

    # C5 — bootstrap pareado candidato vs baseline.
    boot = paired_block_bootstrap(
        [r for _, r in daily[BASELINE_ARM]],
        [r for _, r in daily[CANDIDATE_ARM]],
        block=BOOT_BLOCK,
        n_resamples=args.resamples,
        seed=BOOT_SEED,
    )

    # C6 — PBO sobre la rejilla de gates.
    rets_all = {n: [r for _, r in daily[n]] for n in daily}
    T = len(next(iter(rets_all.values()))) if rets_all else 0
    pbo = pbo_cscv(rets_all, n_splits=10) if T >= 10 else None

    # C7 — sensibilidad a 5 slots (baseline + candidato).
    sens: dict[str, Any] | None = None
    if not args.no_sensitivity:
        print(f"  [{args.sens_max_positions} slots] sensibilidad …", file=log, flush=True)
        s_res: dict[str, Any] = {
            n: run_gate(GATE_ARMS[n], entries, max_positions=args.sens_max_positions)
            for n in (BASELINE_ARM, CANDIDATE_ARM)
        }
        s_daily = aligned_daily(s_res, [BASELINE_ARM, CANDIDATE_ARM])
        s_reg = {n: regime_window_returns(s_daily[n]) for n in s_daily}
        s_sum = {n: summarise(r) for n, r in s_res.items()}
        bear = "stress_bear_2022"
        sens = {
            "max_positions": args.sens_max_positions,
            "base_cagr": s_sum[BASELINE_ARM]["cagr"],
            "cand_cagr": s_sum[CANDIDATE_ARM]["cagr"],
            "dcagr": s_sum[CANDIDATE_ARM]["cagr"] - s_sum[BASELINE_ARM]["cagr"],
            "bear_delta": s_reg[CANDIDATE_ARM][bear] - s_reg[BASELINE_ARM][bear],
            "c1_sign": (s_sum[CANDIDATE_ARM]["cagr"] - s_sum[BASELINE_ARM]["cagr"]) >= KILL_MIN_DCAGR,
            "c2_bear": (s_reg[CANDIDATE_ARM][bear] - s_reg[BASELINE_ARM][bear]) > 0.0,
        }

    bites = gate_bites(results[BASELINE_ARM], results[CANDIDATE_ARM])
    sanity: dict[str, Any] = {
        "accounting": all(summaries[n]["accounting_ok"] for n in results),
        "oracle_edge": summaries[ORACLE_ARM]["cagr"] - summaries[BASELINE_ARM]["cagr"],
        "oracle_ok": (summaries[ORACLE_ARM]["cagr"] >= summaries[BASELINE_ARM]["cagr"] + SANITY_ORACLE_EDGE),
        "baseline_vs_random_p95": summaries[BASELINE_ARM]["cagr"] - rb["cagr_p95"],
        "edge_survives": summaries[BASELINE_ARM]["cagr"] > rb["cagr_p95"],
        "gate_bites": bites,
    }
    sanity["all_ok"] = bool(
        sanity["accounting"] and sanity["oracle_ok"] and sanity["edge_survives"] and bites["ok"]
    )

    verdict = evaluate(
        summaries[BASELINE_ARM],
        summaries[CANDIDATE_ARM],
        reg_by[BASELINE_ARM],
        reg_by[CANDIDATE_ARM],
        boot,
        rb,
        (pbo.pbo if pbo else None),
        sens,
    )
    if not sanity["all_ok"]:
        verdict["ship"] = False
        if not sanity["edge_survives"]:
            verdict["outcome"] = (
                "CORRIDA INVÁLIDA — sanity §5.3: el edge de T11b NO sobrevive a la "
                "config viva, así que **la premisa de la tarea se cayó**. Es publicable "
                "y cierra la línea."
            )
        else:
            verdict["outcome"] = (
                "CORRIDA INVÁLIDA — falla un sanity del §5; no hay "
                "veredicto. No se re-especifica nada para salvarla."
            )

    # Los secundarios se reportan como descriptivos: NO pueden reemplazar al primario.
    others = {n: summaries[n]["cagr"] for n in GATE_ARMS if n not in (BASELINE_ARM, CANDIDATE_ARM)}
    ctx: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries": len(entries),
        "signal": f"A_k{SIGNAL_K}_m{SIGNAL_M}",
        "max_positions": args.max_positions,
        "cap_days": args.cap_days,
        "eval_mode": EVAL_MODE,
        "fill_mode": HARNESS_FILL_MODE,
        "live_gates": LIVE_GATES,
        "risk_off_share": n_off / len(spy),
        "random_baseline": rb,
        "sanity": sanity,
        "verdict": verdict,
        "bootstrap": vars(boot),
        "pbo": (pbo.pbo if pbo else None),
        "obs": T,
        "regimes": reg_by,
        "regime_n_trades": n_trades_by,
        "regime_per_trade": per_trade_by,
        "secondary_cagr": others,
        "sensitivity": sens,
    }

    if args.json:
        print(json.dumps({"context": ctx, "summaries": summaries}, ensure_ascii=False, indent=2, default=str))
        return 0

    _report(summaries, ctx, verdict, sanity, boot, rb)
    return 0


def _f(x, w=9, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries, ctx, verdict, sanity, boot, rb):
    hdr = f"{'brazo':<16}{'CAGR':>10}{'Sharpe':>9}{'maxDD':>9}{'tomad':>8}{'expos':>8}"
    print(hdr)
    print("-" * len(hdr))
    tags = {BASELINE_ARM: "BASE (T11b tal cual)", CANDIDATE_ARM: "*CANDIDATO primario", ORACLE_ARM: "sanity"}
    for n, s in summaries.items():
        print(
            f"{n:<16}{_f(s['cagr'], 10, 2, '%')}{_f(s['sharpe'], 9, 2)}"
            f"{_f(s['max_dd'], 9, 1, '%')}{s['n_taken']:>8}{_f(s['exposure'], 8, 1, '%')}"
            f"  {tags.get(n, 'secundario (descriptivo)')}"
        )
    print(
        f"{'AZAR_TIME_MATCH':<16}{_f(rb['cagr_median'], 10, 2, '%')}"
        f"{_f(rb['sharpe_median'], 9, 2)}{_f(rb['maxdd_median'], 9, 1, '%')}{'':>8}{'':>8}"
        f"  Monte Carlo K={rb['k']} (p95 CAGR {_f(rb['cagr_p95'], 0, 2, '%')})"
    )

    print("\nSanity del instrumento (§5):")
    print(f"  [{'OK' if sanity['accounting'] else 'FALLA'}] contabilidad")
    print(
        f"  [{'OK' if sanity['oracle_ok'] else 'FALLA'}] el oráculo despega: "
        f"+{100 * sanity['oracle_edge']:.2f}pp sobre el baseline (mín +20.00pp)"
    )
    print(
        f"  [{'OK' if sanity['edge_survives'] else 'FALLA'}] el edge de T11b sobrevive: "
        f"baseline {_f(summaries[BASELINE_ARM]['cagr'], 0, 2, '%')} vs p95 del azar "
        f"{_f(rb['cagr_p95'], 0, 2, '%')}"
    )
    b = sanity["gate_bites"]
    print(
        f"  [{'OK' if b['ok'] else 'FALLA'}] el gate muerde: {100 * b['trade_diff']:.1f}% "
        f"de trades distintos o {100 * b['capital_diff']:.1f}% del capital (mín 10%)"
    )
    print(
        f"       descriptivo (NO es el criterio): el gate achicó "
        f"{100 * b['scaled_trade_share']:.1f}% de las entradas del candidato, "
        f"{100 * b['scaled_capital_share']:.1f}% del capital que desplegó"
    )

    print("\nRetorno de CARTERA por ventana de régimen (§4, cash = 0) · n_trades al lado:")
    for r in [BULL_NORMAL] + [x.name for x in STRESS_REGIMES]:
        rb_ = ctx["regimes"][BASELINE_ARM][r]
        rc_ = ctx["regimes"][CANDIDATE_ARM][r]
        nb = ctx["regime_n_trades"][BASELINE_ARM][r]
        nc = ctx["regime_n_trades"][CANDIDATE_ARM][r]
        star = " ←C2 estricto" if r in C2_STRICT_REGIMES else ""
        print(
            f"  {r:<20} base {100 * rb_:>+8.2f}% (n={nb:>3}) · cand {100 * rc_:>+8.2f}% "
            f"(n={nc:>3}) · Δ {100 * (rc_ - rb_):>+7.2f}pp{star}"
        )

    print("\nMISMO eje, métrica POR TRADE (descriptivo — es con la que T11b midió su fallo de régimen):")
    for r in [BULL_NORMAL] + [x.name for x in STRESS_REGIMES]:
        pb = ctx["regime_per_trade"][BASELINE_ARM][r]["mean_ret_pts"]
        pc = ctx["regime_per_trade"][CANDIDATE_ARM][r]["mean_ret_pts"]
        print(f"  {r:<20} base {pb:>+7.2f} pts · cand {pc:>+7.2f} pts")

    print(
        f"\nΔCAGR {_f(verdict['dcagr'], 0, 2, '%')} · ΔmaxDD {_f(verdict['dd_delta'], 0, 2, '%')} "
        f"· ΔSharpe {verdict['sharpe_delta']:+.3f}"
    )
    print(
        f"Bootstrap pareado: ΔCAGR obs {100 * boot.observed:+.2f}pp · "
        f"IC95% [{100 * boot.ci_low:+.2f}, {100 * boot.ci_high:+.2f}]pp · p={boot.p_value:.3f}"
    )
    if ctx["sensitivity"]:
        s = ctx["sensitivity"]
        print(
            f"Sensibilidad a {s['max_positions']} slots: ΔCAGR "
            f"{100 * s['dcagr']:+.2f}pp · Δbear {100 * s['bear_delta']:+.2f}pp"
        )
    print(
        "Secundarios (descriptivos, NO promovibles): "
        + " · ".join(f"{n} {100 * v:.2f}%" for n, v in ctx["secondary_cagr"].items())
    )

    print("\nRegla de decisión (§6):")
    for k, label in [
        ("c1_cagr", "C1 ΔCAGR ≥ 0.00pp (no puede costar retorno)"),
        ("c2_regime", "C2 régimen: ≥ −0.50pp en los 4 Y estricto en bear/2018Q4"),
        ("c3_maxdd", "C3 maxDD no empeora"),
        ("c4_sharpe", "C4 Sharpe ≥ base y > p95 del azar"),
        ("c5_bootstrap", "C5 IC95% inferior > −0.005"),
        ("c6_pbo", "C6 PBO < 0.5"),
        ("c7_sensitivity", "C7 C1 y el bear de C2 aguantan a 5 slots"),
    ]:
        print(f"  [{'PASA' if verdict[k] else 'FALLA'}] {label}")
    print(f"\n  PBO = {ctx['pbo'] if ctx['pbo'] is None else round(ctx['pbo'], 3)} (T={ctx['obs']} obs)")
    print(f"\n  VEREDICTO: {verdict['outcome']}")


if __name__ == "__main__":
    raise SystemExit(main())
