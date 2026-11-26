"""Tarea 473 — los veredictos de la semana, releídos con el orden de candidatos del vivo (DESCRIPTIVO).

Todos los runners desde la T170 corren ``simulate_portfolio`` sin ``rank_score``: los candidatos de
cada día se procesan en orden **alfabético**. El vivo los ordena por ``ml_probability``
(``analysis.orden_del_dia.orden_del_vivo``). Con ~56 candidatos por día para 10 lugares, el orden
decide quién entra, y en la 471 un Δ entre brazos cambió de signo al cambiarlo.

Este script relee, con el pre-registro de cada uno sin tocar y con su misma función de evaluación,
los cuatro veredictos que deciden algo de la cuenta:

- la **456** (la estrategia contra SPY + caja), con el costo del vivo y la tajada (el marco de la 468);
- la **457** (el overlay de σ contra su caja equivalente);
- la **465** (el régimen contra su caja, en los dos sentidos);
- la **458** (el Gate 6).

**No re-decide nada.** Con el orden alfabético tiene que reproducir lo publicado (si no, la corrida
es inválida); con el del vivo, el baseline tiene que dar lo que midió la 471 (9,75% / 0,63). Si un
veredicto cambia, se le presenta a Chapa.

Comando::

    python scripts/releer_orden_t473.py --allow-stale-artifacts --cache-dir .cache/t473
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from analysis.earnings_sim import ALMACEN, cargar_fechas, filtro_de_balances
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
from analysis.orden_del_dia import ORDEN_ALFABETICO, ORDEN_VIVO, ORDENES, rank_del_orden
from analysis.overlay_sim import OverlayDeVolatilidad
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_activo_pasivo_t456 import (
    CALIBRACION_HASTA,
    cortar,
    evaluar,
    exposicion_media,
    metricas,
    mezcla_constante,
    serie_en_calendario,
    w_por_regla,
)
from scripts.run_blackout_t458 import evaluar_gate as evaluar_458
from scripts.run_market_regime_r2 import load_spy_bars
from scripts.run_ranking_t21 import load_bars_signals_scores
from scripts.run_regimen_caja_t465 import TRAMOS, evaluar_tramo
from scripts.run_regimen_caja_t465 import veredicto as veredicto_465
from scripts.run_signal_exit_delay_t219 import BASELINE as T219_BASELINE
from scripts.run_signal_exit_delay_t219 import _common_kwargs, _so_params
from scripts.run_stop_cal_replay_t26 import NO_STOP
from scripts.run_stop_value_t37 import CAP_DAYS, EVAL_MODE, FILL_MODE, LIVE_GATES, SimCache
from scripts.run_tp_cal_replay_t23 import buy_entries
from scripts.run_vol_overlay_t457 import alinear, w_caja_equivalente
from scripts.run_vol_overlay_t457 import evaluar_gate as evaluar_457

SIN, REG, OV, BLOQ = "sin", "regimen", "overlay", "bloqueo"

# Lo publicado, con el orden alfabético (la 468 para la 456; la 457, la 465 y la 458).
PUBLICADO = {
    "456": {"veredicto": "NO DECIDIBLE", "dcagr_oos_pp": 1.66},
    "457": {"veredicto": "NO-SHIP: NO SE DISTINGUE", "d_sharpe": -0.063},
    "465": {"veredicto": "DEPENDE DEL TRAMO", "w": {"A": 0.67, "B": 0.96}},
    "458": {"veredicto": "NO MOVER", "dcagr_oos_pp": 0.61},
}
ANCLA_BASE = {ORDEN_ALFABETICO: (13.72, 0.79), ORDEN_VIVO: (9.75, 0.63)}  # la 468 y la 471


def releer(res: dict[str, PortfolioResult], spy_c: dict[str, float], capital: float, resamples: int) -> dict:
    """Los cuatro veredictos sobre un juego de corridas (un orden)."""
    costo = LIVE_COST_PER_SIDE
    out: dict[str, Any] = {}

    # 456 — el vivo con régimen contra SPY + caja, w por la regla de calibración.
    viv = res[REG].equity_curve
    cal = [d for d, _ in viv]
    spy = serie_en_calendario(cal, spy_c)
    dd_obj = max_drawdown(cortar(viv, None, CALIBRACION_HASTA))
    w = w_por_regla(dd_obj, [d for d in cal if d <= CALIBRACION_HASTA], spy, costo=costo, capital=capital)
    if w is None:
        out["456"] = {"veredicto": "sin w", "w": None}
    else:
        ev = evaluar(viv, mezcla_constante(cal, spy, w, costo=costo, capital=capital), resamples=resamples)
        out["456"] = {
            "veredicto": ev["veredicto"],
            "dcagr_oos_pp": round(100.0 * ev["dcagr_oos"], 2),
            "ic_pp": (round(100.0 * ev["boot"]["ci_low"], 2), round(100.0 * ev["boot"]["ci_high"], 2)),
            "folds_pasivo": ev["folds_gana_pasivo"],
            "w": w,
        }

    # 457 — el overlay contra sin overlay y contra su caja equivalente.
    sin = res[SIN].equity_curve
    w457 = w_caja_equivalente(exposicion_media(res[OV], BARRAS), exposicion_media(res[SIN], BARRAS))
    caja = mezcla_constante([d for d, _ in sin], dict(sin), w457, costo=costo, capital=capital)
    ev = evaluar_457(res[OV].equity_curve, sin, caja, resamples=resamples)
    out["457"] = {
        "veredicto": ev["veredicto"],
        "d_sharpe": round(ev["d_sharpe"], 3),
        "ic": (round(ev["boot_sharpe"]["ci_low"], 3), round(ev["boot_sharpe"]["ci_high"], 3)),
        "sharpe_caja": round(ev["sharpe_caja"], 3),
        "w": round(w457, 3),
    }

    # 465 — el régimen contra su caja, en los dos sentidos.
    reg_al, sin_al, _ = alinear(res[REG].equity_curve, sin)
    tramos = [
        evaluar_tramo(reg_al, sin_al, t, costo=costo, capital=capital, resamples=resamples) for t in TRAMOS
    ]
    out["465"] = {
        "veredicto": veredicto_465({t["tramo"]: t.get("pasa", False) for t in tramos}),
        "w": {t["tramo"]: t["w"] for t in tramos},
        "pasa": {t["tramo"]: t.get("pasa") for t in tramos},
        "sharpe": {
            t["tramo"]: (round(t["regimen"]["sharpe"], 2), round(t["caja"]["sharpe"], 2))
            for t in tramos
            if t["w"]
        },
    }

    # 458 — sacar el Gate 6 contra dejarlo.
    ev = evaluar_458(res[BLOQ], res[SIN], resamples=resamples)
    out["458"] = {
        "veredicto": ev["veredicto"],
        "dcagr_oos_pp": round(100.0 * ev["dcagr_oos"], 2),
        "folds": ev["folds_ganados"],
        "ic_pp": (round(100.0 * ev["boot"]["ci_low"], 2), round(100.0 * ev["boot"]["ci_high"], 2)),
        "condiciones": ev["condiciones"],
    }
    return out


def reproduce(alfa: dict, base: tuple[float, float]) -> dict:
    """Con el orden alfabético, lo publicado: si no, la corrida es inválida."""
    chequeos = {
        "base": base == ANCLA_BASE[ORDEN_ALFABETICO],
        "456": alfa["456"].get("veredicto") == PUBLICADO["456"]["veredicto"]
        and alfa["456"].get("dcagr_oos_pp") == PUBLICADO["456"]["dcagr_oos_pp"],
        "457": alfa["457"]["veredicto"] == PUBLICADO["457"]["veredicto"]
        and alfa["457"]["d_sharpe"] == PUBLICADO["457"]["d_sharpe"],
        "465": alfa["465"]["veredicto"] == PUBLICADO["465"]["veredicto"]
        and alfa["465"]["w"] == PUBLICADO["465"]["w"],
        "458": alfa["458"]["veredicto"] == PUBLICADO["458"]["veredicto"]
        and alfa["458"]["dcagr_oos_pp"] == PUBLICADO["458"]["dcagr_oos_pp"],
    }
    chequeos["VALIDA"] = all(chequeos.values())
    return chequeos


BARRAS: dict = {}  # lo llena main; `exposicion_media` necesita las barras para marcar a mercado


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ORDEN-DEL-DIA-SIN-DECLARAR (tarea 473), re-lectura")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=2000)
    p.add_argument("--almacen", default=str(ALMACEN))
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--allow-stale-artifacts", action="store_true")
    args = p.parse_args(argv)
    cache = SimCache(Path(args.cache_dir) if args.cache_dir else None, None)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    fechas, meta = cargar_fechas(_HERE.parent / args.almacen)
    bars_by, sigs_by, score_by, missing = load_bars_signals_scores(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)
    BARRAS.update(bars_by)
    entries = buy_entries(bars_by, sigs_by, args.warmup)
    esperado, actual = POPULATION_LIVE_ACCT2.tickers_fp, universe_fingerprint(args.universe)
    if esperado and actual and actual != esperado:
        print(
            f"*** ABORTA — la población no es la de la cuenta: {actual} contra {esperado} ***",
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
        tajada_del_dia=True,
        costo_por_lado=LIVE_COST_PER_SIDE,
    )
    print(
        "(Los brazos difieren del banner en el régimen, el overlay, el Gate 6 y el orden, según el veredicto.)\n"
    )

    run_tag = f"{window}|n{len(bars_by)}|e{len(entries)}|mp{args.max_positions}|cap{args.cap_days}|${args.capital:.2f}"
    base = {
        **_common_kwargs(args),
        "so_params": _so_params(T219_BASELINE),
        "tajada_del_dia": True,
        "costs": live_cost_model(),
    }
    regimen = make_entry_filter(build_regime_series(spy_bars), mode="scale", factor=LIVE_REGIME_SCALE_FACTOR)
    bloqueo = filtro_de_balances(fechas, LIVE_EARNINGS_BLACKOUT_DAYS)
    spy_c = {b[0]: b[4] for b in spy_bars}
    tag = f"t473|{meta.get('capturado')}|{run_tag}"

    lecturas: dict[str, dict] = {}
    bases: dict[str, tuple[float, float]] = {}
    for orden in ORDENES:
        rank = rank_del_orden(orden, score_by)
        brazos = {
            SIN: {},
            REG: {"entry_filter": regimen},
            OV: {"vol_overlay": OverlayDeVolatilidad(bars_by, objetivo=LIVE_VOL_TARGET_ANNUAL)},
            BLOQ: {"entry_filter": bloqueo},
        }
        res: dict[str, PortfolioResult] = {}
        for nombre, kw in brazos.items():
            print(f"  corriendo orden {orden} · {nombre}…", flush=True)
            res[nombre] = cache.run(
                f"{tag}|{orden}|{nombre}",
                lambda kw=kw, rank=rank: simulate_portfolio(
                    entries, bars_by, sigs_by, rank_score=rank, **kw, **base
                ),
            )
        m = metricas(res[SIN].equity_curve)
        bases[orden] = (round(m["cagr"] * 100.0, 2), round(m["sharpe"], 2))
        lecturas[orden] = releer(res, spy_c, args.capital, args.resamples)

    rep = reproduce(lecturas[ORDEN_ALFABETICO], bases[ORDEN_ALFABETICO])
    vivo_ok = bases[ORDEN_VIVO] == ANCLA_BASE[ORDEN_VIVO]
    print("\nSanity:")
    print(f"  base alfabético {bases[ORDEN_ALFABETICO]} (la 468: {ANCLA_BASE[ORDEN_ALFABETICO]})")
    for k in ("456", "457", "465", "458"):
        print(f"  {k} con el orden alfabético reproduce lo publicado: {'OK' if rep[k] else 'FALLA'}")
    print(
        f"  base con el orden del vivo {bases[ORDEN_VIVO]} (la 471: {ANCLA_BASE[ORDEN_VIVO]}): {'OK' if vivo_ok else 'FALLA'}"
    )
    if not (rep["VALIDA"] and vivo_ok):
        print("*** CORRIDA INVÁLIDA — la tabla no se lee ***", file=sys.stderr)
        for orden in ORDENES:
            print(f"\n{orden}: {lecturas[orden]}", file=sys.stderr)
        return 2

    print(f"\n{'veredicto':<6}{'orden alfabético (publicado)':<44}{'orden del vivo':<44}{'¿cambia?'}")
    for k in ("456", "457", "465", "458"):
        a, v = lecturas[ORDEN_ALFABETICO][k], lecturas[ORDEN_VIVO][k]
        print(
            f"{k:<6}{a['veredicto']:<44}{v['veredicto']:<44}{'SÍ' if a['veredicto'] != v['veredicto'] else 'no'}"
        )
    for orden in ORDENES:
        print(f"\nDetalle, orden {orden}:")
        for k in ("456", "457", "465", "458"):
            print(f"  {k}: {lecturas[orden][k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
