"""
Runner del walk-forward power harness — backlog E4.

Carga el cache 10y del universo, arma la grilla de entradas point-in-time y corre
las dos re-evaluaciones potenciadas:

  * ``--only a1``  — stop-vs-no-stop por régimen + robustez CPCV/PBO/DSR sobre las
    variantes de stop-mult (rápido, puro; no toca red salvo la carga inicial).
  * ``--only t3``  — corr(buy_score, fwd) pooled + IC cross-sectional. CARO:
    computa ``analyze().ml_probability`` PIT en cada entrada (entrena XGBoost por
    llamada). **Resumable**: cachea los scores en disco keyed por (ticker, fecha).
  * ``--only both`` (default) — las dos.

Enabler puro (E4): reporta poder + hallazgos, NO cambia ningún flag vivo.

Uso típico (precargar el cache primero para no pegarle a Yahoo durante el run):
    python scripts/prefetch_harness_cache.py data/harness_universe_41_10y.txt -p 10y
    python scripts/run_walkforward_power.py --only a1
    python scripts/run_walkforward_power.py --only t3        # largo, resumable

Salidas: tablas por stdout + ``data/walkforward_power/{ts}/summary.{json,txt}``.
El caché de scores vive en ``data/walkforward_power/scores_<hash>.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import AtrParams, Bar  # noqa: E402
from analysis.walkforward_power import (  # noqa: E402
    A1_VARIANTS,
    EntrySample,
    cpcv_effect_distribution,
    cross_sectional_ic,
    deflated_sharpe_ratio,
    n_for_correlation,
    n_for_mean_effect,
    pbo_cscv,
    per_entry_returns_by_config,
    pooled_correlation,
    replay_stop_vs_nostop,
    sample_universe,
    stop_stats_by_regime,
    _sharpe,
    _skew_kurt,
)

DEFAULT_UNIVERSE = "data/harness_universe_41_10y.txt"
OUT_ROOT = _HERE.parent / "data" / "walkforward_power"


def parse_universe_file(path: Path) -> list[str]:
    """Un ticker por línea; ``#`` introduce comentario (inline o full-line)."""
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


def df_to_bars(df) -> list[Bar]:
    """DataFrame OHLCV (índice temporal) → lista de Bar iso10, saltando NaN."""
    import math

    bars: list[Bar] = []
    for ts, row in df.iterrows():
        try:
            o, h, lo, c = (float(row["Open"]), float(row["High"]),
                           float(row["Low"]), float(row["Close"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (o, h, lo, c)) or c <= 0:
            continue
        bars.append((ts.strftime("%Y-%m-%d"), o, h, lo, c))
    return bars


def load_universe_bars(universe_file: Path, period: str, batch_size: int):
    """Devuelve (data, dfs): ``data`` = {ticker: [Bar]}, ``dfs`` = {ticker: DataFrame}."""
    from data.yahoo_finance import get_historical_data_batch

    tickers = parse_universe_file(universe_file)
    print(f"Cargando {period} de OHLCV para {len(tickers)} tickers desde cache...")
    fetched = get_historical_data_batch(tickers, period=period, batch_size=batch_size)
    data: dict[str, list[Bar]] = {}
    dfs: dict[str, object] = {}
    failed: list[str] = []
    for t in tickers:
        df = fetched.get(t.upper())
        if df is None or df.empty or "Close" not in df.columns:
            failed.append(t)
            continue
        bars = df_to_bars(df)
        if len(bars) < 260:  # <~1y no sirve para warmup 250 + forward
            failed.append(t)
            continue
        data[t] = bars
        dfs[t] = df
    if failed:
        print(f"  WARNING: {len(failed)} tickers sin data suficiente: {', '.join(failed)}")
    print(f"  Cargados {len(data)}/{len(tickers)} tickers")
    return data, dfs


# ── A1: stop-vs-no-stop ──────────────────────────────────────────────────────


def run_a1(entries: list[EntrySample], data: dict[str, list[Bar]], cap_days: int):
    bar_loader = lambda t: data.get(t)  # noqa: E731
    outcomes = replay_stop_vs_nostop(entries, bar_loader, cap_days=cap_days,
                                     atr_p=AtrParams())
    stats = stop_stats_by_regime(outcomes)
    return outcomes, stats


def run_a1_robustness(entries, data, outcomes, cap_days: int):
    """Ampliación E4: PBO/DSR sobre las variantes de stop-mult + distribución del
    Δ por CPCV (por régimen). Devuelve (dict serializable, texto)."""
    bar_loader = lambda t: data.get(t)  # noqa: E731
    used, cols = per_entry_returns_by_config(entries, bar_loader, A1_VARIANTS,
                                             cap_days=cap_days)
    trial_sharpes = {name: _sharpe(col) for name, col in cols.items()}
    pbo = pbo_cscv(cols, n_splits=10)
    best_name = max(trial_sharpes, key=lambda k: trial_sharpes[k]) if trial_sharpes else None
    dsr = None
    if best_name is not None:
        sk, ku = _skew_kurt(cols[best_name])
        dsr = deflated_sharpe_ratio(list(trial_sharpes.values()), n_obs=len(used),
                                    selected=trial_sharpes[best_name], skew=sk, kurtosis=ku)

    regimes = ["all", "bull_normal", "stress_2018q4", "stress_covid_2020", "stress_bear_2022"]
    cpcv = {r: cpcv_effect_distribution(outcomes, regime=r) for r in regimes}

    out = {
        "n_obs": len(used),
        "trial_sharpes": trial_sharpes,
        "best_config": best_name,
        "pbo": vars(pbo),
        "dsr": (vars(dsr) if dsr is not None else None),
        "cpcv_delta_by_regime": {
            r: {k: v for k, v in vars(res).items() if k != "per_path_delta"}
            for r, res in cpcv.items()
        },
    }
    return out, render_a1_robustness(out)


def render_a1_robustness(rob: dict) -> str:
    lines = [
        "A1 robustez — CPCV + PBO/DSR sobre las variantes de stop-mult",
        f"Variantes (Sharpe por-obs, n_obs={rob['n_obs']}): "
        + ", ".join(f"{k}={v:+.4f}" for k, v in rob["trial_sharpes"].items()),
        "",
    ]
    pbo = rob["pbo"]
    if pbo.get("pbo") == pbo.get("pbo"):  # no-NaN
        interp = ("selección puro ruido" if pbo["pbo"] >= 0.4
                  else "el ganador aguanta OOS" if pbo["pbo"] <= 0.1 else "señal débil")
        lines.append(
            f"PBO (CSCV S={pbo['n_splits']}, {pbo['n_combos']} combos): "
            f"{pbo['pbo']:.2f}  → {interp}"
        )
    d = rob.get("dsr")
    if d is not None:
        lines.append(
            f"DSR del mejor ({rob['best_config']}): SR0(máx esperado bajo H0)="
            f"{d['expected_max_sharpe']:.4f}  DSR=P(SR>0)={d['deflated_sharpe']:.3f}  "
            f"(PSR sin deflactar={d['prob_positive_raw']:.3f})"
        )
    lines += ["", "CPCV Δ (no_stops − baseline_2.0) por régimen:",
              f"{'régimen':<20} {'paths':>6} {'Δ mean':>9} {'Δ std':>9} {'%Δ>0':>7}"]

    def _p(x, w=9):
        return f"{'—':>{w}}" if x is None else f"{100*x:>{w-1}.2f}%"

    for reg, res in rob["cpcv_delta_by_regime"].items():
        if res["n_paths"] == 0:
            continue
        fp = res["frac_positive"]
        lines.append(
            f"{reg:<20} {res['n_paths']:>6} {_p(res['mean_delta'])} {_p(res['std_delta'])} "
            f"{('—' if fp is None else f'{100*fp:.0f}%'):>7}"
        )
    return "\n".join(lines)


def render_a1(stats: dict) -> str:
    order = ["all", "bull_normal", "stress_2018q4", "stress_covid_2020", "stress_bear_2022"]
    lines = [
        "A1 potenciado — retorno por-share stop(2.0) vs sin-stops (mantener a cap)",
        "Δ = no_stops − with_stops. Δ>0 ⇒ sacar stops habría ayudado (régimen).",
        "",
        f"{'régimen':<20} {'n':>5} {'ret_stop':>9} {'ret_nost':>9} "
        f"{'Δ mean':>9} {'d':>7} {'power':>7} {'ΔLOO':>9}",
    ]

    def _p(x, w=9, pct=True):
        if x is None:
            return f"{'—':>{w}}"
        return f"{100*x:>{w-1}.2f}%" if pct else f"{x:>{w}.3f}"

    for reg in order:
        s = stats.get(reg)
        if s is None:
            continue
        lines.append(
            f"{reg:<20} {s.n:>5} {_p(s.mean_ret_with_stops)} {_p(s.mean_ret_no_stops)} "
            f"{_p(s.mean_delta)} {_p(s.d, 7, pct=False)} "
            f"{_p(s.achieved_power, 7, pct=False)} {_p(s.loo_worst_delta)}"
        )
    # N necesario para el efecto observado (all)
    all_s = stats.get("all")
    if all_s and all_s.d is not None:
        need = n_for_mean_effect(all_s.d)
        lines.append("")
        lines.append(
            f"Efecto observado (all): d={all_s.d:.3f} → N para 80% potencia ≈ {need} "
            f"(n generado={all_s.n}, potencia lograda={all_s.achieved_power:.2f})"
        )
    return "\n".join(lines)


# ── Tarea 3: buy_score PIT + corr/IC ─────────────────────────────────────────


def _scores_cache_path(universe_file: Path, period: str, spacing: int, warmup: int) -> Path:
    key = f"{universe_file.name}|{period}|{spacing}|{warmup}"
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    return OUT_ROOT / f"scores_{h}.json"


def compute_scores(
    entries: list[EntrySample],
    dfs: dict,
    cache_path: Path,
    *,
    save_every: int = 25,
    limit: int | None = None,
):
    """Completa ``e.score`` con ``analyze().ml_probability`` PIT. Resumable: lee y
    reescribe ``cache_path`` (dict "ticker|fecha" → score/null). Devuelve cuántas
    entradas nuevas se computaron."""
    from analysis.technical import analyze

    cache: dict[str, float | None] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cache = {}

    def _flush():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")

    todo = [e for e in entries if f"{e.ticker}|{e.entry_date}" not in cache]
    if limit is not None:
        todo = todo[:limit]
    print(f"  scores: {len(entries)-len(todo)} en cache, {len(todo)} por computar "
          f"(analyze() PIT, entrena XGBoost por llamada — lento)")

    computed = 0
    t0 = time.time()
    for i, e in enumerate(todo, 1):
        df = dfs.get(e.ticker)
        key = f"{e.ticker}|{e.entry_date}"
        score: float | None = None
        if df is not None:
            df_slice = df.iloc[: e.entry_idx + 1]
            try:
                res = analyze(e.ticker, df_slice, enable_xgboost=True)
                if res is not None and res.ml_probability is not None:
                    p = float(res.ml_probability)
                    score = p if p == p else None  # descarta NaN
            except Exception:  # noqa: BLE001 — un ticker que falla no corta el run
                score = None
        cache[key] = score
        computed += 1
        if i % save_every == 0:
            _flush()
            rate = i / max(1e-9, time.time() - t0)
            print(f"    {i}/{len(todo)}  ({rate:.1f}/s)")
    _flush()

    # Volcar los scores del cache a las entradas
    for e in entries:
        v = cache.get(f"{e.ticker}|{e.entry_date}")
        e.score = float(v) if isinstance(v, (int, float)) else None
    return computed


def render_t3(entries: list[EntrySample]) -> str:
    lines = ["Tarea 3 potenciado — corr(buy_score, fwd) pooled + IC cross-sectional", ""]
    for h in ("fwd5", "fwd20"):
        c = pooled_correlation(entries, h)
        corr_s = f"{c.corr:+.3f}" if c.corr is not None else "—"
        lines.append(
            f"pooled {h:5}: n={c.n:>5}  corr={corr_s}  "
            f"(|ρ| detectable @80% con n={c.n}: {c.detectable_rho:.3f})"
        )
    lines.append("")
    for h in ("fwd5", "fwd20"):
        ic = cross_sectional_ic(entries, horizon=h)
        if ic.mean_ic is None:
            lines.append(f"IC {h:5}: sin fechas con ≥5 nombres")
            continue
        t_s = f"{ic.t_stat:+.2f}" if ic.t_stat is not None else "—"
        lines.append(
            f"IC {h:5}: fechas={ic.n_dates:>4}  mean_IC={ic.mean_ic:+.4f}  "
            f"std={ic.std_ic:.4f}  t={t_s}"
        )
    lines.append("")
    lines.append("N para 80% potencia (Fisher-z): "
                 + "  ".join(f"ρ={r}→{int(n_for_correlation(r))}" for r in (0.05, 0.10, 0.15, 0.20)))
    return "\n".join(lines)


# ── Orquestación ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Walk-forward power harness (E4)")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--period", default="10y")
    p.add_argument("--spacing", type=int, default=20,
                   help="días hábiles entre entradas (≥ fwd_long=20 para no-solapar)")
    p.add_argument("--warmup", type=int, default=250,
                   help="barras iniciales antes de la primera entrada (≥200 para analyze())")
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--only", choices=["a1", "t3", "both"], default="both")
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--score-limit", type=int, default=None,
                   help="tope de scores nuevos a computar en esta corrida (para runs parciales)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    universe_file = Path(args.universe)
    if not universe_file.is_absolute():
        universe_file = _HERE.parent / universe_file
    if not universe_file.exists():
        print(f"universo no encontrado: {universe_file}", file=sys.stderr)
        return 1

    data, dfs = load_universe_bars(universe_file, args.period, args.batch_size)
    if len(data) < 5:
        print("Error: muy pocos tickers cargados para un backtest con sentido.", file=sys.stderr)
        return 2

    entries = sample_universe(data, spacing=args.spacing, warmup=args.warmup)
    n_dates = len({e.entry_date for e in entries})
    print(f"Grilla PIT: {len(entries)} entradas · {n_dates} fechas distintas · "
          f"spacing={args.spacing} · warmup={args.warmup}")
    reg_counts: dict[str, int] = {}
    for e in entries:
        reg_counts[e.regime] = reg_counts.get(e.regime, 0) + 1
    print("  por régimen: " + ", ".join(f"{k}={v}" for k, v in sorted(reg_counts.items())))

    out: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": universe_file.name,
        "period": args.period,
        "spacing": args.spacing,
        "warmup": args.warmup,
        "n_entries": len(entries),
        "n_dates": n_dates,
        "regime_counts": reg_counts,
        "tickers": sorted(data.keys()),
    }
    text_blocks: list[str] = []

    if args.only in ("a1", "both"):
        outcomes, stats = run_a1(entries, data, args.cap_days)
        block = render_a1(stats)
        print("\n" + "=" * 76 + "\n" + block)
        text_blocks.append(block)
        out["a1"] = {reg: vars(s) for reg, s in stats.items()}

        rob, rob_block = run_a1_robustness(entries, data, outcomes, args.cap_days)
        print("\n" + "=" * 76 + "\n" + rob_block)
        text_blocks.append(rob_block)
        out["a1_robustness"] = rob

    if args.only in ("t3", "both"):
        cache_path = _scores_cache_path(universe_file, args.period, args.spacing, args.warmup)
        compute_scores(entries, dfs, cache_path, limit=args.score_limit)
        block = render_t3(entries)
        print("\n" + "=" * 76 + "\n" + block)
        text_blocks.append(block)
        out["t3"] = {
            "pooled": {h: vars(pooled_correlation(entries, h)) for h in ("fwd5", "fwd20")},
            "ic": {h: {k: v for k, v in vars(cross_sectional_ic(entries, horizon=h)).items()
                       if k != "per_date_ic"} for h in ("fwd5", "fwd20")},
            "scored_entries": sum(1 for e in entries if e.score is not None),
        }

    # Persistir resumen
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_ROOT / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8")
    (run_dir / "summary.txt").write_text("\n\n".join(text_blocks), encoding="utf-8")
    print(f"\nResumen en {run_dir}/summary.{{json,txt}}")

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
