"""Tarea 458 — EARNINGS-BLACKOUT-SIN-MEDIR: el Gate 6 modelado, con y sin, fuera de muestra.

Pre-registro congelado: ``docs/blackout_prereg_t458_2026-11-25.md``. Los brazos (§3), el gate (§4,
los umbrales de la T170) y los sanity (§5) son los de ahí.

- ``vivo`` y ``sin_bloqueo``: la config de la T170 con el costo del vivo (468) y la tajada por día
  (464); el primero con ``entry_filter=filtro_de_balances(fechas, 2)``.
- El marco de la cuenta (régimen a ×0,25 y overlay de σ), descriptivo.
- ``sin_bloqueo_harness``: al costo de ``CostModel()``, tiene que reproducir la T170.

Las fechas salen de ``data/earnings_dates/fechas_balance.json`` (``scripts/bajar_fechas_balance_t458.py``).

Comando::

    python scripts/run_blackout_t458.py --allow-stale-artifacts --cache-dir .cache/t458
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from analysis.earnings_sim import ALMACEN, cargar_fechas, componer, filtro_de_balances
from analysis.exit_replay import max_drawdown
from analysis.harness_config import (
    LIVE_COST_PER_SIDE,
    LIVE_EARNINGS_BLACKOUT_DAYS,
    LIVE_MAX_POSITIONS,
    LIVE_REGIME_SCALE_FACTOR,
    LIVE_TRAIL_MULT,
    LIVE_UNIVERSE_FILE,
    LIVE_VOL_TARGET_ANNUAL,
    POPULATION_LIVE_ACCT2,
    SignalStoreGapError,
    StaleArtifactError,
    announce,
    announce_artifacts,
    announce_signal_store,
    artifact_window,
    live_cost_model,
    universe_fingerprint,
)
from analysis.market_regime import build_regime_series, make_entry_filter
from analysis.overlay_sim import OverlayDeVolatilidad
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import cagr
from analysis.scaleout_replay import CostModel
from analysis.walkforward_power import paired_block_bootstrap
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_activo_pasivo_t456 import (
    CALIBRACION_HASTA,
    OOS_DESDE,
    OOS_HASTA,
    cortar,
    metricas,
    retornos_diarios,
)
from scripts.run_exit_policy_t170 import (
    BOOT_BLOCK,
    BOOT_RESAMPLES,
    BOOT_SEED,
    D1_MIN_DCAGR_OOS,
    D2_MIN_FOLDS,
    D3_TAIL_TOL_PTS,
    D5_DD_TOL,
)
from scripts.run_market_regime_r2 import load_spy_bars
from scripts.run_signal_exit_delay_t219 import BASELINE as T219_BASELINE
from scripts.run_signal_exit_delay_t219 import _common_kwargs, _so_params, reproduce_t170
from scripts.run_stop_cal_replay_t26 import NO_STOP, summarise
from scripts.run_stop_value_t37 import CAP_DAYS, EVAL_MODE, FILL_MODE, FOLDS, LIVE_GATES, SimCache, tail_stats
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals
from scripts.run_vol_overlay_t457 import alinear

# ── Brazos (CONGELADOS — §3) ─────────────────────────────────────────────────
VIVO = "vivo"
SIN = "sin_bloqueo"
VIVO_C = "vivo_cuenta"
SIN_C = "sin_bloqueo_cuenta"
SIN_H = "sin_bloqueo_harness"

SACAR = "SACAR EL BLOQUEO"
RESTA = "EL BLOQUEO RESTA, PERO NO ALCANZA"
NO_MOVER = "NO MOVER"

# ── Sanity (§5) ──────────────────────────────────────────────────────────────
ANCLA_468 = (13.72, 0.79)  # `sin_bloqueo` al costo del vivo, CAGR % y Sharpe
COBERTURA_MIN = 0.90
COHORTE_DESDE = "2016-09-12"
SUPRIMIDAS_MIN, SUPRIMIDAS_MAX = 0.02, 0.25


# ── Piezas puras ─────────────────────────────────────────────────────────────


def cobertura_del_almacen(
    fechas: dict[str, list[str]], tickers: list[str], desde: str = COHORTE_DESDE
) -> dict:
    """§5.2 — fracción de tickers con fechas, y de ésos, con una fecha anterior a ``desde``."""
    con = [t for t in tickers if fechas.get(t)]
    antes = [t for t in con if fechas[t][0] < desde]
    f_con = len(con) / len(tickers) if tickers else 0.0
    f_antes = len(antes) / len(con) if con else 0.0
    return {
        "tickers": len(tickers),
        "con_fechas": len(con),
        "con_fechas_antes": len(antes),
        "frac_con": f_con,
        "frac_antes": f_antes,
        "sin_fechas": sorted(set(tickers) - set(con)),
        "ok": bool(f_con >= COBERTURA_MIN and f_antes >= COBERTURA_MIN),
    }


def evaluar_gate(
    vivo: PortfolioResult, sin: PortfolioResult, *, resamples: int = BOOT_RESAMPLES
) -> dict[str, Any]:
    """§4 — las cinco condiciones de la T170, con los brazos cortados de una sola corrida y el
    bootstrap sobre los retornos OOS (la misma muestra que D1)."""
    v_al, s_al, cob = alinear(vivo.equity_curve, sin.equity_curve)
    oos_v, oos_s = cortar(v_al, OOS_DESDE, OOS_HASTA), cortar(s_al, OOS_DESDE, OOS_HASTA)
    is_v, is_s = cortar(v_al, None, CALIBRACION_HASTA), cortar(s_al, None, CALIBRACION_HASTA)
    d_cagr = cagr(oos_s) - cagr(oos_v)
    folds = []
    for _train_end, lo, hi in FOLDS:
        cv, cs = cagr(cortar(v_al, lo, hi)), cagr(cortar(s_al, lo, hi))
        folds.append({"test": f"{lo}..{hi}", "vivo": cv, "sin": cs, "delta_pp": 100.0 * (cs - cv)})
    ganados = sum(1 for f in folds if f["delta_pp"] > 0.0)
    tv, ts = tail_stats(vivo), tail_stats(sin)
    d_worst, d_p1 = ts["worst"] - tv["worst"], ts["p1"] - tv["p1"]
    boot = paired_block_bootstrap(
        [r for _, r in retornos_diarios(oos_v)],
        [r for _, r in retornos_diarios(oos_s)],
        block=BOOT_BLOCK,
        n_resamples=resamples,
        seed=BOOT_SEED,
    )
    dd_is = max_drawdown(is_s) - max_drawdown(is_v)
    dd_oos = max_drawdown(oos_s) - max_drawdown(oos_v)
    c = {
        "D1": d_cagr >= D1_MIN_DCAGR_OOS,
        "D2": ganados >= D2_MIN_FOLDS,
        "D3": d_worst >= -D3_TAIL_TOL_PTS and d_p1 >= -D3_TAIL_TOL_PTS,
        "D4": boot.ci_low > 0.0,
        "D5": dd_is <= D5_DD_TOL and dd_oos <= D5_DD_TOL,
    }
    if all(c.values()):
        veredicto = SACAR
    elif c["D1"]:
        veredicto = RESTA
    else:
        veredicto = NO_MOVER
    return {
        "dcagr_oos": d_cagr,
        "cagr_oos_vivo": cagr(oos_v),
        "cagr_oos_sin": cagr(oos_s),
        "folds": folds,
        "folds_ganados": ganados,
        "tail_worst_delta": d_worst,
        "tail_p1_delta": d_p1,
        "boot": {
            "observed": boot.observed,
            "ci_low": boot.ci_low,
            "ci_high": boot.ci_high,
            "p_value": boot.p_value,
        },
        "dd_delta_is": dd_is,
        "dd_delta_oos": dd_oos,
        "cobertura": cob,
        "condiciones": c,
        "veredicto": veredicto,
    }


def lo_que_se_pierde(sin: PortfolioResult, filtro) -> dict[str, Any]:
    """§6 — en ``sin_bloqueo``, el retorno de los trades que el gate habría suprimido contra el
    de los demás."""
    tocados = [t.ret for t in sin.trades if filtro(t.ticker, t.entry_date) <= 0.0]
    otros = [t.ret for t in sin.trades if filtro(t.ticker, t.entry_date) > 0.0]
    return {
        "n_tocados": len(tocados),
        "n_otros": len(otros),
        "ret_medio_tocados": statistics.fmean(tocados) if tocados else None,
        "ret_medio_otros": statistics.fmean(otros) if otros else None,
    }


def evaluar_sanity(
    sum_h: dict, sum_sin: dict, cob: dict, vivo: PortfolioResult, cobertura_cal: float
) -> dict:
    """§5 — reproducción, cobertura del almacén, el gate muerde, calendario."""
    repro = reproduce_t170(sum_h)
    vivo_468 = (round(sum_sin["cagr"] * 100.0, 2), round(sum_sin["sharpe"], 2))
    suprimidas = vivo.n_filtered / vivo.n_offered if vivo.n_offered else 0.0
    s = {
        "repro_t170": repro,
        "sin_al_costo_del_vivo": vivo_468,
        "ok_468": vivo_468 == ANCLA_468,
        "cobertura": cob,
        "suprimidas": suprimidas,
        "muerde_ok": bool(SUPRIMIDAS_MIN <= suprimidas <= SUPRIMIDAS_MAX),
        "calendario": cobertura_cal,
        "calendario_ok": bool(cobertura_cal >= 0.99),
    }
    s["VALIDA"] = bool(repro["OK"] and s["ok_468"] and cob["ok"] and s["muerde_ok"] and s["calendario_ok"])
    return s


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EARNINGS-BLACKOUT-SIN-MEDIR (tarea 458)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--almacen", default=str(ALMACEN))
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--allow-stale-artifacts", action="store_true")
    p.add_argument("--json", default=None, help="ruta donde dejar el resultado en JSON")
    args = p.parse_args(argv)
    cache = SimCache(Path(args.cache_dir) if args.cache_dir else None, None)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    fechas, meta = cargar_fechas(_HERE.parent / args.almacen)
    cob = cobertura_del_almacen(fechas, tickers)
    print(
        f"Almacén: {args.almacen} · capturado {meta.get('capturado')} · {cob['con_fechas']}/{cob['tickers']} "
        f"tickers con fechas, {cob['con_fechas_antes']} desde antes del {COHORTE_DESDE}"
    )
    bars_by, sigs_by, missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)
    entries = buy_entries(bars_by, sigs_by, args.warmup)
    esperado, actual = POPULATION_LIVE_ACCT2.tickers_fp, universe_fingerprint(args.universe)
    print(f"Población: {args.universe} · huella {actual} (pre-registro: {esperado})")
    if esperado and actual and actual != esperado:
        print(
            f"*** ABORTA — la población NO es la del pre-registro: {actual} contra {esperado} ***",
            file=sys.stderr,
        )
        return 4
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts)
        announce_signal_store(bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts)
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3
    spy_bars = load_spy_bars("max")
    if not spy_bars:
        print("*** ABORTA — sin SPY__max__1d en el cache ***", file=sys.stderr)
        return 1

    window = artifact_window(bars_by)
    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=window,
        eval_mode=EVAL_MODE,
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
        atr_stop_mult=NO_STOP,
        atr_trail_mult=LIVE_TRAIL_MULT,
        models_earnings_blackout=True,
        tajada_del_dia=True,
        costo_por_lado=LIVE_COST_PER_SIDE,
    )
    print(
        "(El banner es el de los brazos del gate: Gate 6 modelado, sin régimen ni overlay, costo del vivo. "
        "El marco de la cuenta va en el descriptivo.)\n"
    )

    run_tag = f"{window}|n{len(bars_by)}|e{len(entries)}|mp{args.max_positions}|cap{args.cap_days}|${args.capital:.2f}"
    base = {**_common_kwargs(args), "so_params": _so_params(T219_BASELINE), "tajada_del_dia": True}
    vivo_kw = {**base, "costs": live_cost_model()}
    bloqueo = filtro_de_balances(fechas, LIVE_EARNINGS_BLACKOUT_DAYS)
    regimen = make_entry_filter(build_regime_series(spy_bars), mode="scale", factor=LIVE_REGIME_SCALE_FACTOR)
    tag = f"t458|d{LIVE_EARNINGS_BLACKOUT_DAYS}|{meta.get('capturado')}|{run_tag}"

    def _ov() -> OverlayDeVolatilidad:
        return OverlayDeVolatilidad(bars_by, objetivo=LIVE_VOL_TARGET_ANNUAL)

    corridas = {
        SIN_H: lambda: simulate_portfolio(entries, bars_by, sigs_by, **{**base, "costs": CostModel()}),
        SIN: lambda: simulate_portfolio(entries, bars_by, sigs_by, **vivo_kw),
        VIVO: lambda: simulate_portfolio(entries, bars_by, sigs_by, entry_filter=bloqueo, **vivo_kw),
        SIN_C: lambda: simulate_portfolio(
            entries, bars_by, sigs_by, entry_filter=regimen, vol_overlay=_ov(), **vivo_kw
        ),
        VIVO_C: lambda: simulate_portfolio(
            entries, bars_by, sigs_by, entry_filter=componer(regimen, bloqueo), vol_overlay=_ov(), **vivo_kw
        ),
    }
    res: dict[str, PortfolioResult] = {}
    for nombre, fn in corridas.items():
        print(f"  corriendo {nombre}…", flush=True)
        res[nombre] = cache.run(f"{tag}|{nombre}", fn)

    _a, _b, cob_cal = alinear(res[VIVO].equity_curve, res[SIN].equity_curve)
    sanity = evaluar_sanity(summarise(res[SIN_H]), summarise(res[SIN]), cob, res[VIVO], cob_cal)
    r = sanity["repro_t170"]
    print("\nSanity (§5):")
    print(
        f"  1. sin bloqueo al costo del harness: {r['cagr']:.2%} / {r['sharpe']:.2f} / {r['n_taken']} "
        f"({'OK' if r['OK'] else 'FALLA'}); al del vivo {sanity['sin_al_costo_del_vivo']} contra {ANCLA_468} "
        f"({'OK' if sanity['ok_468'] else 'FALLA'})"
    )
    print(
        f"  2. almacén: {cob['frac_con']:.1%} con fechas, {cob['frac_antes']:.1%} de ésos desde antes del "
        f"cohorte; sin fechas: {cob['sin_fechas']} ({'OK' if cob['ok'] else 'FALLA'})"
    )
    print(
        f"  3. el gate suprime el {sanity['suprimidas']:.2%} de las entradas ofrecidas "
        f"({res[VIVO].n_filtered} de {res[VIVO].n_offered}; rango {SUPRIMIDAS_MIN:.0%}–{SUPRIMIDAS_MAX:.0%}): "
        f"{'OK' if sanity['muerde_ok'] else 'FALLA'}"
    )
    print(f"  5. calendario: {cob_cal:.2%} ({'OK' if sanity['calendario_ok'] else 'FALLA'})")

    salida: dict[str, Any] = {"sanity": sanity, "almacen": meta}
    if not sanity["VALIDA"]:
        print("\n*** CORRIDA INVÁLIDA — no hay veredicto ***", file=sys.stderr)
        if args.json:
            Path(args.json).write_bytes(json.dumps(salida, indent=2, default=str).encode("utf-8"))
        return 2

    ev = evaluar_gate(res[VIVO], res[SIN], resamples=args.resamples)
    c, b = ev["condiciones"], ev["boot"]
    print(f"\nGate (§4), fuera de muestra {OOS_DESDE} → {OOS_HASTA} (sin bloqueo − vivo):")
    print(
        f"  D1 ΔCAGR OOS {100 * ev['dcagr_oos']:+.2f} pp ({ev['cagr_oos_sin']:.2%} contra {ev['cagr_oos_vivo']:.2%}): "
        f"{'pasa' if c['D1'] else 'no'}"
    )
    print(f"  D2 folds ganados {ev['folds_ganados']}/5: {'pasa' if c['D2'] else 'no'}")
    print(
        f"  D3 cola Δpeor {ev['tail_worst_delta']:+.2f} / Δp1 {ev['tail_p1_delta']:+.2f} pp: {'pasa' if c['D3'] else 'no'}"
    )
    print(
        f"  D4 IC95% [{100 * b['ci_low']:+.2f}, {100 * b['ci_high']:+.2f}] pp p={b['p_value']:.3f}: {'pasa' if c['D4'] else 'no'}"
    )
    print(
        f"  D5 Δcaída dentro {100 * ev['dd_delta_is']:+.2f} / fuera {100 * ev['dd_delta_oos']:+.2f} pp: "
        f"{'pasa' if c['D5'] else 'no'}"
    )
    print(f"\n  VEREDICTO: {ev['veredicto']}")

    print("\nDescriptivo (§6):")
    for f in ev["folds"]:
        print(f"  fold {f['test']}: vivo {f['vivo']:.2%} · sin {f['sin']:.2%} · Δ {f['delta_pp']:+.2f} pp")
    print(f"\n  {'muestra completa':<22}{'CAGR':>8}{'Sharpe':>8}{'caída':>8}{'trades':>8}{'suprim.':>9}")
    for n in (VIVO, SIN, VIVO_C, SIN_C, SIN_H):
        m = metricas(res[n].equity_curve)
        print(
            f"  {n:<22}{m['cagr']:>8.2%}{(m['sharpe'] or 0.0):>8.2f}{m['max_dd']:>8.1%}"
            f"{len(res[n].trades):>8}{res[n].n_filtered:>9}"
        )
    perdida = lo_que_se_pierde(res[SIN], bloqueo)
    if perdida["ret_medio_tocados"] is not None:
        print(
            f"\n  En `sin_bloqueo`, los {perdida['n_tocados']} trades que el gate habría suprimido rinden "
            f"{100 * perdida['ret_medio_tocados']:+.2f}% en promedio, contra {100 * perdida['ret_medio_otros']:+.2f}% "
            f"de los otros {perdida['n_otros']}"
        )
    ev_c = evaluar_gate(res[VIVO_C], res[SIN_C], resamples=args.resamples)
    bc = ev_c["boot"]
    print(
        f"\n  El marco de la cuenta (régimen ×{LIVE_REGIME_SCALE_FACTOR:g} y overlay): ΔCAGR OOS "
        f"{100 * ev_c['dcagr_oos']:+.2f} pp, {ev_c['folds_ganados']}/5 folds, IC [{100 * bc['ci_low']:+.2f}, "
        f"{100 * bc['ci_high']:+.2f}] · la misma lectura daría: {ev_c['veredicto']}"
    )

    salida.update({"gate": ev, "cuenta": ev_c, "lo_que_se_pierde": perdida})
    if args.json:
        Path(args.json).write_bytes(json.dumps(salida, indent=2, default=str).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
