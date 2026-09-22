#!/usr/bin/env python
"""Tarea 219 — ¿conviene DEMORAR la salida por señal? (Gate 2b)

Pre-registro congelado: ``docs/signal_exit_delay_prereg_t219_2026-09-22.md``. Lo de acá
implementa esos brazos y esos sanity, y nada más.

**La pregunta NO es la de la tarea 7.** La T7 midió el extremo del eje —``C_A4``,
``sell_fraction=0``, *«la señal no vende»*— y dio **Δ +0,54 pts** con IC95%
[+0,410, +0,666], PBO 0,000, DSR 1,000, ganando in-sample 252/252. El efecto es **real**.
Lo mató (a) el criterio de stress —indistinguible de cero en las tres ventanas, **signo
negativo en bear-2022**— y (b), declarado allá como post-hoc, la **ocupación de slot**:
13,0 días de tenencia contra 7,5, y ajustado por tiempo-capital el +0,536 se cae a +0,088.

Acá se pregunta si existe un punto **intermedio**: ``paper_signal_sell_min_age_bdays``
(vivo en **3**) que la T7 y la T13 dejaron **fijo** y nadie barrió. Demorar no es eliminar.

Uso::

    python scripts/run_signal_exit_delay_t219.py
    python scripts/run_signal_exit_delay_t219.py --json > salida.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_REGIME_SCALE_FACTOR,
    LIVE_SIGNAL_SELL_BYPASS_SCORE,
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
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.scaleout_replay import AtrParams, CostModel, ScaleOutParams
from analysis.walkforward_power import paired_block_bootstrap, regime_for_date
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_stop_cal_replay_t26 import NO_STOP, summarise
from scripts.run_stop_value_t37 import CAP_DAYS, EVAL_MODE, FILL_MODE, LIVE_GATES
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

# ── Brazos (CONGELADOS — §3 del pre-registro) ────────────────────────────────
#
# Los cuatro del gate mueven UNA perilla: `min_age_bdays`. `bypass_score` queda fijo en
# 0.25 en todos — mover dos a la vez haría indecidible cuál movió el resultado.
BASELINE = "age3"  # la política viva
_EDADES = {"age3": 3, "age5": 5, "age10": 10, "age20": 20}
DESAFIANTES = ("age5", "age10", "age20")
# Referencia, NO desafiante: la re-corrida de C_A4 en ESTA población, para saber cuánto
# del +0,54 de la T7 hay disponible acá (126 tickers x 10 slots contra 41 x 5).
REFERENCIA = "C_A4_repl"
ORACULO = "ORACULO_SALIDA"
AZAR = "AZAR_MISMA_TASA"

ORACLE_HORIZON = 20  # mismas ruedas de look-ahead que el oráculo de la T26
AZAR_SEED = 20260922

# Sanity §5: el oráculo tiene que separarse del azar igualado en tasa. Mismos umbrales
# que la T26/T37 usaron para el suyo — no se re-eligen acá.
# En FRACCIÓN de CAGR, no en pp: es la convención de los demás umbrales de magnitud
# (`run_stop_value_t37.py:SANITY_ORACLE_VS_RANDOM_CAGR = 0.0150`) y la que el guard de
# la tarea 164 verifica — un 2.0 clasificado como magnitud lo caza por absurdo.
SANITY_ORACULO_VS_AZAR_CAGR = 0.0200  # +2 pp de CAGR
BOOT_RESAMPLES = 2000

# ── El sanity que CAZÓ el bug de esta tarea (enmienda 2 del pre-registro) ────
#
# El baseline `age3` es, por construcción, el mismo brazo que la **T170** publicó como
# `soff_t2.0` sobre esta MISMA población: misma config viva, mismos 126 tickers, misma
# ventana, `ScaleOutParams()` por default (que es `min_age_bdays=3`). Así que tiene que
# reproducir su número **publicado**.
#
# No es decorativo. La primera corrida de esta tarea puso `stop_mult=0.0` creyendo que era
# "stop apagado" —es `NO_STOP=1e9`— y `0.0` pone el stop en el precio de entrada: salió con
# 8.838 trades, tenencia 1,6 días y CAGR −17,9% en TODOS los brazos. Los Δ entre brazos
# seguían pareciendo razonables y la curva seguía siendo monótona: **el veredicto habría
# salido sin que nada lo marcara**. Lo cazó comparar contra un número ya publicado.
#
# Es la referencia correcta justamente porque es EXTERNA a esta corrida — no sale de la
# misma población que se está chequeando, que es el defecto de las tareas 101 y 110.
T170_BASELINE_CAGR = 0.0878  # `soff_t2.0` en docs/exit_policy_t170_2026-09-10.md §1
T170_BASELINE_SHARPE = 0.55
T170_BASELINE_TAKEN = 2531
REPRO_TOL_CAGR = 0.005  # 0,5 pp — holgura para redondeo del doc publicado
REPRO_TOL_SHARPE = 0.05
REPRO_TOL_TAKEN = 0.02  # 2% de los tomados


def _oraculo_salida(bars, i: int, ticker: str = "") -> bool:
    """Deja vender **sólo si vender era lo correcto**: ``close[i+20] < close[i]``.

    Mira el futuro a propósito. Es el contrafactual de la pregunta: si el harness no
    distingue una salida por señal buena de una mala, el Δ de los brazos del gate no
    significa nada y el §5.1 del pre-registro invalida la corrida.

    Cuando no hay barra ``i+20`` **se permite vender**, o sea que el brazo cae al
    comportamiento del baseline en vez de inventar una ventaja — la misma decisión que
    tomó el oráculo de la T26.
    """
    j = i + ORACLE_HORIZON
    if j >= len(bars):
        return True
    return bars[j][4] < bars[i][4]


def azar_misma_tasa(keep_prob: float, seed: int = AZAR_SEED):
    """Supresión **aleatoria** de salidas por señal, a tasa ``keep_prob``.

    Separa dos cosas que el oráculo mezcla: suprimir salidas *y* elegir cuáles. Si el
    oráculo no le gana a esto, el harness responde al **número** de salidas y no a su
    **calidad**, y el sanity no podía pasar por construcción.

    **El sorteo es función pura de (semilla, ticker, fecha), no del índice de barra** —
    la lección de la tarea 164: con el índice, cualquier refresh que corra el `start` del
    cohorte re-sortea el control entero (51% de las decisiones se daban vuelta para las
    MISMAS fechas), y eso dejó inválidas dos corridas con veredicto publicado.
    """

    def _f(bars, i: int, ticker: str = "") -> bool:
        if not ticker:
            raise ValueError(
                "azar_misma_tasa necesita el ticker: sin él el sorteo es el mismo para toda "
                "la cartera en cada fecha (tarea 164). Pasalo vía replay_cycle(..., ticker=...)."
            )
        raw = f"{seed}|{ticker}|{bars[i][0]}".encode()
        u = int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")
        return (u / 2**64) < keep_prob

    return _f


def _so_params(brazo: str) -> ScaleOutParams:
    """`ScaleOutParams` del brazo. Los sanity corren con la config del BASELINE."""
    if brazo == REFERENCIA:
        return ScaleOutParams(
            sell_fraction=0.0, min_age_bdays=_EDADES[BASELINE], bypass_score=LIVE_SIGNAL_SELL_BYPASS_SCORE
        )
    edad = _EDADES.get(brazo, _EDADES[BASELINE])
    return ScaleOutParams(sell_fraction=1.0, min_age_bdays=edad, bypass_score=LIVE_SIGNAL_SELL_BYPASS_SCORE)


def _common_kwargs(args) -> dict[str, Any]:
    """Config viva, igual para todos los brazos (§2 del pre-registro)."""
    return {
        "max_positions": args.max_positions,
        "initial_capital": args.capital,
        "cap_days": args.cap_days,
        # Barreras de la política viva tras la T37/T53, que la T170 re-decidió NO MOVER:
        # hard stop APAGADO, trailing 2.0, TP 4.0.
        #
        # **`NO_STOP` (=1e9) y NO `0.0`.** La primera versión de esto puso `stop_mult=0.0`
        # creyendo que era "apagado", y `0.0` pone el stop EN EL PRECIO DE ENTRADA: dispara
        # ante cualquier baja. La corrida salió con 8.838 trades, tenencia 1,6 días y CAGR
        # −17,9% en TODOS los brazos, contra el +8,78% que la T170 publicó sobre esta misma
        # población. Lo cazó comparar el baseline contra un veredicto ya publicado, no leer
        # el código. `trail_mult` va SIEMPRE explícito: en `None` el trailing sigue al stop,
        # que es el acople que la T7 rompió a propósito.
        "atr_p": AtrParams(stop_mult=NO_STOP, trail_mult=LIVE_TRAIL_MULT, tp_mult=4.0),
        "costs": CostModel(),
        "eval_mode": EVAL_MODE,
        "fill_mode": FILL_MODE,
        "live_gates": LIVE_GATES,
        "regime_of": regime_for_date,
    }


def correr_brazo(brazo: str, entries, bars_by, sigs_by, common: dict, *, keep_prob: float | None = None):
    """Una corrida. Los sanity van por ``senal_filter``; los del gate, por la perilla."""
    kw = dict(common)
    kw["so_params"] = _so_params(brazo)
    if brazo == ORACULO:
        kw["senal_filter"] = _oraculo_salida
    elif brazo == AZAR:
        if keep_prob is None:
            raise ValueError("el brazo de azar necesita la tasa medida del oráculo")
        kw["senal_filter"] = azar_misma_tasa(keep_prob)
    return simulate_portfolio(entries, bars_by, sigs_by, **kw)


# ── Métricas ─────────────────────────────────────────────────────────────────


def tenencia_media(res: PortfolioResult) -> float:
    """Días de tenencia medios. **Va AL LADO del Δ, siempre** (§4 del pre-registro).

    Es la variable que explicó el veredicto de la T7: C_A4 ganaba +0,54 comprando +73%
    de tenencia, y ajustado por tiempo-capital eso se caía a +0,088. Un brazo que gane Δ
    reteniendo mucho más se lee distinto de uno que lo gane reteniendo igual.
    """
    if not res.trades:
        return 0.0
    return sum(t.held_days for t in res.trades) / len(res.trades)


def tasa_salida_senal(res: PortfolioResult) -> float:
    """Fracción de trades que salieron por señal. Con esto se iguala la tasa del azar."""
    if not res.trades:
        return 0.0
    return sum(1 for t in res.trades if "signal" in (t.exit_reason or "")) / len(res.trades)


def por_regimen(res: PortfolioResult) -> dict[str, list[float]]:
    """Retornos por trade agrupados por régimen — la mitad heredada del kill-criteria."""
    out: dict[str, list[float]] = {}
    for t in res.trades:
        out.setdefault(t.regime or "bull_normal", []).append(t.ret)
    return out


def resumen(res: PortfolioResult) -> dict:
    d = dict(summarise(res))
    d["held_days"] = tenencia_media(res)
    d["signal_exit_share"] = tasa_salida_senal(res)
    return d


def evaluar(res: dict[str, dict], regimenes: dict[str, dict[str, list[float]]], boot: dict) -> dict:
    """La regla de §4: hacen falta LAS CUATRO, y la 3 es la que mató a C_A4."""
    base = res[BASELINE]
    veredicto: dict[str, Any] = {}
    # Sólo los brazos presentes: una corrida parcial tiene que poder evaluarse, y si
    # falta uno lo dice `reporte` al no listarlo. Que un brazo falte NO se confunde con
    # que no pase — `evaluar_sanity` decide aparte si la corrida es válida.
    for brazo in (b for b in DESAFIANTES if b in res):
        a = res[brazo]
        d_sharpe = a["sharpe"] - base["sharpe"]
        d_cagr = (a["cagr"] - base["cagr"]) * 100.0
        d_dd = a["max_dd"] - base["max_dd"]
        magnitud_ok = d_sharpe >= 0.10 or d_cagr >= 1.0
        dd_ok = d_dd <= 0.0
        # (3) HEREDADO DE LA T7: el efecto no puede apagarse en stress ni cambiar de signo.
        stress = {}
        signo_ok = True
        for reg, deltas in regimenes.get(brazo, {}).items():
            if reg == "bull_normal":
                continue
            m = sum(deltas) / len(deltas) if deltas else 0.0
            stress[reg] = {"n": len(deltas), "delta_medio_pts": m * 100.0}
            if m < 0:
                signo_ok = False
        veredicto[brazo] = {
            "d_sharpe": d_sharpe,
            "d_cagr_pp": d_cagr,
            "d_maxdd_pp": d_dd * 100.0,
            "held_days": a["held_days"],
            "held_days_vs_base": a["held_days"] - base["held_days"],
            "magnitud_ok": magnitud_ok,
            "maxdd_ok": dd_ok,
            "stress_signo_ok": signo_ok,
            "stress": stress,
            "boot": boot.get(brazo),
            "PASS": bool(magnitud_ok and dd_ok and signo_ok),
        }
    return veredicto


def reproduce_t170(base: dict) -> dict:
    """¿El baseline reproduce el `soff_t2.0` que la T170 publicó? Ver el comentario de
    ``T170_BASELINE_CAGR``: es una referencia **externa** a esta corrida."""
    d_cagr = base["cagr"] - T170_BASELINE_CAGR
    d_sharpe = base["sharpe"] - T170_BASELINE_SHARPE
    d_taken = (base["n_taken"] - T170_BASELINE_TAKEN) / T170_BASELINE_TAKEN
    ok = (
        abs(d_cagr) <= REPRO_TOL_CAGR
        and abs(d_sharpe) <= REPRO_TOL_SHARPE
        and abs(d_taken) <= REPRO_TOL_TAKEN
    )
    return {
        "cagr": base["cagr"],
        "cagr_t170": T170_BASELINE_CAGR,
        "d_cagr_pp": d_cagr * 100.0,
        "sharpe": base["sharpe"],
        "sharpe_t170": T170_BASELINE_SHARPE,
        "d_sharpe": d_sharpe,
        "n_taken": base["n_taken"],
        "n_taken_t170": T170_BASELINE_TAKEN,
        "d_taken_pct": d_taken * 100.0,
        "OK": bool(ok),
    }


def evaluar_sanity(res: dict[str, dict]) -> dict:
    """§5. Si alguno falla ⇒ INVÁLIDA, sin veredicto."""
    o, a, base = res.get(ORACULO), res.get(AZAR), res[BASELINE]
    d_cagr = (o["cagr"] - a["cagr"]) if (o and a) else 0.0
    oraculo_ok = d_cagr >= SANITY_ORACULO_VS_AZAR_CAGR
    # Monotonía esperada, declarada ANTES de correr: el Δ debería ser no decreciente de
    # age3 a C_A4_repl. Si sale en U, se sospecha del instrumento antes que del hallazgo
    # — es lo que le pasó a la T23 con la curva del TP.
    escala = [BASELINE, *DESAFIANTES, REFERENCIA]
    curva = [(b, (res[b]["cagr"] - base["cagr"]) * 100.0) for b in escala if b in res]
    monotona = all(curva[k][1] <= curva[k + 1][1] + 1e-9 for k in range(len(curva) - 1))
    contab = all(v.get("accounting_ok", False) for v in res.values())
    repro = reproduce_t170(base)
    return {
        "repro_t170": repro,
        "oraculo_vs_azar_cagr_pp": d_cagr * 100.0,
        "oraculo_ok": bool(oraculo_ok),
        "curva": curva,
        "monotona": bool(monotona),
        "contabilidad_ok": bool(contab),
        "VALIDA": bool(oraculo_ok and contab and repro["OK"]),
        "nota_monotonia": (
            "la monotonía es un sanity BLANDO: si falla no invalida, pero obliga a "
            "explicar por qué antes de leer el veredicto (§5.3)"
        ),
    }


# ── Reporte ──────────────────────────────────────────────────────────────────


def _f(x, w=9, p=2, suf="") -> str:
    return f"{x:>{w}.{p}f}{suf}" if isinstance(x, (int, float)) else f"{x!s:>{w}}{suf}"


def reporte(res, veredicto, sanity, log=sys.stdout) -> None:
    print("\n── Brazos ────────────────────────────────────────────────────────", file=log)
    print(
        f"{'brazo':<14}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'tenencia':>10}{'%señal':>9}{'trades':>8}",
        file=log,
    )
    for b, v in res.items():
        print(
            f"{b:<14}{_f(v['cagr'] * 100, 8, 2, '%')}{_f(v['sharpe'], 9)}"
            f"{_f(v['max_dd'] * 100, 8, 1, '%')}{_f(v['held_days'], 10, 1)}"
            f"{_f(v['signal_exit_share'] * 100, 8, 0, '%')}{v['n_taken']:>8}",
            file=log,
        )
    print("\n── Sanity (§5) ───────────────────────────────────────────────────", file=log)
    print(
        f"  oráculo − azar (CAGR): {sanity['oraculo_vs_azar_cagr_pp']:+.2f} pp "
        f"(hace falta ≥ {SANITY_ORACULO_VS_AZAR_CAGR * 100:.1f}) → {'OK' if sanity['oraculo_ok'] else 'FALLA'}",
        file=log,
    )
    print(f"  contabilidad: {'OK' if sanity['contabilidad_ok'] else 'FALLA'}", file=log)
    r = sanity["repro_t170"]
    print(
        f"  baseline reproduce la T170 (`soff_t2.0`): CAGR {r['cagr'] * 100:.2f}% vs "
        f"{r['cagr_t170'] * 100:.2f}% ({r['d_cagr_pp']:+.2f}pp) · Sharpe {r['sharpe']:.2f} vs "
        f"{r['sharpe_t170']:.2f} · tomados {r['n_taken']} vs {r['n_taken_t170']} "
        f"({r['d_taken_pct']:+.1f}%) → {'OK' if r['OK'] else 'FALLA'}",
        file=log,
    )
    print("  curva dosis-respuesta: " + " → ".join(f"{b} {d:+.2f}" for b, d in sanity["curva"]), file=log)
    print(
        f"  monotónica: {'sí' if sanity['monotona'] else 'NO — explicar antes de leer el veredicto'}",
        file=log,
    )
    print(f"\n  >>> CORRIDA {'VÁLIDA' if sanity['VALIDA'] else 'INVÁLIDA — sin veredicto'}", file=log)
    if not sanity["VALIDA"]:
        return
    print("\n── Veredicto (§4: hacen falta las cuatro) ────────────────────────", file=log)
    for b, v in veredicto.items():
        print(
            f"\n  {b}:  ΔSharpe {v['d_sharpe']:+.3f} · ΔCAGR {v['d_cagr_pp']:+.2f}pp · "
            f"ΔmaxDD {v['d_maxdd_pp']:+.2f}pp · tenencia {v['held_days']:.1f}d "
            f"({v['held_days_vs_base']:+.1f} vs base)",
            file=log,
        )
        print(
            f"     magnitud {'OK' if v['magnitud_ok'] else 'no'} · "
            f"maxDD {'OK' if v['maxdd_ok'] else 'no'} · "
            f"stress {'OK' if v['stress_signo_ok'] else 'NO (signo negativo en alguna ventana)'}",
            file=log,
        )
        for reg, s in sorted(v["stress"].items()):
            print(f"       {reg:<20} n={s['n']:>4}  Δ {s['delta_medio_pts']:+.3f} pts", file=log)
        print(f"     → {'PASS' if v['PASS'] else 'NO PASA'}", file=log)
    if not any(v["PASS"] for v in veredicto.values()):
        print(
            "\n  NINGÚN BRAZO PASA — no se shipea. El resultado negativo cierra el "
            "último eje sin medir de la familia de salidas.",
            file=log,
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SIGNAL-EXIT-DELAY (tarea 219)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--allow-stale-artifacts", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    log = sys.stderr if args.json else sys.stdout

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

    # §8.2 — el fingerprint de población se VERIFICA antes de leer cualquier Δ, no se
    # imprime. La primera versión de esto sólo lo imprimía, que es el defecto que la tarea
    # 87 vino a cerrar: `127 == 127` seguía afirmando "MISMA muestra" con un ticker
    # cambiado por otro. Y `refresh_live_universe.py` reescribe el archivo EN EL LUGAR,
    # con el mismo nombre, así que la huella es la única señal.
    esperado = POPULATION_LIVE_ACCT2.tickers_fp
    actual = universe_fingerprint(args.universe)
    print(
        f"Población: {args.universe} · huella {actual} (pre-registro: {esperado}) · "
        f"{len(bars_by)} tickers cargados (pre-registro: {POPULATION_LIVE_ACCT2.n_tickers})",
        file=log,
    )
    if esperado and actual and actual != esperado:
        print(
            f"*** ABORTA — la población NO es la del pre-registro: {actual} contra {esperado}. "
            f"Los Δ no son comparables con el pre-registro congelado. ***",
            file=sys.stderr,
        )
        return 4
    if len(bars_by) != POPULATION_LIVE_ACCT2.n_tickers:
        print(
            f"AVISO: cargaron {len(bars_by)} tickers y el pre-registro declara "
            f"{POPULATION_LIVE_ACCT2.n_tickers}. La huella coincide, así que el universo "
            f"DECLARADO es el mismo: es un hipo de carga y va al reporte.",
            file=sys.stderr,
        )

    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts, file=log)
        announce_signal_store(
            bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts, file=log
        )
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3

    window = artifact_window(bars_by)
    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=window,
        eval_mode=EVAL_MODE,
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
        file=log,
    )
    print(
        f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)} · "
        f"factor régimen vivo: {LIVE_REGIME_SCALE_FACTOR}",
        file=log,
    )

    common = _common_kwargs(args)
    corridas: dict[str, PortfolioResult] = {}
    for brazo in (BASELINE, *DESAFIANTES, REFERENCIA, ORACULO):
        print(f"  corriendo {brazo}…", file=log)
        corridas[brazo] = correr_brazo(brazo, entries, bars_by, sigs_by, common)
    # El azar se iguala en tasa AL ORÁCULO, medido en esta corrida y no hardcodeado.
    tasa_oraculo = tasa_salida_senal(corridas[ORACULO])
    tasa_base = tasa_salida_senal(corridas[BASELINE])
    keep = (tasa_oraculo / tasa_base) if tasa_base > 0 else 1.0
    print(f"  corriendo {AZAR} (keep_prob={keep:.3f}, igualado a la tasa del oráculo)…", file=log)
    corridas[AZAR] = correr_brazo(AZAR, entries, bars_by, sigs_by, common, keep_prob=min(1.0, keep))

    res = {b: resumen(r) for b, r in corridas.items()}
    regs = {b: por_regimen(r) for b, r in corridas.items()}
    # Δ por régimen contra el baseline, pareado por trade cuando se puede.
    base_reg = regs[BASELINE]
    deltas_reg: dict[str, dict[str, list[float]]] = {}
    for b in (*DESAFIANTES, REFERENCIA):
        deltas_reg[b] = {}
        for reg, rets in regs[b].items():
            b0 = base_reg.get(reg, [])
            if not rets or not b0:
                continue
            m0 = sum(b0) / len(b0)
            deltas_reg[b][reg] = [r - m0 for r in rets]
    boot: dict[str, Any] = {}
    for b in DESAFIANTES:
        pares = deltas_reg[b].get("bull_normal", [])
        if len(pares) > 30:
            try:
                boot[b] = paired_block_bootstrap(pares, resamples=args.resamples)
            except Exception:
                boot[b] = None

    sanity = evaluar_sanity(res)
    veredicto = evaluar(res, deltas_reg, boot)
    reporte(res, veredicto, sanity, log=log)

    if args.json:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "prereg": "docs/signal_exit_delay_prereg_t219_2026-09-22.md",
                "window": window,
                "n_tickers": len(bars_by),
                "n_entries": len(entries),
                "poblacion_esperada": esperado,
                "brazos": res,
                "sanity": sanity,
                "veredicto": veredicto,
                "keep_prob_azar": keep,
            },
            sys.stdout,
            indent=2,
            default=str,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
