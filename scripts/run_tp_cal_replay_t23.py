"""
Runner del replay de recalibración del take-profit ATR — Tarea 23 (TP-CAL).

Pre-registro con kill-criteria CONGELADOS: ``docs/tp_cal_prereg_t23_2026-08-11.md``.
Reusa el harness PIT de T7 (señal ``analyze()`` completa, ``data/pit_signals/``) +
``analysis/portfolio_sim.py`` (capital finito, ``max_positions=5``, engine-faithful).

Qué hace (fiel al pre-registro)
-------------------------------
1. Carga barras + señal PIT de los 41 tickers y arma las entradas **``analyze BUY``**
   (la población real del engine, no entradas neutras como el barrido exploratorio).
2. Corre ``simulate_portfolio`` por brazo variando **solo** ``AtrParams.tp_mult``:
   {4.0 baseline, 6.0, sin-TP (1e9)} de decisión + 2.0 de sanity. Todo lo demás fijo
   (stop 2.0, trail default, cap 20d, costos, flip ``analyze SELL``).
3. Mide CAGR/Sharpe/maxDD de cartera + p5 por trade + retorno medio por trade por
   régimen. DSR/PBO sobre los 3 brazos de decisión.
4. Aplica el kill-criteria (§5): ΔCAGR ≥ +0.30pp, Sharpe no-inferior, maxDD
   DD-neutral, p5 no peor, robustez de régimen (Δ ≥ −0.05 pts en los 4), DSR>0.5 &
   PBO<0.5. Sanity: TP_2.0 debe rendir claramente por debajo de TP_4.0.

Sin red, sin tocar ``finanzias.db``: lee Parquet + los JSON de señal. No cambia
ningún flag vivo.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import AtrParams, Bar
from analysis.harness_config import (
    HARNESS_FILL_MODE,
    LEGACY_FILL_MODE,
    LEGACY_MAX_POSITIONS,
    LIVE_MAX_POSITIONS,
    announce,
    artifact_window,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import cagr, sharpe_annual
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import (
    STRESS_REGIMES,
    _sharpe,
    _skew_kurt,
    deflated_sharpe_ratio,
    pbo_cscv,
    regime_for_date,
)
from scripts.precompute_pit_signals import _load_existing, _out_path, parse_universe_file

DEFAULT_UNIVERSE = "data/harness_universe_41_10y.txt"
NO_TP = 1e9  # tp_mult que nunca dispara ("sin-TP")

# Brazos (§3). Decisión = {TP_4.0, TP_6.0, TP_off}; TP_2.0 = sanity (fuera del DSR).
DECISION_ARMS: dict[str, float] = {"TP_4.0": 4.0, "TP_6.0": 6.0, "TP_off": NO_TP}
BASELINE_ARM = "TP_4.0"
CANDIDATE_ARMS = ("TP_6.0", "TP_off")
SANITY_ARM = "TP_2.0"
SANITY_TP = 2.0

# Kill-criteria (§5) — congelados.
KILL_MIN_DCAGR = 0.0030  # ΔCAGR ≥ +0.30pp
KILL_SHARPE_TOL = 0.02  # Sharpe(cand) ≥ Sharpe(base) − 0.02
KILL_DD_TOL = 0.005  # maxDD(cand) ≤ maxDD(base) + 0.5pp
KILL_P5_TOL = 0.005  # p5_trade(cand) ≥ p5_trade(base) − 0.5pp
KILL_REGIME_TOL = 0.05  # Δ ret medio por trade ≥ −0.05 pts en cada régimen
KILL_MIN_DSR = 0.5
KILL_MAX_PBO = 0.5


# ── Carga (barras + señal PIT) ───────────────────────────────────────────────


def load_bars_signals(tickers: list[str], period: str, warmup: int):
    """{ticker: [Bar]} + {ticker: {iso10: signal}} para los tickers con artefacto
    PIT completo y barras en Parquet."""
    from data import parquet_cache

    bars_by: dict[str, list[Bar]] = {}
    sigs_by: dict[str, dict] = {}
    missing: list[str] = []
    for t in tickers:
        blob = _load_existing(_out_path(t, period, warmup))
        if not blob or not blob.get("complete"):
            missing.append(t)
            continue
        df = parquet_cache.read(t, period, "1d", None)
        if df is None or df.empty:
            missing.append(t)
            continue
        df = df.sort_index()
        bars: list[Bar] = []
        for ts, row in df.iterrows():
            try:
                o, h, lo, c = (float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]))
            except (KeyError, TypeError, ValueError):
                continue
            bars.append((ts.strftime("%Y-%m-%d"), o, h, lo, c))
        if not bars:
            missing.append(t)
            continue
        bars_by[t] = bars
        sigs_by[t] = {d: sv[0] for d, sv in (blob.get("signals") or {}).items() if sv[0]}
    return bars_by, sigs_by, missing


def buy_entries(bars_by, sigs_by, warmup: int) -> list[tuple[str, int]]:
    """Entradas = eventos ``analyze BUY`` point-in-time, dominio ``[warmup, n-2]``
    (hay barra posterior para el ciclo). La población real del engine."""
    out: list[tuple[str, int]] = []
    for t, bars in bars_by.items():
        sig = sigs_by.get(t) or {}
        n = len(bars)
        for idx in range(warmup, n - 1):
            if sig.get(bars[idx][0]) == "BUY":
                out.append((t, idx))
    out.sort(key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]))
    return out


# ── Simulación / métricas ────────────────────────────────────────────────────


def run_arm(entries, bars_by, sigs_by, tp_mult: float, common) -> PortfolioResult:
    return simulate_portfolio(entries, bars_by, sigs_by, atr_p=AtrParams(tp_mult=tp_mult), **common)


def _p5_trade(res: PortfolioResult) -> float:
    rets = sorted(t.ret for t in res.trades)
    if not rets:
        return 0.0
    return rets[int(0.05 * len(rets))]


def _tp_share(res: PortfolioResult) -> float:
    if not res.trades:
        return 0.0
    return sum(1 for t in res.trades if "atr_tp" in (t.exit_reason or "")) / len(res.trades)


def _accounting_ok(res: PortfolioResult) -> bool:
    if not res.equity_curve or res.final_equity <= 0:
        return True
    dev = abs(res.equity_curve[-1][1] - res.final_equity) / res.final_equity
    return dev <= 1e-6


def summarise(res: PortfolioResult) -> dict:
    return {
        "cagr": cagr(res.equity_curve),
        "sharpe": sharpe_annual(res.equity_curve),
        "max_dd": res.max_dd,
        "p5_trade": _p5_trade(res),
        "n_taken": res.n_taken,
        "n_offered": res.n_offered,
        "exposure": res.exposure_share,
        "tp_share": _tp_share(res),
        "total_return_pts": res.total_return_pts,
        "accounting_ok": _accounting_ok(res),
    }


def regime_trade_breakdown(res: PortfolioResult) -> dict:
    out: dict[str, dict] = {}
    for name in ["bull_normal"] + [r.name for r in STRESS_REGIMES]:
        tr = [t for t in res.trades if t.regime == name]
        out[name] = {
            "n": len(tr),
            "mean_ret_pts": 100.0 * statistics.fmean([t.ret for t in tr]) if tr else 0.0,
        }
    return out


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


# ── Kill-criteria (§5) ───────────────────────────────────────────────────────


def evaluate(summaries: dict, regimes: dict, dsr, pbo) -> dict:
    """Aplica el AND de los 6 criterios. Devuelve el detalle + ship."""
    base = summaries[BASELINE_ARM]
    # candidato = mejor Sharpe entre los dos candidatos.
    cand_name = max(
        CANDIDATE_ARMS,
        key=lambda n: summaries[n]["sharpe"] if summaries[n]["sharpe"] is not None else -1e9,
    )
    cand = summaries[cand_name]
    b_sh = base["sharpe"] if base["sharpe"] is not None else -1e9
    c_sh = cand["sharpe"] if cand["sharpe"] is not None else -1e9

    reg_ok = True
    reg_delta: dict[str, float] = {}
    for r, v in regimes[cand_name].items():
        d = v["mean_ret_pts"] - regimes[BASELINE_ARM][r]["mean_ret_pts"]
        reg_delta[r] = d
        if d < -KILL_REGIME_TOL:
            reg_ok = False

    c1 = (cand["cagr"] - base["cagr"]) >= KILL_MIN_DCAGR
    c2 = c_sh >= b_sh - KILL_SHARPE_TOL
    c3 = cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL
    c4 = cand["p5_trade"] >= base["p5_trade"] - KILL_P5_TOL
    c5 = reg_ok
    c6 = (dsr is not None and dsr > KILL_MIN_DSR) and (pbo is not None and pbo < KILL_MAX_PBO)
    ship = bool(cand["accounting_ok"] and c1 and c2 and c3 and c4 and c5 and c6)
    return {
        "candidate": cand_name,
        "dcagr": cand["cagr"] - base["cagr"],
        "sharpe_delta": c_sh - b_sh,
        "dd_delta": cand["max_dd"] - base["max_dd"],
        "p5_delta": cand["p5_trade"] - base["p5_trade"],
        "regime_delta": reg_delta,
        "c1_cagr": c1,
        "c2_sharpe": c2,
        "c3_dd": c3,
        "c4_p5": c4,
        "c5_regime": c5,
        "c6_dsr_pbo": c6,
        "ship": ship,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay de recalibración del TP ATR (Tarea 23)")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument(
        "--fill-mode",
        choices=(HARNESS_FILL_MODE, LEGACY_FILL_MODE),
        default=HARNESS_FILL_MODE,
        help=f"'{LEGACY_FILL_MODE}' reproduce el veredicto publicado "
        f"(look-ahead en el fill de la barrera — Tarea 33)",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)

    entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not entries:
        print("Sin entradas BUY — nada que evaluar.", file=sys.stderr)
        return 1
    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=artifact_window(bars_by),
        verdict_max_positions=LEGACY_MAX_POSITIONS,
        fill_mode=args.fill_mode,
    )
    print(f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)}\n")

    common = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        fill_mode=args.fill_mode,
    )

    all_arms = {**DECISION_ARMS, SANITY_ARM: SANITY_TP}
    results = {n: run_arm(entries, bars_by, sigs_by, tp, common) for n, tp in all_arms.items()}
    summaries = {n: summarise(results[n]) for n in all_arms}
    regimes = {n: regime_trade_breakdown(results[n]) for n in all_arms}

    # sanity: TP_2.0 debe rendir claramente por debajo de TP_4.0
    sanity_ok = summaries[SANITY_ARM]["cagr"] < summaries[BASELINE_ARM]["cagr"]

    # DSR/PBO sobre los 3 brazos de decisión
    dec = list(DECISION_ARMS)
    rets = aligned_returns(results, dec)
    T = len(next(iter(rets.values()))) if rets else 0
    pbo = pbo_cscv({c: rets[c] for c in dec}, n_splits=10) if T >= 10 else None
    trial_sharpes = [_sharpe(rets[c]) for c in dec]
    # el candidato para el DSR = mejor Sharpe entre los candidatos
    cand_name = max(
        CANDIDATE_ARMS, key=lambda n: summaries[n]["sharpe"] if summaries[n]["sharpe"] is not None else -1e9
    )
    dsr = None
    if T >= 2:
        sk, ku = _skew_kurt(rets[cand_name])
        dsr = deflated_sharpe_ratio(
            trial_sharpes, n_obs=T, selected=_sharpe(rets[cand_name]), skew=sk, kurtosis=ku
        )

    verdict = evaluate(summaries, regimes, dsr.deflated_sharpe if dsr else None, pbo.pbo if pbo else None)
    verdict["sanity_ok"] = sanity_ok
    ship = bool(verdict["ship"] and sanity_ok)
    verdict["ship"] = ship

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries": len(entries),
        "max_positions": args.max_positions,
        "capital": args.capital,
        "fill_mode": args.fill_mode,
        "dsr": (dsr.deflated_sharpe if dsr else None),
        "pbo": (pbo.pbo if pbo else None),
        "dsr_obs": T,
        "verdict": verdict,
        "kill_criteria": {
            "min_dcagr": KILL_MIN_DCAGR,
            "sharpe_tol": KILL_SHARPE_TOL,
            "dd_tol": KILL_DD_TOL,
            "p5_tol": KILL_P5_TOL,
            "regime_tol": KILL_REGIME_TOL,
            "min_dsr": KILL_MIN_DSR,
            "max_pbo": KILL_MAX_PBO,
        },
    }

    if args.json:
        print(
            json.dumps(
                {
                    "context": ctx,
                    "summaries": summaries,
                    "regimes": regimes,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    _report(summaries, regimes, ctx, verdict, dsr, pbo, T)
    return 0


def _f(x, w=8, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries, regimes, ctx, verdict, dsr, pbo, T):
    hdr = f"{'brazo':<10}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'p5trade':>9}{'%TP':>7}{'tomad':>7}{'expos':>7}"
    print(hdr)
    print("-" * len(hdr))
    for n in [*list(DECISION_ARMS), SANITY_ARM]:
        s = summaries[n]
        mark = (
            "BASE"
            if n == BASELINE_ARM
            else ("*cand" if n == verdict["candidate"] else ("sanity" if n == SANITY_ARM else ""))
        )
        print(
            f"{n:<10}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9, 2)}{_f(s['max_dd'], 9, 1, '%')}"
            f"{_f(s['p5_trade'], 9, 1, '%')}{_f(s['tp_share'], 7, 0, '%')}{s['n_taken']:>7}"
            f"{_f(s['exposure'], 7, 0, '%')}  {mark}"
        )

    print(f"\nCandidato (mejor Sharpe): {verdict['candidate']}")
    print("Por régimen — ret medio por trade (pts), Δ vs baseline:")
    for r in regimes[verdict["candidate"]]:
        b = regimes[BASELINE_ARM][r]["mean_ret_pts"]
        c = regimes[verdict["candidate"]][r]["mean_ret_pts"]
        print(f"  {r:<18} base {b:>+6.2f} · cand {c:>+6.2f} · Δ {verdict['regime_delta'][r]:>+6.2f}")

    print(
        f"\nΔCAGR {_f(verdict['dcagr'], 0, 2, '%')} · ΔSharpe {verdict['sharpe_delta']:+.3f} · "
        f"ΔmaxDD {_f(verdict['dd_delta'], 0, 2, '%')} · Δp5 {_f(verdict['p5_delta'], 0, 2, '%')}"
    )
    print(
        f"DSR = {dsr.deflated_sharpe:.3f}" if dsr else "DSR = n/d",
        f"· PBO = {pbo.pbo:.3f}" if pbo else "· PBO = n/d",
        f"(T={T} obs)",
    )
    print("\nCriterios (§5):")
    for k, label in [
        ("c1_cagr", "ΔCAGR ≥ +0.30pp"),
        ("c2_sharpe", "Sharpe no-inferior"),
        ("c3_dd", "DD-neutral"),
        ("c4_p5", "p5 no peor"),
        ("c5_regime", "régimen robusto"),
        ("c6_dsr_pbo", "DSR>0.5 & PBO<0.5"),
    ]:
        print(f"  [{'PASA' if verdict[k] else 'FALLA'}] {label}")
    print(f"  [{'PASA' if verdict['sanity_ok'] else 'FALLA'}] sanity TP_2.0 < TP_4.0")
    print(f"\n  VEREDICTO: {'SHIP (' + verdict['candidate'] + ')' if verdict['ship'] else 'NO-SHIP'}")


if __name__ == "__main__":
    raise SystemExit(main())
