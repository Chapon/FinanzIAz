"""
Runner de EXIT-POLICY-REDECIDE — **Tarea 170**.

Pre-registro **congelado antes de escribir esto**:
``docs/exit_policy_prereg_t170_2026-09-10.md`` (commit `207b165`).

Qué decide, y en qué se diferencia del T37
------------------------------------------
La pregunta es **¿hay evidencia para mover la política de salida viva?** —de
``soff_t2.0`` (stop duro apagado + trailing 2.0×ATR, lo que corre hoy en la cuenta 2)
a ``s2.0_t2.0`` (la que tenía evidencia antes del 2026-08-27)—. Y la diferencia con
el T37 está en el eje que se le rompió:

**Acá NO HAY SELECCIÓN.** El T37 mide el **procedimiento**: en cada fold elige la
celda con mejor CAGR de train y la cobra en el test (``dcagr_oos = wf["proc"] −
wf["base"]``, y su bootstrap corre sobre ``wf["star"]``, el brazo que eligen los
datos). Eso introduce sesgo de selección, y es lo que hizo que su margen fuera de
muestra no generalizara: el 2026-09-10 el mismo experimento pasó de **SHIP** a
**NO-SHIP** (tarea 167). Este runner compara **dos brazos fijos, nombrados por
procedencia antes de mirar un número**, sobre los mismos cinco folds. Sin selección
no hay nada que sobreajustar.

Las cinco condiciones (§4 del pre-registro, umbrales del T37 sin tocar uno) van
sobre el Δ = **desafiante − vivo**, y hacen falta **todas** para mover la política:

===  =========================================  ==================
D1   ΔCAGR fuera de muestra (5 folds agregados)  ≥ +1.00 pp
D2   folds en que el desafiante gana             ≥ 4 de 5
D3   cola por trade: Δ(peor) **y** Δ(p1)         ≥ −2.00 pp
D4   bootstrap pareado por bloques (20 ruedas)   IC95% inferior > 0
D5   maxDD de cartera, in-sample **y** OOS       ≤ vivo +1.00 pp
===  =========================================  ==================

La asimetría es deliberada: para **mover** una política viva se pide evidencia en
todos los ejes; para **dejarla** no se pide nada. El que propone el cambio carga la
prueba, y el resultado esperado —escrito en el pre-registro antes de correr— es **NO
MOVER**.

La pregunta (B), descriptiva
---------------------------
¿La elección de celda en la rejilla stop×trail es **decidible** con esta muestra? La
serie 26 → 26b → 34 → 37 → 167 minó la misma rejilla cinco veces y eligió distinto
cada vez. Se mide el ΔCAGR OOS de las 15 celdas contra el vivo con su IC95%, y la
**regla de lectura está congelada**: si el IC de ninguna excluye el cero, se publica
*«no es decidible con esta muestra»* y la rejilla queda cerrada hasta que haya
muestra nueva. Una celda que sí lo excluya **no se cabla**: abre su propio
pre-registro, porque elegir entre 15 por su intervalo necesita un gate de
multiplicidad que esta tarea no define.

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py`` ni ninguna perilla viva.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.harness_config import (
    LIVE_HARD_STOP_ENABLED,
    LIVE_MAX_POSITIONS,
    LIVE_STOP_MULT,
    LIVE_TRAIL_MULT,
    LIVE_UNIVERSE_FILE,
    POPULATION_LIVE_ACCT2,
    REPRO_OK,
    WINDOW_REFRESH_2026_09_01_LIVE,
    SignalStoreGapError,
    StaleArtifactError,
    announce,
    announce_artifacts,
    announce_signal_store,
    artifact_window,
    reproduction_check,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import cagr
from analysis.ruin_injection import ticker_years
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import paired_block_bootstrap, regime_for_date
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_rank_neutral_t39 import aligned_daily
from scripts.run_stop_cal_replay_t26 import (
    NO_STOP,
    RANDOM_KEEP_PROB,
    _oracle_stop_filter,
    random_stop_filter,
    summarise,
)
from scripts.run_stop_value_t37 import (
    CAP_DAYS,
    EVAL_MODE,
    FILL_MODE,
    FOLDS,
    LIVE_GATES,
    ORACLE_ARM,
    RANDOM_KEEP_ARM,
    REPRO_TOL,
    SANITY_ORACLE_VS_RANDOM_CAGR,
    SANITY_ORACLE_VS_RANDOM_DD,
    SimCache,
    _prev_day,
    _repro_targets,
    arm_name,
    arm_params,
    entries_between,
    grid_cells,
    max_drawdown,
    tail_stats,
)
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

# ── Los dos brazos del gate (CONGELADOS — §3 del pre-registro) ───────────────
# Se eligen por PROCEDENCIA, no por su número: uno es lo que corre hoy en la cuenta 2 y
# el otro es lo que tenía evidencia antes del 2026-08-27. No se agrega, saca ni re-nombra
# ninguno después de congelar.
#
# **La celda de la política se DERIVA de los espejos, no se clava** (regla de la tarea 134,
# y el guard me cazó clavándola). Acá decía `(NO_STOP, 2.0)`, que hoy es correcto y habría
# quedado viejo exactamente como el rótulo que la **169** acaba de arreglar: si Chapa mueve
# la política, el brazo la sigue, y `test_los_espejos_siguen_al_settings_VIVO` (tarea 130)
# mantiene los espejos honestos contra el `settings.json`.
POLICY_CELL = ((LIVE_STOP_MULT if LIVE_HARD_STOP_ENABLED else NO_STOP), LIVE_TRAIL_MULT)
CHALLENGER_CELL = (2.0, 2.0)  # `s2.0_t2.0` — la que tenía evidencia antes del 2026-08-27
POLICY_ARM = arm_name(*POLICY_CELL)
CHALLENGER_ARM = arm_name(*CHALLENGER_CELL)

# ── Umbrales (CONGELADOS — son los del T37, sin tocar uno) ───────────────────
D1_MIN_DCAGR_OOS = 0.0100  # ≥ +1.00 pp
D2_MIN_FOLDS = 4  # de 5
D3_TAIL_TOL_PTS = 2.00  # Δ(peor) y Δ(p1) ≥ −2.00 pp
D5_DD_TOL = 0.0100  # maxDD ≤ vivo +1.00 pp

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345

_CACHE = SimCache(None, None)


def arm_fingerprint(kw: dict) -> str:
    """Huella de **lo que el brazo computa**, para que entre en la clave de cache.

    El tag de las simulaciones identificaba al brazo por **nombre**, y eso tiene un
    agujero en el que me caí: al corregir sobre qué celda se montan los brazos de sanity
    (el `stop_filter` sólo gatea el stop duro, así que montados sobre el stop **apagado**
    eran un no-op), el nombre siguió siendo `ORACULO_STOP` y la corrida **reusó el
    resultado viejo del cache** — salió `ΔCAGR +0.00` y la corrida quedó inválida por un
    brazo que ya estaba arreglado.

    Es textual lo que el T37 dice de su propio tag: *«un cache que sobrevive a un cambio de
    config es un bug de reproducibilidad, no una optimización»*. Acá la clave pasa a
    incluir los multiplicadores, los modos y **qué filtro** se le puso.
    """
    a = kw["atr_p"]
    sf = kw.get("stop_filter")
    if sf is None:
        sf_id = "-"
    else:
        # El closure de `random_stop_filter` no expone su tasa, así que se agrega explícita:
        # dos controles con distinta `keep_prob` son dos cómputos distintos.
        sf_id = getattr(sf, "__qualname__", type(sf).__name__).split(".")[0]
        if sf_id == "random_stop_filter":
            sf_id += f"@{RANDOM_KEEP_PROB}"
    return (
        f"s{a.stop_mult:g}|t{a.trail_mult:g}|{kw['eval_mode']}|{kw['fill_mode']}"
        f"|g{int(kw['live_gates'])}|{sf_id}"
    )


def _sim(tag: str, entries, bars_by, sigs_by, **kw) -> PortfolioResult:
    return _CACHE.run(
        f"{tag}|{arm_fingerprint(kw)}", lambda: simulate_portfolio(entries, bars_by, sigs_by, **kw)
    )


# ── §4 — el gate, sin selección ──────────────────────────────────────────────


def fixed_arms_walk_forward(entries, bars_by, sigs_by, common: dict, *, tag: str, log=sys.stdout) -> dict:
    """Los dos brazos FIJOS sobre los cinco folds, con el equity compuesto.

    Es el walk-forward del T37 **sin el paso que elige**: mismos folds, mismas
    ventanas de test, misma composición de capital entre folds. Lo único que se saca
    es el ``max(cells, key=train_cagr)``, que es de donde venía el sesgo.

    El train **no se corre**: sin selección no hay nada que entrenar. Se deja el
    conteo de entradas de train en el reporte sólo para que las ventanas se puedan
    comparar con las del T37 fold por fold.
    """
    per_fold: list[dict] = []
    curves: dict[str, list[tuple[str, float]]] = {POLICY_ARM: [], CHALLENGER_ARM: []}
    eq = {POLICY_ARM: float(common["initial_capital"]), CHALLENGER_ARM: float(common["initial_capital"])}

    for fi, (train_end, test_lo, test_hi) in enumerate(FOLDS, 1):
        n_train = len(entries_between(entries, bars_by, None, _prev_day(train_end)))
        test = entries_between(entries, bars_by, test_lo, test_hi)
        print(f"    fold {fi}/{len(FOLDS)} — test {len(test)} entradas …", file=log, flush=True)

        fold: dict[str, Any] = {
            "train_end": train_end,
            "test": f"{test_lo}..{test_hi}",
            "n_train": n_train,
            "n_test": len(test),
        }
        for name, cell in ((POLICY_ARM, POLICY_CELL), (CHALLENGER_ARM, CHALLENGER_CELL)):
            r = _sim(
                f"wf{fi}|test|{name}|eq{eq[name]:.6f}|{tag}",
                test,
                bars_by,
                sigs_by,
                **arm_params(*cell),
                **{**common, "initial_capital": eq[name]},
            )
            curves[name].extend(r.equity_curve)
            eq[name] = r.final_equity
            fold[f"oos_cagr_{name}"] = cagr(r.equity_curve)
        fold["delta_pp"] = 100.0 * (fold[f"oos_cagr_{CHALLENGER_ARM}"] - fold[f"oos_cagr_{POLICY_ARM}"])
        per_fold.append(fold)

    agg = {
        name: {"cagr": cagr(curves[name]), "max_dd": max_drawdown(curves[name]), "final_equity": eq[name]}
        for name in (POLICY_ARM, CHALLENGER_ARM)
    }
    return {
        "per_fold": per_fold,
        "agg": agg,
        "dcagr_oos": agg[CHALLENGER_ARM]["cagr"] - agg[POLICY_ARM]["cagr"],
        "dd_delta_oos": agg[CHALLENGER_ARM]["max_dd"] - agg[POLICY_ARM]["max_dd"],
        "folds_won": sum(1 for f in per_fold if f["delta_pp"] > 0.0),
    }


def evaluate(wf: dict, summaries: dict, tails: dict, boot) -> dict:
    """Las cinco condiciones. **Hacen falta todas** para mover la política."""
    live, chal = summaries[POLICY_ARM], summaries[CHALLENGER_ARM]
    d_worst = tails[CHALLENGER_ARM]["worst"] - tails[POLICY_ARM]["worst"]
    d_p1 = tails[CHALLENGER_ARM]["p1"] - tails[POLICY_ARM]["p1"]
    dd_in = chal["max_dd"] - live["max_dd"]

    d1 = wf["dcagr_oos"] >= D1_MIN_DCAGR_OOS
    d2 = wf["folds_won"] >= D2_MIN_FOLDS
    d3 = d_worst >= -D3_TAIL_TOL_PTS and d_p1 >= -D3_TAIL_TOL_PTS
    d4 = boot is not None and boot.ci_low > 0.0
    d5 = dd_in <= D5_DD_TOL and wf["dd_delta_oos"] <= D5_DD_TOL

    mover = bool(d1 and d2 and d3 and d4 and d5)
    return {
        "D1": d1,
        "D2": d2,
        "D3": d3,
        "D4": d4,
        "D5": d5,
        "mover": mover,
        "dcagr_oos": wf["dcagr_oos"],
        "folds_won": wf["folds_won"],
        "tail_worst_delta": d_worst,
        "tail_p1_delta": d_p1,
        "dd_delta_insample": dd_in,
        "dd_delta_oos": wf["dd_delta_oos"],
        "dcagr_insample": chal["cagr"] - live["cagr"],
        "veredicto": (
            "MOVER la política a " + CHALLENGER_ARM
            if mover
            else "NO MOVER — la política viva (" + POLICY_ARM + ") queda como está"
        ),
    }


# ── §5 — sanity del instrumento ──────────────────────────────────────────────


def evaluate_sanity(summaries: dict, repro: dict) -> dict:
    """Si alguno falla, la corrida es INVÁLIDA y no hay veredicto."""
    orac, azar = summaries[ORACLE_ARM], summaries[RANDOM_KEEP_ARM]
    d_cagr = orac["cagr"] - azar["cagr"]
    d_dd = orac["max_dd"] - azar["max_dd"]
    s = {
        "accounting": all(s_["accounting_ok"] for s_ in summaries.values()),
        "oracle_vs_random_cagr": d_cagr,
        "oracle_vs_random_dd": d_dd,
        "oracle_quality_cagr_ok": d_cagr >= SANITY_ORACLE_VS_RANDOM_CAGR,
        "oracle_quality_dd_ok": d_dd <= -SANITY_ORACLE_VS_RANDOM_DD,
        "repro_ok": all(v["state"] == REPRO_OK for v in repro.values()),
        "repro": repro,
    }
    s["all_ok"] = bool(
        s["accounting"] and s["oracle_quality_cagr_ok"] and s["oracle_quality_dd_ok"] and s["repro_ok"]
    )
    return s


# ── §7 — la pregunta (B), descriptiva ────────────────────────────────────────


def grid_descriptive(
    entries, bars_by, sigs_by, common: dict, results: dict, *, tag: str, resamples: int, log=sys.stdout
) -> dict:
    """ΔCAGR OOS y IC95% de **cada celda** contra el vivo. NO es un gate.

    La regla de lectura está congelada en el §7 del pre-registro: si ningún IC
    excluye el cero, *«no es decidible con esta muestra»* y la rejilla queda cerrada.
    """
    celdas = [c for c in grid_cells() if arm_name(*c) != POLICY_ARM]
    tests = [entries_between(entries, bars_by, lo, hi) for _, lo, hi in FOLDS]

    def _oos_curve(cell: tuple[float, float]) -> list[tuple[str, float]]:
        """La curva OOS encadenada de una celda, con el equity compuesto entre folds."""
        name = arm_name(*cell)
        eq = float(common["initial_capital"])
        curve: list[tuple[str, float]] = []
        for fi, test in enumerate(tests, 1):
            r = _sim(
                f"wf{fi}|test|{name}|eq{eq:.6f}|{tag}",
                test,
                bars_by,
                sigs_by,
                **arm_params(*cell),
                **{**common, "initial_capital": eq},
            )
            curve.extend(r.equity_curve)
            eq = r.final_equity
        return curve

    # El brazo vivo se corre **una sola vez**: su trayectoria no depende de la celda
    # contra la que se lo compara, y `SimCache` sin `--cache-dir` no memoiza nada, así
    # que calcularlo adentro del loop serían 14 corridas idénticas pagadas 14 veces.
    curve_l = _oos_curve(POLICY_CELL)
    cagr_l = cagr(curve_l)

    out: dict[str, dict] = {}
    for i, cell in enumerate(celdas, 1):
        name = arm_name(*cell)
        print(f"    celda {i}/{len(celdas)} {name} …", file=log, flush=True)
        curve_c = _oos_curve(cell)
        daily = aligned_daily(results, [POLICY_ARM, name])
        b = paired_block_bootstrap(
            [r for _, r in daily[POLICY_ARM]],
            [r for _, r in daily[name]],
            block=BOOT_BLOCK,
            n_resamples=resamples,
            seed=BOOT_SEED,
        )
        out[name] = {
            "dcagr_oos": cagr(curve_c) - cagr_l,
            "ci_low": b.ci_low,
            "ci_high": b.ci_high,
            "p_value": b.p_value,
            "excludes_zero": bool(b.ci_low > 0.0 or b.ci_high < 0.0),
        }
    decidible = [n for n, v in out.items() if v["excludes_zero"]]
    return {"celdas": out, "decidibles": decidible, "es_decidible": bool(decidible)}


# ── Reporte ──────────────────────────────────────────────────────────────────


def _f(x, w=9, p=2, suf="") -> str:
    return f"{'—':>{w}}" if x is None else f"{100 * x if suf == '%' else x:>{w}.{p}f}{suf}"


def _report(summaries, wf, verdict, sanity, boot, grid, log=sys.stdout) -> None:
    hdr = f"{'brazo':<18}{'CAGR':>10}{'Sharpe':>9}{'maxDD':>9}{'tomad':>8}"
    print("\n" + hdr, file=log)
    print("-" * len(hdr), file=log)
    for n in (POLICY_ARM, CHALLENGER_ARM, ORACLE_ARM, RANDOM_KEEP_ARM):
        s = summaries[n]
        tag = {POLICY_ARM: "LA POLÍTICA VIVA", CHALLENGER_ARM: "*DESAFIANTE"}.get(n, "sanity")
        print(
            f"{n:<18}{_f(s['cagr'], 10, 2, '%')}{_f(s['sharpe'], 9, 2)}"
            f"{_f(s['max_dd'], 9, 1, '%')}{s['n_taken']:>8}  {tag}",
            file=log,
        )

    print("\n§5 — Sanity del instrumento:", file=log)
    print(f"  [{'OK' if sanity['accounting'] else 'FALLA'}] contabilidad", file=log)
    print(
        f"  [{'OK' if sanity['oracle_quality_cagr_ok'] else 'FALLA'}] oráculo vs control igualado — "
        f"ΔCAGR ≥ +{100 * SANITY_ORACLE_VS_RANDOM_CAGR:.2f} pp ({100 * sanity['oracle_vs_random_cagr']:+.2f})",
        file=log,
    )
    print(
        f"  [{'OK' if sanity['oracle_quality_dd_ok'] else 'FALLA'}] oráculo vs control igualado — "
        f"ΔmaxDD ≤ −{100 * SANITY_ORACLE_VS_RANDOM_DD:.2f} pp ({100 * sanity['oracle_vs_random_dd']:+.2f})",
        file=log,
    )
    for n, v in sanity["repro"].items():
        print(
            f"  [{v['state']:<14}] reproduce {n}: {100 * v['actual']:.2f}% (esp. {100 * v['expected']:.2f}%)",
            file=log,
        )

    print("\n§4 — Fuera de muestra, fold por fold (dos brazos FIJOS, sin selección):", file=log)
    h2 = f"{'fold':<6}{'test':<24}{'entradas':>9}{'vivo':>9}{'desafiante':>12}{'Δ pp':>9}"
    print(h2, file=log)
    print("-" * len(h2), file=log)
    for i, f_ in enumerate(wf["per_fold"], 1):
        print(
            f"{i:<6}{f_['test']:<24}{f_['n_test']:>9}"
            f"{100 * f_[f'oos_cagr_{POLICY_ARM}']:>8.2f}%{100 * f_[f'oos_cagr_{CHALLENGER_ARM}']:>11.2f}%"
            f"{f_['delta_pp']:>+9.2f}",
            file=log,
        )
    print(
        f"{'agregado':<6}{'':<24}{'':>9}{100 * wf['agg'][POLICY_ARM]['cagr']:>8.2f}%"
        f"{100 * wf['agg'][CHALLENGER_ARM]['cagr']:>11.2f}%{100 * wf['dcagr_oos']:>+9.2f}",
        file=log,
    )

    print("\n§4 — Las cinco condiciones (hacen falta TODAS para mover):", file=log)
    filas = [
        ("D1", "ΔCAGR fuera de muestra ≥ +1.00 pp", f"{100 * verdict['dcagr_oos']:+.2f} pp"),
        ("D2", "el desafiante gana en ≥4/5 folds", f"{verdict['folds_won']}/5"),
        (
            "D3",
            "cola: Δ(peor) y Δ(p1) ≥ −2.00 pp",
            f"{verdict['tail_worst_delta']:+.2f} / {verdict['tail_p1_delta']:+.2f} pp",
        ),
        (
            "D4",
            "bootstrap pareado, IC95% inferior > 0",
            "—"
            if boot is None
            else f"[{100 * boot.ci_low:+.2f}, {100 * boot.ci_high:+.2f}] p={boot.p_value:.3f}",
        ),
        (
            "D5",
            "maxDD in-sample Y OOS ≤ vivo +1.00 pp",
            f"{100 * verdict['dd_delta_insample']:+.2f} / {100 * verdict['dd_delta_oos']:+.2f} pp",
        ),
    ]
    for cid, texto, valor in filas:
        print(f"  {cid}  {'PASA ' if verdict[cid] else 'FALLA'} {texto:<42} {valor}", file=log)
    print(
        f"\n  (in-sample el Δ es {100 * verdict['dcagr_insample']:+.2f} pp — descriptivo, no es gate)",
        file=log,
    )

    if grid is not None:
        print("\n§7 — La rejilla, DESCRIPTIVO (ninguna celda se cabla desde acá):", file=log)
        for n, v in sorted(grid["celdas"].items(), key=lambda kv: -kv[1]["dcagr_oos"]):
            marca = " ← excluye el cero" if v["excludes_zero"] else ""
            print(
                f"  {n:<12} ΔCAGR OOS {100 * v['dcagr_oos']:>+7.2f} pp · "
                f"IC95% [{100 * v['ci_low']:+.2f}, {100 * v['ci_high']:+.2f}] p={v['p_value']:.3f}{marca}",
                file=log,
            )
        if grid["es_decidible"]:
            print(
                f"\n  LECTURA (§7): {len(grid['decidibles'])} celda(s) excluyen el cero "
                f"({', '.join(grid['decidibles'])}). NO se cablan: cada una abre su propio "
                "pre-registro, con gate de multiplicidad.",
                file=log,
            )
        else:
            print(
                "\n  LECTURA (§7): **ninguna** celda excluye el cero ⇒ con esta muestra la "
                "elección de celda NO es decidible. La rejilla queda CERRADA hasta que haya "
                "muestra nueva.",
                file=log,
            )

    print("\n" + "=" * 78, file=log)
    if not sanity["all_ok"]:
        print("VEREDICTO: CORRIDA INVÁLIDA — falla un sanity del §5; no hay veredicto.", file=log)
    else:
        print(f"VEREDICTO: {verdict['veredicto']}", file=log)
    print("=" * 78, file=log)


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EXIT-POLICY-REDECIDE (tarea 170)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--no-grid", action="store_true", help="saltea el descriptivo §7 (el gate no cambia)")
    p.add_argument("--allow-stale-artifacts", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    global _CACHE
    _CACHE = SimCache(Path(args.cache_dir) if args.cache_dir else None, None)

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

    window = artifact_window(bars_by)
    run_tag = (
        f"{window}|u{args.universe}|n{len(bars_by)}|e{len(entries)}"
        f"|mp{args.max_positions}|cap{args.cap_days}|cap${args.capital:.2f}"
        f"|{EVAL_MODE}|{FILL_MODE}|g{int(LIVE_GATES)}"
    )
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts, file=log)
        announce_signal_store(
            bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts, file=log
        )
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3

    cfg = announce(
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
        f"ticker-años: {ticker_years(bars_by):.0f}",
        file=log,
    )
    print(
        f"GATE sin selección: {POLICY_ARM} (la política VIVA) vs {CHALLENGER_ARM} "
        f"(la que tenía evidencia antes del 2026-08-27)\n",
        file=log,
    )

    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
    )

    # 1. In-sample: los dos del gate + los dos de sanity + la rejilla si va el §7.
    celdas = list(grid_cells()) if not args.no_grid else [POLICY_CELL, CHALLENGER_CELL]
    arms: dict[str, dict] = {arm_name(*c): arm_params(*c) for c in celdas}
    # **Los brazos de sanity van sobre la celda donde la perilla ACTÚA**, que es la del
    # desafiante (stop duro a 2.0, la misma base que usa el T37). Montarlos sobre la celda
    # de la política sería montarlos sobre el stop **apagado**: `stop_filter` sólo gatea el
    # stop duro, así que sin stop que disparar el filtro es un no-op y el oráculo, el
    # control y la política salen **idénticos** —medido en el smoke: ΔCAGR +0.00—. Un
    # sanity que no puede distinguir nada pasa o falla por construcción, no por evidencia.
    sanity_kw = {**arm_params(*CHALLENGER_CELL)}
    arms[ORACLE_ARM] = {**sanity_kw, "stop_filter": _oracle_stop_filter}
    arms[RANDOM_KEEP_ARM] = {**sanity_kw, "stop_filter": random_stop_filter(RANDOM_KEEP_PROB)}
    results: dict[str, PortfolioResult] = {}
    for i, (n, kw) in enumerate(arms.items(), 1):
        print(f"  [{args.max_positions} slots] {i}/{len(arms)} {n} …", file=log, flush=True)
        results[n] = _sim(f"grid|{n}|{run_tag}", entries, bars_by, sigs_by, **kw, **common)
    summaries = {n: summarise(r) for n, r in results.items()}
    tails = {n: tail_stats(r) for n, r in results.items()}

    # 2. Reproducción (T48/T52): las mismas anclas del T37, con su población.
    pop = cfg.population(len(entries))
    repro: dict[str, dict] = {}
    for n, esperado in _repro_targets().items():
        if n not in summaries:
            continue
        # Mismos argumentos que el T37, y el `measured_over` es la población del ANCLA
        # (la del universo vivo), no la de esta corrida: comparar el ancla contra sí misma
        # sería el chequeo ciego a la muestra que la tarea 52 vino a cerrar.
        estado, _motivo = reproduction_check(
            summaries[n]["cagr"],
            esperado,
            tol=REPRO_TOL,
            current=window,
            measured_on=WINDOW_REFRESH_2026_09_01_LIVE,
            population=pop,
            measured_over=POPULATION_LIVE_ACCT2,
        )
        repro[n] = {"state": estado, "actual": summaries[n]["cagr"], "expected": esperado}

    # 3. El gate: walk-forward de los dos brazos fijos.
    print("\n§4 — walk-forward de los DOS brazos fijos …", file=log, flush=True)
    wf = fixed_arms_walk_forward(entries, bars_by, sigs_by, common, tag=run_tag, log=log)

    # 4. D4 — bootstrap pareado sobre la serie diaria completa.
    daily = aligned_daily(results, [POLICY_ARM, CHALLENGER_ARM])
    boot = paired_block_bootstrap(
        [r for _, r in daily[POLICY_ARM]],
        [r for _, r in daily[CHALLENGER_ARM]],
        block=BOOT_BLOCK,
        n_resamples=args.resamples,
        seed=BOOT_SEED,
    )

    sanity = evaluate_sanity(summaries, repro)
    verdict = evaluate(wf, summaries, tails, boot)

    # 5. §7 — el descriptivo de la rejilla.
    grid = None
    if not args.no_grid:
        print("\n§7 — descriptivo de la rejilla (NO es gate) …", file=log, flush=True)
        grid = grid_descriptive(
            entries, bars_by, sigs_by, common, results, tag=run_tag, resamples=args.resamples, log=log
        )

    _report(summaries, wf, verdict, sanity, boot, grid, log=log)

    if args.json:
        print(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "window": str(window),
                    "population": str(pop),
                    "live_arm": POLICY_ARM,
                    "challenger_arm": CHALLENGER_ARM,
                    "summaries": {
                        n: {k: v for k, v in s.items() if not isinstance(v, list)}
                        for n, s in summaries.items()
                    },
                    "walk_forward": wf,
                    "sanity": {k: v for k, v in sanity.items() if k != "repro"},
                    "repro": repro,
                    "verdict": verdict,
                    "grid": grid,
                    "boot": {"ci_low": boot.ci_low, "ci_high": boot.ci_high, "p_value": boot.p_value},
                },
                indent=2,
                default=str,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
