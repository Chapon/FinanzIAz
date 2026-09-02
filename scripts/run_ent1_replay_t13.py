"""
Runner del replay de micro-reglas de entrada/salida — Tarea 13 (ENT1).

Pre-registro con kill-criteria CONGELADOS: ``docs/ent1_prereg_t13_2026-08-12.md``.
Reusa el harness PIT de T7 (señal ``analyze()`` completa, ``data/pit_signals/``) +
``analysis/portfolio_sim.py`` (capital finito, ``max_positions=5``, engine-faithful).

Qué hace (fiel al pre-registro)
-------------------------------
1. Carga barras + señal PIT de los 41 tickers y arma las entradas ``analyze BUY``.
2. Corre ``simulate_portfolio`` por brazo con **``cap_days=250``** (§2: el cap 20 del
   harness haría que el brazo (b) midiera cero por construcción, porque el engine
   vivo no tiene tope de tenencia). **El baseline se re-corre con el mismo cap**, así
   que los números NO son comparables con T7/T8/T9/T10/T23.
3. Brazos: ``BASE``; ``A_pullback`` (EMA20, K=5) y ``B_timestop`` (N=20) de decisión;
   ``A_negday`` y ``B_N10`` exploratorios. ``A+B`` sólo si los dos primarios pasan.
4. Gate anti-overfit = **block-bootstrap pareado** sobre Δ(retorno diario de equity),
   bloques de 20 ruedas, 2000 resamples, IC95% inferior > 0 (§5 C5). DSR/PBO se
   reportan como **descriptivos**, no como gate (lección T23).
5. Aplica los kill-criteria por brazo **por separado** y corre los 4 sanity checks
   del §6 (si uno falla, la corrida es inválida y no hay veredicto).

Sin red, sin tocar ``finanzias.db``: lee Parquet + los JSON de señal. No cambia
ningún flag vivo ni toca ``engine.py``/``strategies.py``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.entry_rules import apply_pullback
from analysis.exit_replay import AtrParams
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
from analysis.meta_labeling import MAX_DAYS
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.risk_sizing import cagr, sharpe_annual
from analysis.scaleout_replay import CostModel, ScaleOutParams, replay_cycle
from analysis.walkforward_power import (
    STRESS_REGIMES,
    _sharpe,
    _skew_kurt,
    deflated_sharpe_ratio,
    paired_block_bootstrap,
    pbo_cscv,
    regime_for_date,
)
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_tp_cal_replay_t23 import aligned_returns, buy_entries, load_bars_signals

DEFAULT_UNIVERSE = "data/harness_universe_41_10y.txt"

# §2 — cap efectivamente no vinculante (el engine vivo no tiene tope de tenencia).
CAP_DAYS = 250

# §4 — parámetros congelados de los brazos.
PULLBACK_WINDOW = 5  # K días hábiles
TIME_STOP_N = MAX_DAYS  # heredado de meta_labeling (nota de la tarea 21)
TIME_STOP_N_EXPLORATORY = 10

BASELINE_ARM = "BASE"
PRIMARY_ARMS = ("A_pullback", "B_timestop")
EXPLORATORY_ARMS = ("A_negday", "B_N10")
COMBINED_ARM = "A+B"

# §5 — kill-criteria congelados.
KILL_MIN_DCAGR = 0.0030  # C1: ΔCAGR ≥ +0.30pp
KILL_SHARPE_TOL = 0.02  # C2: Sharpe ≥ base − 0.02
KILL_DD_TOL = 0.005  # C3: maxDD ≤ base + 0.5pp
KILL_REGIME_TOL = 0.05  # C4: Δ ret medio por trade ≥ −0.05 pts por régimen
KILL_MAX_EXPIRED = 0.20  # C6a: ≤ 20% de las esperas expiran
KILL_WINNER_MEAN_TOL = 0.25  # C6b: ret medio de ganadores no cae > 0.25 pts
KILL_P95_TOL = 1.00  # C6b: p95 del ret por trade no cae > 1.0 pt

# §6 — sanity.
SANITY_MIN_TIMESTOP_POP = 0.05  # ≥ 5% de los trades del BASE alcanzables por (b)
SANITY_MAX_CAP_SHARE = 0.02  # cap_reached residual en BASE

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345


# ── Métricas ─────────────────────────────────────────────────────────────────


def _pct_trade(res: PortfolioResult, q: float) -> float:
    rets = sorted(t.ret for t in res.trades)
    if not rets:
        return 0.0
    return rets[min(len(rets) - 1, int(q * len(rets)))]


def _winner_mean(res: PortfolioResult) -> float:
    """Retorno medio de los trades ganadores, en puntos — la cola derecha (C6b)."""
    w = [t.ret for t in res.trades if t.ret > 0]
    return 100.0 * statistics.fmean(w) if w else 0.0


def _reason_share(res: PortfolioResult, needle: str) -> float:
    if not res.trades:
        return 0.0
    return sum(1 for t in res.trades if needle in (t.exit_reason or "")) / len(res.trades)


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
        "p5_trade": _pct_trade(res, 0.05),
        "p95_trade": _pct_trade(res, 0.95),
        "winner_mean_pts": _winner_mean(res),
        "n_taken": res.n_taken,
        "n_offered": res.n_offered,
        "exposure": res.exposure_share,
        "time_stop_share": _reason_share(res, "time_stop"),
        "cap_share": _reason_share(res, "cap_reached"),
        "mean_held_days": (statistics.fmean([t.held_days for t in res.trades]) if res.trades else 0.0),
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


# ── Sanity §6.3: ¿existe población para el time stop en el BASE? ─────────────


def timestop_population(res: PortfolioResult, bars_by, sigs_by, n_days: int, common) -> float:
    """Fracción de los trades del BASE sobre los que el time stop *actuaría*.

    Se re-corre el ciclo de cada trade tomado por el baseline con el time stop
    activo y se cuenta cuántos habrían salido por ``time_stop``. Es la medición
    exacta de la población objetivo (§6.3): si es chica, el brazo está sin poder y
    el resultado se reporta como "sin población", no como "no funciona".
    """
    if not res.trades:
        return 0.0
    idx_by: dict[str, dict[str, int]] = {}
    hits = 0
    for t in res.trades:
        if t.ticker not in idx_by:
            idx_by[t.ticker] = {b[0]: i for i, b in enumerate(bars_by[t.ticker])}
        i = idx_by[t.ticker].get(t.entry_date)
        if i is None:
            continue
        cyc = replay_cycle(
            bars_by[t.ticker],
            i,
            sigs_by.get(t.ticker) or {},
            params=common["so_params"],
            atr_p=AtrParams(),
            cap_days=common["cap_days"],
            costs=common["costs"],
            notional=10_000.0,
            time_stop_days=n_days,
            fill_mode=common["fill_mode"],
        )
        if cyc is not None and "time_stop" in cyc.exit_reasons:
            hits += 1
    return hits / len(res.trades)


def held_days_profile(res: PortfolioResult, n_days: int) -> dict:
    """Distribución de la tenencia en el baseline + mezcla de razones de salida.

    Es el diagnóstico que interpreta el sanity §6.3: si el brazo (b) queda sin
    población, esto dice **por qué** (la maquinaria de salida ya cierra rápido) en
    vez de dejarlo como un número suelto.
    """
    if not res.trades:
        return {}
    hd = sorted(t.held_days for t in res.trades)
    n = len(hd)
    reasons: dict[str, int] = {}
    for t in res.trades:
        reasons[t.exit_reason or "?"] = reasons.get(t.exit_reason or "", 0) + 1
    long_ones = [t for t in res.trades if t.held_days >= n_days]
    return {
        "n": n,
        "pcts": {f"p{int(q * 100)}": hd[int(q * n)] for q in (0.25, 0.5, 0.75, 0.9, 0.95, 0.99)},
        "max": hd[-1],
        "mean": statistics.fmean(hd),
        "share_ge_n": sum(1 for x in hd if x >= n_days) / n,
        "n_ge_n": len(long_ones),
        "n_ge_n_losing": sum(1 for t in long_ones if t.ret <= 0),
        "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
    }


def pullback_counterfactual(entries, bars_by, sigs_by, common, *, window: int, condition: str) -> dict:
    """Qué habría rendido cada espera **entrando el día de la señal** (baseline),
    separada por cómo terminó la espera.

    Es la pregunta que decide si el brazo (a) filtra bien o mal: si las entradas que
    **expiran** (las que nunca retroceden) rinden más que las que fillan, la regla
    está descartando sistemáticamente a las mejores.
    """
    from analysis.entry_rules import ema_series, resolve_pullback

    buckets: dict[str, list[float]] = {"filled": [], "expired": [], "cancelled": []}
    by_ticker: dict[str, list[int]] = {}
    for tk, idx in entries:
        by_ticker.setdefault(tk, []).append(idx)

    for tk, idxs in by_ticker.items():
        bars = bars_by.get(tk)
        if not bars:
            continue
        ema = ema_series(bars) if condition == "ema20" else []
        sig = sigs_by.get(tk) or {}
        blocked = -1
        for idx in sorted(idxs):
            if idx <= blocked:
                continue
            r = resolve_pullback(bars, idx, sig, window=window, condition=condition, ema=ema)
            blocked = r.resolved_idx
            cyc = replay_cycle(
                bars,
                idx,
                sig,
                params=common["so_params"],
                atr_p=AtrParams(),
                cap_days=common["cap_days"],
                costs=common["costs"],
                notional=10_000.0,
                fill_mode=common["fill_mode"],
            )
            if cyc is not None:
                buckets[r.status].append(cyc.ret)

    out: dict[str, dict] = {}
    for k, v in buckets.items():
        if not v:
            out[k] = {"n": 0}
            continue
        s = sorted(v)
        out[k] = {
            "n": len(v),
            "mean_pts": 100.0 * statistics.fmean(v),
            "median_pts": 100.0 * s[len(s) // 2],
            "p90_pts": 100.0 * s[int(0.9 * len(s))],
            "win_share": sum(1 for x in v if x > 0) / len(v),
        }
    return out


# ── Kill-criteria (§5) ───────────────────────────────────────────────────────


def evaluate_arm(name: str, summaries: dict, regimes: dict, boot, pb_stats) -> dict:
    """Aplica el AND de los criterios a UN brazo contra el baseline."""
    base = summaries[BASELINE_ARM]
    cand = summaries[name]
    b_sh = base["sharpe"] if base["sharpe"] is not None else -1e9
    c_sh = cand["sharpe"] if cand["sharpe"] is not None else -1e9

    reg_delta: dict[str, float] = {}
    reg_ok = True
    for r, v in regimes[name].items():
        d = v["mean_ret_pts"] - regimes[BASELINE_ARM][r]["mean_ret_pts"]
        reg_delta[r] = d
        if d < -KILL_REGIME_TOL:
            reg_ok = False

    c1 = (cand["cagr"] - base["cagr"]) >= KILL_MIN_DCAGR
    c2 = c_sh >= b_sh - KILL_SHARPE_TOL
    c3 = cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL
    c4 = reg_ok
    c5 = boot is not None and boot.ci_low > 0.0

    # C6 — específico del brazo.
    if name.startswith("A"):
        c6 = pb_stats is not None and pb_stats.expired_share <= KILL_MAX_EXPIRED
        c6_label = f"expiran {100 * pb_stats.expired_share:.1f}% ≤ 20%" if pb_stats else "n/d"
    else:
        d_win = cand["winner_mean_pts"] - base["winner_mean_pts"]
        d_p95 = 100.0 * (cand["p95_trade"] - base["p95_trade"])
        c6 = (d_win >= -KILL_WINNER_MEAN_TOL) and (d_p95 >= -KILL_P95_TOL)
        c6_label = f"ganadores Δ{d_win:+.2f} pts · p95 Δ{d_p95:+.2f} pts"

    ship = bool(cand["accounting_ok"] and c1 and c2 and c3 and c4 and c5 and c6)
    return {
        "arm": name,
        "dcagr": cand["cagr"] - base["cagr"],
        "sharpe_delta": c_sh - b_sh,
        "dd_delta": cand["max_dd"] - base["max_dd"],
        "winner_delta": cand["winner_mean_pts"] - base["winner_mean_pts"],
        "p95_delta": 100.0 * (cand["p95_trade"] - base["p95_trade"]),
        "regime_delta": reg_delta,
        "c1_cagr": c1,
        "c2_sharpe": c2,
        "c3_dd": c3,
        "c4_regime": c4,
        "c5_bootstrap": c5,
        "c6_specific": c6,
        "c6_label": c6_label,
        "ship": ship,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay de micro-reglas de entrada/salida (Tarea 13)")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument(
        "--no-diagnose", action="store_true", help="saltea los diagnósticos que interpretan el veredicto"
    )
    p.add_argument(
        "--fill-mode",
        choices=(HARNESS_FILL_MODE, LEGACY_FILL_MODE),
        default=HARNESS_FILL_MODE,
        help=f"'{LEGACY_FILL_MODE}' reproduce el veredicto publicado "
        f"(look-ahead en el fill de la barrera — Tarea 33)",
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
    bars_by, sigs_by, missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)

    base_entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not base_entries:
        print("Sin entradas BUY — nada que evaluar.", file=sys.stderr)
        return 1

    pull_entries, pull_stats = apply_pullback(
        base_entries, bars_by, sigs_by, window=PULLBACK_WINDOW, condition="ema20"
    )
    neg_entries, neg_stats = apply_pullback(
        base_entries, bars_by, sigs_by, window=PULLBACK_WINDOW, condition="negday"
    )

    # Progreso a stderr: con --json el stdout tiene que ser JSON puro y nada más.
    log = sys.stderr if args.json else sys.stdout
    # T30 — frescura del cohorte, ANTES de pagar la corrida (tarea 76). La ventana
    # que declara `artifact_window` es min(starts)..max(ends), así que un solo
    # artefacto desalineado la corre sin que se note. Falla ruidoso (política T22).
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts, file=log)
        announce_signal_store(
            bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts, file=log
        )
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3

    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=artifact_window(bars_by),
        verdict_max_positions=LEGACY_MAX_POSITIONS,
        fill_mode=args.fill_mode,
        file=log,
    )
    print(f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(base_entries)}", file=log)
    for label, st in (("EMA20 ", pull_stats), ("negday", neg_stats)):
        print(
            f"Pullback {label} K={PULLBACK_WINDOW}: {st.n_waits} esperas → "
            f"{st.n_filled} fills / {st.n_expired} expiradas / "
            f"{st.n_cancelled} canceladas ({st.n_dup_skipped} dup)",
            file=log,
        )
    print("", file=log)

    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        fill_mode=args.fill_mode,
    )

    arm_spec: dict[str, tuple[list, int | None]] = {
        BASELINE_ARM: (base_entries, None),
        "A_pullback": (pull_entries, None),
        "B_timestop": (base_entries, TIME_STOP_N),
        "A_negday": (neg_entries, None),
        "B_N10": (base_entries, TIME_STOP_N_EXPLORATORY),
    }
    results = {
        n: simulate_portfolio(ent, bars_by, sigs_by, atr_p=AtrParams(), time_stop_days=ts, **common)
        for n, (ent, ts) in arm_spec.items()
    }
    summaries = {n: summarise(r) for n, r in results.items()}
    regimes = {n: regime_trade_breakdown(r) for n, r in results.items()}

    # ── Bootstrap pareado (C5) por brazo, contra el baseline ─────────────────
    boots: dict[str, object] = {}
    for name in list(PRIMARY_ARMS) + list(EXPLORATORY_ARMS):
        rets = aligned_returns(results, [BASELINE_ARM, name])
        boots[name] = paired_block_bootstrap(
            rets[BASELINE_ARM], rets[name], block=BOOT_BLOCK, n_resamples=args.resamples, seed=BOOT_SEED
        )

    # ── Sanity §6 ────────────────────────────────────────────────────────────
    ts_pop = timestop_population(results[BASELINE_ARM], bars_by, sigs_by, TIME_STOP_N, common)
    sanity = {
        "accounting": all(summaries[n]["accounting_ok"] for n in results),
        "pullback_detector": 0.0 < pull_stats.lost_share < 1.0,
        "timestop_population": ts_pop,
        "timestop_population_ok": ts_pop >= SANITY_MIN_TIMESTOP_POP,
        "cap_share_base": summaries[BASELINE_ARM]["cap_share"],
        "cap_marginal_ok": summaries[BASELINE_ARM]["cap_share"] < SANITY_MAX_CAP_SHARE,
    }
    sanity["all_ok"] = bool(
        sanity["accounting"] and sanity["pullback_detector"] and sanity["cap_marginal_ok"]
    )

    # ── Veredicto por brazo ──────────────────────────────────────────────────
    verdicts = {
        "A_pullback": evaluate_arm("A_pullback", summaries, regimes, boots["A_pullback"], pull_stats),
        "B_timestop": evaluate_arm("B_timestop", summaries, regimes, boots["B_timestop"], None),
    }
    if not sanity["timestop_population_ok"]:
        verdicts["B_timestop"]["ship"] = False
        verdicts["B_timestop"]["no_population"] = True

    # ── A+B: sólo si los dos primarios pasan (§4.3) ──────────────────────────
    if verdicts["A_pullback"]["ship"] and verdicts["B_timestop"]["ship"]:
        results[COMBINED_ARM] = simulate_portfolio(
            pull_entries, bars_by, sigs_by, atr_p=AtrParams(), time_stop_days=TIME_STOP_N, **common
        )
        summaries[COMBINED_ARM] = summarise(results[COMBINED_ARM])
        regimes[COMBINED_ARM] = regime_trade_breakdown(results[COMBINED_ARM])
        rets = aligned_returns(results, [BASELINE_ARM, COMBINED_ARM])
        boots[COMBINED_ARM] = paired_block_bootstrap(
            rets[BASELINE_ARM],
            rets[COMBINED_ARM],
            block=BOOT_BLOCK,
            n_resamples=args.resamples,
            seed=BOOT_SEED,
        )
        verdicts[COMBINED_ARM] = evaluate_arm(
            COMBINED_ARM, summaries, regimes, boots[COMBINED_ARM], pull_stats
        )

    # ── Descriptivos: DSR/PBO sobre todos los brazos corridos ────────────────
    all_names = list(results)
    rets_all = aligned_returns(results, all_names)
    T = len(next(iter(rets_all.values()))) if rets_all else 0
    pbo = pbo_cscv({c: rets_all[c] for c in all_names}, n_splits=10) if T >= 10 else None
    trial_sharpes = [_sharpe(rets_all[c]) for c in all_names]
    shipped = [n for n, v in verdicts.items() if v["ship"]]
    best = max(shipped, key=lambda n: summaries[n]["cagr"]) if shipped else PRIMARY_ARMS[0]
    dsr = None
    if T >= 2:
        sk, ku = _skew_kurt(rets_all[best])
        dsr = deflated_sharpe_ratio(
            trial_sharpes, n_obs=T, selected=_sharpe(rets_all[best]), skew=sk, kurtosis=ku
        )

    # ── Diagnósticos (descriptivos: interpretan el veredicto, no lo deciden) ──
    diag: dict = {}
    if not args.no_diagnose:
        diag["held_days"] = held_days_profile(results[BASELINE_ARM], TIME_STOP_N)
        diag["pullback_cf"] = pullback_counterfactual(
            base_entries, bars_by, sigs_by, common, window=PULLBACK_WINDOW, condition="ema20"
        )

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "diagnostics": diag,
        "n_tickers": len(bars_by),
        "n_entries": len(base_entries),
        "cap_days": args.cap_days,
        "max_positions": args.max_positions,
        "capital": args.capital,
        "time_stop_n": TIME_STOP_N,
        "fill_mode": args.fill_mode,
        "pullback_window": PULLBACK_WINDOW,
        "pullback_stats": vars(pull_stats) | {"expired_share": pull_stats.expired_share},
        "negday_stats": vars(neg_stats) | {"expired_share": neg_stats.expired_share},
        "sanity": sanity,
        "verdicts": verdicts,
        "dsr": (dsr.deflated_sharpe if dsr else None),
        "pbo": (pbo.pbo if pbo else None),
        "dsr_obs": T,
        "bootstrap": {n: vars(b) for n, b in boots.items()},
    }

    if args.json:
        print(
            json.dumps(
                {"context": ctx, "summaries": summaries, "regimes": regimes},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    _report(summaries, regimes, ctx, verdicts, boots, dsr, pbo, T, sanity)
    return 0


def _f(x, w=8, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries, regimes, ctx, verdicts, boots, dsr, pbo, T, sanity):
    hdr = (
        f"{'brazo':<12}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'p5':>8}{'p95':>8}"
        f"{'ganad':>8}{'tomad':>7}{'días':>7}{'%TS':>6}"
    )
    print(hdr)
    print("-" * len(hdr))
    for n in summaries:
        s = summaries[n]
        mark = "BASE" if n == BASELINE_ARM else ("*" if n in PRIMARY_ARMS else "expl")
        print(
            f"{n:<12}{_f(s['cagr'], 9, 2, '%')}{_f(s['sharpe'], 9, 2)}{_f(s['max_dd'], 9, 1, '%')}"
            f"{_f(s['p5_trade'], 8, 1, '%')}{_f(s['p95_trade'], 8, 1, '%')}"
            f"{s['winner_mean_pts']:>8.2f}{s['n_taken']:>7}{s['mean_held_days']:>7.1f}"
            f"{_f(s['time_stop_share'], 6, 0, '%')}  {mark}"
        )

    print("\nSanity (§6):")
    print(f"  [{'OK' if sanity['accounting'] else 'FALLA'}] contabilidad de todos los brazos")
    print(
        f"  [{'OK' if sanity['pullback_detector'] else 'FALLA'}] el detector de pullback "
        f"hace algo (pérdida {100 * ctx['pullback_stats']['n_expired'] / max(1, ctx['pullback_stats']['n_waits']):.1f}% expiradas)"
    )
    print(
        f"  [{'OK' if sanity['timestop_population_ok'] else 'SIN POBLACIÓN'}] población del "
        f"time stop en BASE = {100 * sanity['timestop_population']:.1f}% (mín 5%)"
    )
    print(
        f"  [{'OK' if sanity['cap_marginal_ok'] else 'FALLA'}] cap_reached residual en BASE = "
        f"{100 * sanity['cap_share_base']:.2f}% (máx 2%)"
    )

    for name, v in verdicts.items():
        b = boots.get(name)
        print(f"\n── {name} ──")
        print(
            f"  ΔCAGR {_f(v['dcagr'], 0, 2, '%')} · ΔSharpe {v['sharpe_delta']:+.3f} · "
            f"ΔmaxDD {_f(v['dd_delta'], 0, 2, '%')}"
        )
        if b is not None:
            print(
                f"  Bootstrap pareado: ΔCAGR obs {100 * b.observed:+.2f}pp · "
                f"IC95% [{100 * b.ci_low:+.2f}, {100 * b.ci_high:+.2f}]pp · "
                f"p={b.p_value:.3f} (bloques {b.block}, {b.n_resamples} resamples, T={b.n_obs})"
            )
        print(
            "  Por régimen (Δ ret medio por trade, pts): "
            + " · ".join(f"{r} {d:+.2f}" for r, d in v["regime_delta"].items())
        )
        for k, label in [
            ("c1_cagr", "C1 ΔCAGR ≥ +0.30pp"),
            ("c2_sharpe", "C2 Sharpe no-inferior"),
            ("c3_dd", "C3 DD no peor"),
            ("c4_regime", "C4 régimen robusto"),
            ("c5_bootstrap", "C5 IC95% inferior > 0"),
            ("c6_specific", f"C6 {v['c6_label']}"),
        ]:
            print(f"    [{'PASA' if v[k] else 'FALLA'}] {label}")
        if v.get("no_population"):
            print("    [SIN POBLACIÓN] el sanity §6.3 no se cumple → no es un veredicto de eficacia")
        print(f"    VEREDICTO {name}: {'SHIP' if v['ship'] else 'NO-SHIP'}")

    diag = ctx.get("diagnostics") or {}
    if diag.get("held_days"):
        h = diag["held_days"]
        print("\n── Diagnóstico: tenencia en el BASE (interpreta el §6.3) ──")
        print(
            "  "
            + " · ".join(f"{k} {v}d" for k, v in h["pcts"].items())
            + f" · máx {h['max']}d · media {h['mean']:.1f}d"
        )
        print(
            f"  trades que llegan a {ctx['time_stop_n']} ruedas: {h['n_ge_n']}/{h['n']} "
            f"({100 * h['share_ge_n']:.1f}%) — de ésos, en pérdida al cierre: "
            f"{h['n_ge_n_losing']}"
        )
        print("  razones de salida: " + " · ".join(f"{k} {v}" for k, v in h["reasons"].items()))
    if diag.get("pullback_cf"):
        print("\n── Diagnóstico: qué rinden las esperas del brazo (a) entrando el día de la señal ──")
        for k in ("filled", "expired", "cancelled"):
            d = diag["pullback_cf"].get(k) or {}
            if not d.get("n"):
                continue
            print(
                f"  {k:<10} n={d['n']:>5}  ret medio {d['mean_pts']:+6.2f} pts · "
                f"mediana {d['median_pts']:+6.2f} · p90 {d['p90_pts']:+6.2f} · "
                f"ganadoras {100 * d['win_share']:.0f}%"
            )

    tail = f"· PBO = {pbo.pbo:.3f}" if pbo else "· PBO = n/d"
    head = f"DSR = {dsr.deflated_sharpe:.3f}" if dsr else "DSR = n/d"
    print(f"\nDescriptivos (NO son gate — §5 C5): {head} {tail} (T={T} obs)")


if __name__ == "__main__":
    raise SystemExit(main())
