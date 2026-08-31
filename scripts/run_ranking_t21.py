"""
Runner de la decisión sobre el ranking vivo — **Tarea 21**.

Pre-registro con la regla CONGELADA: ``docs/ranking_prereg_t21_2026-08-12.md``.

Qué hace (fiel al pre-registro)
-------------------------------
1. Universo **vivo** (127 tickers, T27), entradas ``analyze BUY`` PIT, ``portfolio_sim``
   con **10 slots** y ``cap_days=250`` (lección T13). Lo único que cambia entre brazos
   es el **orden** de los candidatos del mismo día.
2. Brazos: ``B1_score`` (baseline = lo que corre hoy) vs ``B0_neutral`` (candidato,
   orden alfabético = sin información); ``B2_no_volpen`` (diagnóstico: ¿alcanza el
   parche de una línea?); ``B0r_random`` ×N semillas (¿el alfabético fue suerte?);
   ``ORACULO``/``ANTI_ORACULO`` (sanity del instrumento).
3. Regla de decisión §4 con el **maxDD como criterio propio** y el **caso partido
   resuelto ex ante**: si el candidato rinde más pero con drawdown materialmente
   peor, es NO-SHIP y la tarea cierra en la opción (a).
4. Gate anti-overfit = **block-bootstrap pareado** (la T27 midió que el PBO es
   inestable a la config). DSR/PBO se reportan como descriptivos.

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py``/``strategies.py``.

Enabler agregado por la **Tarea 39** (no mueve el veredicto publicado): ``--eval-mode``
(regla del engine, 26b) y ``--live-gates`` (gates de re-entrada, T34). Los defaults
son los de la corrida publicada — ``close`` y OFF—, así que reproducirla sigue siendo
``--fill-mode resting`` y nada más.

Limitación declarada de los brazos ``B0r_random`` (**tarea 40**, encontrada al auditar
el instrumento para la T39): el valor de ranking sale de ``random.random()`` cacheado
por par ``(ticker, fecha)``, así que **depende del orden en que el ``sorted()`` del día
pide las claves**, no sólo de la semilla y el par. Es determinista y reproducible dentro
de una corrida —``by_date`` se arma de ``entries``, idéntico entre brazos, y la clave se
pide una vez por candidato del día—, por eso **la banda publicada de la T21 se sostiene**
y se deja tal cual para poder reproducirla bit a bit. Pero **no es el objeto shipeable**:
el engine ve otro conjunto de candidatos en cada scan. Todo harness nuevo usa
``analysis.rank_policy.neutral_rank``, que es una función pura de
``(semilla, fecha, ticker)``.
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

from analysis.exit_replay import AtrParams
from analysis.harness_config import (
    HARNESS_FILL_MODE,
    LEGACY_FILL_MODE,
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    announce,
    artifact_window,
)
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
from scripts.precompute_pit_risk_score import load_existing as _load_risk
from scripts.precompute_pit_risk_score import out_path as _risk_path
from scripts.precompute_pit_signals import _load_existing, _out_path, parse_universe_file
from scripts.run_tp_cal_replay_t23 import aligned_returns, buy_entries

CAP_DAYS = 250  # lección T13 §2 (el engine no tiene tope de tenencia)
VOL_PENALTY_COEF = 0.08  # ml_signals.py:1147

BASELINE_ARM = "B1_score"
CANDIDATE_ARM = "B0_neutral"
DIAGNOSTIC_ARM = "B2_no_volpen"
ORACLE_ARM = "ORACULO"
ANTI_ORACLE_ARM = "ANTI_ORACULO"

# §4 — regla de decisión congelada.
KILL_MIN_DCAGR = 0.0050  # C1: ΔCAGR ≥ +0.50pp
KILL_DD_TOL = 0.0300  # C2: maxDD ≤ base + 3.00pp (la métrica de riesgo, al frente)
KILL_SHARPE_TOL = 0.05  # C4: Sharpe ≥ base − 0.05

# §5 — sanity del instrumento.
SANITY_ORACLE_EDGE = 0.0500  # ORACULO ≥ B1 + 5.00pp de CAGR
SANITY_MIN_TRADE_DIFF = 0.10  # ≥10% de los trades difieren entre B0 y B1

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345


# ── Carga ────────────────────────────────────────────────────────────────────


def load_bars_signals_scores(tickers, period: str, warmup: int):
    """{ticker: [Bar]}, {ticker: {iso: signal}}, {ticker: {iso: score}}, faltantes."""
    from data import parquet_cache

    bars_by: dict[str, list] = {}
    sigs_by: dict[str, dict] = {}
    score_by: dict[str, dict] = {}
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
        bars = []
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
        sig_rows = blob.get("signals") or {}
        sigs_by[t] = {d: sv[0] for d, sv in sig_rows.items() if sv[0]}
        score_by[t] = {d: sv[1] for d, sv in sig_rows.items() if len(sv) > 1 and sv[1] is not None}
    return bars_by, sigs_by, score_by, missing


# El brazo B2 sólo es válido si el precómputo cubre **todo** el universo: con
# cobertura parcial rankearía unos tickers por ``raw_prob`` y otros por ``score``,
# o sea un brazo que no es ni uno ni otro. Ante duda, no existe.
MIN_RISK_COVERAGE = 0.99


def load_risk_scores(tickers, period: str, warmup: int) -> tuple[dict[str, dict], float]:
    """({ticker: {iso: risk_score}}, cobertura). Devuelve ``({}, cob)`` si la
    cobertura no alcanza — ver ``MIN_RISK_COVERAGE``."""
    out: dict[str, dict] = {}
    for t in tickers:
        blob = _load_risk(_risk_path(t, period, warmup))
        if not (blob or {}).get("complete"):
            continue
        rows = (blob or {}).get("risk") or {}
        if rows:
            out[t] = {d: v for d, v in rows.items() if v is not None}
    coverage = (len(out) / len(tickers)) if tickers else 0.0
    if coverage < MIN_RISK_COVERAGE:
        return {}, coverage
    return out, coverage


# ── Brazos ───────────────────────────────────────────────────────────────────


def build_rank_fns(score_by, risk_by, realized, *, n_random: int, seed: int):
    """Los ``rank_score`` de cada brazo. ``None`` ⇒ alfabético (sin información)."""
    import random

    def b1(t: str, d: str) -> float:
        return float((score_by.get(t) or {}).get(d, 0.0))

    def b2(t: str, d: str) -> float:
        """``raw_prob`` = score + 0.08·risk_score (deshace la penalidad de vol)."""
        s = (score_by.get(t) or {}).get(d)
        r = (risk_by.get(t) or {}).get(d)
        if s is None:
            return 0.0
        if r is None:
            return float(s)
        return float(s) + VOL_PENALTY_COEF * float(r)

    arms: dict[str, object] = {
        BASELINE_ARM: b1,
        CANDIDATE_ARM: None,
        ORACLE_ARM: (lambda t, d: realized.get((t, d), -9.9)),
        ANTI_ORACLE_ARM: (lambda t, d: -realized.get((t, d), 9.9)),
    }
    if risk_by:
        arms[DIAGNOSTIC_ARM] = b2

    for k in range(n_random):
        rnd = random.Random(seed + k)
        cache: dict[tuple[str, str], float] = {}

        def rand_rank(t: str, d: str, _rnd=rnd, _cache=cache) -> float:
            key = (t, d)
            if key not in _cache:
                _cache[key] = _rnd.random()
            return _cache[key]

        arms[f"B0r_random_{k}"] = rand_rank
    return arms


def precompute_realized(entries, bars_by, sigs_by, common) -> dict:
    """Retorno realizado del ciclo de cada entrada — alimenta el oráculo (§5.2)."""
    out: dict[tuple[str, str], float] = {}
    for ticker, idx in entries:
        bars = bars_by.get(ticker)
        if not bars or idx >= len(bars):
            continue
        cyc = replay_cycle(
            bars,
            idx,
            sigs_by.get(ticker) or {},
            params=common["so_params"],
            atr_p=AtrParams(),
            cap_days=common["cap_days"],
            costs=common["costs"],
            notional=10_000.0,
            eval_mode=common.get("eval_mode", "close"),
            fill_mode=common["fill_mode"],
        )
        if cyc is not None and cyc.entry_cost > 0:
            out[(ticker, bars[idx][0])] = cyc.total_proceeds / cyc.entry_cost - 1.0
    return out


# ── Métricas ─────────────────────────────────────────────────────────────────


def _accounting_ok(res: PortfolioResult) -> bool:
    if not res.equity_curve or res.final_equity <= 0:
        return True
    return abs(res.equity_curve[-1][1] - res.final_equity) / res.final_equity <= 1e-6


def summarise(res: PortfolioResult) -> dict:
    return {
        "cagr": cagr(res.equity_curve),
        "sharpe": sharpe_annual(res.equity_curve),
        "max_dd": res.max_dd,
        "n_taken": res.n_taken,
        "n_offered": res.n_offered,
        "final_equity": res.final_equity,
        "mean_held_days": (statistics.fmean([t.held_days for t in res.trades]) if res.trades else 0.0),
        "accounting_ok": _accounting_ok(res),
    }


def regime_breakdown(res: PortfolioResult) -> dict:
    out: dict[str, dict] = {}
    for name in ["bull_normal"] + [r.name for r in STRESS_REGIMES]:
        tr = [t for t in res.trades if t.regime == name]
        out[name] = {
            "n": len(tr),
            "mean_ret_pts": 100.0 * statistics.fmean([t.ret for t in tr]) if tr else 0.0,
        }
    return out


def trade_overlap(a: PortfolioResult, b: PortfolioResult) -> float:
    """Fracción de trades que **difieren** entre dos brazos (§5.4)."""
    sa = {(t.ticker, t.entry_date) for t in a.trades}
    sb = {(t.ticker, t.entry_date) for t in b.trades}
    union = sa | sb
    if not union:
        return 0.0
    return len(union - (sa & sb)) / len(union)


# ── Regla de decisión (§4) ───────────────────────────────────────────────────


def evaluate(summaries: dict, boot) -> dict:
    base = summaries[BASELINE_ARM]
    cand = summaries[CANDIDATE_ARM]
    b_sh = base["sharpe"] if base["sharpe"] is not None else -1e9
    c_sh = cand["sharpe"] if cand["sharpe"] is not None else -1e9

    c1 = (cand["cagr"] - base["cagr"]) >= KILL_MIN_DCAGR
    c2 = cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL
    c3 = boot is not None and boot.ci_low > 0.0
    c4 = c_sh >= b_sh - KILL_SHARPE_TOL
    ship = bool(cand["accounting_ok"] and c1 and c2 and c3 and c4)

    # El caso partido, resuelto ex ante por el pre-registro §4.
    if c1 and not c2:
        outcome = (
            "NO-SHIP — caso partido resuelto ex ante: el ranking neutral rinde "
            "más pero el drawdown se deteriora por encima de la tolerancia "
            "declarada. La tarea 21 cierra en la OPCIÓN (a)."
        )
    elif ship:
        outcome = "SHIP — el ranking pasa a no-predictivo (opción (b))."
    else:
        outcome = "NO-SHIP — la tarea 21 cierra en la OPCIÓN (a)."

    return {
        "dcagr": cand["cagr"] - base["cagr"],
        "dd_delta": cand["max_dd"] - base["max_dd"],
        "sharpe_delta": c_sh - b_sh,
        "c1_cagr": c1,
        "c2_maxdd": c2,
        "c3_bootstrap": c3,
        "c4_sharpe": c4,
        "ship": ship,
        "outcome": outcome,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Decisión sobre el ranking vivo (Tarea 21)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--random-arms", type=int, default=10)
    p.add_argument(
        "--fill-mode",
        choices=(HARNESS_FILL_MODE, LEGACY_FILL_MODE),
        default=HARNESS_FILL_MODE,
        help=f"'{LEGACY_FILL_MODE}' reproduce el veredicto publicado "
        f"(look-ahead en el fill de la barrera — Tarea 33)",
    )
    # Enabler de la Tarea 39: los dos desvíos que la T21 no modelaba. Defaults =
    # los de la corrida publicada, así agregarlos no mueve su veredicto.
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
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, score_by, missing = load_bars_signals_scores(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}", file=sys.stderr)

    entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not entries:
        print("Sin entradas BUY.", file=sys.stderr)
        return 1

    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=artifact_window(bars_by),
        eval_mode=args.eval_mode,
        fill_mode=args.fill_mode,
        live_gates=args.live_gates,
        file=log,
    )
    risk_by, risk_cov = load_risk_scores(list(bars_by), args.period, args.warmup)
    print(
        f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)} · "
        f"risk_score PIT: {100 * risk_cov:.0f}% de cobertura"
        + (
            ""
            if risk_by
            else f"  (< {100 * MIN_RISK_COVERAGE:.0f}% → SIN brazo B2: con cobertura parcial "
            "rankearía unos tickers por raw_prob y otros por score)"
        ),
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
        eval_mode=args.eval_mode,
        fill_mode=args.fill_mode,
        live_gates=args.live_gates,
    )
    realized = precompute_realized(entries, bars_by, sigs_by, common)
    print(f"Retornos realizados para el oráculo: {len(realized)}\n", file=log)

    arms = build_rank_fns(score_by, risk_by, realized, n_random=args.random_arms, seed=BOOT_SEED)
    results = {
        name: simulate_portfolio(entries, bars_by, sigs_by, atr_p=AtrParams(), rank_score=fn, **common)
        for name, fn in arms.items()
    }
    summaries = {n: summarise(r) for n, r in results.items()}
    regimes = {n: regime_breakdown(results[n]) for n in (BASELINE_ARM, CANDIDATE_ARM)}

    # C3 — bootstrap pareado candidato vs baseline.
    rets = aligned_returns(results, [BASELINE_ARM, CANDIDATE_ARM])
    boot = paired_block_bootstrap(
        rets[BASELINE_ARM], rets[CANDIDATE_ARM], block=BOOT_BLOCK, n_resamples=args.resamples, seed=BOOT_SEED
    )

    # §5 — sanity del instrumento.
    diff_share = trade_overlap(results[BASELINE_ARM], results[CANDIDATE_ARM])
    sanity = {
        "accounting": all(summaries[n]["accounting_ok"] for n in results),
        "oracle_edge": summaries[ORACLE_ARM]["cagr"] - summaries[BASELINE_ARM]["cagr"],
        "oracle_ok": (summaries[ORACLE_ARM]["cagr"] >= summaries[BASELINE_ARM]["cagr"] + SANITY_ORACLE_EDGE),
        "anti_oracle_ok": summaries[ANTI_ORACLE_ARM]["cagr"] <= summaries[BASELINE_ARM]["cagr"],
        "trade_diff_share": diff_share,
        "ranking_bites": diff_share >= SANITY_MIN_TRADE_DIFF,
    }
    sanity["all_ok"] = bool(
        sanity["accounting"] and sanity["oracle_ok"] and sanity["anti_oracle_ok"] and sanity["ranking_bites"]
    )

    verdict = evaluate(summaries, boot)
    if not sanity["all_ok"]:
        verdict["ship"] = False
        verdict["outcome"] = (
            "CORRIDA INVÁLIDA — falla un sanity del §5; no hay veredicto (el instrumento no está validado)."
        )

    rand_names = [n for n in results if n.startswith("B0r_random")]
    rand_cagrs = sorted(summaries[n]["cagr"] for n in rand_names)

    # Descriptivos (NO gate): DSR/PBO sobre los brazos reales.
    real_arms = [n for n in (BASELINE_ARM, CANDIDATE_ARM, DIAGNOSTIC_ARM) if n in results]
    rets_all = aligned_returns(results, real_arms)
    T = len(next(iter(rets_all.values()))) if rets_all else 0
    pbo = pbo_cscv({c: rets_all[c] for c in real_arms}, n_splits=10) if T >= 10 else None
    dsr = None
    if T >= 2:
        sk, ku = _skew_kurt(rets_all[CANDIDATE_ARM])
        dsr = deflated_sharpe_ratio(
            [_sharpe(rets_all[c]) for c in real_arms],
            n_obs=T,
            selected=_sharpe(rets_all[CANDIDATE_ARM]),
            skew=sk,
            kurtosis=ku,
        )

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by),
        "n_entries": len(entries),
        "max_positions": args.max_positions,
        "cap_days": args.cap_days,
        "eval_mode": args.eval_mode,
        "fill_mode": args.fill_mode,
        "live_gates": args.live_gates,
        "sanity": sanity,
        "verdict": verdict,
        "bootstrap": vars(boot),
        "random_cagr": {
            "n": len(rand_cagrs),
            "min": rand_cagrs[0] if rand_cagrs else None,
            "median": statistics.median(rand_cagrs) if rand_cagrs else None,
            "max": rand_cagrs[-1] if rand_cagrs else None,
        },
        "dsr": (dsr.deflated_sharpe if dsr else None),
        "pbo": (pbo.pbo if pbo else None),
        "dsr_obs": T,
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

    _report(summaries, regimes, ctx, verdict, sanity, boot, rand_cagrs, dsr, pbo, T)
    return 0


def _f(x, w=9, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x * (100 if suf == '%' else 1):>{w - len(suf)}.{p}f}{suf}"


def _report(summaries, regimes, ctx, verdict, sanity, boot, rand_cagrs, dsr, pbo, T):
    hdr = f"{'brazo':<16}{'CAGR':>10}{'Sharpe':>9}{'maxDD':>9}{'tomad':>8}{'días':>7}"
    print(hdr)
    print("-" * len(hdr))
    order = [BASELINE_ARM, CANDIDATE_ARM, DIAGNOSTIC_ARM, ORACLE_ARM, ANTI_ORACLE_ARM]
    for n in order:
        if n not in summaries:
            continue
        s = summaries[n]
        tag = {
            BASELINE_ARM: "BASE (lo vivo)",
            CANDIDATE_ARM: "*candidato",
            DIAGNOSTIC_ARM: "diagnóstico",
        }.get(n, "sanity")
        print(
            f"{n:<16}{_f(s['cagr'], 10, 2, '%')}{_f(s['sharpe'], 9, 2)}{_f(s['max_dd'], 9, 1, '%')}"
            f"{s['n_taken']:>8}{s['mean_held_days']:>7.1f}  {tag}"
        )
    if rand_cagrs:
        print(
            f"{'B0r_random':<16}{_f(statistics.median(rand_cagrs), 10, 2, '%')}"
            f"{'':>9}{'':>9}{'':>8}{'':>7}  n={len(rand_cagrs)} "
            f"[{100 * rand_cagrs[0]:.2f}%, {100 * rand_cagrs[-1]:.2f}%]"
        )

    print("\nSanity del instrumento (§5):")
    print(f"  [{'OK' if sanity['accounting'] else 'FALLA'}] contabilidad")
    print(
        f"  [{'OK' if sanity['oracle_ok'] else 'FALLA'}] el oráculo despega: "
        f"+{100 * sanity['oracle_edge']:.2f}pp sobre el baseline (mín +5.00pp)"
    )
    print(f"  [{'OK' if sanity['anti_oracle_ok'] else 'FALLA'}] el anti-oráculo hunde")
    print(
        f"  [{'OK' if sanity['ranking_bites'] else 'FALLA'}] el ranking muerde: "
        f"{100 * sanity['trade_diff_share']:.1f}% de trades distintos (mín 10%)"
    )

    print("\nPor régimen (ret medio por trade, pts):")
    for r in regimes[BASELINE_ARM]:
        b = regimes[BASELINE_ARM][r]["mean_ret_pts"]
        c = regimes[CANDIDATE_ARM][r]["mean_ret_pts"]
        print(f"  {r:<20} base {b:>+6.2f} · cand {c:>+6.2f} · Δ {c - b:>+6.2f}")

    print(
        f"\nΔCAGR {_f(verdict['dcagr'], 0, 2, '%')} · ΔmaxDD {_f(verdict['dd_delta'], 0, 2, '%')} · "
        f"ΔSharpe {verdict['sharpe_delta']:+.3f}"
    )
    print(
        f"Bootstrap pareado: ΔCAGR obs {100 * boot.observed:+.2f}pp · "
        f"IC95% [{100 * boot.ci_low:+.2f}, {100 * boot.ci_high:+.2f}]pp · p={boot.p_value:.3f} "
        f"(bloques {boot.block}, {boot.n_resamples} resamples, T={boot.n_obs})"
    )

    print("\nRegla de decisión (§4):")
    for k, label in [
        ("c1_cagr", "C1 ΔCAGR ≥ +0.50pp"),
        ("c2_maxdd", "C2 maxDD ≤ base + 3.00pp  ← métrica de riesgo"),
        ("c3_bootstrap", "C3 IC95% inferior > 0"),
        ("c4_sharpe", "C4 Sharpe no-inferior"),
    ]:
        print(f"  [{'PASA' if verdict[k] else 'FALLA'}] {label}")
    head = f"DSR = {dsr.deflated_sharpe:.3f}" if dsr else "DSR = n/d"
    tail = f"· PBO = {pbo.pbo:.3f}" if pbo else "· PBO = n/d"
    print(f"\nDescriptivos (NO son gate): {head} {tail} (T={T} obs)")
    print(f"\n  VEREDICTO: {verdict['outcome']}")


if __name__ == "__main__":
    raise SystemExit(main())
