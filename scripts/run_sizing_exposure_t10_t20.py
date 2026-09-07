"""
Runner del **bloque 10 + 20** — sizing por riesgo (nombre) + escalado por régimen
(mercado), co-registrados como un solo experimento.

Pre-registro con kill-criteria CONGELADOS:
``docs/sizing_exposure_prereg_t10_t20_2026-07-22.md``. Requiere el artefacto de
señal PIT (``data/pit_signals/``, tarea 7) y SPY 10y en cache.

    python scripts/run_sizing_exposure_t10_t20.py
    python scripts/run_sizing_exposure_t10_t20.py --json

Qué hace
--------
1. Corre los 7 brazos candidatos + el oráculo de validación sobre el simulador de
   cartera real (``analysis/portfolio_sim.py``): max_positions=5, capital finito,
   allow_reentry_while_open=False (engine-faithful).
2. Mide **CAGR, Sharpe anualizado y max DD de cartera** sobre la curva de equity
   (NO puntos acumulados — corrige el defecto de la lápida de la tarea 8).
3. Verifica invariantes ANTES de leer: integridad contable (curva vs cash),
   invariante de exits y sanidad del baseline.
4. Descuenta por selección múltiple: PBO (CSCV) + DSR sobre los 7 brazos.
5. Aplica el kill-criteria. No cambia ningún flag vivo.

Sin red y sin tocar ``finanzias.db``.
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
    LEGACY_FILL_MODE,
    LEGACY_MAX_POSITIONS,
    LIVE_MAX_POSITIONS,
    SignalStoreGapError,
    StaleArtifactError,
    announce,
    announce_artifacts,
    announce_signal_store,
    artifact_window,
)
from analysis.market_regime import build_regime_series, make_entry_filter
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import (
    build_sigma_map,
    cagr,
    make_size_weight,
    precompute_oracle_returns,
    sharpe_annual,
)
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    STRESS_REGIMES,
    _sharpe,
    _skew_kurt,
    deflated_sharpe_ratio,
    pbo_cscv,
    regime_for_date,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_market_regime_r2 import check_exit_invariant, load_spy_bars
from scripts.run_scaleout_replay_t7 import build_entries, load_bars_and_signals

DEFAULT_UNIVERSE = "data/harness_universe_41_10y.txt"

# Brazos pre-registrados (§4). Cada uno = kwargs de sizing/régimen; el resto fijo.
# sizing ∈ {equal, inverse_vol, vol_target, oracle}; regime = (mode, factor).
CANDIDATE_ARMS: dict[str, dict] = {
    "B0_equal_weight": {"sizing": None, "regime": None},
    "S1_inverse_vol": {"sizing": "inverse_vol", "regime": None},
    "S2_vol_target": {"sizing": "vol_target", "regime": None},
    "R2b_f025": {"sizing": None, "regime": ("scale", 0.25)},
    "R2b_f050": {"sizing": None, "regime": ("scale", 0.50)},
    "R2b_f075": {"sizing": None, "regime": ("scale", 0.75)},
    "C_S2xf050": {"sizing": "vol_target", "regime": ("scale", 0.50)},
}
BASELINE_ARM = "B0_equal_weight"
ORACLE_ARM = "V_oracle_size"

# Kill-criteria (§5) — congelados.
KILL_MIN_DSHARPE = 0.10  # OR: mejora de Sharpe anualizado
KILL_MIN_DCAGR = 0.01  # OR: mejora de CAGR (1.0 punto porcentual)
KILL_SIZING_DD_MULT = 1.5  # sizing: max DD no sube más de 1.5×
# régimen: max DD de cartera no sube (tolerancia numérica chica)
KILL_REGIME_DD_EPS = 1e-4
_REG_NAMES = ["bull_normal"] + [r.name for r in STRESS_REGIMES]
REGIME_ARMS = {"R2b_f025", "R2b_f050", "R2b_f075", "C_S2xf050"}


def regime_breakdown(res: PortfolioResult) -> dict:
    """Por régimen: retorno medio por trade, n, y **contribución al capital** — T120.

    ``mean_ret_pts`` es la métrica histórica y **no puede discriminar brazos que sólo
    cambian el TAMAÑO**: los trades son los mismos, así que sale idéntica en los
    siete. Con ella el criterio 4 del pre-registro (*"el beneficio no puede venir de
    una sola ventana"*) es inevaluable por construcción — y encima nunca estuvo
    cableado a la decisión, así que nadie lo notó.

    ``pnl_pts`` es la que sí discrimina: el P/L de esa ventana en **puntos del
    capital inicial**, que depende del notional y por lo tanto del brazo. Es la
    forma correcta de preguntar *"¿de qué régimen viene el beneficio?"* cuando el
    eje del brazo es cuánto se invierte y no en qué se invierte.
    """
    out: dict[str, dict] = {}
    cap = res.initial_capital or 1.0
    names = ["bull_normal"] + [r.name for r in STRESS_REGIMES]
    for name in names:
        tr = [t for t in res.trades if t.regime == name]
        out[name] = {
            "n_trades": len(tr),
            "mean_ret_pts": 100.0 * statistics.fmean([t.ret for t in tr]) if tr else 0.0,
            "pnl_pts": 100.0 * sum(t.pnl for t in tr) / cap,
        }
    return out


def regime_source_ok(base: PortfolioResult, cand: PortfolioResult) -> tuple[bool, dict]:
    """Criterio 4 del pre-registro, **implementado al pie de la letra** — Tarea 120.

    Texto congelado (§5.4): *"el signo del beneficio no puede venir enteramente de
    una sola ventana. Si el efecto es positivo **solo** en un régimen y negativo o
    nulo en el resto, NO-SHIP"*. O sea que falla **exactamente** cuando hay un solo
    régimen con Δ > 0 y todos los demás con Δ ≤ 0 — es un criterio deliberadamente
    laxo, y se implementa así y no más estricto: aflojarlo o apretarlo en septiembre
    un umbral congelado en julio es justo lo que la regla 2 prohíbe.

    Se evalúa sobre ``pnl_pts`` porque es la única de las dos métricas que
    **discrimina** cuando el brazo cambia el tamaño (ver ``regime_breakdown``).
    """
    b, c = regime_breakdown(base), regime_breakdown(cand)
    return regime_source_ok_desde({n: c[n]["pnl_pts"] - b[n]["pnl_pts"] for n in c})


def regime_source_ok_desde(deltas: dict[str, float]) -> tuple[bool, dict]:
    """La regla del §5.4, aislada de cómo se calculen los Δ — Tarea 120.

    Separada a propósito: el criterio es una **regla**, y una regla se testea con
    números a mano. Enterrarla adentro del cálculo obliga a fabricar dos carteras
    para probar un `if`, y ahí es donde un criterio termina no teniendo test.
    """
    positivos = [n for n, d in deltas.items() if d > 0.0]
    # "positivo sólo en uno Y no-positivo en el resto" -> falla. Con 0 positivos no
    # hay beneficio del que preguntar de dónde viene, y C1 ya lo habrá frenado;
    # frenarlo también acá sería contar el mismo hecho dos veces.
    ok = not (len(positivos) == 1 and len(deltas) > 1)
    return ok, {"deltas": deltas, "solo_en": positivos[0] if len(positivos) == 1 else None}


def regime_metric_discriminates(base: PortfolioResult, cand: PortfolioResult, key: str) -> bool:
    """¿Esa métrica por régimen distingue a estos dos brazos? — Tarea 120.

    Existe para que el runner **diga cuándo un criterio no es evaluable** en vez de
    imprimir una tabla que parece informativa. Una tabla idéntica entre brazos no es
    un resultado: es un instrumento que no mide el eje bajo test.
    """
    b, c = regime_breakdown(base), regime_breakdown(cand)
    return any(abs(c[n][key] - b[n][key]) > 1e-9 for n in c)


def accounting_ok(res: PortfolioResult) -> tuple[bool, float]:
    """La curva de equity termina en la equity final contable (desvío ~0)."""
    if not res.equity_curve or res.final_equity <= 0:
        return True, 0.0
    dev = abs(res.equity_curve[-1][1] - res.final_equity) / res.final_equity
    return dev <= 1e-6, dev


def weight_stats(res: PortfolioResult) -> dict:
    """Peso medio/máx por nombre (fracción de la equity inicial) — descriptivo."""
    if not res.trades:
        return {"mean_w": 0.0, "max_w": 0.0}
    ws = [t.invested / res.initial_capital for t in res.trades]
    return {"mean_w": statistics.fmean(ws), "max_w": max(ws)}


def _aligned_returns(results: dict[str, PortfolioResult], arms: list[str]) -> dict[str, list[float]]:
    """Retornos por-observación de cada brazo, alineados a un calendario común
    (unión de fechas, forward-fill de equity) → matriz rectangular para PBO/DSR."""
    eq_by: dict[str, dict[str, float]] = {}
    cal: set[str] = set()
    for name in arms:
        d = {dt: v for dt, v in results[name].equity_curve}
        eq_by[name] = d
        cal |= set(d)
    dates = sorted(cal)
    out: dict[str, list[float]] = {}
    for name in arms:
        d = eq_by[name]
        last = results[name].initial_capital
        filled: list[float] = []
        for dt in dates:
            if dt in d:
                last = d[dt]
            filled.append(last)
        out[name] = [filled[i] / filled[i - 1] - 1.0 for i in range(1, len(filled)) if filled[i - 1] > 0]
    return out


def summarise(name: str, res: PortfolioResult, base: PortfolioResult | None) -> dict:
    out: dict[str, Any] = {
        "arm": name,
        "cagr": cagr(res.equity_curve),
        "sharpe": sharpe_annual(res.equity_curve),
        "max_dd": res.max_dd,
        "total_return_pts": res.total_return_pts,
        "final_equity": res.final_equity,
        "exposure": res.exposure_share,
        "n_taken": res.n_taken,
        "n_filtered": res.n_filtered,
        "n_no_slot": res.n_no_slot,
        "n_no_cash": res.n_no_cash,
        "n_cash_capped": res.n_cash_capped,  # tarea 118: el camino por el que los brazos divergen
        "n_already_open": res.n_already_open,
        # Tarea 115 — el §5 del pre-registro los pide como sanity: que los gates
        # MUERDAN (>0) y que muerdan IGUAL en los siete brazos, que es la prediccion
        # falsable del §3 de la 36. Sin publicarlos no hay forma de verificarlo.
        "n_gate5_blocked": res.n_gate5_blocked,
        "n_gate5b_blocked": res.n_gate5b_blocked,
        "by_regime": regime_breakdown(res),
        "weights": weight_stats(res),
    }
    acc_ok, acc_dev = accounting_ok(res)
    out["accounting_ok"] = acc_ok
    out["accounting_dev"] = acc_dev
    if base is None:
        return out
    bs = sharpe_annual(base.equity_curve)
    out["delta_sharpe"] = (out["sharpe"] - bs) if (out["sharpe"] is not None and bs is not None) else None
    out["delta_cagr"] = out["cagr"] - cagr(base.equity_curve)
    out["dd_ratio"] = (res.max_dd / base.max_dd) if base.max_dd > 0 else float("inf")
    ok, detail = check_exit_invariant(base, res)
    out["exit_invariant_ok"] = ok
    out["exit_invariant_detail"] = detail

    benefit = (out["delta_sharpe"] is not None and out["delta_sharpe"] >= KILL_MIN_DSHARPE) or out[
        "delta_cagr"
    ] >= KILL_MIN_DCAGR
    if name in REGIME_ARMS:
        risk_ok = res.max_dd <= base.max_dd + KILL_REGIME_DD_EPS
    else:
        risk_ok = out["dd_ratio"] <= KILL_SIZING_DD_MULT
    out["benefit"] = bool(benefit)
    out["risk_ok"] = bool(risk_ok)
    # Criterio 4 del pre-registro (§5.4). **Nunca había estado cableado** (tarea
    # 120): `passes_local` miraba beneficio + riesgo + integridad y el régimen se
    # imprimía al costado, así que la T20 declaró SHIP sobre cuatro criterios
    # evaluando tres. Se implementa el texto congelado tal cual, sin re-decidirlo.
    regime_ok, regime_detail = regime_source_ok(base, res)
    out["regime_ok"] = bool(regime_ok)
    out["regime_c4"] = regime_detail
    out["regime_discriminates"] = {
        k: regime_metric_discriminates(base, res, k) for k in ("mean_ret_pts", "pnl_pts")
    }
    # 'passes' local = beneficio + riesgo + régimen + invariante; el descuento por
    # selección múltiple (DSR/PBO) se aplica al brazo seleccionado, aparte.
    out["passes_local"] = bool(benefit and risk_ok and regime_ok and ok and acc_ok)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bloque 10+20 — sizing por riesgo + régimen")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--spacing", type=int, default=20)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument(
        "--fill-mode",
        choices=(HARNESS_FILL_MODE, LEGACY_FILL_MODE),
        default=HARNESS_FILL_MODE,
        help=f"'{LEGACY_FILL_MODE}' reproduce el veredicto publicado "
        f"(look-ahead en el fill de la barrera — Tarea 33)",
    )
    p.add_argument(
        "--live-gates",
        action="store_true",
        help="modela los gates de re-entrada del engine (Gate 5 anti-whipsaw + Gate 5b "
        "anti-churn, T34). Default OFF ⇒ reproduce la corrida publicada. Tarea 115",
    )
    p.add_argument(
        "--allow-stale-artifacts",
        action="store_true",
        help="no abortar si el cohorte de artefactos está desalineado (T30) NI si el "
        "store de señales PIT está corto (T86) — declararlo en el pre-registro",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    spy = load_spy_bars(args.period)
    if not spy:
        print("SPY sin cache 10y.", file=sys.stderr)
        return 1
    series = build_regime_series(spy)
    n_off = sum(1 for x in series.risk_off if x)
    print(
        f"SPY: {len(spy)} barras ({spy[0][0]} → {spy[-1][0]}) · "
        f"días risk-off: {n_off} ({100 * n_off / len(spy):.1f}%)"
    )

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, missing, incomplete = load_bars_and_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if incomplete or missing:
        print(f"AVISO: {len(incomplete)} incompletos, {len(missing)} sin datos", file=sys.stderr)

    entries = build_entries(bars_by, sigs_by, spacing=args.spacing, warmup=args.warmup)
    sigma_by = build_sigma_map(entries, bars_by)
    oracle_ret = precompute_oracle_returns(entries, bars_by, sigs_by, fill_mode=args.fill_mode)
    # T30 — frescura del cohorte, ANTES de pagar la corrida (tarea 76). La ventana
    # que declara `artifact_window` es min(starts)..max(ends), así que un solo
    # artefacto desalineado la corre sin que se note. Falla ruidoso (política T22).
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts)
        announce_signal_store(bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts)
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3

    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=artifact_window(bars_by),
        verdict_max_positions=LEGACY_MAX_POSITIONS,
        entry_spacing=args.spacing,
        fill_mode=args.fill_mode,
        live_gates=args.live_gates,
    )
    print(
        f"Tickers: {len(bars_by)} · entradas: {len(entries)} · "
        f"σ computables: {len(sigma_by)} · max_positions={args.max_positions} · "
        f"capital={args.capital:,.0f}\n"
    )

    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        atr_p=AtrParams(),
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,  # engine-faithful (tarea 9), §2 del pre-registro
        fill_mode=args.fill_mode,
        live_gates=args.live_gates,
    )

    def build_arm(cfg: dict):
        sw = None
        if cfg["sizing"] is not None:
            sw = make_size_weight(cfg["sizing"], sigma_by, oracle_returns=oracle_ret)
        ef = None
        if cfg["regime"] is not None:
            mode, factor = cfg["regime"]
            ef = make_entry_filter(series, mode=mode, factor=factor)
        return sw, ef

    results: dict[str, PortfolioResult] = {}
    for name, cfg in CANDIDATE_ARMS.items():
        sw, ef = build_arm(cfg)
        results[name] = simulate_portfolio(
            entries, bars_by, sigs_by, size_weight=sw, entry_filter=ef, **common
        )
    # oráculo de validación (no candidato)
    results[ORACLE_ARM] = simulate_portfolio(
        entries,
        bars_by,
        sigs_by,
        size_weight=make_size_weight("oracle", sigma_by, oracle_returns=oracle_ret),
        entry_filter=None,
        **common,
    )

    base = results[BASELINE_ARM]
    summaries: dict[str, Any] = {
        name: summarise(name, results[name], None if name == BASELINE_ARM else base)
        for name in CANDIDATE_ARMS
    }
    oracle_sum = summarise(ORACLE_ARM, results[ORACLE_ARM], base)

    # ── descuento por selección múltiple (PBO + DSR) sobre los 7 candidatos ──
    cand = list(CANDIDATE_ARMS)
    rets = _aligned_returns(results, cand)
    T = len(next(iter(rets.values())))
    pbo = pbo_cscv({c: rets[c] for c in cand}, n_splits=10)
    trial_sharpes = [_sharpe(rets[c]) for c in cand]
    # brazo seleccionado = mejor Sharpe anualizado entre los que pasan local
    eligibles = [c for c in cand if c != BASELINE_ARM and summaries[c]["passes_local"]]
    ranked = sorted(cand, key=lambda c: summaries[c]["sharpe"] or -9e9, reverse=True)
    selected = next((c for c in ranked if c in eligibles), None)
    dsr = None
    if selected is not None:
        sk, ku = _skew_kurt(rets[selected])
        dsr = deflated_sharpe_ratio(
            trial_sharpes, n_obs=T, selected=_sharpe(rets[selected]), skew=sk, kurtosis=ku
        )

    ship = selected is not None and dsr is not None and dsr.deflated_sharpe > 0.5 and pbo.pbo < 0.5

    ctx: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_entries": len(entries),
        "n_tickers": len(bars_by),
        "max_positions": args.max_positions,
        "capital": args.capital,
        "risk_off_share": n_off / len(spy),
        "pbo": pbo.pbo,
        "pbo_n_combos": pbo.n_combos,
        "dsr_obs": T,
        "selected_arm": selected,
        "deflated_sharpe": (dsr.deflated_sharpe if dsr else None),
        "expected_max_sharpe": (dsr.expected_max_sharpe if dsr else None),
        "ship": ship,
        "kill_criteria": {
            "min_dsharpe": KILL_MIN_DSHARPE,
            "min_dcagr": KILL_MIN_DCAGR,
            "sizing_dd_mult": KILL_SIZING_DD_MULT,
        },
    }

    if args.json:
        print(
            json.dumps(
                {"context": ctx, "summaries": list(summaries.values()), "oracle": oracle_sum},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    def _f(x, w=8, p=2, suf=""):
        return f"{'—':>{w}}" if x is None else f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"

    def _ddx(s: dict) -> str:
        v = s.get("dd_ratio")
        return "—" if v in (None, float("inf")) else f"{v:.2f}"

    def _local(s: dict) -> str:
        pl = s.get("passes_local")
        return "" if pl is None else ("SI" if pl else "no")

    hdr = (
        f"{'brazo':<18}{'CAGR':>9}{'Sharpe':>9}{'ΔSh':>8}{'ΔCAGR':>9}"
        f"{'maxDD':>8}{'DDx':>7}{'tomad':>7}{'expos':>7}{'local':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for name in CANDIDATE_ARMS:
        s = summaries[name]
        print(
            f"{name:<18}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9, 2)}"
            f"{_f(s.get('delta_sharpe'), 8, 2)}{_f(s.get('delta_cagr'), 9, 2, '%')}"
            f"{_f(s['max_dd'], 8, 1, '%')}{_ddx(s):>7}"
            f"{s['n_taken']:>7}{_f(s['exposure'], 7, 0, '%')}{_local(s):>7}"
        )
    o = oracle_sum
    print(
        f"{ORACLE_ARM:<18}{_f(o['cagr'], 9, 2, '%')}{_f(o['sharpe'], 9, 2)}"
        f"{_f(o.get('delta_sharpe'), 8, 2)}{_f(o.get('delta_cagr'), 9, 2, '%')}"
        f"{_f(o['max_dd'], 8, 1, '%')}{'—':>7}{o['n_taken']:>7}{_f(o['exposure'], 7, 0, '%')}{'val':>7}"
    )

    if args.live_gates:
        # No es decorativo: un gate que no bloquea nada no esta midiendo su eje, y
        # que los siete bloqueen DISTINTO refutaria el §3 del doc de la tarea 36.
        print("\nGates de re-entrada (tarea 115) — bloqueos por brazo:")
        for name in CANDIDATE_ARMS:
            s = summaries[name]
            print(f"  {name:<18} Gate 5: {s['n_gate5_blocked']:>5}   Gate 5b: {s['n_gate5b_blocked']:>5}")
        g5 = {summaries[n]["n_gate5_blocked"] for n in CANDIDATE_ARMS}
        g5b = {summaries[n]["n_gate5b_blocked"] for n in CANDIDATE_ARMS}
        muerden = bool(g5 - {0})
        mismo = len(g5) == 1 and len(g5b) == 1
        print(f"  [{'OK  ' if muerden else 'FALLA'}] los gates muerden (§5.4 del pre-registro)")
        print(
            f"  [{'OK  ' if mismo else 'FALLA'}] los siete bloquean el MISMO conjunto "
            f"(§5.5 — la prediccion falsable de la tarea 36)"
        )

    print("\nInvariantes (deben pasar ANTES de leer el veredicto):")
    for name in CANDIDATE_ARMS:
        s = summaries[name]
        inv = "OK" if s.get("exit_invariant_ok", True) else "ROTO"
        acc = "OK" if s["accounting_ok"] else f"DESVÍO {s['accounting_dev']:.2e}"
        print(f"  {name:<18} exits: {inv:<5} contab: {acc}")

    print("\nPor régimen — Tarea 120. `ret medio/trade` NO discrimina brazos que sólo")
    print("cambian el TAMAÑO (mismos trades); el criterio 4 se evalúa sobre `pnl pts`,")
    print("que es el P/L de esa ventana en puntos del capital inicial.")
    anchos = "  {:<20}" + "{:>22}" * len(_REG_NAMES)
    print(anchos.format("brazo", *_REG_NAMES))
    for name in CANDIDATE_ARMS:
        s = summaries[name]
        celdas = [
            f"{s['by_regime'][n]['pnl_pts']:>+8.2f}pp  ret{s['by_regime'][n]['mean_ret_pts']:>+6.2f}"
            for n in _REG_NAMES
        ]
        print(anchos.format(name, *celdas))

    print("\n  ¿la métrica distingue este brazo del baseline?")
    for name in CANDIDATE_ARMS:
        if name == BASELINE_ARM:
            continue
        d = summaries[name].get("regime_discriminates") or {}
        est = "sí" if d.get("mean_ret_pts") else "NO — tabla idéntica al baseline"
        print(f"    {name:<20} ret medio/trade: {est:<32} pnl pts: {'sí' if d.get('pnl_pts') else 'NO'}")

    print("\n  C4 (§5.4) — el beneficio no puede venir de UNA sola ventana:")
    for name in CANDIDATE_ARMS:
        if name == BASELINE_ARM:
            continue
        s = summaries[name]
        marca = "PASA " if s.get("regime_ok") else "FALLA"
        solo = (s.get("regime_c4") or {}).get("solo_en")
        motivo = f" — positivo SÓLO en {solo}" if solo else ""
        print(f"    [{marca}] {name}{motivo}")

    print(f"\nDescuento por selección múltiple ({len(cand)} brazos, T={T} obs):")
    print(f"  PBO (CSCV) = {pbo.pbo:.3f}  ({pbo.n_combos} combinaciones)")
    if dsr is not None:
        print(f"  brazo seleccionado = {selected}")
        print(
            f"  DSR = {dsr.deflated_sharpe:.3f}  (SR0 esperado bajo el nulo = {dsr.expected_max_sharpe:.4f})"
        )
    else:
        print("  ningún brazo pasa el filtro local → no hay nada que deflactar")
    print(f"\n  VEREDICTO: {'SHIP' if ship else 'NO-SHIP'}  (requiere brazo local-OK con DSR>0.5 y PBO<0.5)")
    print(
        f"\nKill-criteria: (ΔSharpe ≥ +{KILL_MIN_DSHARPE} O ΔCAGR ≥ +{100 * KILL_MIN_DCAGR:.0f}pp)"
        f"  Y  (maxDD no sube [régimen] / DDx ≤ {KILL_SIZING_DD_MULT} [sizing])"
        f"  Y  DSR>0.5 Y PBO<0.5  Y  no depende de un solo régimen"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
