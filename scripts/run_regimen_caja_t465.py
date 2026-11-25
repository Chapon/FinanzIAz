"""Tarea 465 — REGIMEN-CONTRA-SU-CAJA: el escalado por régimen contra la caja constante, en los dos sentidos.

Pre-registro congelado: ``docs/regimen_caja_prereg_t465_2026-11-25.md``. Los brazos, los dos tramos
(§3), el gate (§4) y los sanity (§5) son los de ahí.

- ``regimen`` y ``sin_regimen``: la config de la T170 con el costo del vivo (468) y la tajada por
  día (464); el primero con el escalado a ×0,25 en risk-off.
- ``caja_A`` y ``caja_B``: ``sin_regimen`` con caja constante, con la ``w`` fijada en un tramo para
  que caiga lo mismo que ``regimen`` y medida en el otro.
- El marco de la cuenta (overlay de σ prendido), descriptivo.
- Al costo de ``CostModel()``, los dos tienen que reproducir la T170 y la 464.

Comando::

    python scripts/run_regimen_caja_t465.py --allow-stale-artifacts --cache-dir .cache/t465
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import max_drawdown
from analysis.harness_config import (
    LIVE_COST_PER_SIDE,
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
from analysis.risk_sizing import cagr, sharpe_annual
from analysis.scaleout_replay import CostModel
from analysis.walkforward_power import paired_block_bootstrap, regime_window_returns, sharpe_compuesto
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_activo_pasivo_t456 import (
    CALIBRACION_HASTA,
    OOS_DESDE,
    OOS_HASTA,
    cortar,
    fraccion_escalada,
    metricas,
    mezcla_constante,
    retornos_diarios,
)
from scripts.run_exit_policy_t170 import BOOT_BLOCK, BOOT_RESAMPLES, BOOT_SEED
from scripts.run_market_regime_r2 import load_spy_bars
from scripts.run_signal_exit_delay_t219 import BASELINE as T219_BASELINE
from scripts.run_signal_exit_delay_t219 import _common_kwargs, _so_params, reproduce_t170
from scripts.run_stop_cal_replay_t26 import NO_STOP, summarise
from scripts.run_stop_value_t37 import CAP_DAYS, EVAL_MODE, FILL_MODE, LIVE_GATES, SimCache
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals
from scripts.run_vol_overlay_t457 import alinear

# ── Los tramos (CONGELADOS — §3) ─────────────────────────────────────────────
# (nombre, calibración desde, calibración hasta, test desde, test hasta); None = la punta de la curva.
TRAMOS: tuple[tuple[str, str | None, str | None, str | None, str | None], ...] = (
    ("A", None, CALIBRACION_HASTA, OOS_DESDE, OOS_HASTA),
    ("B", OOS_DESDE, OOS_HASTA, None, CALIBRACION_HASTA),
)
GRILLA_W: tuple[float, ...] = tuple(round(0.01 * k, 2) for k in range(1, 101))  # 0,01 … 1,00

# ── El gate (CONGELADO — §4) ─────────────────────────────────────────────────
D_TOL = 0.01  # la caída del régimen puede pasar la de la caja hasta en 1,00 pp

SE_SOSTIENE = "EL ESCALADO SE SOSTIENE"
NO_SE_SOSTIENE = "EL ESCALADO NO SE SOSTIENE"
DEPENDE = "DEPENDE DEL TRAMO"

# ── Sanity (§5) ──────────────────────────────────────────────────────────────
ANCLA_464_CAGR_PCT = 6.41  # `regimen` al costo del harness (la 464)
ANCLA_468 = {  # al costo del vivo, muestra completa (la 468 §2): CAGR %, Sharpe, caída %
    "sin_regimen": (13.72, 0.79, 29.5),
    "regimen": (11.35, 0.77, 21.4),
}
ESCALADO_MIN, ESCALADO_MAX = 0.01, 0.50
CALENDARIO_MIN = 0.99

REG, SIN = "regimen", "sin_regimen"


# ── Piezas puras ─────────────────────────────────────────────────────────────


def w_por_caida(
    curva_sin: list[tuple[str, float]], dd_objetivo: float, *, costo: float, capital: float
) -> float | None:
    """§3 — la ``w`` más alta de la grilla cuya mezcla sobre ``curva_sin`` (arrancando en su
    primera fecha) no cae más que ``dd_objetivo``. ``None`` si ninguna."""
    if not curva_sin:
        return None
    fechas = [d for d, _ in curva_sin]
    precio = dict(curva_sin)
    mejor = None
    for w in GRILLA_W:
        if (
            max_drawdown(mezcla_constante(fechas, precio, w, costo=costo, capital=capital))
            <= dd_objetivo + 1e-12
        ):
            mejor = w
    return mejor


def veredicto(pasa: dict[str, bool]) -> str:
    """§4 — los dos tramos ⇒ se sostiene; ninguno ⇒ no se sostiene; uno ⇒ depende del tramo."""
    n = sum(1 for v in pasa.values() if v)
    if n == len(pasa):
        return SE_SOSTIENE
    if n == 0:
        return NO_SE_SOSTIENE
    return DEPENDE


def evaluar_tramo(
    reg: list[tuple[str, float]],
    sin: list[tuple[str, float]],
    tramo: tuple[str, str | None, str | None, str | None, str | None],
    *,
    costo: float,
    capital: float,
    resamples: int = BOOT_RESAMPLES,
) -> dict[str, Any]:
    """§3–§4 para un tramo: la ``w`` en la calibración, y en el test S, D y el bootstrap."""
    nombre, cal_desde, cal_hasta, test_desde, test_hasta = tramo
    reg_c, sin_c = cortar(reg, cal_desde, cal_hasta), cortar(sin, cal_desde, cal_hasta)
    dd_obj = max_drawdown(reg_c)
    w = w_por_caida(sin_c, dd_obj, costo=costo, capital=capital)
    out: dict[str, Any] = {"tramo": nombre, "dd_calibracion_regimen": dd_obj, "w": w}
    if w is None:
        return out
    reg_t, sin_t = alinear(cortar(reg, test_desde, test_hasta), cortar(sin, test_desde, test_hasta))[:2]
    caja_t = mezcla_constante([d for d, _ in sin_t], dict(sin_t), w, costo=costo, capital=capital)
    s_reg, s_caja = sharpe_annual(reg_t), sharpe_annual(caja_t)
    dd_reg, dd_caja = max_drawdown(reg_t), max_drawdown(caja_t)
    if s_reg is None or s_caja is None:
        raise ValueError(f"tramo {nombre}: un Sharpe sin definir")
    rr = [r for _, r in retornos_diarios(reg_t)]
    rc = [r for _, r in retornos_diarios(caja_t)]
    b_sh = paired_block_bootstrap(
        rc, rr, block=BOOT_BLOCK, n_resamples=resamples, seed=BOOT_SEED, stat=sharpe_compuesto
    )
    b_cg = paired_block_bootstrap(rc, rr, block=BOOT_BLOCK, n_resamples=resamples, seed=BOOT_SEED)
    s_ok, d_ok = s_reg >= s_caja, dd_reg <= dd_caja + D_TOL
    out.update(
        {
            "test": f"{reg_t[0][0]}..{reg_t[-1][0]}",
            "regimen": {"cagr": cagr(reg_t), "sharpe": s_reg, "max_dd": dd_reg},
            "caja": {"cagr": cagr(caja_t), "sharpe": s_caja, "max_dd": dd_caja},
            "sin_regimen": {
                "cagr": cagr(sin_t),
                "sharpe": sharpe_annual(sin_t),
                "max_dd": max_drawdown(sin_t),
            },
            "S": s_ok,
            "D": d_ok,
            "pasa": bool(s_ok and d_ok),
            "boot_sharpe": {"observed": b_sh.observed, "ci_low": b_sh.ci_low, "ci_high": b_sh.ci_high},
            "boot_cagr": {"observed": b_cg.observed, "ci_low": b_cg.ci_low, "ci_high": b_cg.ci_high},
            "ventanas_regimen": regime_window_returns(retornos_diarios(reg_t)),
            "ventanas_caja": regime_window_returns(retornos_diarios(caja_t)),
        }
    )
    return out


def _redondeo(m: dict[str, Any]) -> tuple[float, float, float]:
    return (round(m["cagr"] * 100.0, 2), round(m["sharpe"], 2), round(m["max_dd"] * 100.0, 1))


def evaluar_sanity(
    res_h: dict[str, PortfolioResult], res: dict[str, PortfolioResult], tramos: list[dict], cobertura: float
) -> dict[str, Any]:
    """§5 — los cinco. Si uno falla, la corrida es INVÁLIDA."""
    repro = reproduce_t170(summarise(res_h[SIN]))
    cagr_464 = round(cagr(res_h[REG].equity_curve) * 100.0, 2)
    vivo = {n: _redondeo(metricas(res[n].equity_curve)) for n in (SIN, REG)}
    escalada = fraccion_escalada(res[REG])
    s = {
        "repro_t170": repro,
        "cagr_464": cagr_464,
        "ok_464": cagr_464 == ANCLA_464_CAGR_PCT,
        "vivo": vivo,
        "ok_468": all(vivo[n] == ANCLA_468[n] for n in (SIN, REG)),
        "fraccion_escalada": escalada,
        "escalado_ok": bool(ESCALADO_MIN < escalada < ESCALADO_MAX),
        "w": {t["tramo"]: t["w"] for t in tramos},
        "w_ok": all(t["w"] is not None for t in tramos),
        "cobertura": cobertura,
        "calendario_ok": bool(cobertura >= CALENDARIO_MIN),
    }
    s["VALIDA"] = bool(
        repro["OK"] and s["ok_464"] and s["ok_468"] and s["escalado_ok"] and s["w_ok"] and s["calendario_ok"]
    )
    return s


# ── Reporte ──────────────────────────────────────────────────────────────────


def _m(m: dict[str, Any]) -> str:
    return f"{m['cagr']:.2%} / {m['sharpe']:.2f} / {m['max_dd']:.1%}"


def reportar_tramo(t: dict[str, Any], titulo: str) -> None:
    if t["w"] is None:
        print(
            f"  {titulo} {t['tramo']}: ninguna w cumple la regla (caída objetivo {t['dd_calibracion_regimen']:.1%})"
        )
        return
    bs, bc = t["boot_sharpe"], t["boot_cagr"]
    print(
        f"  {titulo} {t['tramo']} — w = {t['w']:.2f} (caída del régimen en la calibración "
        f"{t['dd_calibracion_regimen']:.1%}) · test {t['test']}"
    )
    print(f"    régimen      {_m(t['regimen'])}")
    print(f"    caja         {_m(t['caja'])}")
    print(f"    sin régimen  {_m(t['sin_regimen'])}")
    print(
        f"    S (Sharpe ≥): {'sí' if t['S'] else 'no'} · D (caída ≤ +1 pp): {'sí' if t['D'] else 'no'} · "
        f"{'PASA' if t['pasa'] else 'no pasa'}"
    )
    print(
        f"    ΔSharpe {bs['observed']:+.3f} IC [{bs['ci_low']:+.3f}, {bs['ci_high']:+.3f}] · "
        f"ΔCAGR {100 * bc['observed']:+.2f} pp IC [{100 * bc['ci_low']:+.2f}, {100 * bc['ci_high']:+.2f}]"
    )
    vr, vc = t["ventanas_regimen"], t["ventanas_caja"]
    print(
        "    ventanas (régimen / caja): "
        + " · ".join(f"{k} {100 * vr[k]:+.1f}% / {100 * vc[k]:+.1f}%" for k in vr if k != "bull_normal")
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="REGIMEN-CONTRA-SU-CAJA (tarea 465)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--allow-stale-artifacts", action="store_true")
    p.add_argument("--json", default=None, help="ruta donde dejar el resultado en JSON")
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
        models_regime_scale=True,
        tajada_del_dia=True,
        costo_por_lado=LIVE_COST_PER_SIDE,
    )
    print(
        "(El banner es el de los brazos del gate: régimen modelado, overlay apagado, costo del vivo. El "
        "overlay va en el descriptivo, y los brazos al costo del harness son sólo el sanity.)\n"
    )

    run_tag = f"{window}|n{len(bars_by)}|e{len(entries)}|mp{args.max_positions}|cap{args.cap_days}|${args.capital:.2f}"
    base = {**_common_kwargs(args), "so_params": _so_params(T219_BASELINE), "tajada_del_dia": True}
    vivo = {**base, "costs": live_cost_model()}
    harness = {**base, "costs": CostModel()}
    filtro = make_entry_filter(build_regime_series(spy_bars), mode="scale", factor=LIVE_REGIME_SCALE_FACTOR)
    tag = f"t465|f{LIVE_REGIME_SCALE_FACTOR}|{run_tag}"

    def _ov() -> OverlayDeVolatilidad:
        return OverlayDeVolatilidad(bars_by, objetivo=LIVE_VOL_TARGET_ANNUAL)

    corridas = {
        "h|" + SIN: lambda: simulate_portfolio(entries, bars_by, sigs_by, **harness),
        "h|" + REG: lambda: simulate_portfolio(entries, bars_by, sigs_by, entry_filter=filtro, **harness),
        SIN: lambda: simulate_portfolio(entries, bars_by, sigs_by, **vivo),
        REG: lambda: simulate_portfolio(entries, bars_by, sigs_by, entry_filter=filtro, **vivo),
        "ov|" + SIN: lambda: simulate_portfolio(entries, bars_by, sigs_by, vol_overlay=_ov(), **vivo),
        "ov|" + REG: lambda: simulate_portfolio(
            entries, bars_by, sigs_by, entry_filter=filtro, vol_overlay=_ov(), **vivo
        ),
    }
    todo: dict[str, PortfolioResult] = {}
    for nombre, fn in corridas.items():
        print(f"  corriendo {nombre}…", flush=True)
        todo[nombre] = cache.run(f"{tag}|{nombre}", fn)
    res = {SIN: todo[SIN], REG: todo[REG]}
    res_h = {SIN: todo["h|" + SIN], REG: todo["h|" + REG]}
    res_ov = {SIN: todo["ov|" + SIN], REG: todo["ov|" + REG]}

    kw = {"costo": LIVE_COST_PER_SIDE, "capital": args.capital, "resamples": args.resamples}
    reg_al, sin_al, cobertura = alinear(res[REG].equity_curve, res[SIN].equity_curve)
    tramos = [evaluar_tramo(reg_al, sin_al, t, **kw) for t in TRAMOS]
    sanity = evaluar_sanity(res_h, res, tramos, cobertura)

    r = sanity["repro_t170"]
    print("\nSanity (§5):")
    print(
        f"  1. al costo del harness: sin régimen {r['cagr']:.2%} / {r['sharpe']:.2f} / {r['n_taken']} contra la "
        f"T170 ({'OK' if r['OK'] else 'FALLA'}); régimen {sanity['cagr_464']:.2f}% contra {ANCLA_464_CAGR_PCT:.2f}% "
        f"de la 464 ({'OK' if sanity['ok_464'] else 'FALLA'})"
    )
    print(
        f"  2. al costo del vivo: {sanity['vivo']} contra {ANCLA_468}: {'OK' if sanity['ok_468'] else 'FALLA'}"
    )
    print(
        f"  3. el escalado muerde: {sanity['fraccion_escalada']:.1%} de las entradas con factor < 1: "
        f"{'OK' if sanity['escalado_ok'] else 'FALLA'}"
    )
    print(f"  4. w por tramo: {sanity['w']}: {'OK' if sanity['w_ok'] else 'FALLA'}")
    print(f"  5. calendario: cobertura {cobertura:.2%}: {'OK' if sanity['calendario_ok'] else 'FALLA'}")

    salida: dict[str, Any] = {"sanity": sanity}
    if not sanity["VALIDA"]:
        print("\n*** CORRIDA INVÁLIDA — no hay veredicto ***", file=sys.stderr)
        if args.json:
            Path(args.json).write_bytes(json.dumps(salida, indent=2, default=str).encode("utf-8"))
        return 2

    print("\nGate (§4):")
    for t in tramos:
        reportar_tramo(t, "tramo")
    v = veredicto({t["tramo"]: t["pasa"] for t in tramos})
    print(f"\n  VEREDICTO: {v}")

    print("\nDescriptivo (§6) — el marco de la cuenta (overlay de σ prendido):")
    reg_o, sin_o, _cob = alinear(res_ov[REG].equity_curve, res_ov[SIN].equity_curve)
    tramos_ov = [evaluar_tramo(reg_o, sin_o, t, **kw) for t in TRAMOS]
    for t in tramos_ov:
        reportar_tramo(t, "tramo (con overlay)")
    v_ov = veredicto({t["tramo"]: t.get("pasa", False) for t in tramos_ov})
    print(f"  la misma lectura daría: {v_ov}")
    print("\n  Muestra completa (costo del vivo):")
    for etiqueta, rr in (
        ("sin régimen", res[SIN]),
        ("régimen", res[REG]),
        ("sin régimen + overlay", res_ov[SIN]),
        ("régimen + overlay", res_ov[REG]),
    ):
        print(f"    {etiqueta:<24}{_m(metricas(rr.equity_curve))}")

    salida.update({"tramos": tramos, "veredicto": v, "tramos_overlay": tramos_ov, "veredicto_overlay": v_ov})
    if args.json:
        Path(args.json).write_bytes(json.dumps(salida, indent=2, default=str).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
