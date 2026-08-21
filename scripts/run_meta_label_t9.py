"""
Runner del rediseño del modelo predictivo — backlog **Tarea 9**.

Pre-registro con kill-criteria congelados: ``docs/meta_labeling_t9_2026-07-21.md``.
Requiere el artefacto de señal PIT (``scripts/precompute_pit_signals.py``, generado
por la Tarea 7) y el cache Parquet 10y.

    python scripts/run_meta_label_t9.py
    python scripts/run_meta_label_t9.py --json

Qué hace
--------
1. Arma el dataset pooled: cada barra con señal primaria BUY, etiquetada con la
   triple barrera (TP 4×ATR antes que stop 2×ATR, 20 ruedas, sobre el close).
2. Entrena el meta-modelo **pooled** walk-forward con purge + embargo y produce
   predicciones **estrictamente out-of-sample**.
3. Corre los 4 brazos pre-registrados sobre ``analysis/portfolio_sim.py``
   (max_positions=5, capital finito, ranking entre candidatos del mismo día),
   todos sobre **la misma ventana OOS**.
4. Verifica los **gates de integridad ANTES de leer resultados**: invariante de
   exits y desvío de la curva de equity vs la contabilidad de cash.
5. Aplica el kill-criteria en **CAGR** y reporta DSR/PBO.

No cambia ningún flag vivo, no toca ``finanzias.db`` y no usa red.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import AtrParams  # noqa: E402
from analysis.harness_config import (  # noqa: E402
    HARNESS_FILL_MODE,
    LEGACY_FILL_MODE,
    LEGACY_MAX_POSITIONS,
    LIVE_MAX_POSITIONS,
    announce,
    artifact_window,
)
from analysis.meta_labeling import build_dataset  # noqa: E402
from analysis.meta_model import cross_sectional_percentile, walkforward_oof  # noqa: E402
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio  # noqa: E402
from analysis.scaleout_replay import CostModel, ScaleOutParams  # noqa: E402
from analysis.walkforward_power import (  # noqa: E402
    STRESS_REGIMES,
    deflated_sharpe_ratio,
    pbo_cscv,
    regime_for_date,
)
from scripts.precompute_pit_signals import (  # noqa: E402
    _load_existing,
    _out_path,
    parse_universe_file,
)

DEFAULT_UNIVERSE = "data/harness_universe_41_10y.txt"

# Brazos pre-registrados (§6). Difieren SOLO en cómo ordenan los candidatos que
# compiten por el mismo slot el mismo día.
BASELINE_ARM = "B0_neutral"
PRIMARY_ARM = "M1_meta_pooled"
ARM_NAMES = [BASELINE_ARM, "B1_buy_score", PRIMARY_ARM, "F1_mom121"]

# Kill-criteria (§9) — congelados.
KILL_MIN_CAGR_PTS = 1.5     # CAGR >= CAGR(B0) + 1.5 puntos porcentuales
KILL_MAX_DD_RATIO = 1.5     # max DD de la cartera <= 1.5 x el de B0
KILL_MAX_PBO = 0.50
KILL_MIN_DSR = 0.0
# Gate de integridad: desvío tolerado entre la curva de equity y el cash contable.
INTEGRITY_MAX_DRIFT = 1e-4  # 0.01%


# ── Carga de datos ──────────────────────────────────────────────────────────


def load_bars_signals_probs(tickers: list[str], period: str, warmup: int):
    """``(bars_by, sigs_by, probs_by, frames_by, missing, incomplete)``.

    Igual que ``run_scaleout_replay_t7.load_bars_and_signals`` pero conservando
    (a) la ``ml_probability`` del artefacto, que es el score del brazo B1, y
    (b) el DataFrame crudo, que es de donde salen las features pooled.
    """
    from data import parquet_cache

    bars_by: dict[str, list] = {}
    sigs_by: dict[str, dict] = {}
    probs_by: dict[str, dict] = {}
    frames_by: dict = {}
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
        bars = []
        keep = []
        for ts, row in df.iterrows():
            try:
                o, h, lo, c = (float(row["Open"]), float(row["High"]),
                               float(row["Low"]), float(row["Close"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in (o, h, lo, c)) or c <= 0:
                continue
            bars.append((ts.strftime("%Y-%m-%d"), o, h, lo, c))
            keep.append(ts)
        if not bars:
            missing.append(t)
            continue
        signals = blob.get("signals") or {}
        bars_by[t] = bars
        sigs_by[t] = {d: v[0] for d, v in signals.items() if v[0]}
        probs_by[t] = {d: v[1] for d, v in signals.items() if v[1] is not None}
        # El frame se recorta a las mismas barras que sobrevivieron el filtro de
        # OHLC, para que features y barras no se desalineen.
        frames_by[t] = df.loc[keep]
    return bars_by, sigs_by, probs_by, frames_by, missing, incomplete


# ── Métricas de cartera ─────────────────────────────────────────────────────


def _daily_returns(curve: list[tuple[str, float]]) -> list[float]:
    out = []
    for (_, prev), (_, cur) in zip(curve, curve[1:]):
        if prev > 0 and math.isfinite(prev) and math.isfinite(cur):
            out.append(cur / prev - 1.0)
    return out


def _years_span(curve: list[tuple[str, float]]) -> float:
    if len(curve) < 2:
        return 0.0
    d0 = datetime.strptime(curve[0][0], "%Y-%m-%d")
    d1 = datetime.strptime(curve[-1][0], "%Y-%m-%d")
    return max((d1 - d0).days / 365.25, 1e-9)


def cagr(res: PortfolioResult) -> float:
    """CAGR en % — la **métrica primaria** del pre-registro (§9).

    No P/L acumulado en puntos: sobre años de compounding ese umbral es ruido y lo
    pasa cualquier cosa (defecto de especificación que detectó la Tarea 8).
    """
    yrs = _years_span(res.equity_curve)
    if yrs <= 0 or res.initial_capital <= 0 or res.final_equity <= 0:
        return 0.0
    return 100.0 * ((res.final_equity / res.initial_capital) ** (1.0 / yrs) - 1.0)


def sharpe_annual(res: PortfolioResult) -> float:
    """Sharpe anualizado de la curva diaria. **Secundaria** — no decide."""
    rets = _daily_returns(res.equity_curve)
    if len(rets) < 2:
        return 0.0
    sd = statistics.pstdev(rets)
    if sd <= 0:
        return 0.0
    return (statistics.fmean(rets) / sd) * math.sqrt(252)


def equity_integrity_drift(res: PortfolioResult) -> float:
    """Desvío relativo entre el último punto de la curva y el equity contable.

    Gate de integridad, se corre **antes** de leer cualquier resultado — el mismo
    chequeo que R2 pasó con 0.000% antes de mirar sus números.
    """
    if not res.equity_curve or res.final_equity <= 0:
        return 0.0
    return abs(res.equity_curve[-1][1] - res.final_equity) / res.final_equity


def check_exit_invariant(base: PortfolioResult, arm: PortfolioResult) -> tuple[bool, str]:
    """El ranking NUNCA toca exits: una posición abierta en los dos brazos, mismo
    ticker y misma fecha de entrada, tiene que salir el mismo día y al mismo
    retorno. Si falla, es un bug, no un resultado."""
    base_by = {(t.ticker, t.entry_date): t for t in base.trades}
    checked = mismatched = 0
    for t in arm.trades:
        b = base_by.get((t.ticker, t.entry_date))
        if b is None:
            continue
        checked += 1
        if b.exit_date != t.exit_date or abs(b.ret - t.ret) > 1e-9:
            mismatched += 1
    if mismatched:
        return False, f"{mismatched}/{checked} posiciones con salida distinta"
    return True, f"{checked} posiciones compartidas, todas con salida idéntica"


def by_regime(res: PortfolioResult) -> dict:
    out: dict[str, dict] = {}
    for name in [r.name for r in STRESS_REGIMES] + ["bull_normal"]:
        tr = [t for t in res.trades if t.regime == name]
        out[name] = {
            "n_trades": len(tr),
            "mean_ret_pts": 100.0 * statistics.fmean([t.ret for t in tr]) if tr else 0.0,
        }
    return out


# ── Rankings de cada brazo ──────────────────────────────────────────────────


def build_rank_scores(dataset, oof, probs_by) -> dict:
    """``{brazo: rank_score(ticker, date) | None}`` (§6)."""
    # B1 — el engine de hoy: ml_probability de analyze().
    def b1(ticker: str, date: str) -> float:
        v = (probs_by.get(ticker) or {}).get(date)
        return float(v) if v is not None and math.isfinite(v) else 0.0

    # M1 — meta-modelo pooled, predicción OOS. Un candidato sin predicción (por
    # ejemplo el que quedó sin etiqueta) va al fondo, no al frente.
    def m1(ticker: str, date: str) -> float:
        return float(oof.proba.get((ticker, date), 0.0))

    # F1 — momentum 12-1, percentil cross-sectional del día. Se precomputa por
    # fecha porque el percentil depende de todos los candidatos del día.
    mom_by_date: dict[str, dict[str, float | None]] = {}
    for s in dataset.samples:
        mom_by_date.setdefault(s.date, {})[s.ticker] = s.mom121
    pct_by_date = {d: cross_sectional_percentile(v) for d, v in mom_by_date.items()}

    def f1(ticker: str, date: str) -> float:
        return float((pct_by_date.get(date) or {}).get(ticker, 0.0))

    return {BASELINE_ARM: None, "B1_buy_score": b1, PRIMARY_ARM: m1, "F1_mom121": f1}


def run_diagnostics(ds, oof, probs_by, bars_by, sigs_by, entries, common) -> dict:
    """Diagnósticos **post-hoc** — NO participan del veredicto pre-registrado.

    Existen para responder dos preguntas que el resultado de los brazos no
    contesta por sí solo:

    1. **¿El harness puede detectar un ranking bueno?** Un resultado nulo no vale
       nada si el instrumento es ciego. El brazo ``ORACULO`` rankea por el
       retorno **realizado** del ciclo — mira el futuro descaradamente y no se
       puede shipear jamás — y el ``ANTI_ORACULO`` hace lo contrario. Si el
       oráculo no le saca ventaja al baseline, el resultado de los brazos reales
       no significa nada y hay que arreglar el harness antes de concluir.
    2. **¿Algún score correlaciona con el resultado?** Es el número que explica
       *por qué* pasó lo que pasó, y el que se compara contra el
       ``corr(buy_score, fwd5) ≈ −0.08 (n=27)`` de la auditoría 2026-06-30.
    """
    from analysis.scaleout_replay import replay_cycle
    from analysis.walkforward_power import pearson

    oos_start = f"{min(f.test_year for f in oof.folds)}-01-01"
    realized: dict[tuple[str, str], float] = {}
    rows = []
    for s in ds.samples:
        if s.date < oos_start:
            continue
        cyc = replay_cycle(
            bars_by[s.ticker], s.bar_idx, sigs_by.get(s.ticker) or {},
            params=common["so_params"], atr_p=common["atr_p"],
            cap_days=common["cap_days"], costs=common["costs"], notional=10_000.0,
            fill_mode=common["fill_mode"],
        )
        if cyc is None:
            continue
        r = cyc.total_proceeds / cyc.entry_cost - 1.0
        realized[(s.ticker, s.date)] = r
        rows.append((s, r))

    print("\n" + "=" * 78)
    print("DIAGNÓSTICOS POST-HOC — no pre-registrados, no deciden el veredicto")
    print("=" * 78)

    print("\n[a] ¿El harness puede detectar un ranking bueno? (oráculo = mira el futuro)")
    probes = {
        "B0_neutral": None,
        "ORACULO": lambda t, d: realized.get((t, d), -9.9),
        "ANTI_ORACULO": lambda t, d: -realized.get((t, d), 9.9),
    }
    out_probe = {}
    print(f"    {'brazo':<16}{'CAGR':>10}{'Sharpe':>9}{'max DD':>9}{'equity':>16}")
    for name, rs in probes.items():
        r = simulate_portfolio(entries, bars_by, sigs_by, rank_score=rs, **common)
        out_probe[name] = {"cagr": cagr(r), "sharpe": sharpe_annual(r),
                           "max_dd": r.max_dd, "final_equity": r.final_equity}
        print(f"    {name:<16}{cagr(r):>9.2f}%{sharpe_annual(r):>9.2f}"
              f"{100*r.max_dd:>8.1f}%{r.final_equity:>16,.0f}")

    print("\n[b] ¿Algún score correlaciona con el retorno realizado del ciclo?")
    mom_by_date: dict[str, dict] = {}
    for s, _ in rows:
        mom_by_date.setdefault(s.date, {})[s.ticker] = s.mom121
    pct = {d: cross_sectional_percentile(v) for d, v in mom_by_date.items()}
    scores = {
        "B1 buy_score": [s.buy_score or 0.0 for s, _ in rows],
        "M1 meta proba": [oof.proba.get((s.ticker, s.date), 0.0) for s, _ in rows],
        "F1 mom 12-1": [pct[s.date][s.ticker] for s, _ in rows],
    }
    rets = [r for _, r in rows]
    labels = [float(s.label) for s, _ in rows]
    out_corr = {}
    print(f"    {'score':<16}{'corr vs retorno':>17}{'corr vs etiqueta':>18}"
          f"{'ret top-20%':>14}{'ret bot-20%':>14}")
    for name, xs in scores.items():
        c_ret, c_lab = pearson(xs, rets), pearson(xs, labels)
        order = sorted(range(len(xs)), key=lambda i: xs[i], reverse=True)
        k = max(1, len(order) // 5)
        top = statistics.fmean(rets[i] for i in order[:k])
        bot = statistics.fmean(rets[i] for i in order[-k:])
        out_corr[name] = {"corr_return": c_ret, "corr_label": c_lab,
                          "top20_ret": top, "bot20_ret": bot}
        print(f"    {name:<16}{c_ret:>+17.4f}{c_lab:>+18.4f}"
              f"{100*top:>13.2f}%{100*bot:>13.2f}%")
    lab_corr = pearson(labels, rets)
    print(f"    {'(la etiqueta)':<16}{lab_corr:>+17.4f}   ← la etiqueta SÍ es lo que "
          f"hay que predecir; el problema es predecirla")
    return {"n": len(rows), "probes": out_probe, "correlations": out_corr,
            "label_corr": lab_corr}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rediseño del modelo predictivo (Tarea 9)")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--fill-mode", choices=(HARNESS_FILL_MODE, LEGACY_FILL_MODE),
                   default=HARNESS_FILL_MODE,
                   help=f"'{LEGACY_FILL_MODE}' reproduce el veredicto publicado "
                        f"(look-ahead en el fill de la barrera — Tarea 33)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--diagnostics", action="store_true",
                   help="oráculo (valida que el harness detecte rankings) + "
                        "correlaciones score-vs-resultado. Post-hoc, no deciden.")
    args = p.parse_args(argv)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, probs_by, frames_by, missing, incomplete = load_bars_signals_probs(
        tickers, args.period, args.warmup
    )
    if missing or incomplete:
        print(f"AVISO: {len(missing)} sin datos, {len(incomplete)} incompletos",
              file=sys.stderr)
    if not bars_by:
        print("Sin datos: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1

    announce(args.max_positions, args.universe, len(bars_by),
             window=artifact_window(bars_by),
             verdict_max_positions=LEGACY_MAX_POSITIONS, fill_mode=args.fill_mode)
    print(f"Tickers: {len(bars_by)} · period={args.period} · warmup={args.warmup}")

    # 1 · Dataset pooled con la etiqueta triple-barrera.
    ds = build_dataset(bars_by, sigs_by, frames_by, probs_by=probs_by, warmup=args.warmup)
    if not ds.samples:
        print("Dataset vacío.", file=sys.stderr)
        return 1
    print(f"Muestras BUY etiquetadas: {len(ds.samples):,} "
          f"(descartadas: {ds.n_dropped_no_label:,} sin etiqueta, "
          f"{ds.n_dropped_nan_features:,} sin features) · "
          f"tasa base y=1: {100*ds.base_rate:.1f}%")

    # 2 · Meta-modelo pooled walk-forward (purge + embargo).
    print("\nEntrenando el meta-modelo pooled walk-forward…", flush=True)
    oof = walkforward_oof(ds)
    if not oof.folds:
        print("El walk-forward no produjo ningún fold utilizable.", file=sys.stderr)
        return 1
    print(f"{'año':>6}{'train':>9}{'purgadas':>10}{'calib':>8}{'test':>7}"
          f"{'base y=1':>10}{'AUC OOS':>10}")
    for f in oof.folds:
        auc = "—" if f.auc is None else f"{f.auc:.3f}"
        print(f"{f.test_year:>6}{f.n_train:>9,}{f.n_purged:>10,}{f.n_calib:>8,}"
              f"{f.n_test:>7,}{100*f.test_base_rate:>9.1f}%{auc:>10}")
    agg_auc = oof.auc
    print(f"AUC OOS agregada: {'—' if agg_auc is None else f'{agg_auc:.4f}'} "
          f"(0.500 = sin poder discriminante)")

    # 3 · Ventana OOS común a los cuatro brazos (§8, aclaración pre-corrida).
    oos_years = {f.test_year for f in oof.folds}
    oos_start = f"{min(oos_years)}-01-01"
    entries = [(s.ticker, s.bar_idx) for s in ds.samples if s.date >= oos_start]
    print(f"\nVentana OOS: {oos_start} → fin · entradas candidatas: {len(entries):,} "
          f"· max_positions={args.max_positions} · capital={args.capital:,.0f}")

    rank_scores = build_rank_scores(ds, oof, probs_by)
    common = dict(
        max_positions=args.max_positions, initial_capital=args.capital,
        cap_days=args.cap_days, atr_p=AtrParams(), so_params=ScaleOutParams(),
        costs=CostModel(), regime_of=regime_for_date, fill_mode=args.fill_mode,
    )
    results: dict[str, PortfolioResult] = {
        name: simulate_portfolio(entries, bars_by, sigs_by,
                                 rank_score=rank_scores[name], **common)
        for name in ARM_NAMES
    }

    # 4 · Gates de integridad — ANTES de leer resultados.
    base = results[BASELINE_ARM]
    integrity_ok = True
    print("\nGates de integridad (se evalúan antes de leer resultados):")
    for name in ARM_NAMES:
        drift = equity_integrity_drift(results[name])
        ok_d = drift <= INTEGRITY_MAX_DRIFT
        inv_ok, detail = (True, "—") if name == BASELINE_ARM else \
            check_exit_invariant(base, results[name])
        integrity_ok = integrity_ok and ok_d and inv_ok
        print(f"  {name:<16} equity-vs-cash {100*drift:.4f}% {'OK' if ok_d else 'ROTO'}"
              f"  ·  exits {'OK' if inv_ok else 'ROTO'} ({detail})")
    if not integrity_ok:
        print("\nGATE DE INTEGRIDAD ROTO — los resultados no se leen. "
              "Es un bug del harness, no un veredicto.", file=sys.stderr)
        return 2

    # 5 · Métricas + kill-criteria.
    base_cagr, base_dd = cagr(base), base.max_dd
    curves = {n: _daily_returns(results[n].equity_curve) for n in ARM_NAMES}
    T = min(len(v) for v in curves.values())
    perf = {n: v[:T] for n, v in curves.items()}
    pbo = pbo_cscv(perf)
    trial_sharpes = [
        (statistics.fmean(v) / statistics.pstdev(v)) if len(v) > 1 and statistics.pstdev(v) > 0
        else 0.0
        for v in perf.values()
    ]
    prim = perf[PRIMARY_ARM]
    prim_sharpe = ((statistics.fmean(prim) / statistics.pstdev(prim))
                   if len(prim) > 1 and statistics.pstdev(prim) > 0 else 0.0)
    dsr = deflated_sharpe_ratio(trial_sharpes, n_obs=T, selected=prim_sharpe)

    summaries = []
    for name in ARM_NAMES:
        r = results[name]
        c, dd = cagr(r), r.max_dd
        s = {
            "arm": name, "cagr": c, "sharpe": sharpe_annual(r),
            "total_return_pts": r.total_return_pts, "final_equity": r.final_equity,
            "max_dd": dd, "n_offered": r.n_offered, "n_taken": r.n_taken,
            "n_no_slot": r.n_no_slot, "n_already_open": r.n_already_open,
            "exposure": r.exposure_share, "by_regime": by_regime(r),
        }
        if name != BASELINE_ARM:
            s["delta_cagr_pts"] = c - base_cagr
            s["dd_ratio"] = (dd / base_dd) if base_dd > 0 else 0.0
            s["passes_cagr"] = s["delta_cagr_pts"] >= KILL_MIN_CAGR_PTS
            s["passes_dd"] = s["dd_ratio"] <= KILL_MAX_DD_RATIO
            s["passes"] = bool(s["passes_cagr"] and s["passes_dd"]
                               and pbo.pbo <= KILL_MAX_PBO
                               and dsr.deflated_sharpe > KILL_MIN_DSR)
        summaries.append(s)

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": len(ds.samples), "base_rate": ds.base_rate,
        "auc_oos": agg_auc, "oos_start": oos_start, "n_entries": len(entries),
        "n_tickers": len(bars_by), "max_positions": args.max_positions,
        "capital": args.capital,
        "pbo": pbo.pbo, "dsr": dsr.deflated_sharpe, "n_trials": len(ARM_NAMES),
        "kill_criteria": {
            "min_cagr_pts": KILL_MIN_CAGR_PTS, "max_dd_ratio": KILL_MAX_DD_RATIO,
            "max_pbo": KILL_MAX_PBO, "min_dsr": KILL_MIN_DSR,
        },
        "folds": [vars(f) for f in oof.folds],
    }
    if args.json:
        print(json.dumps({"context": ctx, "summaries": summaries},
                         ensure_ascii=False, indent=2, default=str))
        return 0

    hdr = (f"{'brazo':<16}{'CAGR':>9}{'Δ CAGR':>9}{'Sharpe':>8}{'max DD':>9}"
           f"{'DD ratio':>10}{'equity':>12}{'tomadas':>9}{'PASS':>6}")
    print("\n" + hdr)
    print("-" * len(hdr))
    for s in summaries:
        d = s.get("delta_cagr_pts")
        ddr = s.get("dd_ratio")
        print(f"{s['arm']:<16}{s['cagr']:>8.2f}%"
              f"{('—' if d is None else f'{d:+.2f}'):>9}"
              f"{s['sharpe']:>8.2f}{100*s['max_dd']:>8.1f}%"
              f"{('—' if ddr is None else f'{ddr:.2f}x'):>10}"
              f"{s['final_equity']:>12,.0f}{s['n_taken']:>9}"
              f"{('' if s.get('passes') is None else ('SI' if s['passes'] else 'no')):>6}")

    print("\nPor régimen — retorno medio por trade (pts) / n trades:")
    names = ["bull_normal"] + [r.name for r in STRESS_REGIMES]
    print(f"  {'brazo':<16}" + "".join(f"{n:>22}" for n in names))
    for s in summaries:
        cells = "".join(
            f"{s['by_regime'][n]['mean_ret_pts']:>+15.2f} (n={s['by_regime'][n]['n_trades']:>3})"
            for n in names
        )
        print(f"  {s['arm']:<16}{cells}")

    print(f"\nRobustez ({len(ARM_NAMES)} brazos como intentos, T={T} observaciones):")
    print(f"  PBO (CSCV) = {pbo.pbo:.3f}   (umbral ≤ {KILL_MAX_PBO})")
    print(f"  DSR        = {dsr.deflated_sharpe:.3f}   (umbral > {KILL_MIN_DSR}) · "
          f"SR0 esperado bajo el nulo = {dsr.expected_max_sharpe:.4f}")

    print(f"\nKill-criteria (§9): CAGR ≥ CAGR(B0) + {KILL_MIN_CAGR_PTS} pts "
          f"Y max DD ≤ {KILL_MAX_DD_RATIO}× Y PBO ≤ {KILL_MAX_PBO} Y DSR > {KILL_MIN_DSR}")
    prim_s = next(s for s in summaries if s["arm"] == PRIMARY_ARM)
    print(f"Brazo PRIMARIO ({PRIMARY_ARM}): "
          f"{'PASA' if prim_s.get('passes') else 'NO PASA'}")

    # La comparación B1 vs B0 tiene su propia regla de decisión (§9, tabla).
    b1_s = next(s for s in summaries if s["arm"] == "B1_buy_score")
    d_b1 = b1_s["delta_cagr_pts"]
    if d_b1 <= -KILL_MIN_CAGR_PTS:
        verdict = ("el buy_score elige PEOR que el orden alfabético → corresponde "
                   "shipear la simplificación (ranking no-predictivo, score display-only)")
    elif d_b1 >= KILL_MIN_CAGR_PTS:
        verdict = ("el buy_score aporta pese al corr(score,fwd5)≈−0.08 → se documenta "
                   "el hallazgo y no se toca nada")
    else:
        verdict = ("no hay diferencia medible entre rankear por score y no rankear → "
                   "no se cambia nada en el engine; el score queda anotado como no-validado")
    print(f"\nB1 vs B0 (regla propia): Δ CAGR = {d_b1:+.2f} pts → {verdict}")

    if args.diagnostics:
        run_diagnostics(ds, oof, probs_by, bars_by, sigs_by, entries, common)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
