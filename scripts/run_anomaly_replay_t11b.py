"""
Runner del replay del **detector de anomalía precio/volumen** — Tarea 11, Brazo B.

Pre-registro con kill-criteria CONGELADOS:
``docs/anomaly_signal_prereg_t11b_2026-07-23.md``. Requiere el artefacto de señal
PIT (``data/pit_signals/``, tarea 7) + el cache Parquet OHLCV (con volumen).

    python scripts/precompute_pit_signals.py         # una vez, si falta
    python scripts/run_anomaly_replay_t11b.py
    python scripts/run_anomaly_replay_t11b.py --json
    python scripts/run_anomaly_replay_t11b.py --k-random 100   # corrida rápida

Qué hace (fiel al pre-registro)
-------------------------------
1. Arma las entradas del detector para los 9 brazos ``(k, m)`` (§4) y las corre
   sobre el simulador de cartera real (``portfolio_sim``: max_positions=5, capital
   finito, engine-faithful). Sin overlay de régimen (T20) — atribución limpia (§7).
2. Baseline = **Monte Carlo de K carteras aleatorias time-matched** por mes
   calendario al brazo PRIMARIO (§3), mismo capital y mismos exits.
3. Oráculo de validación: las mejores entradas operables por retorno realizado
   (mira el futuro) — confirma que el harness detecta calidad de entrada (si el
   oráculo no despega, el NO-SHIP no vale).
4. Mide CAGR, Sharpe anualizado y maxDD de cartera sobre la curva de equity.
5. Descuenta por selección múltiple: PBO (CSCV) + DSR sobre los 9 brazos.
6. Aplica el kill-criteria (§6). No cambia ningún flag vivo.

Sin red y sin tocar ``finanzias.db``: lee Parquet + los JSON de señal.

Enabler agregado por la **Tarea 38** (no mueve el veredicto publicado): ``--eval-mode``
(regla del engine, 26b) y ``--live-gates`` (gates de re-entrada, T34). Los defaults son
los de la corrida publicada — ``close`` y OFF —, así que reproducirla sigue siendo
``--max-positions 5 --universe data/harness_universe_41_10y.txt --fill-mode resting``.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import numpy as np

from analysis.anomaly_signal import AnomalyParams, build_anomaly_entries
from analysis.exit_replay import AtrParams, Bar
from analysis.harness_config import (
    HARNESS_FILL_MODE,
    LEGACY_FILL_MODE,
    LEGACY_MAX_POSITIONS,
    LIVE_MAX_POSITIONS,
    SignalStoreGapError,
    StaleArtifactError,
    announce,
    announce_artifacts,
    announce_signal_store,
    artifact_window,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import cagr, precompute_oracle_returns, sharpe_annual
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    STRESS_REGIMES,
    _sharpe,
    _skew_kurt,
    deflated_sharpe_ratio,
    pbo_cscv,
    regime_for_date,
)
from scripts.precompute_pit_signals import (
    _load_existing,
    _out_path,
    parse_universe_file,
)

DEFAULT_UNIVERSE = "data/harness_universe_41_10y.txt"

# Brazos pre-registrados (§4): grilla del par umbral (k, m). Todo lo demás fijo.
CANDIDATE_ARMS: dict[str, tuple[float, float]] = {
    "A_k1.5_m1.5": (1.5, 1.5),
    "A_k1.5_m2.0": (1.5, 2.0),
    "A_k1.5_m3.0": (1.5, 3.0),
    "A_k2.0_m1.5": (2.0, 1.5),
    "A_k2.0_m2.0": (2.0, 2.0),
    "A_k2.0_m3.0": (2.0, 3.0),
    "A_k2.5_m1.5": (2.5, 1.5),
    "A_k2.5_m2.0": (2.5, 2.0),
    "A_k2.5_m3.0": (2.5, 3.0),
}
PRIMARY_ARM = "A_k2.0_m2.0"
ORACLE_ARM = "V_oracle_entry"

# Kill-criteria (§6) — congelados.
KILL_MIN_DCAGR = 0.02  # +2pp de CAGR vs la mediana del baseline random
KILL_RANDOM_PCTILE = 95  # CAGR y Sharpe > percentil 95 del baseline
KILL_DD_MULT = 1.5  # maxDD <= 1.5× la mediana del maxDD random
KILL_MIN_DSR = 0.5
KILL_MAX_PBO = 0.5


# ── Carga (barras + señal PIT + volumen alineado) ────────────────────────────


def load_bars_signals_volume(tickers: list[str], period: str, warmup: int):
    """{ticker: [Bar]} + {ticker: {iso10: signal}} + {ticker: [volumen]} alineado.

    El volumen se construye en el **mismo** loop que las barras (mismo filtrado)
    para que ``bars[i]`` y ``vol[i]`` correspondan exactamente."""
    from data import parquet_cache

    bars_by: dict[str, list[Bar]] = {}
    sigs_by: dict[str, dict] = {}
    vol_by: dict[str, list[float]] = {}
    missing: list[str] = []
    incomplete: list[str] = []
    for t in tickers:
        blob = _load_existing(_out_path(t, period, warmup))
        if not blob:
            missing.append(t)
            continue
        if not blob.get("complete"):
            incomplete.append(t)
            continue
        df = parquet_cache.read(t, period, "1d", None)
        if df is None or df.empty:
            missing.append(t)
            continue
        df = df.sort_index()
        bars: list[Bar] = []
        vols: list[float] = []
        for ts, row in df.iterrows():
            try:
                o, h, lo, c = (float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]))
                v = float(row["Volume"])
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(x) for x in (o, h, lo, c)) or c <= 0:
                continue
            if not math.isfinite(v) or v < 0:
                v = 0.0
            bars.append((ts.strftime("%Y-%m-%d"), o, h, lo, c))
            vols.append(v)
        if not bars:
            missing.append(t)
            continue
        bars_by[t] = bars
        vol_by[t] = vols
        sigs_by[t] = {d: sv[0] for d, sv in (blob.get("signals") or {}).items() if sv[0]}
    return bars_by, sigs_by, vol_by, missing, incomplete


# ── Grilla operable (para baseline y oráculo) ────────────────────────────────


def operable_entries(bars_by: dict[str, list[Bar]], warmup: int) -> list[tuple[str, int]]:
    """Todas las entradas operables ``(ticker, idx)`` (mismo dominio que la
    anomalía: ``idx ∈ [warmup+1, n-2]`` — hay barra de fill y una posterior)."""
    out: list[tuple[str, int]] = []
    for t, bars in bars_by.items():
        n = len(bars)
        for idx in range(warmup + 1, n - 1):
            out.append((t, idx))
    return out


def _month(bars_by, ti: tuple[str, int]) -> str:
    return bars_by[ti[0]][ti[1]][0][:7]  # "YYYY-MM"


# ── Simulación ───────────────────────────────────────────────────────────────


def make_runner(bars_by, sigs_by, common):
    def run(entries: list[tuple[str, int]]) -> PortfolioResult:
        return simulate_portfolio(entries, bars_by, sigs_by, **common)

    return run


def summarise(res: PortfolioResult) -> dict:
    sh = sharpe_annual(res.equity_curve)
    return {
        "cagr": cagr(res.equity_curve),
        "sharpe": sh,
        "max_dd": res.max_dd,
        "n_taken": res.n_taken,
        "n_offered": res.n_offered,
        "exposure": res.exposure_share,
        "total_return_pts": res.total_return_pts,
        "accounting_ok": _accounting_ok(res),
    }


def _accounting_ok(res: PortfolioResult) -> bool:
    if not res.equity_curve or res.final_equity <= 0:
        return True
    dev = abs(res.equity_curve[-1][1] - res.final_equity) / res.final_equity
    return dev <= 1e-6


def regime_trade_breakdown(res: PortfolioResult) -> dict:
    """Retorno medio por trade (pts) y n por régimen — robustez de signo (§6.5)."""
    out: dict[str, dict] = {}
    names = ["bull_normal"] + [r.name for r in STRESS_REGIMES]
    for name in names:
        tr = [t for t in res.trades if t.regime == name]
        out[name] = {
            "n": len(tr),
            "mean_ret_pts": 100.0 * statistics.fmean([t.ret for t in tr]) if tr else 0.0,
        }
    return out


def loto_edge(run, entries: list[tuple[str, int]], random_median_cagr: float) -> dict | None:
    """Saca el ticker que más aporta al P/L y re-corre; el edge sobrevive si el
    CAGR sigue por encima de la mediana del baseline random (§6.6)."""
    res = run(entries)
    if not res.trades:
        return None
    pnl_by: dict[str, float] = {}
    for t in res.trades:
        pnl_by[t.ticker] = pnl_by.get(t.ticker, 0.0) + t.pnl
    dropped = max(pnl_by, key=lambda k: pnl_by[k])
    kept = [ti for ti in entries if ti[0] != dropped]
    res2 = run(kept)
    cg = cagr(res2.equity_curve)
    return {"dropped": dropped, "cagr_without": cg, "survives": cg > random_median_cagr}


# ── Baseline Monte Carlo time-matched ────────────────────────────────────────


def random_baseline(
    run,
    bars_by,
    count_by_month: dict[str, int],
    operable_by_month: dict[str, list[tuple[str, int]]],
    *,
    k_random: int,
    seed0: int,
    regime_pts: dict[str, list[float]] | None = None,
) -> dict[str, list[float]]:
    """K carteras aleatorias que respetan la distribución mensual del brazo
    primario. Devuelve las distribuciones de CAGR / Sharpe / maxDD.

    ``regime_pts`` (enabler de la **Tarea 45**, §9.1 de su pre-registro): si se
    pasa un dict, se le acumulan los **retornos por trade en pts, por régimen**,
    de las K carteras. Es el **control** contra el que la 45 mide su criterio de
    régimen (C5′): comparar el nivel de una ventana de stress contra **cero** mide
    el mercado, no la señal; contra el azar time-matched, mide la señal.
    Default ``None`` ⇒ cero cambio para T11b y T38.
    """
    dist: dict[str, list[float]] = {"cagr": [], "sharpe": [], "max_dd": []}
    for s in range(k_random):
        rng = random.Random(seed0 + s)
        entries: list[tuple[str, int]] = []
        for month, cnt in count_by_month.items():
            pool = operable_by_month.get(month) or []
            if not pool or cnt <= 0:
                continue
            if len(pool) >= cnt:
                entries.extend(rng.sample(pool, cnt))
            else:
                entries.extend(rng.choices(pool, k=cnt))
        entries.sort(key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]))
        res = run(entries)
        dist["cagr"].append(cagr(res.equity_curve))
        sh = sharpe_annual(res.equity_curve)
        dist["sharpe"].append(sh if sh is not None else 0.0)
        dist["max_dd"].append(res.max_dd)
        if regime_pts is not None:
            for t in res.trades:
                regime_pts.setdefault(t.regime, []).append(100.0 * t.ret)
    return dist


def _pct(xs: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(xs, dtype=float), q)) if xs else float("nan")


def _median(xs: list[float]) -> float:
    return float(np.median(np.asarray(xs, dtype=float))) if xs else float("nan")


# ── PBO/DSR sobre retornos diarios de equity (patrón T10) ────────────────────


def aligned_returns(results: dict[str, PortfolioResult], arms: list[str]) -> dict[str, list[float]]:
    eq_by: dict[str, dict[str, float]] = {}
    cal: set[str] = set()
    for name in arms:
        d = {dt: v for dt, v in results[name].equity_curve}
        eq_by[name] = d
        cal |= set(d)
    dates = sorted(cal)
    out: dict[str, list[float]] = {}
    for name in arms:
        d = eq_by[name]
        last = results[name].initial_capital
        filled: list[float] = []
        for dt in dates:
            if dt in d:
                last = d[dt]
            filled.append(last)
        out[name] = [filled[i] / filled[i - 1] - 1.0 for i in range(1, len(filled)) if filled[i - 1] > 0]
    return out


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay detector de anomalía (Tarea 11 Brazo B)")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--k-random", type=int, default=500, help="nº de carteras Monte Carlo")
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument(
        "--fill-mode",
        choices=(HARNESS_FILL_MODE, LEGACY_FILL_MODE),
        default=HARNESS_FILL_MODE,
        help=f"'{LEGACY_FILL_MODE}' reproduce el veredicto publicado "
        f"(look-ahead en el fill de la barrera — Tarea 33)",
    )
    # Enabler de la Tarea 38 (§4 de su pre-registro): los dos desvíos que la T11b
    # no modelaba. Defaults = los de la corrida publicada, así agregarlos no mueve
    # su veredicto.
    p.add_argument(
        "--eval-mode",
        choices=("close", "touch"),
        default="close",
        help="'close' reproduce el veredicto publicado; 'touch' es la "
        "regla que ejecuta el engine (Tarea 26b)",
    )
    p.add_argument(
        "--live-gates",
        action="store_true",
        help="modela los gates de re-entrada del engine vivo (Gate 5 anti-whipsaw / 5b anti-churn, Tarea 34)",
    )
    p.add_argument(
        "--allow-stale-artifacts",
        action="store_true",
        help="no abortar si el cohorte de artefactos está desalineado (T30) NI si el "
        "store de señales PIT está corto (T86) — declararlo en el pre-registro",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, vol_by, missing, incomplete = load_bars_signals_volume(
        tickers, args.period, args.warmup
    )
    if not bars_by:
        print("Sin datos: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if incomplete or missing:
        print(f"AVISO: {len(incomplete)} incompletos, {len(missing)} sin datos", file=sys.stderr)

    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        atr_p=AtrParams(),
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,  # engine-faithful
        eval_mode=args.eval_mode,
        fill_mode=args.fill_mode,
        live_gates=args.live_gates,
    )
    run = make_runner(bars_by, sigs_by, common)

    # entradas por brazo
    entries_by: dict[str, list[tuple[str, int]]] = {}
    for name, (k, m) in CANDIDATE_ARMS.items():
        entries_by[name] = build_anomaly_entries(bars_by, vol_by, AnomalyParams(k=k, m=m), warmup=args.warmup)
    prim = entries_by[PRIMARY_ARM]
    # T30 — frescura del cohorte, ANTES de pagar la corrida (tarea 76). La ventana
    # que declara `artifact_window` es min(starts)..max(ends), así que un solo
    # artefacto desalineado la corre sin que se note. Falla ruidoso (política T22).
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts)
        announce_signal_store(bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts)
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3

    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=artifact_window(bars_by),
        verdict_max_positions=LEGACY_MAX_POSITIONS,
        eval_mode=args.eval_mode,
        fill_mode=args.fill_mode,
        live_gates=args.live_gates,
    )
    print(f"Tickers: {len(bars_by)} · entradas por brazo: { {n: len(e) for n, e in entries_by.items()} }")
    print(f"Brazo primario {PRIMARY_ARM}: {len(prim)} entradas\n")
    if not prim:
        print("El brazo primario no produjo entradas — nada que evaluar.", file=sys.stderr)
        return 1

    # baseline Monte Carlo time-matched al primario
    operable = operable_entries(bars_by, args.warmup)
    operable_by_month: dict[str, list[tuple[str, int]]] = {}
    for ti in operable:
        operable_by_month.setdefault(_month(bars_by, ti), []).append(ti)
    count_by_month: dict[str, int] = {}
    for ti in prim:
        count_by_month[_month(bars_by, ti)] = count_by_month.get(_month(bars_by, ti), 0) + 1
    rand_dist = random_baseline(
        run,
        bars_by,
        count_by_month,
        operable_by_month,
        k_random=args.k_random,
        seed0=args.seed,
    )
    rb: dict[str, Any] = {
        "cagr_p95": _pct(rand_dist["cagr"], KILL_RANDOM_PCTILE),
        "cagr_median": _median(rand_dist["cagr"]),
        "sharpe_p95": _pct(rand_dist["sharpe"], KILL_RANDOM_PCTILE),
        "sharpe_median": _median(rand_dist["sharpe"]),
        "maxdd_median": _median(rand_dist["max_dd"]),
        "k": args.k_random,
    }

    # oráculo: las mejores entradas operables por retorno realizado (look-ahead)
    oracle_ret = precompute_oracle_returns(
        operable,
        bars_by,
        sigs_by,
        so_params=ScaleOutParams(),
        atr_p=AtrParams(),
        cap_days=args.cap_days,
        costs=CostModel(),
        fill_mode=args.fill_mode,
    )
    op_scored = [(ti, oracle_ret.get((ti[0], bars_by[ti[0]][ti[1]][0]))) for ti in operable]
    # Nombre nuevo y no `op_scored` otra vez: al re-bindear, el tipo declarado
    # sigue siendo `float | None` aunque el filtro ya saco los None, y el sort
    # queda con una clave que no se puede ordenar.
    scored = [(ti, r) for ti, r in op_scored if r is not None]
    scored.sort(key=lambda x: x[1], reverse=True)
    oracle_entries = sorted(
        (ti for ti, _ in scored[: len(prim)]), key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0])
    )

    # correr todos los brazos + oráculo
    results: dict[str, PortfolioResult] = {n: run(e) for n, e in entries_by.items()}
    results[ORACLE_ARM] = run(oracle_entries)

    summaries = {n: summarise(results[n]) for n in CANDIDATE_ARMS}
    oracle_sum = summarise(results[ORACLE_ARM])

    # filtro local por brazo: bate p95 en CAGR y Sharpe + riesgo OK
    def passes_local(s: dict) -> bool:
        sh = s["sharpe"] if s["sharpe"] is not None else -1e9
        return bool(
            s["accounting_ok"]
            and s["cagr"] > rb["cagr_p95"]
            and sh > rb["sharpe_p95"]
            and s["max_dd"] <= KILL_DD_MULT * rb["maxdd_median"]
            and (s["cagr"] - rb["cagr_median"]) >= KILL_MIN_DCAGR
        )

    for _n, s in summaries.items():
        s["passes_local"] = passes_local(s)

    # brazo de decisión = mejor Sharpe entre los que pasan local
    eligibles = [n for n in CANDIDATE_ARMS if summaries[n]["passes_local"]]
    ranked = sorted(
        CANDIDATE_ARMS,
        key=lambda n: summaries[n]["sharpe"] if summaries[n]["sharpe"] is not None else -1e9,
        reverse=True,
    )
    selected = next((n for n in ranked if n in eligibles), None)

    # PBO/DSR sobre los 9 brazos
    cand = list(CANDIDATE_ARMS)
    rets = aligned_returns(results, cand)
    T = len(next(iter(rets.values()))) if rets else 0
    pbo = pbo_cscv({c: rets[c] for c in cand}, n_splits=10) if T >= 10 else None
    trial_sharpes = [_sharpe(rets[c]) for c in cand]
    dsr = None
    if selected is not None and T >= 2:
        sk, ku = _skew_kurt(rets[selected])
        dsr = deflated_sharpe_ratio(
            trial_sharpes, n_obs=T, selected=_sharpe(rets[selected]), skew=sk, kurtosis=ku
        )

    # robustez del brazo de decisión: régimen + LOTO
    reg = regime_trade_breakdown(results[selected]) if selected else {}
    regime_sign_ok = bool(reg) and all(v["mean_ret_pts"] >= 0 for v in reg.values())
    loto = loto_edge(run, entries_by[selected], rb["cagr_median"]) if selected else None

    ship = bool(
        selected is not None
        and dsr is not None
        and dsr.deflated_sharpe > KILL_MIN_DSR
        and pbo is not None
        and pbo.pbo < KILL_MAX_PBO
        and regime_sign_ok
        and loto is not None
        and loto["survives"]
    )

    ctx: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries_primary": len(prim),
        "max_positions": args.max_positions,
        "capital": args.capital,
        "random_baseline": rb,
        "selected_arm": selected,
        "pbo": (pbo.pbo if pbo else None),
        "dsr": (dsr.deflated_sharpe if dsr else None),
        "dsr_obs": T,
        "regime_sign_ok": regime_sign_ok,
        "loto": loto,
        "ship": ship,
        "kill_criteria": {
            "min_dcagr": KILL_MIN_DCAGR,
            "random_pctile": KILL_RANDOM_PCTILE,
            "dd_mult": KILL_DD_MULT,
            "min_dsr": KILL_MIN_DSR,
            "max_pbo": KILL_MAX_PBO,
        },
    }

    if args.json:
        print(
            json.dumps(
                {
                    "context": ctx,
                    "summaries": {n: summaries[n] for n in CANDIDATE_ARMS},
                    "oracle": oracle_sum,
                    "regime_breakdown_selected": reg,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    _report(summaries, oracle_sum, rb, cand, selected, pbo, dsr, T, reg, regime_sign_ok, loto, ship)
    return 0


def _f(x, w=8, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries, oracle_sum, rb, cand, selected, pbo, dsr, T, reg, regime_sign_ok, loto, ship):
    print(
        f"Baseline random (K={rb['k']}): "
        f"CAGR mediana {_f(rb['cagr_median'], 0, 1, '%')} · p95 {_f(rb['cagr_p95'], 0, 1, '%')} | "
        f"Sharpe mediana {rb['sharpe_median']:.2f} · p95 {rb['sharpe_p95']:.2f} | "
        f"maxDD mediana {_f(rb['maxdd_median'], 0, 1, '%')}\n"
    )
    hdr = f"{'brazo':<14}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'tomad':>7}{'ofrec':>7}{'expos':>7}{'local':>7}"
    print(hdr)
    print("-" * len(hdr))
    for n in cand:
        s = summaries[n]
        mark = "*" if n == selected else ("PRIM" if n == PRIMARY_ARM else "")
        print(
            f"{n:<14}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9, 2)}{_f(s['max_dd'], 9, 1, '%')}"
            f"{s['n_taken']:>7}{s['n_offered']:>7}{_f(s['exposure'], 7, 0, '%')}"
            f"{('SI' if s['passes_local'] else 'no'):>5}{mark:>2}"
        )
    o = oracle_sum
    print(
        f"{ORACLE_ARM:<14}{_f(o['cagr'], 9, 2, '%')}{_f(o['sharpe'], 9, 2)}{_f(o['max_dd'], 9, 1, '%')}"
        f"{o['n_taken']:>7}{o['n_offered']:>7}{_f(o['exposure'], 7, 0, '%')}{'val':>7}"
    )

    print("\nBrazo de decisión:", selected or "(ninguno pasa el filtro local)")
    if selected:
        print("Por régimen — ret medio por trade (pts) / n:")
        for name, v in reg.items():
            print(f"  {name:<18} {v['mean_ret_pts']:>+7.2f}  (n={v['n']})")
        print(f"  signo estable por régimen: {'SI' if regime_sign_ok else 'NO'}")
        if loto:
            print(
                f"  LOTO (sacando {loto['dropped']}): CAGR {_f(loto['cagr_without'], 0, 2, '%')} "
                f"→ edge {'sobrevive' if loto['survives'] else 'SE CAE'}"
            )
    print(f"\nDescuento por selección múltiple (9 brazos, T={T} obs):")
    print(f"  PBO (CSCV) = {pbo.pbo:.3f}" if pbo else "  PBO = n/d")
    print(
        f"  DSR = {dsr.deflated_sharpe:.3f} (SR0={dsr.expected_max_sharpe:.4f})"
        if dsr
        else "  DSR = n/d (ningún brazo pasa local)"
    )
    print(f"\n  VEREDICTO: {'SHIP' if ship else 'NO-SHIP'}")
    print(
        f"\nKill-criteria: CAGR y Sharpe > p95 random · ΔCAGR ≥ +{100 * KILL_MIN_DCAGR:.0f}pp vs mediana "
        f"· maxDD ≤ {KILL_DD_MULT}× · DSR>{KILL_MIN_DSR} · PBO<{KILL_MAX_PBO} · "
        f"signo estable por régimen y por ticker (LOTO)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
