"""
R1 — validación del circuit breaker de drawdown a nivel cuenta.

Corre la cartera ``analyze_single`` (kill_only, equal-weight, 5 slots) sobre el
cache 10y UNA vez con el breaker y UNA vez sin él, y mide el max drawdown y el
retorno **por sub-período** (ventanas de stress vs normales) sobre las dos
curvas de equity. Contrasta contra el kill-criteria pre-registrado en
``docs/dd_breaker_r1_2026-07-08.md``.

Por qué una sola corrida 10y (y no una por ventana): resuelve el warmup y le da
al breaker **contexto de equity continuo** (peak rolling real) exactamente como
en vivo, en vez de arrancar cada ventana de stress desde cero sin historia.

Semántica del breaker en el replay (stateful, fiel al rearme MANUAL vivo): se
**arma** al cruzar el umbral de DD y permanece armado hasta que el equity
recupera un nuevo peak de la ventana (``drawdown_pct == 0``) — no reabre BUYs en
rebotes transitorios intra-caída. Suprime SOLO entradas nuevas; los exits/stops
y el rebalanceo de lo tenido siguen.

Uso:
    python scripts/run_dd_breaker_validation.py data/harness_universe_41_10y.txt

La señal usa ``enable_xgboost=False`` (determinista y factible sobre 10y). El
breaker es agnóstico a la señal — opera sobre la equity del portfolio — así que
el veredicto sobre el guardrail no depende del bloque ML.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

# Umbral pre-registrado (decisión de Chapa 2026-07-08).
THRESHOLD_PCT = 0.15
WINDOW_DAYS = 90

# Ventanas (mismas fechas de stress que el harness E4). Normales = tramos bull.
STRESS_WINDOWS: dict[str, tuple[str, str]] = {
    "stress_2018q4": ("2018-10-01", "2018-12-31"),
    "stress_covid_2020": ("2020-02-15", "2020-04-30"),
    "stress_bear_2022": ("2022-01-01", "2022-10-31"),
}
NORMAL_WINDOWS: dict[str, tuple[str, str]] = {
    "normal_2017": ("2017-01-01", "2017-12-31"),
    "normal_2019": ("2019-01-01", "2019-12-31"),
    "normal_2021": ("2021-01-01", "2021-12-31"),
}

# Kill-criteria pre-registrado.
STRESS_MIN_REL_DD_REDUCTION = 0.20  # el breaker reduce el max DD ≥ 20% relativo
NORMAL_MAX_PL_CUT_PTS = 0.005  # sin recortar el P/L normal más de 0.5 pts


def parse_universe_file(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    tickers: list[str] = []
    for line in raw.splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        line = line.strip()
        if not line:
            continue
        for tok in line.split(","):
            t = tok.strip().upper()
            if t:
                tickers.append(t)
    seen, out = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def make_breaker(threshold: float, window_days: int):
    """Breaker stateful (rearme a nuevo peak). Ver docstring del módulo."""
    from paper_trading.dd_breaker import compute_drawdown_state

    state = {"armed": False}

    def breaker(date: pd.Timestamp, val: float, equity_so_far: pd.Series) -> bool:
        if equity_so_far is None or len(equity_so_far) == 0:
            return state["armed"]
        cutoff = date - pd.Timedelta(days=window_days)
        recent = equity_so_far[equity_so_far.index >= cutoff]
        snaps = [(ts.to_pydatetime(), float(v)) for ts, v in zip(recent.index, recent.values, strict=True)]
        st = compute_drawdown_state(
            float(val),
            snaps,
            threshold_pct=threshold,
            window_days=window_days,
            now=date.to_pydatetime(),
        )
        if st.triggered:
            state["armed"] = True
        elif st.drawdown_pct <= 0.0:
            state["armed"] = False  # nuevo peak → rearme (desarma)
        return state["armed"]

    return breaker


def _segment(equity: pd.Series, start: str, end: str) -> pd.Series:
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    return equity[(equity.index >= lo) & (equity.index <= hi)]


def _seg_dd(equity: pd.Series, start: str, end: str) -> float:
    from analysis.backtest import _max_drawdown

    seg = _segment(equity, start, end)
    if len(seg) < 2:
        return 0.0
    return float(_max_drawdown(seg))  # negativo


def _seg_return(equity: pd.Series, start: str, end: str) -> float:
    seg = _segment(equity, start, end)
    if len(seg) < 2 or seg.iloc[0] <= 0:
        return 0.0
    return float(seg.iloc[-1] / seg.iloc[0] - 1.0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("universe_file", type=Path)
    parser.add_argument("-p", "--period", default="10y")
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--initial-capital", type=float, default=50_000.0)
    args = parser.parse_args()

    from analysis.backtest import signal_from_analyze
    from analysis.portfolio_backtest import AllocationMode, portfolio_backtest
    from data.yahoo_finance import get_historical_data_batch

    tickers = parse_universe_file(args.universe_file)
    print(f"Cargando {args.period} de OHLCV para {len(tickers)} tickers (cache)...")
    fetched = get_historical_data_batch(tickers, period=args.period)
    data: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    for t in tickers:
        df = fetched.get(t.upper())
        if df is None or df.empty or "Close" not in df.columns:
            failed.append(t)
        else:
            data[t] = df
    if failed:
        print(f"  WARNING: sin datos para {len(failed)}: {', '.join(failed)}")
    print(f"  Cargados {len(data)}/{len(tickers)} tickers")
    if len(data) < 5:
        print("Error: universo insuficiente.")
        return 2

    signal_fn = signal_from_analyze(enable_xgboost=False)
    common_kw = dict(
        tickers=list(data.keys()),
        data=data,
        allocation_mode=AllocationMode.EQUAL_WEIGHT,
        max_positions=args.max_positions,
        initial_capital=args.initial_capital,
        step=args.step,
    )

    t0 = time.time()
    print("Corrida BASELINE (sin breaker)...")
    base = portfolio_backtest(signal_fn, breaker_fn=None, **common_kw)
    if base is None:  # sin datos o con menos barras que el warmup
        raise SystemExit("BASELINE sin resultado: revisar universo/periodo")
    print(
        f"  baseline listo en {time.time() - t0:.0f}s "
        f"(final ${base.final_equity:,.0f}, maxDD {base.max_drawdown * 100:.1f}%)"
    )

    t1 = time.time()
    print("Corrida BREAKER (DD ≥ 15% / peak rolling 90d)...")
    brk = portfolio_backtest(signal_fn, breaker_fn=make_breaker(THRESHOLD_PCT, WINDOW_DAYS), **common_kw)
    if brk is None:
        raise SystemExit("BREAKER sin resultado: revisar universo/periodo")
    print(
        f"  breaker listo en {time.time() - t1:.0f}s "
        f"(final ${brk.final_equity:,.0f}, maxDD {brk.max_drawdown * 100:.1f}%, "
        f"steps suprimidos={brk.n_breaker_suppressed})"
    )

    # ── Métricas por sub-período ──────────────────────────────────────────────
    def window_rows(windows: dict[str, tuple[str, str]]) -> list[dict]:
        rows = []
        for name, (s, e) in windows.items():
            dd_b = _seg_dd(base.equity_curve, s, e)
            dd_k = _seg_dd(brk.equity_curve, s, e)
            rel = (1.0 - abs(dd_k) / abs(dd_b)) if dd_b != 0 else 0.0
            rows.append(
                {
                    "window": name,
                    "start": s,
                    "end": e,
                    "dd_baseline": dd_b,
                    "dd_breaker": dd_k,
                    "dd_rel_reduction": rel,
                    "ret_baseline": _seg_return(base.equity_curve, s, e),
                    "ret_breaker": _seg_return(brk.equity_curve, s, e),
                }
            )
        return rows

    stress_rows = window_rows(STRESS_WINDOWS)
    normal_rows = window_rows(NORMAL_WINDOWS)

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    # Kill-criteria: reducción relativa MEDIA del DD en stress; recorte MEDIO de
    # P/L en normal.
    mean_dd_base = _mean([abs(r["dd_baseline"]) for r in stress_rows])
    mean_dd_brk = _mean([abs(r["dd_breaker"]) for r in stress_rows])
    stress_rel_reduction = (1.0 - mean_dd_brk / mean_dd_base) if mean_dd_base > 0 else 0.0

    mean_ret_base = _mean([r["ret_baseline"] for r in normal_rows])
    mean_ret_brk = _mean([r["ret_breaker"] for r in normal_rows])
    normal_pl_cut = mean_ret_base - mean_ret_brk  # positivo = el breaker recortó

    stress_pass = stress_rel_reduction >= STRESS_MIN_REL_DD_REDUCTION
    normal_pass = normal_pl_cut <= NORMAL_MAX_PL_CUT_PTS
    verdict = "PASS" if (stress_pass and normal_pass) else "NO-SHIP"

    # ── Reporte ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print(f"R1 DRAWDOWN BREAKER — umbral {THRESHOLD_PCT:.0%} / peak rolling {WINDOW_DAYS}d")
    print("=" * 72)
    print("\nVentanas de STRESS (queremos MENOS drawdown con breaker):")
    print(f"  {'ventana':<20}{'DD base':>10}{'DD brk':>10}{'reducc.':>10}{'ret base':>10}{'ret brk':>10}")
    for r in stress_rows:
        print(
            f"  {r['window']:<20}{r['dd_baseline'] * 100:>9.1f}%"
            f"{r['dd_breaker'] * 100:>9.1f}%{r['dd_rel_reduction'] * 100:>9.1f}%"
            f"{r['ret_baseline'] * 100:>9.1f}%{r['ret_breaker'] * 100:>9.1f}%"
        )
    print(
        f"  {'MEDIA':<20}{-mean_dd_base * 100:>9.1f}%{-mean_dd_brk * 100:>9.1f}%"
        f"{stress_rel_reduction * 100:>9.1f}%"
    )

    print("\nVentanas NORMALES (queremos P/L ~intacto con breaker):")
    print(f"  {'ventana':<20}{'DD base':>10}{'DD brk':>10}{'ret base':>10}{'ret brk':>10}")
    for r in normal_rows:
        print(
            f"  {r['window']:<20}{r['dd_baseline'] * 100:>9.1f}%"
            f"{r['dd_breaker'] * 100:>9.1f}%"
            f"{r['ret_baseline'] * 100:>9.1f}%{r['ret_breaker'] * 100:>9.1f}%"
        )
    print(f"  {'MEDIA ret':<20}{'':>20}{mean_ret_base * 100:>9.1f}%{mean_ret_brk * 100:>9.1f}%")

    print("\n" + "-" * 72)
    print(
        f"Kill-criteria STRESS: reducción media de DD {stress_rel_reduction * 100:.1f}% "
        f"(≥ {STRESS_MIN_REL_DD_REDUCTION * 100:.0f}%?) → {'PASS' if stress_pass else 'FAIL'}"
    )
    print(
        f"Kill-criteria NORMAL: recorte medio de P/L {normal_pl_cut * 100:+.2f} pts "
        f"(≤ {NORMAL_MAX_PL_CUT_PTS * 100:.1f} pts?) → {'PASS' if normal_pass else 'FAIL'}"
    )
    print(f"\nVEREDICTO: {verdict}")
    print("=" * 72)

    # ── Persistencia ──────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = repo_root / "data" / "dd_breaker_validation" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now().isoformat(),
        "threshold_pct": THRESHOLD_PCT,
        "window_days": WINDOW_DAYS,
        "universe": list(data.keys()),
        "step": args.step,
        "max_positions": args.max_positions,
        "initial_capital": args.initial_capital,
        "signal": "analyze_single (enable_xgboost=False)",
        "breaker_semantics": "stateful; arm on DD>=thr, rearm on new window peak",
        "baseline": {
            "final_equity": base.final_equity,
            "max_drawdown": base.max_drawdown,
            "total_return_pct": base.total_return_pct,
        },
        "breaker": {
            "final_equity": brk.final_equity,
            "max_drawdown": brk.max_drawdown,
            "total_return_pct": brk.total_return_pct,
            "n_breaker_suppressed": brk.n_breaker_suppressed,
        },
        "stress_windows": stress_rows,
        "normal_windows": normal_rows,
        "kill_criteria": {
            "stress_rel_dd_reduction": stress_rel_reduction,
            "stress_min_required": STRESS_MIN_REL_DD_REDUCTION,
            "stress_pass": stress_pass,
            "normal_pl_cut_pts": normal_pl_cut,
            "normal_max_cut": NORMAL_MAX_PL_CUT_PTS,
            "normal_pass": normal_pass,
        },
        "verdict": verdict,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nResumen persistido en {out_dir / 'summary.json'}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
