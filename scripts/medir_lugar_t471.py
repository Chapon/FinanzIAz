"""Tarea 471 — cuánto vale que el pick frenado se quede con su lugar, como en vivo (DESCRIPTIVO).

En vivo, el motor corta los candidatos a los lugares libres **antes** de correr los gates de compra,
y un pick frenado (Gate 5, 5b o 6) deja su lugar vacío en ese scan. El simulador se lo daba al
siguiente candidato. Este script corre las dos reglas (``lugar_del_bloqueado``), con el costo del vivo
y la tajada por día, en tres marcos:

- los gates de re-entrada solos (5 y 5b, lo que todo runner con ``live_gates`` modela);
- más el Gate 6 de la 458 (el único que frenó picks en vivo desde el 2026-10-02);
- el marco de la cuenta: régimen ×0,25 y Gate 6 (el overlay no se combina con la regla del vivo).

Y con dos órdenes de los candidatos del día, porque cuántos picks frena un gate depende de quién
queda arriba: el del harness (sin ``rank_score``, alfabético; la tarea 473 es que no está declarado)
y el del vivo (``_default_strength``: la ``ml_probability`` del store).

**No decide nada.** Mide el desvío para declararlo con su precio, y para que Chapa decida si el
vivo debería darle el lugar al siguiente (un cambio al motor, con su propio pre-registro).

Sanity duro: con el orden del harness, la regla de hoy reproduce la 468 (13,72% / 0,79) sin Gate 6,
y la 458 (13,14% / 0,77) con él.

Comando::

    python scripts/medir_lugar_t471.py --allow-stale-artifacts --cache-dir .cache/t471
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from analysis.earnings_sim import ALMACEN, cargar_fechas, componer, filtro_de_balances
from analysis.harness_config import (
    LIVE_COST_PER_SIDE,
    LIVE_EARNINGS_BLACKOUT_DAYS,
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
from analysis.risk_sizing import cagr
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_activo_pasivo_t456 import OOS_DESDE, OOS_HASTA, cortar, metricas
from scripts.run_market_regime_r2 import load_spy_bars
from scripts.run_ranking_t21 import load_bars_signals_scores
from scripts.run_signal_exit_delay_t219 import BASELINE as T219_BASELINE
from scripts.run_signal_exit_delay_t219 import _common_kwargs, _so_params
from scripts.run_stop_cal_replay_t26 import NO_STOP
from scripts.run_stop_value_t37 import CAP_DAYS, EVAL_MODE, FILL_MODE, LIVE_GATES, SimCache
from scripts.run_tp_cal_replay_t23 import buy_entries

MARCOS = ("gates_5_5b", "mas_gate_6", "cuenta")
ORDENES = ("alfabetico", "vivo")
ANCLAS = {
    ("alfabetico", "gates_5_5b"): (13.72, 0.79),
    ("alfabetico", "mas_gate_6"): (13.14, 0.77),
}


def orden_del_vivo(score_by: dict[str, dict[str, float]]):
    """El ``rank_score`` del vivo: ``_default_strength("BUY", ml_probability)`` (topada a [0, 1],
    y 1 si falta la probabilidad)."""

    def rank(ticker: str, fecha: str) -> float:
        p = (score_by.get(ticker) or {}).get(fecha)
        if p is None or p != p:
            return 1.0
        return max(0.0, min(1.0, float(p)))

    return rank


def fila(res: PortfolioResult) -> dict:
    m = metricas(res.equity_curve)
    return {
        "cagr": m["cagr"],
        "sharpe": m["sharpe"],
        "max_dd": m["max_dd"],
        "cagr_oos": cagr(cortar(res.equity_curve, OOS_DESDE, OOS_HASTA)),
        "trades": len(res.trades),
        "perdidos": res.n_lugar_perdido,
        "gate5": res.n_gate5_blocked,
        "gate5b": res.n_gate5b_blocked,
        "filtrados": res.n_filtered,
    }


def sanity(filas: dict[tuple[str, str, bool], dict]) -> dict:
    """Con el orden del harness, la regla de hoy reproduce la 468 y la 458."""
    out: dict = {}
    for (orden, marco), (c0, s0) in ANCLAS.items():
        f = filas[(orden, marco, False)]
        got = (round(f["cagr"] * 100.0, 2), round(f["sharpe"], 2))
        out[marco] = {"got": got, "esperado": (c0, s0), "OK": got == (c0, s0)}
    out["VALIDA"] = all(v["OK"] for v in out.values())
    return out


def _tabla(filas: dict, orden: str) -> None:
    print(f"\nOrden de los candidatos: {orden}")
    print(
        f"{'marco':<12}{'regla':<8}{'CAGR':>8}{'Sharpe':>8}{'caída':>8}{'CAGR OOS':>10}"
        f"{'trades':>8}{'perdidos':>10}{'g5':>6}{'g5b':>6}{'filtr.':>8}"
    )
    for marco in MARCOS:
        for vivo in (False, True):
            f = filas[(orden, marco, vivo)]
            print(
                f"{marco:<12}{'vivo' if vivo else 'hoy':<8}{f['cagr']:>8.2%}{(f['sharpe'] or 0.0):>8.2f}"
                f"{f['max_dd']:>8.1%}{f['cagr_oos']:>10.2%}{f['trades']:>8}{f['perdidos']:>10}"
                f"{f['gate5']:>6}{f['gate5b']:>6}{f['filtrados']:>8}"
            )
        h, v = filas[(orden, marco, False)], filas[(orden, marco, True)]
        print(
            f"{'':<12}{'Δ':<8}{100 * (v['cagr'] - h['cagr']):>+7.2f}pp"
            f"{(v['sharpe'] or 0) - (h['sharpe'] or 0):>+8.2f}"
            f"{100 * (v['max_dd'] - h['max_dd']):>+7.1f}pp{100 * (v['cagr_oos'] - h['cagr_oos']):>+9.2f}pp"
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LUGAR-DEL-BLOQUEADO (tarea 471), descriptivo")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
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
        models_earnings_blackout=True,
        tajada_del_dia=True,
        costo_por_lado=LIVE_COST_PER_SIDE,
    )
    print(
        "(El banner es el del marco con el Gate 6; los otros difieren en eso, en el régimen y en el orden.)\n"
    )

    run_tag = f"{window}|n{len(bars_by)}|e{len(entries)}|mp{args.max_positions}|cap{args.cap_days}|${args.capital:.2f}"
    base = {
        **_common_kwargs(args),
        "so_params": _so_params(T219_BASELINE),
        "tajada_del_dia": True,
        "costs": live_cost_model(),
    }
    bloqueo = filtro_de_balances(fechas, LIVE_EARNINGS_BLACKOUT_DAYS)
    regimen = make_entry_filter(build_regime_series(spy_bars), mode="scale", factor=LIVE_REGIME_SCALE_FACTOR)
    filtros = {"gates_5_5b": None, "mas_gate_6": bloqueo, "cuenta": componer(regimen, bloqueo)}
    rangos = {"alfabetico": None, "vivo": orden_del_vivo(score_by)}
    tag = f"t471|{meta.get('capturado')}|{run_tag}"

    filas: dict[tuple[str, str, bool], dict] = {}
    for orden in ORDENES:
        for marco in MARCOS:
            for vivo in (False, True):
                regla = "pierde el lugar" if vivo else "pasa el lugar"
                print(f"  corriendo orden {orden} · {marco} · {regla}…", flush=True)
                r = cache.run(
                    f"{tag}|{orden}|{marco}|{int(vivo)}",
                    lambda orden=orden, marco=marco, vivo=vivo: simulate_portfolio(
                        entries,
                        bars_by,
                        sigs_by,
                        entry_filter=filtros[marco],
                        rank_score=rangos[orden],
                        lugar_del_bloqueado=vivo,
                        **base,
                    ),
                )
                filas[(orden, marco, vivo)] = fila(r)

    s = sanity(filas)
    print("\nSanity (orden del harness, la regla de hoy reproduce lo publicado):")
    for marco, v in s.items():
        if marco != "VALIDA":
            print(f"  {marco}: {v['got']} contra {v['esperado']} → {'OK' if v['OK'] else 'FALLA'}")
    if not s["VALIDA"]:
        print("*** CORRIDA INVÁLIDA — la tabla no se lee ***", file=sys.stderr)
        return 2
    for orden in ORDENES:
        _tabla(filas, orden)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
