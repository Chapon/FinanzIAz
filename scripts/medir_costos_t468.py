"""Tarea 468 — los mismos brazos con el costo del vivo, el del harness y cero (DESCRIPTIVO).

El harness cobra 0,15% por lado (``CostModel()``) y el vivo ~0,063% (IBKR Pro Tiered + slippage,
``analysis.harness_config.live_cost_model()``). Con la rotación de la estrategia (~26× el capital
por año) esa diferencia mueve el nivel de todo y el signo de algunas comparaciones. Este script
pone lado a lado, en el marco de la cuenta (cohorte de la 456, 10 slots, salida viva, tajada por día
de la 464):

- la estrategia sin régimen y la de la cuenta (régimen ×0,25);
- el pasivo de la 456 (SPY + caja, con la ``w`` por su regla) y su gate;
- el régimen contra la caja constante a la misma caída (``caja_hasta_la_caida`` de la 464).

**No decide nada:** no hay pre-registro. Corrige el instrumento con que se van a medir la 457, la
465 y la 458, y los números que hoy se citan como el precio de la cuenta.

Sanity duro, al costo del harness: el brazo sin régimen reproduce la T170 (8,78% / 0,55 / 2531) y el
de la cuenta reproduce la 464 (6,41%).

Comando::

    python scripts/medir_costos_t468.py --allow-stale-artifacts --cache-dir .cache/t468
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import max_drawdown
from analysis.harness_config import (
    HARNESS_DEFAULT_COST_PER_SIDE,
    LIVE_COST_PER_SIDE,
    LIVE_MAX_POSITIONS,
    LIVE_REGIME_SCALE_FACTOR,
    LIVE_TRAIL_MULT,
    LIVE_UNIVERSE_FILE,
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
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.scaleout_replay import CostModel
from scripts.medir_tajada_t464 import caja_hasta_la_caida
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
from scripts.run_market_regime_r2 import load_spy_bars
from scripts.run_signal_exit_delay_t219 import BASELINE as T219_BASELINE
from scripts.run_signal_exit_delay_t219 import _common_kwargs, _so_params, reproduce_t170
from scripts.run_stop_cal_replay_t26 import NO_STOP, summarise
from scripts.run_stop_value_t37 import CAP_DAYS, EVAL_MODE, FILL_MODE, LIVE_GATES, SimCache
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

CERO, VIVO, HARNESS = "cero", "vivo", "harness"
ANCLA_464_CAGR_PCT = 6.41  # el brazo de la cuenta en la 464, al costo del harness


def niveles_de_costo() -> dict[str, CostModel]:
    """Los tres costos, en el orden en que se imprimen. El del harness es el de todo lo publicado."""
    return {CERO: CostModel(commission=0.0, slippage=0.0), VIVO: live_cost_model(), HARNESS: CostModel()}


def costo_por_lado(cm: CostModel) -> float:
    return cm.commission + cm.slippage


def evaluar_sanity(sin_harness: PortfolioResult, vivo_harness: PortfolioResult) -> dict[str, Any]:
    """Al costo del harness, el instrumento tiene que dar lo publicado."""
    repro = reproduce_t170(summarise(sin_harness))
    cagr_464 = round(metricas(vivo_harness.equity_curve)["cagr"] * 100.0, 2)
    return {
        "repro_t170": repro,
        "cagr_464": cagr_464,
        "ok_464": cagr_464 == ANCLA_464_CAGR_PCT,
        "VALIDA": bool(repro["OK"] and cagr_464 == ANCLA_464_CAGR_PCT),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="COSTOS-DEL-HARNESS (tarea 468): los brazos con tres costos")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=2000)
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--allow-stale-artifacts", action="store_true")
    args = p.parse_args(argv)
    cache = SimCache(Path(args.cache_dir) if args.cache_dir else None, None)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)
    entries = buy_entries(bars_by, sigs_by, args.warmup)
    esperado, actual = POPULATION_LIVE_ACCT2.tickers_fp, universe_fingerprint(args.universe)
    print(f"Población: {args.universe} · huella {actual} (la de la 456: {esperado})")
    if esperado and actual and actual != esperado:
        print(
            f"*** ABORTA — la población NO es la de la 456: {actual} contra {esperado} ***", file=sys.stderr
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
        models_regime_scale=True,
        tajada_del_dia=True,
        costo_por_lado=LIVE_COST_PER_SIDE,
    )
    print(
        f"(El banner es el del costo del vivo; los brazos al {100 * HARNESS_DEFAULT_COST_PER_SIDE:.2f}% "
        "y a costo cero difieren sólo en eso.)\n"
    )

    run_tag = f"{window}|n{len(bars_by)}|e{len(entries)}|mp{args.max_positions}|cap{args.cap_days}|${args.capital:.2f}"
    filtro = make_entry_filter(build_regime_series(spy_bars), mode="scale", factor=LIVE_REGIME_SCALE_FACTOR)
    spy_c = {b[0]: b[4] for b in spy_bars}
    res: dict[str, dict[str, PortfolioResult]] = {}
    for nombre, cm in niveles_de_costo().items():
        common = {
            **_common_kwargs(args),
            "so_params": _so_params(T219_BASELINE),
            "costs": cm,
            "tajada_del_dia": True,
        }
        tag = f"t468|{nombre}|{costo_por_lado(cm):.6f}|{run_tag}"
        print(f"  corriendo costo {nombre}…", flush=True)
        res[nombre] = {
            "sin": cache.run(
                f"{tag}|sin", lambda common=common: simulate_portfolio(entries, bars_by, sigs_by, **common)
            ),
            "vivo": cache.run(
                f"{tag}|vivo",
                lambda common=common: simulate_portfolio(
                    entries, bars_by, sigs_by, entry_filter=filtro, **common
                ),
            ),
        }

    sanity = evaluar_sanity(res[HARNESS]["sin"], res[HARNESS]["vivo"])
    r = sanity["repro_t170"]
    print("\nSanity, al costo del harness:")
    print(
        f"  1. reproduce la T170: {r['cagr']:.2%} / {r['sharpe']:.2f} / {r['n_taken']} contra "
        f"{r['cagr_t170']:.2%} / {r['sharpe_t170']:.2f} / {r['n_taken_t170']}: {'OK' if r['OK'] else 'FALLA'}"
    )
    print(
        f"  2. reproduce la 464: {sanity['cagr_464']:.2f}% contra {ANCLA_464_CAGR_PCT:.2f}%: "
        f"{'OK' if sanity['ok_464'] else 'FALLA'}"
    )
    if not sanity["VALIDA"]:
        print("*** CORRIDA INVÁLIDA — la tabla no se lee ***", file=sys.stderr)
        return 2

    print(
        f"\n{'costo':<9}{'por lado':>9}  {'brazo':<16}{'CAGR':>8}{'Sharpe':>8}{'caída':>8}{'trades':>8}{'expos.':>8}"
    )
    for nombre, cm in niveles_de_costo().items():
        for brazo in ("sin", "vivo"):
            rr = res[nombre][brazo]
            mm = metricas(rr.equity_curve)
            etiqueta = "sin régimen" if brazo == "sin" else "régimen ×0,25"
            print(
                f"{nombre:<9}{costo_por_lado(cm):>9.4%}  {etiqueta:<16}{mm['cagr']:>8.2%}{mm['sharpe']:>8.2f}"
                f"{mm['max_dd']:>8.1%}{len(rr.trades):>8}{exposicion_media(rr, bars_by):>8.1%}"
            )

    print("\nEl pasivo de la 456 y su gate, con cada costo:")
    for nombre, cm in niveles_de_costo().items():
        viv = res[nombre]["vivo"]
        costo = costo_por_lado(cm)
        cal = [d for d, _ in viv.equity_curve]
        spy = serie_en_calendario(cal, spy_c)
        dd_obj = max_drawdown(cortar(viv.equity_curve, None, CALIBRACION_HASTA))
        w = w_por_regla(
            dd_obj, [d for d in cal if d <= CALIBRACION_HASTA], spy, costo=costo, capital=args.capital
        )
        if w is None:
            print(f"  {nombre:<9} ninguna w cumple la regla")
            continue
        pas = mezcla_constante(cal, spy, w, costo=costo, capital=args.capital)
        ev = evaluar(viv.equity_curve, pas, resamples=args.resamples)
        mp, b = metricas(pas), ev["boot"]
        print(
            f"  {nombre:<9} SPY+caja w={w:.2f}: {mp['cagr']:.2%} / {mp['sharpe']:.2f} / {mp['max_dd']:.1%} · "
            f"gate {ev['veredicto']}: ΔCAGR OOS {ev['dcagr_oos'] * 100:+.2f} pp "
            f"({ev['cagr_oos_pasivo']:.2%} contra {ev['cagr_oos_vivo']:.2%}), {ev['folds_gana_pasivo']}/5, "
            f"IC [{b['ci_low'] * 100:+.2f}, {b['ci_high'] * 100:+.2f}] p={b['p_value']:.3f}, "
            f"caída OOS {ev['dd_oos_pasivo']:.1%} contra {ev['dd_oos_vivo']:.1%}"
        )

    print("\nEl régimen contra la caja constante a la misma caída:")
    for nombre, cm in niveles_de_costo().items():
        mv = metricas(res[nombre]["vivo"].equity_curve)
        w, curva = caja_hasta_la_caida(
            res[nombre]["sin"].equity_curve, mv["max_dd"], costo=costo_por_lado(cm), capital=args.capital
        )
        if curva is None:
            print(f"  {nombre:<9} ninguna w llega a {mv['max_dd']:.1%}")
            continue
        mc = metricas(curva)
        print(
            f"  {nombre:<9} caída {mv['max_dd']:.1%}: caja w={w:.2f} {mc['cagr']:.2%} / {mc['sharpe']:.2f} / "
            f"{mc['max_dd']:.1%} · régimen {mv['cagr']:.2%} / {mv['sharpe']:.2f} · régimen − caja "
            f"{(mv['cagr'] - mc['cagr']) * 100:+.2f} pp"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
