#!/usr/bin/env python
"""Tarea 456 — ¿la estrategia viva le gana a SPY + caja con la misma caída máxima?

Pre-registro congelado: ``docs/activo_pasivo_prereg_t456_2026-11-23.md`` (``6d73516``, antes
de escribir esto). Lo de acá implementa esos brazos, esa regla de ``w``, ese gate y esos sanity,
y nada más.

**La pregunta que ningún experimento se hizo.** Los ~30 de la serie compararon una variante
*contra la estrategia viva*. Éste compara la estrategia viva *contra no operar*: SPY a una
proporción constante y el resto en caja, con la proporción fijada por una regla mecánica sobre el
tramo de calibración (la caída máxima del pasivo no supera la del vivo hasta el 2021-07-31) y
evaluada **fuera de muestra** sobre los cinco folds de test de la T170.

**Los umbrales no son de acá:** C1, C2, C3 y C4 son el D1, el D2, el D4 y el D5 de la T170, y se
importan de su runner para que no puedan divergir.

**El vivo se corre una sola vez, de punta a punta, y se corta.** No hay nada que entrenar, así
que no se reinicia la cartera en cada fold como en la T170: sus números por fold no coinciden
con los de la T170, a propósito (§3 del pre-registro).

Uso::

    python scripts/run_activo_pasivo_t456.py --allow-stale-artifacts --cache-dir .cache/t456
    python scripts/run_activo_pasivo_t456.py --allow-stale-artifacts --json > salida.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
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
from analysis.risk_sizing import cagr, sharpe_annual
from analysis.scaleout_replay import CostModel
from analysis.walkforward_power import paired_block_bootstrap, regime_window_returns
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_exit_policy_t170 import (
    BOOT_BLOCK,
    BOOT_RESAMPLES,
    BOOT_SEED,
    D1_MIN_DCAGR_OOS,
    D2_MIN_FOLDS,
    D5_DD_TOL,
)
from scripts.run_market_regime_r2 import load_spy_bars
from scripts.run_signal_exit_delay_t219 import BASELINE as T219_BASELINE
from scripts.run_signal_exit_delay_t219 import _common_kwargs, _so_params, reproduce_t170
from scripts.run_stop_cal_replay_t26 import NO_STOP, summarise
from scripts.run_stop_value_t37 import CAP_DAYS, EVAL_MODE, FILL_MODE, FOLDS, LIVE_GATES, SimCache
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

# ── Brazos (CONGELADOS — §3 del pre-registro) ────────────────────────────────
VIVO = "vivo"  # la config de la T170 + el escalado por régimen vivo: el del gate
VIVO_SIN_REGIMEN = "vivo_sin_regimen"  # el `soff_t2.0` de la T170: ancla y descriptivo
SPY_CAJA = "SPY_caja"  # el del gate
UNIV_CAJA = "UNIV_caja"  # descriptivo: tiene sesgo de supervivencia

# ── La regla de w (CONGELADA) ────────────────────────────────────────────────
# El tramo de calibración termina donde termina el train del primer fold de la T170.
CALIBRACION_HASTA = "2021-07-31"
GRILLA_W: tuple[float, ...] = tuple(round(0.05 * k, 2) for k in range(1, 21))  # 0,05 … 1,00

# ── El gate (CONGELADO — §4): los umbrales SON los de la T170, importados ─────
OOS_DESDE = FOLDS[0][1]  # 2021-08-01
OOS_HASTA = FOLDS[-1][2]  # 2026-07-31
C1_MIN_DCAGR = D1_MIN_DCAGR_OOS  # ≥ +1,00 pp
C2_MIN_FOLDS = D2_MIN_FOLDS  # ≥ 4 de 5
C4_DD_TOL = D5_DD_TOL  # caída OOS ≤ vivo + 1,00 pp

PASIVO_GANA = "EL PASIVO GANA"
ESTRATEGIA_GANA = "LA ESTRATEGIA LE GANA AL PASIVO"
NO_DECIDIBLE = "NO DECIDIBLE"

# ── Sanity (§5) — sin «SANITY» en el nombre: son de construcción, no magnitudes ─
CONTROL_TOL = 1e-9  # §5.2: el pasivo sin costos y con w=1 es el cociente de cierres de SPY
ESCALADO_MIN = 0.01  # §5.4: fracción de entradas del vivo con size_factor < 1 …
ESCALADO_MAX = 0.50  # … estrictamente entre las dos


# ── El pasivo ────────────────────────────────────────────────────────────────


def serie_en_calendario(fechas: list[str], cierres: dict[str, float]) -> dict[str, float]:
    """Cierres sobre ``fechas``, con el último arrastrado. La primera fecha tiene que tener uno.

    Un ticker que deja de cotizar queda quieto, igual que en la T385; una fecha sin cierre en el
    medio (un feriado de una sola bolsa) toma el anterior.
    """
    out: dict[str, float] = {}
    ultimo: float | None = None
    for d in fechas:
        p = cierres.get(d)
        if p is not None and p > 0:
            ultimo = p
        if ultimo is None:
            raise ValueError(f"sin cierre en la primera fecha del calendario ({d})")
        out[d] = ultimo
    return out


def mezcla_constante(
    fechas: list[str], precio: dict[str, float], w: float, *, costo: float, capital: float
) -> list[tuple[str, float]]:
    """Valor diario de ``w`` en el activo y ``1 − w`` en caja al 0%, rebalanceado el primer día
    hábil de cada mes (y el primero de la serie, que es la compra inicial).

    En cada rebalanceo se paga ``costo`` (comisión + slippage de ``CostModel``) sobre lo operado,
    y el objetivo se recalcula una vez sobre el valor neto del costo, así que con ``w = 1`` la
    caja nunca queda negativa. Pura: no lee nada de afuera.
    """
    if not 0.0 <= w <= 1.0:
        raise ValueError(f"w fuera de [0, 1]: {w}")
    out: list[tuple[str, float]] = []
    acciones, caja, mes = 0.0, float(capital), None
    for d in fechas:
        p = precio[d]
        valor = acciones * p + caja
        if d[:7] != mes:
            mes = d[:7]
            actual = acciones * p
            objetivo = w * (valor - abs(w * valor - actual) * costo)
            gasto = abs(objetivo - actual) * costo
            acciones = objetivo / p
            caja = valor - objetivo - gasto
            valor = acciones * p + caja
        out.append((d, valor))
    return out


def indice_universo(
    fechas: list[str], cierres_por_ticker: dict[str, dict[str, float]], *, costo: float
) -> dict[str, float]:
    """Nivel de un índice del universo en partes iguales, rebalanceado el primer día hábil de cada
    mes, con ``costo`` sobre lo operado. Un ticker entra cuando tiene su primer cierre; uno que
    deja de cotizar queda con el último (como en la T385). Arranca en 1,0.
    """
    ultimo: dict[str, float] = {}
    acciones: dict[str, float] = {}
    valor, mes = 1.0, None
    out: dict[str, float] = {}
    for d in fechas:
        for t, c in cierres_por_ticker.items():
            p = c.get(d)
            if p is not None and p > 0:
                ultimo[t] = p
        if acciones:
            valor = sum(n * ultimo[t] for t, n in acciones.items())
        if d[:7] != mes and ultimo:
            mes = d[:7]
            objetivo = valor / len(ultimo)
            operado = sum(abs(objetivo - acciones.get(t, 0.0) * p) for t, p in ultimo.items())
            valor -= operado * costo
            acciones = {t: (valor / len(ultimo)) / p for t, p in ultimo.items()}
        out[d] = valor
    return out


def w_por_regla(
    dd_objetivo: float,
    fechas_calibracion: list[str],
    precio: dict[str, float],
    *,
    costo: float,
    capital: float,
    grilla: tuple[float, ...] = GRILLA_W,
) -> float | None:
    """La ``w`` **más alta** de la grilla cuya caída máxima en el tramo de calibración no supera
    ``dd_objetivo`` (la del vivo en ese mismo tramo). ``None`` si ninguna cumple (§5.5).

    No supone que la caída crezca con ``w``: recorre la grilla entera y se queda con la mayor
    que cumple.
    """
    mejor: float | None = None
    for w in grilla:
        curva = mezcla_constante(fechas_calibracion, precio, w, costo=costo, capital=capital)
        if max_drawdown(curva) <= dd_objetivo + 1e-12:
            mejor = w if mejor is None else max(mejor, w)
    return mejor


# ── Cortes y métricas ────────────────────────────────────────────────────────


def cortar(curva: list[tuple[str, float]], desde: str | None, hasta: str | None) -> list[tuple[str, float]]:
    return [(d, v) for d, v in curva if (desde is None or d >= desde) and (hasta is None or d <= hasta)]


def retornos_diarios(curva: list[tuple[str, float]]) -> list[tuple[str, float]]:
    return [
        (curva[i][0], curva[i][1] / curva[i - 1][1] - 1.0)
        for i in range(1, len(curva))
        if curva[i - 1][1] > 0
    ]


def metricas(curva: list[tuple[str, float]]) -> dict[str, Any]:
    return {
        "cagr": cagr(curva),
        "sharpe": sharpe_annual(curva),
        "max_dd": max_drawdown(curva),
        "desde": curva[0][0] if curva else None,
        "hasta": curva[-1][0] if curva else None,
        "n": len(curva),
    }


def exposicion_media(res: PortfolioResult, bars_by: dict) -> float:
    """Fracción media de la equity invertida, con la misma marca a mercado que
    ``portfolio_sim._build_equity_curve``: una posición cuenta desde su entrada hasta el día
    anterior a su salida."""
    curva = dict(res.equity_curve)
    if not curva:
        return 0.0
    fechas = sorted(curva)
    mtm = dict.fromkeys(fechas, 0.0)
    for t in res.trades:
        cierres = {b[0]: b[4] for b in bars_by.get(t.ticker) or []}
        p0 = cierres.get(t.entry_date)
        for d in fechas:
            if t.entry_date <= d < t.exit_date:
                px = cierres.get(d)
                mtm[d] += t.invested * (px / p0) if (px and p0) else t.invested
    return sum(mtm[d] / curva[d] for d in fechas if curva[d] > 0) / len(fechas)


# ── El gate ──────────────────────────────────────────────────────────────────


def evaluar(
    vivo: list[tuple[str, float]], pasivo: list[tuple[str, float]], *, resamples: int = BOOT_RESAMPLES
) -> dict[str, Any]:
    """Las cuatro condiciones del §4 y su espejo. Los dos brazos tienen que venir sobre el
    mismo calendario: el pasivo se construye sobre las fechas del vivo."""
    oos_v, oos_p = cortar(vivo, OOS_DESDE, OOS_HASTA), cortar(pasivo, OOS_DESDE, OOS_HASTA)
    if [d for d, _ in oos_v] != [d for d, _ in oos_p]:
        raise ValueError("el vivo y el pasivo no están sobre el mismo calendario")
    d_cagr = cagr(oos_p) - cagr(oos_v)

    folds = []
    for _train_end, lo, hi in FOLDS:
        cv, cp = cagr(cortar(vivo, lo, hi)), cagr(cortar(pasivo, lo, hi))
        folds.append({"test": f"{lo}..{hi}", "vivo": cv, "pasivo": cp, "delta_pp": 100.0 * (cp - cv)})
    gana_p = sum(1 for f in folds if f["delta_pp"] > 0.0)
    gana_v = sum(1 for f in folds if f["delta_pp"] < 0.0)

    boot = paired_block_bootstrap(
        [r for _, r in retornos_diarios(oos_v)],
        [r for _, r in retornos_diarios(oos_p)],
        block=BOOT_BLOCK,
        n_resamples=resamples,
        seed=BOOT_SEED,
    )
    dd_v, dd_p = max_drawdown(oos_v), max_drawdown(oos_p)

    c = {
        "C1": d_cagr >= C1_MIN_DCAGR,
        "C2": gana_p >= C2_MIN_FOLDS,
        "C3": boot.ci_low > 0.0,
        "C4": dd_p <= dd_v + C4_DD_TOL,
    }
    espejo = {
        "E1": d_cagr <= -C1_MIN_DCAGR,
        "E2": gana_v >= C2_MIN_FOLDS,
        "E3": boot.ci_high < 0.0,
        "E4": dd_v <= dd_p + C4_DD_TOL,
    }
    if all(c.values()):
        veredicto = PASIVO_GANA
    elif all(espejo.values()):
        veredicto = ESTRATEGIA_GANA
    else:
        veredicto = NO_DECIDIBLE
    return {
        "dcagr_oos": d_cagr,
        "cagr_oos_vivo": cagr(oos_v),
        "cagr_oos_pasivo": cagr(oos_p),
        "dd_oos_vivo": dd_v,
        "dd_oos_pasivo": dd_p,
        "folds": folds,
        "folds_gana_pasivo": gana_p,
        "folds_gana_vivo": gana_v,
        "boot": {
            "observed": boot.observed,
            "ci_low": boot.ci_low,
            "ci_high": boot.ci_high,
            "p_value": boot.p_value,
        },
        "condiciones": c,
        "espejo": espejo,
        "veredicto": veredicto,
    }


# ── Sanity (§5) ──────────────────────────────────────────────────────────────


def control_pasivo(fechas: list[str], precio: dict[str, float], capital: float) -> dict[str, Any]:
    """§5.2 — sin costos, ``w = 1`` reproduce el cociente de cierres y ``w = 0`` queda plano."""
    uno = mezcla_constante(fechas, precio, 1.0, costo=0.0, capital=capital)
    cero = mezcla_constante(fechas, precio, 0.0, costo=0.0, capital=capital)
    esperado = precio[fechas[-1]] / precio[fechas[0]]
    err = abs(uno[-1][1] / capital - esperado)
    plano = max(abs(v - capital) for _, v in cero) / capital
    return {"err_w1": err, "err_w0": plano, "OK": bool(err <= CONTROL_TOL and plano <= CONTROL_TOL)}


def tags_de_corrida(run_tag: str, tajada_del_dia: bool) -> tuple[str, str]:
    """Los tags del cache de los dos brazos: ``(vivo_sin_regimen, vivo)``.

    Tarea 466. Sin la tajada por día son **los publicados**, así la 456 sigue reproduciendo
    desde su cache. Con ella **tienen que cambiar**: si no, la re-lectura leería del cache los
    brazos secuenciales y los publicaría como corregidos sin que nada lo acuse.
    """
    sufijo = "|tajada" if tajada_del_dia else ""
    return (
        f"t456|{VIVO_SIN_REGIMEN}|{run_tag}{sufijo}",
        f"t456|{VIVO}|f{LIVE_REGIME_SCALE_FACTOR}|{run_tag}{sufijo}",
    )


def fraccion_escalada(res: PortfolioResult) -> float:
    """§5.4 — fracción de entradas con ``size_factor < 1`` (la lección de la T38)."""
    if not res.trades:
        return 0.0
    return sum(1 for t in res.trades if t.size_factor < 1.0) / len(res.trades)


def evaluar_sanity(sum_sin: dict, sum_vivo: dict, control: dict, escalada: float, w: float | None) -> dict:
    repro = reproduce_t170(sum_sin)
    s = {
        "repro_t170": repro,
        "control_pasivo": control,
        "contabilidad_ok": bool(sum_sin.get("accounting_ok") and sum_vivo.get("accounting_ok")),
        "fraccion_escalada": escalada,
        "escalado_ok": bool(ESCALADO_MIN < escalada < ESCALADO_MAX),
        "w": w,
        "w_ok": bool(w is not None and 0.0 < w <= 1.0),
    }
    s["VALIDA"] = bool(
        repro["OK"] and control["OK"] and s["contabilidad_ok"] and s["escalado_ok"] and s["w_ok"]
    )
    return s


# ── Reporte ──────────────────────────────────────────────────────────────────


def _pct(x: float | None, p: int = 2) -> str:
    return "—" if x is None else f"{100.0 * x:.{p}f}%"


def reporte(desc: dict, ev: dict | None, sanity: dict, log=sys.stdout) -> None:
    print("\n── Muestra completa, mismo calendario (descriptivo, §6) ──────────", file=log)
    print(f"{'brazo':<26}{'CAGR':>9}{'Sharpe':>9}{'caída':>9}  desde → hasta", file=log)
    for nombre, m in desc["completa"].items():
        sh = "—" if m["sharpe"] is None else f"{m['sharpe']:.2f}"
        print(
            f"{nombre:<26}{_pct(m['cagr']):>9}{sh:>9}{_pct(m['max_dd'], 1):>9}  {m['desde']} → {m['hasta']}",
            file=log,
        )
    print(f"\n  w de SPY_caja = {desc['w']} · w de UNIV_caja = {desc['w_univ']}", file=log)
    print(
        f"  caída del vivo en la calibración (→ {CALIBRACION_HASTA}): {_pct(desc['dd_calibracion_vivo'], 1)}",
        file=log,
    )
    print(f"  exposición media del vivo: {_pct(desc['exposicion_vivo'], 1)}", file=log)

    print("\n── Sanity (§5) ───────────────────────────────────────────────────", file=log)
    r = sanity["repro_t170"]
    print(
        f"  1. {VIVO_SIN_REGIMEN} reproduce la T170: CAGR {_pct(r['cagr'])} vs {_pct(r['cagr_t170'])} · "
        f"Sharpe {r['sharpe']:.2f} vs {r['sharpe_t170']:.2f} · tomados {r['n_taken']} vs {r['n_taken_t170']} "
        f"→ {'OK' if r['OK'] else 'FALLA'}",
        file=log,
    )
    cp = sanity["control_pasivo"]
    print(
        f"  2. control del pasivo: w=1 err {cp['err_w1']:.2e}, w=0 err {cp['err_w0']:.2e} → "
        f"{'OK' if cp['OK'] else 'FALLA'}",
        file=log,
    )
    print(f"  3. contabilidad: {'OK' if sanity['contabilidad_ok'] else 'FALLA'}", file=log)
    print(
        f"  4. el escalado muerde: {_pct(sanity['fraccion_escalada'], 1)} de las entradas "
        f"(entre {_pct(ESCALADO_MIN, 0)} y {_pct(ESCALADO_MAX, 0)}) → {'OK' if sanity['escalado_ok'] else 'FALLA'}",
        file=log,
    )
    print(f"  5. w = {sanity['w']} → {'OK' if sanity['w_ok'] else 'FALLA'}", file=log)
    print(f"\n  >>> CORRIDA {'VÁLIDA' if sanity['VALIDA'] else 'INVÁLIDA — sin veredicto'}", file=log)
    if ev is None:
        return

    print("\n── Fuera de muestra, fold por fold ───────────────────────────────", file=log)
    print(f"{'fold':<6}{'test':<24}{'vivo':>9}{'pasivo':>9}{'Δ pp':>9}", file=log)
    for i, f in enumerate(ev["folds"], 1):
        print(
            f"{i:<6}{f['test']:<24}{_pct(f['vivo']):>9}{_pct(f['pasivo']):>9}{f['delta_pp']:>+9.2f}", file=log
        )
    print(
        f"{'agreg.':<6}{OOS_DESDE + '..' + OOS_HASTA:<24}{_pct(ev['cagr_oos_vivo']):>9}"
        f"{_pct(ev['cagr_oos_pasivo']):>9}{100.0 * ev['dcagr_oos']:>+9.2f}",
        file=log,
    )
    if not sanity["VALIDA"]:
        return
    b = ev["boot"]
    c = ev["condiciones"]
    print("\n── El gate (§4: hacen falta las cuatro) ──────────────────────────", file=log)
    print(
        f"  C1 ΔCAGR OOS ≥ +{100 * C1_MIN_DCAGR:.2f} pp: {100 * ev['dcagr_oos']:+.2f} pp → {'PASA' if c['C1'] else 'no'}",
        file=log,
    )
    print(
        f"  C2 el pasivo gana ≥ {C2_MIN_FOLDS} de 5 folds: {ev['folds_gana_pasivo']}/5 → {'PASA' if c['C2'] else 'no'}",
        file=log,
    )
    print(
        f"  C3 IC95% pareado [{100 * b['ci_low']:+.2f}, {100 * b['ci_high']:+.2f}] pp, p={b['p_value']:.3f} "
        f"→ {'PASA' if c['C3'] else 'no'}",
        file=log,
    )
    print(
        f"  C4 caída OOS pasivo {_pct(ev['dd_oos_pasivo'], 1)} ≤ vivo {_pct(ev['dd_oos_vivo'], 1)} + "
        f"{100 * C4_DD_TOL:.1f} pp → {'PASA' if c['C4'] else 'no'}",
        file=log,
    )
    print(f"\n  >>> VEREDICTO: {ev['veredicto']}", file=log)


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ACTIVO-CONTRA-PASIVO-DE-IGUAL-RIESGO (tarea 456)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--allow-stale-artifacts", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--tajada-del-dia",
        action="store_true",
        help="tarea 466: las compras escaladas del día reciben la misma tajada, como en vivo "
        "(la re-lectura; sin la opción, el sizing secuencial con que se publicó la 456)",
    )
    args = p.parse_args(argv)
    log = sys.stderr if args.json else sys.stdout
    cache = SimCache(Path(args.cache_dir) if args.cache_dir else None, None)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)
    entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not entries:
        print("Sin entradas BUY.", file=sys.stderr)
        return 1

    # La huella de la población se VERIFICA (tarea 87), como en la T219.
    esperado = POPULATION_LIVE_ACCT2.tickers_fp
    actual = universe_fingerprint(args.universe)
    print(f"Población: {args.universe} · huella {actual} (pre-registro: {esperado})", file=log)
    if esperado and actual and actual != esperado:
        print(
            f"*** ABORTA — la población NO es la del pre-registro: {actual} contra {esperado} ***",
            file=sys.stderr,
        )
        return 4

    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts, file=log)
        announce_signal_store(
            bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts, file=log
        )
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
        tajada_del_dia=args.tajada_del_dia,
        file=log,
    )
    print(
        f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)} · "
        f"factor de régimen vivo: {LIVE_REGIME_SCALE_FACTOR} · SPY {spy_bars[0][0]} → {spy_bars[-1][0]}",
        file=log,
    )

    common = {
        **_common_kwargs(args),
        "so_params": _so_params(T219_BASELINE),
        "tajada_del_dia": args.tajada_del_dia,
    }
    print(
        "Sizing: "
        + (
            "TAJADA POR DÍA (tarea 466, la re-lectura)"
            if args.tajada_del_dia
            else "secuencial (el publicado)"
        ),
        file=log,
    )
    run_tag = f"{window}|n{len(bars_by)}|e{len(entries)}|mp{args.max_positions}|cap{args.cap_days}|${args.capital:.2f}"
    filtro = make_entry_filter(build_regime_series(spy_bars), mode="scale", factor=LIVE_REGIME_SCALE_FACTOR)
    tag_sin, tag_vivo = tags_de_corrida(run_tag, args.tajada_del_dia)
    print(f"  corriendo {VIVO_SIN_REGIMEN}…", file=log, flush=True)
    res_sin = cache.run(tag_sin, lambda: simulate_portfolio(entries, bars_by, sigs_by, **common))
    print(f"  corriendo {VIVO} (régimen ×{LIVE_REGIME_SCALE_FACTOR})…", file=log, flush=True)
    res_vivo = cache.run(
        tag_vivo,
        lambda: simulate_portfolio(entries, bars_by, sigs_by, entry_filter=filtro, **common),
    )

    costos = CostModel()
    costo = costos.commission + costos.slippage
    spy_cierres = {b[0]: b[4] for b in spy_bars}
    cierres_univ = {t: {b[0]: b[4] for b in bs} for t, bs in bars_by.items()}

    def _pasivos(res: PortfolioResult) -> dict[str, Any]:
        """El pasivo de cada vivo, sobre SU calendario y con SU caída de calibración."""
        cal = [d for d, _ in res.equity_curve]
        spy = serie_en_calendario(cal, spy_cierres)
        univ = indice_universo(cal, cierres_univ, costo=costo)
        cal_c = [d for d in cal if d <= CALIBRACION_HASTA]
        dd_obj = max_drawdown(cortar(res.equity_curve, None, CALIBRACION_HASTA))
        w = w_por_regla(dd_obj, cal_c, spy, costo=costo, capital=args.capital)
        w_u = w_por_regla(dd_obj, cal_c, univ, costo=costo, capital=args.capital)
        return {
            "cal": cal,
            "spy": spy,
            "dd_obj": dd_obj,
            "w": w,
            "w_univ": w_u,
            "spy_caja": mezcla_constante(cal, spy, w, costo=costo, capital=args.capital) if w else None,
            "univ_caja": mezcla_constante(cal, univ, w_u, costo=costo, capital=args.capital) if w_u else None,
            "spy_solo": mezcla_constante(cal, spy, 1.0, costo=costo, capital=args.capital),
        }

    pv = _pasivos(res_vivo)
    ps = _pasivos(res_sin)
    sum_vivo, sum_sin = summarise(res_vivo), summarise(res_sin)
    control = control_pasivo(pv["cal"], pv["spy"], args.capital)
    sanity = evaluar_sanity(sum_sin, sum_vivo, control, fraccion_escalada(res_vivo), pv["w"])

    if pv["spy_caja"] is None:  # §5.5: ninguna w cumple, no hay nada que comparar
        sin_w = {"completa": {}, "w": None, "w_univ": None, "dd_calibracion_vivo": pv["dd_obj"]}
        reporte({**sin_w, "exposicion_vivo": exposicion_media(res_vivo, bars_by)}, None, sanity, log)
        return 2
    ev = evaluar(res_vivo.equity_curve, pv["spy_caja"], resamples=args.resamples)
    ev_sin = (
        evaluar(res_sin.equity_curve, ps["spy_caja"], resamples=args.resamples) if ps["spy_caja"] else None
    )
    ev_univ = (
        evaluar(res_vivo.equity_curve, pv["univ_caja"], resamples=args.resamples) if pv["univ_caja"] else None
    )

    completa = {
        VIVO: metricas(res_vivo.equity_curve),
        VIVO_SIN_REGIMEN: metricas(res_sin.equity_curve),
        f"{SPY_CAJA} (w={pv['w']})": metricas(pv["spy_caja"]),
        f"{UNIV_CAJA} (w={pv['w_univ']})": metricas(pv["univ_caja"]) if pv["univ_caja"] else None,
        "SPY (w=1)": metricas(pv["spy_solo"]),
    }
    completa = {k: v for k, v in completa.items() if v is not None}
    regimen = {
        VIVO: regime_window_returns(retornos_diarios(res_vivo.equity_curve)),
        SPY_CAJA: regime_window_returns(retornos_diarios(pv["spy_caja"])),
    }
    desc = {
        "completa": completa,
        "w": pv["w"],
        "w_univ": pv["w_univ"],
        "w_sin_regimen": ps["w"],
        "dd_calibracion_vivo": pv["dd_obj"],
        "exposicion_vivo": exposicion_media(res_vivo, bars_by),
        "regimen": regimen,
        "vivo_sin_regimen_vs_spy_caja": ev_sin,
        "vivo_vs_univ_caja": ev_univ,
    }
    reporte(desc, ev, sanity, log)
    print("\n── Descriptivo (no decide) ───────────────────────────────────────", file=log)
    for etiqueta, e in (("vivo_sin_regimen vs SPY_caja", ev_sin), ("vivo vs UNIV_caja", ev_univ)):
        if e:
            print(
                f"  {etiqueta}: ΔCAGR OOS {100 * e['dcagr_oos']:+.2f} pp · folds {e['folds_gana_pasivo']}/5 · "
                f"IC [{100 * e['boot']['ci_low']:+.2f}, {100 * e['boot']['ci_high']:+.2f}] · {e['veredicto']}",
                file=log,
            )
    for brazo, rr in regimen.items():
        print(
            f"  ventanas de régimen, {brazo}: " + ", ".join(f"{k} {100 * v:+.1f}%" for k, v in rr.items()),
            file=log,
        )

    if args.json:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "prereg": "docs/activo_pasivo_prereg_t456_2026-11-23.md",
                "window": str(window),
                "n_tickers": len(bars_by),
                "n_entries": len(entries),
                "sanity": sanity,
                "gate": ev,
                "descriptivo": desc,
            },
            sys.stdout,
            indent=2,
            default=str,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
