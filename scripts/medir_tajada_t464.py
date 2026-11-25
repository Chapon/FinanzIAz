"""Tarea 464 — el precio del escalado por régimen con la tajada por día (DESCRIPTIVO).

La 456 midió que el escalado a ×0,25 lleva la estrategia de 8,78% a 7,32% de CAGR (−1,46 pp) y
de 28,4% a 22,9% de caída. Lo midió con el sizing **secuencial** de ``simulate_portfolio``: cada
compra recibe ``cash / free_slots`` sobre la caja que dejó la anterior, así que lo que una
compra escalada no gasta agranda a la siguiente del mismo día. El motor vivo les da a todas las
compras del scan la misma tajada por el mismo factor. Este script corre los dos brazos de la 456
otra vez con ``tajada_del_dia=True`` y pone los cuatro lado a lado.

**No decide nada:** no hay pre-registro ni gate. Es la corrección de un número que ya está
publicado (el precio con que Chapa decide el factor), con el instrumento corregido.

Sanity duro, los dos tienen que dar OK para leer la tabla:

1. ``vivo_sin_regimen`` con la tajada por día es **idéntico bit a bit** al de la 456 (sin factor
   < 1, el modo nuevo no cambia nada; si cambiara, el instrumento estaría roto).
2. Ese brazo reproduce la T170 (**8,78% / 0,55 / 2531**).

Comando (el cache de la 456 trae los dos brazos viejos)::

    python scripts/medir_tajada_t464.py --allow-stale-artifacts --cache-dir .cache/t456
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import max_drawdown
from analysis.harness_config import (
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
    universe_fingerprint,
)
from analysis.market_regime import build_regime_series, make_entry_filter
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.scaleout_replay import CostModel
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_activo_pasivo_t456 import (
    VIVO,
    VIVO_SIN_REGIMEN,
    exposicion_media,
    metricas,
    mezcla_constante,
)
from scripts.run_market_regime_r2 import load_spy_bars
from scripts.run_signal_exit_delay_t219 import BASELINE as T219_BASELINE
from scripts.run_signal_exit_delay_t219 import _common_kwargs, _so_params, reproduce_t170
from scripts.run_stop_cal_replay_t26 import NO_STOP, summarise
from scripts.run_stop_value_t37 import CAP_DAYS, EVAL_MODE, FILL_MODE, LIVE_GATES, SimCache
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

SECUENCIAL = "secuencial (la 456)"
POR_DIA = "tajada por día"


def compras_escaladas_por_dia(res: PortfolioResult) -> dict[str, int]:
    """Cuántas compras escaladas comparten día. La tajada secuencial agranda desde la segunda
    compra escalada de un día: con una sola por día, las dos fórmulas coinciden."""
    por_dia = Counter(t.entry_date for t in res.trades if t.size_factor < 1.0)
    return {
        "escaladas": sum(por_dia.values()),
        "dias": len(por_dia),
        "no_primeras": sum(c - 1 for c in por_dia.values()),
        "max_por_dia": max(por_dia.values(), default=0),
    }


def invertido_medio_escaladas(res: PortfolioResult) -> float | None:
    """Monto medio de las compras escaladas, en la moneda de la simulación."""
    inv = [t.invested for t in res.trades if t.size_factor < 1.0]
    return sum(inv) / len(inv) if inv else None


def identicos(a: PortfolioResult, b: PortfolioResult) -> bool:
    """Bit a bit: mismos trades, misma curva, misma equity final."""
    return a.trades == b.trades and a.equity_curve == b.equity_curve and a.final_equity == b.final_equity


def precio(con: dict[str, Any], sin: dict[str, Any]) -> dict[str, float]:
    """Lo que el escalado le cambia a la estrategia: con régimen menos sin régimen."""
    return {
        "d_cagr_pp": (con["cagr"] - sin["cagr"]) * 100.0,
        "d_sharpe": con["sharpe"] - sin["sharpe"],
        "d_dd_pp": (con["max_dd"] - sin["max_dd"]) * 100.0,
    }


GRILLA_CAJA = tuple(round(0.50 + 0.01 * i, 2) for i in range(51))  # w en la estrategia: 0,50 … 1,00


def caja_hasta_la_caida(
    curva: list[tuple[str, float]], dd_objetivo: float, *, costo: float, capital: float
) -> tuple[float | None, list[tuple[str, float]] | None]:
    """La ``w`` más alta de la grilla cuya mezcla «estrategia + caja al 0%», rebalanceada cada
    mes (``mezcla_constante`` de la 456), no cae más que ``dd_objetivo``. Es la forma más simple
    de comprar la misma caída que compra el escalado, y por eso la vara para su precio."""
    precio_dia = dict(curva)
    fechas = [d for d, _ in curva]
    mejor: tuple[float | None, list[tuple[str, float]] | None] = (None, None)
    for w in GRILLA_CAJA:
        mezcla = mezcla_constante(fechas, precio_dia, w, costo=costo, capital=capital)
        if max_drawdown(mezcla) <= dd_objetivo + 1e-12:
            mejor = (w, mezcla)
    return mejor


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TAJADA-SECUENCIAL (tarea 464): el precio del régimen, re-medido")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
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

    esperado = POPULATION_LIVE_ACCT2.tickers_fp
    actual = universe_fingerprint(args.universe)
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
    )
    print(
        "(El banner es el de los brazos nuevos; los secuenciales son los de la 456, y su desvío es el de ella.)\n"
    )

    common = {**_common_kwargs(args), "so_params": _so_params(T219_BASELINE)}
    # El mismo tag que la 456, así los dos brazos secuenciales salen de su cache.
    run_tag = f"{window}|n{len(bars_by)}|e{len(entries)}|mp{args.max_positions}|cap{args.cap_days}|${args.capital:.2f}"
    filtro = make_entry_filter(build_regime_series(spy_bars), mode="scale", factor=LIVE_REGIME_SCALE_FACTOR)
    corridas = {
        (VIVO_SIN_REGIMEN, SECUENCIAL): (
            f"t456|{VIVO_SIN_REGIMEN}|{run_tag}",
            lambda: simulate_portfolio(entries, bars_by, sigs_by, **common),
        ),
        (VIVO, SECUENCIAL): (
            f"t456|{VIVO}|f{LIVE_REGIME_SCALE_FACTOR}|{run_tag}",
            lambda: simulate_portfolio(entries, bars_by, sigs_by, entry_filter=filtro, **common),
        ),
        (VIVO_SIN_REGIMEN, POR_DIA): (
            f"t464|{VIVO_SIN_REGIMEN}|tajada|{run_tag}",
            lambda: simulate_portfolio(entries, bars_by, sigs_by, tajada_del_dia=True, **common),
        ),
        (VIVO, POR_DIA): (
            f"t464|{VIVO}|f{LIVE_REGIME_SCALE_FACTOR}|tajada|{run_tag}",
            lambda: simulate_portfolio(
                entries, bars_by, sigs_by, entry_filter=filtro, tajada_del_dia=True, **common
            ),
        ),
    }
    res: dict[tuple[str, str], PortfolioResult] = {}
    for clave, (tag, fn) in corridas.items():
        print(f"  corriendo {clave[0]} · {clave[1]}…", flush=True)
        res[clave] = cache.run(tag, fn)
    print(f"  cache: {cache.hits} de {len(corridas)} brazos salieron del cache\n")

    # ── Sanity ──
    bit_a_bit = identicos(res[(VIVO_SIN_REGIMEN, SECUENCIAL)], res[(VIVO_SIN_REGIMEN, POR_DIA)])
    repro = reproduce_t170(summarise(res[(VIVO_SIN_REGIMEN, POR_DIA)]))
    print("Sanity:")
    print(f"  1. sin régimen, tajada por día == secuencial, bit a bit: {'OK' if bit_a_bit else 'FALLA'}")
    print(
        f"  2. reproduce la T170: {repro['cagr']:.2%} / {repro['sharpe']:.2f} / {repro['n_taken']} "
        f"contra {repro['cagr_t170']:.2%} / {repro['sharpe_t170']:.2f} / {repro['n_taken_t170']}: "
        f"{'OK' if repro['OK'] else 'FALLA'}\n"
    )
    if not (bit_a_bit and repro["OK"]):
        print("*** CORRIDA INVÁLIDA — la tabla no se lee ***", file=sys.stderr)
        return 2

    # ── Tabla ──
    m = {k: metricas(r.equity_curve) for k, r in res.items()}
    print(f"{'brazo':<20} {'sizing':<22} {'CAGR':>8} {'Sharpe':>7} {'caída':>7} {'trades':>7} {'expos.':>7}")
    for (brazo, modo), r in res.items():
        mm = m[(brazo, modo)]
        print(
            f"{brazo:<20} {modo:<22} {mm['cagr']:>8.2%} {mm['sharpe']:>7.2f} {mm['max_dd']:>7.1%} "
            f"{len(r.trades):>7} {exposicion_media(r, bars_by):>7.1%}"
        )
    print("\nEl precio del escalado (con régimen − sin régimen):")
    for modo in (SECUENCIAL, POR_DIA):
        pr = precio(m[(VIVO, modo)], m[(VIVO_SIN_REGIMEN, modo)])
        print(
            f"  {modo:<22} ΔCAGR {pr['d_cagr_pp']:+.2f} pp · ΔSharpe {pr['d_sharpe']:+.2f} · "
            f"Δcaída {pr['d_dd_pp']:+.1f} pp"
        )
    print("\nCompras escaladas que comparten día (donde la tajada secuencial agranda):")
    for modo in (SECUENCIAL, POR_DIA):
        c = compras_escaladas_por_dia(res[(VIVO, modo)])
        inv = invertido_medio_escaladas(res[(VIVO, modo)])
        print(
            f"  {modo:<22} {c['escaladas']} escaladas en {c['dias']} días · {c['no_primeras']} no son la "
            f"primera de su día · hasta {c['max_por_dia']} en un día · monto medio "
            f"{inv:,.2f}"
            if inv is not None
            else f"  {modo:<22} sin compras escaladas"
        )

    # ── La alternativa directa: la misma estrategia con caja constante ──
    sin = res[(VIVO_SIN_REGIMEN, POR_DIA)].equity_curve
    costo = CostModel().commission + CostModel().slippage
    print("\nLa estrategia sin régimen con caja constante, hasta la caída del escalado (descriptivo):")
    for modo in (SECUENCIAL, POR_DIA):
        dd_obj = m[(VIVO, modo)]["max_dd"]
        w, curva = caja_hasta_la_caida(sin, dd_obj, costo=costo, capital=args.capital)
        if curva is None:
            print(f"  {modo:<22} ninguna w de la grilla llega a {dd_obj:.1%}")
            continue
        mc, mv = metricas(curva), m[(VIVO, modo)]
        print(
            f"  caída objetivo {dd_obj:.1%} ({modo}): w = {w:.2f} en la estrategia → "
            f"{mc['cagr']:.2%} / {mc['sharpe']:.2f} / {mc['max_dd']:.1%}, contra el escalado "
            f"{mv['cagr']:.2%} / {mv['sharpe']:.2f} / {mv['max_dd']:.1%}: la caja rinde "
            f"{(mc['cagr'] - mv['cagr']) * 100:+.2f} pp más"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
