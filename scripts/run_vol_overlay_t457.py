"""Tarea 457 — VOL-OVERLAY-SIN-VALIDAR: el overlay de σ de cartera, con y sin, fuera de muestra.

Pre-registro congelado: ``docs/vol_overlay_prereg_t457_2026-11-25.md``. Los brazos (§3), el gate
(§4) y los sanity (§5) son los de ahí; este script no decide nada que no esté escrito ahí.

- ``sin_overlay`` y ``con_overlay``: la config de la T170 con el costo del vivo (468) y la tajada
  por día (464); el segundo con ``simulate_portfolio(vol_overlay=OverlayDeVolatilidad(...))``.
- ``caja_equivalente``: ``sin_overlay`` con caja constante, ``w`` = exposición media de
  ``con_overlay`` / la de ``sin_overlay``.
- El marco de la cuenta (con el régimen a ×0,25), descriptivo.
- ``sin_overlay_harness``: al costo de ``CostModel()``, tiene que reproducir la T170.

Comando::

    python scripts/run_vol_overlay_t457.py --allow-stale-artifacts --cache-dir .cache/t457
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
from analysis.walkforward_power import paired_block_bootstrap, sharpe_compuesto
from scripts.medir_tajada_t464 import caja_hasta_la_caida
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_activo_pasivo_t456 import (
    OOS_DESDE,
    OOS_HASTA,
    cortar,
    exposicion_media,
    metricas,
    mezcla_constante,
    retornos_diarios,
)
from scripts.run_exit_policy_t170 import BOOT_BLOCK, BOOT_RESAMPLES, BOOT_SEED
from scripts.run_market_regime_r2 import load_spy_bars
from scripts.run_signal_exit_delay_t219 import BASELINE as T219_BASELINE
from scripts.run_signal_exit_delay_t219 import _common_kwargs, _so_params, reproduce_t170
from scripts.run_stop_cal_replay_t26 import NO_STOP, summarise
from scripts.run_stop_value_t37 import CAP_DAYS, EVAL_MODE, FILL_MODE, FOLDS, LIVE_GATES, SimCache
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

# ── Brazos (CONGELADOS — §3 del pre-registro) ────────────────────────────────
SIN = "sin_overlay"
CON = "con_overlay"
CAJA = "caja_equivalente"
SIN_REG = "sin_overlay_regimen"
CON_REG = "con_overlay_regimen"
SIN_HARNESS = "sin_overlay_harness"

# ── El gate (CONGELADO — §4) ─────────────────────────────────────────────────
C1_MIN_DSHARPE = 0.05

SE_QUEDA = "EL OVERLAY SE QUEDA"
RESTA = "NO-SHIP: EL OVERLAY RESTA"
NO_SE_DISTINGUE = "NO-SHIP: NO SE DISTINGUE"

# ── Sanity (§5) ──────────────────────────────────────────────────────────────
DESALINEADO_MAX = 0.01  # §5.2: días con compras donde lo previsto no fue lo tomado
MUERDE_MIN = 0.05  # §5.3: fracción de días con compras con factor < 1
CALENDARIO_MIN = 0.99  # §5.5: fechas comunes sobre cada curva, en el tramo OOS


# ── Piezas puras ─────────────────────────────────────────────────────────────


def w_caja_equivalente(expo_con: float, expo_sin: float) -> float | None:
    """§3 — la proporción de la caja constante: la exposición que deja el overlay sobre la que
    hay sin él. ``None`` si la base no tiene exposición."""
    if expo_sin <= 0:
        return None
    return expo_con / expo_sin


def alinear(
    a: list[tuple[str, float]], b: list[tuple[str, float]]
) -> tuple[list[tuple[str, float]], list[tuple[str, float]], float]:
    """Las dos curvas sobre sus fechas comunes, y la cobertura: la fracción más chica de fechas
    de cada una que quedó (§5.5)."""
    comunes = {d for d, _ in a} & {d for d, _ in b}
    aa = [(d, v) for d, v in a if d in comunes]
    bb = [(d, v) for d, v in b if d in comunes]
    cobertura = min(len(aa) / len(a), len(bb) / len(b)) if a and b else 0.0
    return aa, bb, cobertura


def resumen_factor(por_dia: dict[str, float] | None) -> dict[str, Any]:
    """El factor del overlay por día con compras: media, percentiles, fracción < 1 y por año."""
    if not por_dia:
        return {"n_dias": 0}
    vals = sorted(por_dia.values())

    def pct(q: float) -> float:
        return vals[min(len(vals) - 1, int(q * (len(vals) - 1) + 0.5))]

    por_anio: dict[str, list[float]] = {}
    for d, f in por_dia.items():
        por_anio.setdefault(d[:4], []).append(f)
    return {
        "n_dias": len(vals),
        "media": statistics.fmean(vals),
        "p10": pct(0.10),
        "p50": pct(0.50),
        "p90": pct(0.90),
        "minimo": vals[0],
        "frac_menor_1": sum(1 for f in vals if f < 1.0) / len(vals),
        "distintos": len(set(vals)),
        "por_anio": {a: statistics.fmean(fs) for a, fs in sorted(por_anio.items())},
    }


def evaluar_gate(
    con: list[tuple[str, float]],
    sin: list[tuple[str, float]],
    caja: list[tuple[str, float]],
    *,
    resamples: int = BOOT_RESAMPLES,
) -> dict[str, Any]:
    """§4 — las tres condiciones y la lectura. Las curvas entran enteras; se cortan al tramo OOS
    y se comparan sobre sus fechas comunes."""
    oos_con, oos_sin, cob = alinear(cortar(con, OOS_DESDE, OOS_HASTA), cortar(sin, OOS_DESDE, OOS_HASTA))
    oos_caja = cortar(caja, OOS_DESDE, OOS_HASTA)
    s_con, s_sin, s_caja = sharpe_annual(oos_con), sharpe_annual(oos_sin), sharpe_annual(oos_caja)
    if s_con is None or s_sin is None or s_caja is None:
        raise ValueError("un Sharpe OOS sin definir: la curva es plana o muy corta")
    d_sharpe = s_con - s_sin
    rc = [r for _, r in retornos_diarios(oos_con)]
    rs = [r for _, r in retornos_diarios(oos_sin)]
    boot = paired_block_bootstrap(
        rs, rc, block=BOOT_BLOCK, n_resamples=resamples, seed=BOOT_SEED, stat=sharpe_compuesto
    )
    boot_cagr = paired_block_bootstrap(rs, rc, block=BOOT_BLOCK, n_resamples=resamples, seed=BOOT_SEED)
    c = {
        "C1": d_sharpe >= C1_MIN_DSHARPE,
        "C2": boot.ci_low > 0.0,
        "C3": s_con > s_caja,
    }
    if all(c.values()):
        veredicto = SE_QUEDA
    elif d_sharpe <= -C1_MIN_DSHARPE and boot.ci_high < 0.0:
        veredicto = RESTA
    else:
        veredicto = NO_SE_DISTINGUE
    folds = []
    for _train_end, lo, hi in FOLDS:
        fc, fs = cortar(con, lo, hi), cortar(sin, lo, hi)
        folds.append(
            {
                "test": f"{lo}..{hi}",
                "d_sharpe": (sharpe_annual(fc) or 0.0) - (sharpe_annual(fs) or 0.0),
                "d_cagr_pp": 100.0 * (cagr(fc) - cagr(fs)),
            }
        )
    return {
        "sharpe_con": s_con,
        "sharpe_sin": s_sin,
        "sharpe_caja": s_caja,
        "d_sharpe": d_sharpe,
        "boot_sharpe": {"observed": boot.observed, "ci_low": boot.ci_low, "ci_high": boot.ci_high},
        "boot_cagr": {
            "observed": boot_cagr.observed,
            "ci_low": boot_cagr.ci_low,
            "ci_high": boot_cagr.ci_high,
        },
        "cagr_con": cagr(oos_con),
        "cagr_sin": cagr(oos_sin),
        "cagr_caja": cagr(oos_caja),
        "dd_con": max_drawdown(oos_con),
        "dd_sin": max_drawdown(oos_sin),
        "dd_caja": max_drawdown(oos_caja),
        "cobertura": cob,
        "folds": folds,
        "condiciones": c,
        "veredicto": veredicto,
    }


def evaluar_sanity(
    sum_harness: dict, con: PortfolioResult, con_reg: PortfolioResult, w: float | None, cobertura: float
) -> dict[str, Any]:
    """§5 — los cinco. Si uno falla, la corrida es INVÁLIDA."""
    repro = reproduce_t170(sum_harness)
    fac = resumen_factor(con.overlay_por_dia)
    n_con = len(con.overlay_por_dia or {})
    n_reg = len(con_reg.overlay_por_dia or {})
    desal_con = con.n_overlay_desalineado / n_con if n_con else 1.0
    desal_reg = con_reg.n_overlay_desalineado / n_reg if n_reg else 1.0
    s = {
        "repro_t170": repro,
        "desalineado_con": desal_con,
        "desalineado_con_regimen": desal_reg,
        "previstas_ok": bool(desal_con <= DESALINEADO_MAX and desal_reg <= DESALINEADO_MAX),
        "frac_menor_1": fac.get("frac_menor_1", 0.0),
        "muerde_ok": bool(fac.get("frac_menor_1", 0.0) >= MUERDE_MIN and fac.get("distintos", 0) > 1),
        "w": w,
        "w_ok": bool(w is not None and 0.0 < w < 1.0),
        "cobertura": cobertura,
        "calendario_ok": bool(cobertura >= CALENDARIO_MIN),
    }
    s["VALIDA"] = bool(
        repro["OK"] and s["previstas_ok"] and s["muerde_ok"] and s["w_ok"] and s["calendario_ok"]
    )
    return s


# ── Reporte ──────────────────────────────────────────────────────────────────


def _fila(nombre: str, curva: list[tuple[str, float]], expo: float | None, n: int | None) -> str:
    m = metricas(curva)
    expo_s = f"{expo:>8.1%}" if expo is not None else f"{'':>8}"
    n_s = f"{n:>8}" if n is not None else f"{'':>8}"
    return f"  {nombre:<22}{m['cagr']:>8.2%}{(m['sharpe'] or 0.0):>8.2f}{m['max_dd']:>8.1%}{expo_s}{n_s}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="VOL-OVERLAY-SIN-VALIDAR (tarea 457)")
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
        models_vol_overlay=True,
        tajada_del_dia=True,
        costo_por_lado=LIVE_COST_PER_SIDE,
    )
    print(
        "(El banner es el de los brazos del gate: overlay modelado, sin régimen, costo del vivo. El "
        "régimen va en el descriptivo, y el brazo al costo del harness es sólo el sanity.)\n"
    )

    run_tag = f"{window}|n{len(bars_by)}|e{len(entries)}|mp{args.max_positions}|cap{args.cap_days}|${args.capital:.2f}"
    base = {**_common_kwargs(args), "so_params": _so_params(T219_BASELINE), "tajada_del_dia": True}
    vivo = {**base, "costs": live_cost_model()}
    filtro = make_entry_filter(build_regime_series(spy_bars), mode="scale", factor=LIVE_REGIME_SCALE_FACTOR)
    tag = f"t457|vt{LIVE_VOL_TARGET_ANNUAL}|{run_tag}"

    def _overlay() -> OverlayDeVolatilidad:
        return OverlayDeVolatilidad(bars_by, objetivo=LIVE_VOL_TARGET_ANNUAL)

    corridas = {
        SIN_HARNESS: lambda: simulate_portfolio(entries, bars_by, sigs_by, **{**base, "costs": CostModel()}),
        SIN: lambda: simulate_portfolio(entries, bars_by, sigs_by, **vivo),
        CON: lambda: simulate_portfolio(entries, bars_by, sigs_by, vol_overlay=_overlay(), **vivo),
        SIN_REG: lambda: simulate_portfolio(entries, bars_by, sigs_by, entry_filter=filtro, **vivo),
        CON_REG: lambda: simulate_portfolio(
            entries, bars_by, sigs_by, entry_filter=filtro, vol_overlay=_overlay(), **vivo
        ),
    }
    res: dict[str, PortfolioResult] = {}
    for nombre, fn in corridas.items():
        print(f"  corriendo {nombre}…", flush=True)
        res[nombre] = cache.run(f"{tag}|{nombre}", fn)

    expo = {n: exposicion_media(r, bars_by) for n, r in res.items()}
    w = w_caja_equivalente(expo[CON], expo[SIN])
    curva_sin = res[SIN].equity_curve
    caja = (
        mezcla_constante(
            [d for d, _ in curva_sin], dict(curva_sin), w, costo=LIVE_COST_PER_SIDE, capital=args.capital
        )
        if w is not None and 0.0 <= w <= 1.0
        else None
    )
    _a, _b, cobertura = alinear(
        cortar(res[CON].equity_curve, OOS_DESDE, OOS_HASTA), cortar(curva_sin, OOS_DESDE, OOS_HASTA)
    )
    sanity = evaluar_sanity(summarise(res[SIN_HARNESS]), res[CON], res[CON_REG], w, cobertura)

    r = sanity["repro_t170"]
    print("\nSanity (§5):")
    print(
        f"  1. reproduce la T170 al costo del harness: {r['cagr']:.2%} / {r['sharpe']:.2f} / {r['n_taken']} "
        f"contra {r['cagr_t170']:.2%} / {r['sharpe_t170']:.2f} / {r['n_taken_t170']}: {'OK' if r['OK'] else 'FALLA'}"
    )
    print(
        f"  2. previstas = tomadas: desalineados {sanity['desalineado_con']:.2%} (con) y "
        f"{sanity['desalineado_con_regimen']:.2%} (con régimen), máx {DESALINEADO_MAX:.0%}: "
        f"{'OK' if sanity['previstas_ok'] else 'FALLA'}"
    )
    print(
        f"  3. el overlay muerde: factor < 1 en {sanity['frac_menor_1']:.1%} de los días con compras "
        f"(mín {MUERDE_MIN:.0%}): {'OK' if sanity['muerde_ok'] else 'FALLA'}"
    )
    w_txt = f"{w:.3f}" if w is not None else "—"
    print(f"  4. w de la caja equivalente = {w_txt}: {'OK' if sanity['w_ok'] else 'FALLA'}")
    print(
        f"  5. calendario: cobertura {cobertura:.2%} (mín {CALENDARIO_MIN:.0%}): "
        f"{'OK' if sanity['calendario_ok'] else 'FALLA'}"
    )

    salida: dict[str, Any] = {"sanity": sanity, "exposicion": expo, "w": w}
    if not sanity["VALIDA"] or caja is None:
        print("\n*** CORRIDA INVÁLIDA — no hay veredicto ***", file=sys.stderr)
        if args.json:
            Path(args.json).write_bytes(json.dumps(salida, indent=2, default=str).encode("utf-8"))
        return 2

    ev = evaluar_gate(res[CON].equity_curve, curva_sin, caja, resamples=args.resamples)
    c = ev["condiciones"]
    b = ev["boot_sharpe"]
    print(f"\nGate (§4), fuera de muestra {OOS_DESDE} → {OOS_HASTA}:")
    print(
        f"  C1 ΔSharpe {ev['d_sharpe']:+.3f} ({ev['sharpe_con']:.3f} contra {ev['sharpe_sin']:.3f}), "
        f"mín {C1_MIN_DSHARPE:+.2f}: {'sí' if c['C1'] else 'no'}"
    )
    print(
        f"  C2 IC95% del ΔSharpe [{b['ci_low']:+.3f}, {b['ci_high']:+.3f}], inferior > 0: {'sí' if c['C2'] else 'no'}"
    )
    print(
        f"  C3 Sharpe contra la caja equivalente: {ev['sharpe_con']:.3f} contra {ev['sharpe_caja']:.3f}: "
        f"{'sí' if c['C3'] else 'no'}"
    )
    print(f"\n  VEREDICTO: {ev['veredicto']}")

    bc = ev["boot_cagr"]
    print("\nDescriptivo (§6), fuera de muestra:")
    print(
        f"  CAGR {ev['cagr_con']:.2%} con, {ev['cagr_sin']:.2%} sin, {ev['cagr_caja']:.2%} caja · "
        f"ΔCAGR {100 * bc['observed']:+.2f} pp, IC [{100 * bc['ci_low']:+.2f}, {100 * bc['ci_high']:+.2f}] · "
        f"caída {ev['dd_con']:.1%} con, {ev['dd_sin']:.1%} sin, {ev['dd_caja']:.1%} caja"
    )
    for f in ev["folds"]:
        print(f"  fold {f['test']}: ΔSharpe {f['d_sharpe']:+.3f} · ΔCAGR {f['d_cagr_pp']:+.2f} pp")

    print(f"\n  {'muestra completa':<22}{'CAGR':>8}{'Sharpe':>8}{'caída':>8}{'expos.':>8}{'trades':>8}")
    for nombre in (SIN, CON, SIN_REG, CON_REG, SIN_HARNESS):
        print(_fila(nombre, res[nombre].equity_curve, expo[nombre], len(res[nombre].trades)))
    print(_fila(f"{CAJA} (w={w:.2f})", caja, None, None))

    for nombre in (CON, CON_REG):
        fac = resumen_factor(res[nombre].overlay_por_dia)
        print(
            f"\n  factor del overlay en {nombre}: media {fac['media']:.3f} · p10 {fac['p10']:.3f} · "
            f"p50 {fac['p50']:.3f} · p90 {fac['p90']:.3f} · mínimo {fac['minimo']:.3f} · "
            f"< 1 en {fac['frac_menor_1']:.1%} de {fac['n_dias']} días con compras"
        )
        print("    por año: " + ", ".join(f"{a} {v:.2f}" for a, v in fac["por_anio"].items()))
    print("  (en vivo, desde septiembre de 2026: 105 tandas, media 0,74; otro período, no se compara)")

    print("\n  El overlay contra la caja constante a la misma caída (muestra completa):")
    for con_n, sin_n in ((CON, SIN), (CON_REG, SIN_REG)):
        mc = metricas(res[con_n].equity_curve)
        wc, curva = caja_hasta_la_caida(
            res[sin_n].equity_curve, mc["max_dd"], costo=LIVE_COST_PER_SIDE, capital=args.capital
        )
        if curva is None:
            print(f"    {con_n}: ninguna w llega a {mc['max_dd']:.1%}")
            continue
        mk = metricas(curva)
        print(
            f"    {con_n}: caída {mc['max_dd']:.1%} · caja w={wc:.2f} {mk['cagr']:.2%} / {mk['sharpe']:.2f} · "
            f"overlay {mc['cagr']:.2%} / {mc['sharpe']:.2f} · overlay − caja {(mc['cagr'] - mk['cagr']) * 100:+.2f} pp"
        )

    ev_reg = None
    w_reg = w_caja_equivalente(expo[CON_REG], expo[SIN_REG])
    if w_reg is not None and 0.0 <= w_reg <= 1.0:
        cs = res[SIN_REG].equity_curve
        caja_reg = mezcla_constante(
            [d for d, _ in cs], dict(cs), w_reg, costo=LIVE_COST_PER_SIDE, capital=args.capital
        )
        ev_reg = evaluar_gate(res[CON_REG].equity_curve, cs, caja_reg, resamples=args.resamples)
        br = ev_reg["boot_sharpe"]
        print(
            f"\n  El marco de la cuenta (con régimen ×{LIVE_REGIME_SCALE_FACTOR:g}), descriptivo: ΔSharpe OOS "
            f"{ev_reg['d_sharpe']:+.3f} ({ev_reg['sharpe_con']:.3f} contra {ev_reg['sharpe_sin']:.3f}), "
            f"IC [{br['ci_low']:+.3f}, {br['ci_high']:+.3f}], caja w={w_reg:.2f} {ev_reg['sharpe_caja']:.3f} · "
            f"la misma lectura daría: {ev_reg['veredicto']}"
        )

    salida.update({"gate": ev, "regimen": ev_reg, "w_regimen": w_reg})
    if args.json:
        Path(args.json).write_bytes(json.dumps(salida, indent=2, default=str).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
