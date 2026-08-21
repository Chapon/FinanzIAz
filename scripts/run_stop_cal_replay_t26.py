"""
Runner del replay de recalibración del stop ATR — Tarea 26 (STOP-CAL).

Pre-registro con kill-criteria CONGELADOS: ``docs/stop_cal_prereg_t26_2026-08-13.md``
(con la enmienda §0, anterior a toda corrida). Hermana simétrica de la T23: aquélla
movió la barrera de arriba (take-profit), ésta mueve la de abajo.

Qué hace (fiel al pre-registro)
-------------------------------
1. Carga barras + señal PIT del universo **de la cuenta viva** (127 tickers) y arma
   las entradas ``analyze BUY`` — la población real del engine.
2. Corre ``simulate_portfolio`` por brazo variando **solo** ``AtrParams.stop_mult``:
   {1.0, 1.5, 2.0 baseline, 2.5, 3.0, 3.5, off} de decisión, + ``D1_stop_only_3.0``
   de diagnóstico (trailing pineado en 2.0) + ``ORACULO_STOP`` / ``ANTI_ORACULO_STOP``
   de sanity del instrumento.
3. Mide CAGR/Sharpe/maxDD de cartera + mezcla de salidas + retorno medio por trade
   por régimen; bootstrap **pareado** de bloques sobre Δ(retorno diario) como gate
   anti-overfit (DSR/PBO quedan de descriptivos — T13/T27).
4. Aplica §5 (sanity que puede invalidar la corrida) y §6 (los 6 criterios).

**Por qué los brazos mueven stop y trailing juntos:** ``paper_trading/gates.py:101-103``
usa el mismo múltiplo para los dos niveles y ``atr_exit_decision`` ni siquiera recibe
un múltiplo de trailing — mover ``atr_stop_mult`` en vivo mueve las dos barreras. El
brazo ``D1`` existe para atribuir, y **no es promovible** sin pre-registro propio.

Sin red, sin tocar ``finanzias.db``: lee Parquet + los JSON de señal. No cambia ningún
flag vivo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import AtrParams, Bar  # noqa: E402
from analysis.harness_config import (  # noqa: E402
    HARNESS_FILL_MODE,
    LEGACY_FILL_MODE,
    LEGACY_MAX_POSITIONS,
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    announce,
    artifact_window,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio  # noqa: E402
from analysis.risk_sizing import cagr, sharpe_annual  # noqa: E402
from analysis.scaleout_replay import CostModel, ScaleOutParams  # noqa: E402
from analysis.walkforward_power import (  # noqa: E402
    STRESS_REGIMES,
    _sharpe,
    _skew_kurt,
    deflated_sharpe_ratio,
    paired_block_bootstrap,
    pbo_cscv,
    regime_for_date,
)
from scripts.precompute_pit_signals import parse_universe_file  # noqa: E402
from scripts.run_tp_cal_replay_t23 import (  # noqa: E402
    aligned_returns,
    buy_entries,
    load_bars_signals,
)
from scripts.run_ranking_t21 import trade_overlap  # noqa: E402

CAP_DAYS = 250            # lección T13 §2 (el engine no tiene tope de tenencia)
NO_STOP = 1e9             # stop_mult que nunca dispara ("sin barrera de abajo")
ORACLE_HORIZON = 20       # ruedas de look-ahead (el horizonte de la evidencia viva)

BASELINE_ARM = "S_2.0"
# §3.2 — brazos de decisión, en el orden del eje (para la monotonía mecánica y C6).
DECISION_ARMS: dict[str, float] = {
    "S_1.0": 1.0,
    "S_1.5": 1.5,
    "S_2.0": 2.0,
    "S_2.5": 2.5,
    "S_3.0": 3.0,
    "S_3.5": 3.5,
    "S_off": NO_STOP,
}
CANDIDATE_ARMS = tuple(n for n in DECISION_ARMS if n != BASELINE_ARM)
# Lados del baseline (C6, enmienda §0): el baseline no cuenta como vecino.
STRICT_SIDE = ("S_1.0", "S_1.5")
LOOSE_SIDE = ("S_2.5", "S_3.0", "S_3.5", "S_off")

DIAG_ARM = "D1_stop_only_3.0"
DIAG_STOP_MULT = 3.0
DIAG_TRAIL_MULT = 2.0
ORACLE_ARM = "ORACULO_STOP"
ANTI_ORACLE_ARM = "ANTI_ORACULO_STOP"

# Control post-hoc (``--diagnostics``): supresión aleatoria de stops calibrada a la
# tasa que el oráculo realizó en la corrida del 2026-08-13 (6.2% de share contra el
# 13.4% del baseline ⇒ conserva ~46% de las ocasiones). No es un brazo del
# pre-registro y **no decide nada**.
RANDOM_KEEP_ARM = "AZAR_MISMA_TASA"
RANDOM_KEEP_PROB = 0.463
RANDOM_KEEP_SEED = 20260813

# §6 — kill-criteria congelados.
KILL_MIN_DCAGR = 0.0050      # C1: ΔCAGR ≥ +0.50pp
KILL_DD_TOL = 0.0200         # C2: maxDD(cand) ≤ maxDD(base) + 2.00pp
KILL_SHARPE_TOL = 0.05       # C4: Sharpe(cand) ≥ Sharpe(base) − 0.05
KILL_REGIME_TOL = 0.05       # C5: Δ ret medio por trade ≥ −0.05 pts en cada régimen

# §5 — sanity del instrumento.
SANITY_MIN_STOP_SHARE = 0.05   # el stop tiene población en el baseline
SANITY_MIN_TRADE_DIFF = 0.10   # los brazos muerden
SANITY_ORACLE_EDGE = 0.0500    # ORACULO ≥ base + 5.00pp de CAGR

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345


# ── Brazos oráculo (§3.2) ────────────────────────────────────────────────────


def _oracle_stop_filter(bars: list[Bar], i: int) -> bool:
    """El stop duro dispara **sólo si la caída era real**: ``close[i+20] < close[i]``.

    Mira el futuro a propósito — es el contrafactual exacto de la evidencia viva
    (los nombres que el stop corta rebotan +6,81% a 20 ruedas). Cuando no hay
    barra ``i+20`` (final de la serie) **se permite el stop**, o sea que el brazo
    cae al comportamiento del baseline en vez de inventar una ventaja.
    """
    j = i + ORACLE_HORIZON
    if j >= len(bars):
        return True
    return bars[j][4] < bars[i][4]


def _anti_oracle_stop_filter(bars: list[Bar], i: int) -> bool:
    """Al revés: el stop dispara sólo cuando corta un rebote (``close[i+20] ≥ close[i]``)."""
    j = i + ORACLE_HORIZON
    if j >= len(bars):
        return True
    return bars[j][4] >= bars[i][4]


def random_stop_filter(keep_prob: float, seed: int = RANDOM_KEEP_SEED):
    """Supresión **aleatoria** de stops con tasa ``keep_prob`` — control post-hoc.

    NO es un brazo del pre-registro y no decide nada: existe sólo para separar dos
    cosas que el oráculo mezcla. El oráculo suprime stops *y* elige cuáles; este
    control suprime la misma proporción **sin elegir**. Si el oráculo no le gana,
    entonces el harness responde al **número** de stops y no a su **calidad**, y el
    sanity §5.5 no podía pasar por construcción.

    Determinista: el sorteo se deriva de un digest de ``(seed, fecha, i)``, no del
    ``hash()`` de Python (que está salteado por proceso).
    """
    def _f(bars: list[Bar], i: int) -> bool:
        raw = f"{seed}|{bars[i][0]}|{i}".encode()
        u = int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")
        return (u / 2 ** 64) < keep_prob

    return _f


# ── Métricas (§4) ────────────────────────────────────────────────────────────


def _exit_mix(res: PortfolioResult) -> dict[str, float]:
    """Fracción de trades por familia de salida (un trade puede tener 2 tramos)."""
    if not res.trades:
        return {}
    fams = ("atr_stop", "atr_trail", "atr_tp", "signal", "time_stop", "cap_reached")
    out: dict[str, float] = {}
    for f in fams:
        out[f] = sum(1 for t in res.trades if f in (t.exit_reason or "")) / len(res.trades)
    return out


def _p5_trade(res: PortfolioResult) -> float:
    rets = sorted(t.ret for t in res.trades)
    if not rets:
        return 0.0
    return rets[int(0.05 * len(rets))]


def _accounting_ok(res: PortfolioResult) -> bool:
    if not res.equity_curve or res.final_equity <= 0:
        return True
    dev = abs(res.equity_curve[-1][1] - res.final_equity) / res.final_equity
    return dev <= 1e-6


def summarise(res: PortfolioResult) -> dict:
    mix = _exit_mix(res)
    return {
        "cagr": cagr(res.equity_curve),
        "sharpe": sharpe_annual(res.equity_curve),
        "max_dd": res.max_dd,
        "p5_trade": _p5_trade(res),
        "n_taken": res.n_taken,
        "n_offered": res.n_offered,
        "exposure": res.exposure_share,
        "stop_share": mix.get("atr_stop", 0.0),
        "exit_mix": mix,
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


# ── Sanity del instrumento (§5) ──────────────────────────────────────────────


def stop_share_monotone(summaries: dict) -> bool:
    """§5.2 — el %salidas por ``atr_stop`` decrece estrictamente al alejar el stop.

    Mecánica pura (un stop más lejos dispara menos): si falla, el harness está mal
    cableado y no hay veredicto. ``S_off`` se chequea aparte: tiene que ser 0.
    """
    ordered = [n for n in DECISION_ARMS if n != "S_off"]
    shares = [summaries[n]["stop_share"] for n in ordered]
    if not all(shares[i] > shares[i + 1] for i in range(len(shares) - 1)):
        return False
    return summaries["S_off"]["stop_share"] == 0.0


def evaluate_sanity(summaries: dict, results: dict, cand_name: str) -> dict:
    diff_share = trade_overlap(results[BASELINE_ARM], results[cand_name])
    s = {
        "accounting": all(summaries[n]["accounting_ok"] for n in results),
        "stop_monotone": stop_share_monotone(summaries),
        "stop_share_base": summaries[BASELINE_ARM]["stop_share"],
        "stop_has_population": summaries[BASELINE_ARM]["stop_share"] >= SANITY_MIN_STOP_SHARE,
        "trade_diff_share": diff_share,
        "arms_bite": diff_share >= SANITY_MIN_TRADE_DIFF,
        "oracle_edge": summaries[ORACLE_ARM]["cagr"] - summaries[BASELINE_ARM]["cagr"],
        "oracle_ok": (summaries[ORACLE_ARM]["cagr"]
                      >= summaries[BASELINE_ARM]["cagr"] + SANITY_ORACLE_EDGE),
        "anti_oracle_ok": (summaries[ANTI_ORACLE_ARM]["cagr"]
                           <= summaries[BASELINE_ARM]["cagr"]),
    }
    s["all_ok"] = bool(s["accounting"] and s["stop_monotone"] and s["stop_has_population"]
                       and s["arms_bite"] and s["oracle_ok"] and s["anti_oracle_ok"])
    return s


# ── Regla de decisión (§6) ───────────────────────────────────────────────────


def pick_candidate(summaries: dict) -> str:
    """Candidato = mejor Sharpe entre los 6 candidatos (congelado en §6)."""
    return max(
        CANDIDATE_ARMS,
        key=lambda n: (summaries[n]["sharpe"] if summaries[n]["sharpe"] is not None else -1e9),
    )


def c6_dose_response(summaries: dict, cand_name: str) -> bool:
    """C6 (enmienda §0) — otro brazo candidato del **mismo lado** acompaña.

    El baseline no cuenta como vecino: su ΔCAGR es 0 por construcción y volvería
    el criterio vacuo. Convierte "el mejor de 6" en "una región que funciona".
    """
    side = STRICT_SIDE if cand_name in STRICT_SIDE else LOOSE_SIDE
    base_cagr = summaries[BASELINE_ARM]["cagr"]
    return any(summaries[n]["cagr"] - base_cagr >= 0.0
               for n in side if n != cand_name)


def evaluate(summaries: dict, regimes: dict, boot, cand_name: str) -> dict:
    """Aplica el AND de los 6 criterios de §6."""
    base = summaries[BASELINE_ARM]
    cand = summaries[cand_name]
    b_sh = base["sharpe"] if base["sharpe"] is not None else -1e9
    c_sh = cand["sharpe"] if cand["sharpe"] is not None else -1e9

    reg_delta: dict[str, float] = {}
    reg_ok = True
    for r, v in regimes[cand_name].items():
        d = v["mean_ret_pts"] - regimes[BASELINE_ARM][r]["mean_ret_pts"]
        reg_delta[r] = d
        if d < -KILL_REGIME_TOL:
            reg_ok = False

    c1 = (cand["cagr"] - base["cagr"]) >= KILL_MIN_DCAGR
    c2 = cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL
    c3 = boot is not None and boot.ci_low > 0.0
    c4 = c_sh >= b_sh - KILL_SHARPE_TOL
    c5 = reg_ok
    c6 = c6_dose_response(summaries, cand_name)
    ship = bool(c1 and c2 and c3 and c4 and c5 and c6)
    return {
        "candidate": cand_name,
        "dcagr": cand["cagr"] - base["cagr"],
        "dd_delta": cand["max_dd"] - base["max_dd"],
        "sharpe_delta": c_sh - b_sh,
        "p5_delta": cand["p5_trade"] - base["p5_trade"],
        "regime_delta": reg_delta,
        "c1_cagr": c1, "c2_maxdd": c2, "c3_boot": c3, "c4_sharpe": c4,
        "c5_regime": c5, "c6_dose": c6, "ship": ship,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def build_arms(diagnostics: bool = False) -> dict[str, dict]:
    """{nombre: kwargs de simulate_portfolio propios del brazo}."""
    arms: dict[str, dict] = {
        n: {"atr_p": AtrParams(stop_mult=m)} for n, m in DECISION_ARMS.items()
    }
    arms[DIAG_ARM] = {
        "atr_p": AtrParams(stop_mult=DIAG_STOP_MULT, trail_mult=DIAG_TRAIL_MULT)
    }
    base_p = AtrParams(stop_mult=DECISION_ARMS[BASELINE_ARM])
    arms[ORACLE_ARM] = {"atr_p": base_p, "stop_filter": _oracle_stop_filter}
    arms[ANTI_ORACLE_ARM] = {"atr_p": base_p, "stop_filter": _anti_oracle_stop_filter}
    if diagnostics:
        arms[RANDOM_KEEP_ARM] = {
            "atr_p": base_p,
            "stop_filter": random_stop_filter(RANDOM_KEEP_PROB),
        }
    return arms


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay de recalibración del stop ATR (Tarea 26)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--diagnostics", action="store_true",
                   help="suma el control post-hoc de supresión aleatoria (no decide nada)")
    p.add_argument("--fill-mode", choices=(HARNESS_FILL_MODE, LEGACY_FILL_MODE),
                   default=HARNESS_FILL_MODE,
                   help=f"'{LEGACY_FILL_MODE}' reproduce la corrida publicada, cuyo "
                        f"hallazgo central era ese look-ahead (Tareas 26b/33)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}",
              file=sys.stderr)

    entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not entries:
        print("Sin entradas BUY — nada que evaluar.", file=sys.stderr)
        return 1
    announce(args.max_positions, args.universe, len(bars_by),
             window=artifact_window(bars_by),
             verdict_max_positions=LEGACY_MAX_POSITIONS, fill_mode=args.fill_mode)
    print(f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)}\n")

    common = dict(
        max_positions=args.max_positions, initial_capital=args.capital,
        cap_days=args.cap_days, so_params=ScaleOutParams(), costs=CostModel(),
        regime_of=regime_for_date, allow_reentry_while_open=False,
        fill_mode=args.fill_mode,
    )

    arms = build_arms(diagnostics=args.diagnostics)
    results = {
        name: simulate_portfolio(entries, bars_by, sigs_by, **kw, **common)
        for name, kw in arms.items()
    }
    summaries = {n: summarise(r) for n, r in results.items()}
    regimes = {n: regime_trade_breakdown(results[n]) for n in results}

    cand_name = pick_candidate(summaries)

    # C3 — bootstrap pareado candidato vs baseline (el gate anti-overfit).
    rets = aligned_returns(results, [BASELINE_ARM, cand_name])
    boot = paired_block_bootstrap(rets[BASELINE_ARM], rets[cand_name],
                                  block=BOOT_BLOCK, n_resamples=args.resamples,
                                  seed=BOOT_SEED)

    sanity = evaluate_sanity(summaries, results, cand_name)
    verdict = evaluate(summaries, regimes, boot, cand_name)
    if not sanity["all_ok"]:
        verdict["ship"] = False
        verdict["outcome"] = ("CORRIDA INVÁLIDA — falla un sanity del §5; no hay veredicto "
                              "(el instrumento no está validado).")

    # Descriptivos: DSR/PBO sobre los brazos de decisión (NO son gate — T13/T27).
    dec = list(DECISION_ARMS)
    rets_all = aligned_returns(results, dec)
    T = len(next(iter(rets_all.values()))) if rets_all else 0
    pbo = pbo_cscv({c: rets_all[c] for c in dec}, n_splits=10) if T >= 10 else None
    dsr = None
    if T >= 2:
        sk, ku = _skew_kurt(rets_all[cand_name])
        dsr = deflated_sharpe_ratio([_sharpe(rets_all[c]) for c in dec], n_obs=T,
                                    selected=_sharpe(rets_all[cand_name]),
                                    skew=sk, kurtosis=ku)

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by), "n_entries": len(entries),
        "max_positions": args.max_positions, "capital": args.capital,
        "cap_days": args.cap_days, "universe": args.universe,
        "fill_mode": args.fill_mode,
        "dsr": (dsr.deflated_sharpe if dsr else None), "pbo": (pbo.pbo if pbo else None),
        "dsr_obs": T, "verdict": verdict, "sanity": sanity,
        "boot": {"observed": boot.observed, "ci_low": boot.ci_low,
                 "ci_high": boot.ci_high, "p_value": boot.p_value,
                 "block": boot.block, "n_resamples": boot.n_resamples},
        "kill_criteria": {
            "min_dcagr": KILL_MIN_DCAGR, "dd_tol": KILL_DD_TOL,
            "sharpe_tol": KILL_SHARPE_TOL, "regime_tol": KILL_REGIME_TOL,
            "min_stop_share": SANITY_MIN_STOP_SHARE,
            "min_trade_diff": SANITY_MIN_TRADE_DIFF,
            "oracle_edge": SANITY_ORACLE_EDGE,
        },
    }

    if args.json:
        print(json.dumps({"context": ctx, "summaries": summaries, "regimes": regimes},
                         ensure_ascii=False, indent=2, default=str))
        return 0

    _report(summaries, regimes, ctx, verdict, sanity, boot, dsr, pbo, T)
    return 0


def _f(x, w=8, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x*(100 if suf == '%' else 1):>{w-len(suf)}.{p}f}{suf}"


def _report(summaries, regimes, ctx, verdict, sanity, boot, dsr, pbo, T):
    hdr = (f"{'brazo':<20}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'%stop':>8}"
           f"{'%trail':>8}{'%tp':>7}{'p5trd':>8}{'tomad':>7}")
    print(hdr)
    print("-" * len(hdr))
    order = [n for n in
             list(DECISION_ARMS) + [DIAG_ARM, ORACLE_ARM, ANTI_ORACLE_ARM, RANDOM_KEEP_ARM]
             if n in summaries]
    for n in order:
        s = summaries[n]
        mark = ("BASE" if n == BASELINE_ARM else
                "*cand" if n == verdict["candidate"] else
                "diag" if n in (DIAG_ARM, RANDOM_KEEP_ARM) else
                "sanity" if n in (ORACLE_ARM, ANTI_ORACLE_ARM) else "")
        print(f"{n:<20}{_f(s['cagr'],9,2,'%')}{_f(s['sharpe'],9,2)}{_f(s['max_dd'],9,1,'%')}"
              f"{_f(s['stop_share'],8,1,'%')}{_f(s['exit_mix'].get('atr_trail',0),8,1,'%')}"
              f"{_f(s['exit_mix'].get('atr_tp',0),7,0,'%')}{_f(s['p5_trade'],8,1,'%')}"
              f"{s['n_taken']:>7}  {mark}")

    print(f"\nCandidato (mejor Sharpe entre los 6): {verdict['candidate']}")
    print("Por régimen — ret medio por trade (pts), Δ vs baseline:")
    for r in regimes[verdict["candidate"]]:
        b = regimes[BASELINE_ARM][r]["mean_ret_pts"]
        c = regimes[verdict["candidate"]][r]["mean_ret_pts"]
        n = regimes[verdict["candidate"]][r]["n"]
        print(f"  {r:<18} base {b:>+6.2f} · cand {c:>+6.2f} · Δ {verdict['regime_delta'][r]:>+6.2f}"
              f"  (n={n})")

    print(f"\nΔCAGR {_f(verdict['dcagr'],0,2,'%')} · ΔmaxDD {_f(verdict['dd_delta'],0,2,'%')} · "
          f"ΔSharpe {verdict['sharpe_delta']:+.3f} · Δp5 {_f(verdict['p5_delta'],0,2,'%')}")
    print(f"Bootstrap pareado (bloques {boot.block}d, {boot.n_resamples} resamples): "
          f"ΔCAGR obs {_f(boot.observed,0,2,'%')} · IC95% "
          f"[{_f(boot.ci_low,0,2,'%')}, {_f(boot.ci_high,0,2,'%')}] · p={boot.p_value:.3f}")
    print(f"Descriptivos (NO son gate): DSR = "
          f"{dsr.deflated_sharpe:.3f}" if dsr else "Descriptivos: DSR = n/d",
          f"· PBO = {pbo.pbo:.3f}" if pbo else "· PBO = n/d", f"(T={T} obs)")

    print("\nSanity del instrumento (§5) — si falla alguno NO hay veredicto:")
    for k, label in [("accounting", "contabilidad"),
                     ("stop_monotone", "monotonía mecánica del %atr_stop"),
                     ("stop_has_population", f"el stop tiene población "
                                             f"({sanity['stop_share_base']*100:.1f}% ≥ 5%)"),
                     ("arms_bite", f"los brazos muerden "
                                   f"({sanity['trade_diff_share']*100:.1f}% ≥ 10%)"),
                     ("oracle_ok", f"oráculo despega (+{sanity['oracle_edge']*100:.2f}pp ≥ 5pp)"),
                     ("anti_oracle_ok", "anti-oráculo ≤ baseline")]:
        print(f"  [{'OK  ' if sanity[k] else 'FALLA'}] {label}")

    print("\nCriterios (§6):")
    for k, label in [("c1_cagr", "C1 ΔCAGR ≥ +0.50pp"),
                     ("c2_maxdd", "C2 maxDD ≤ base + 2.00pp"),
                     ("c3_boot", "C3 bootstrap pareado IC95% inf > 0"),
                     ("c4_sharpe", "C4 Sharpe ≥ base − 0.05"),
                     ("c5_regime", "C5 régimen robusto (Δ ≥ −0.05 en los 4)"),
                     ("c6_dose", "C6 coherencia dosis-respuesta")]:
        print(f"  [{'PASA ' if verdict[k] else 'FALLA'}] {label}")
    if verdict.get("outcome"):
        print(f"\n  {verdict['outcome']}")
    print(f"\n  VEREDICTO: "
          f"{'SHIP (' + verdict['candidate'] + ')' if verdict['ship'] else 'NO-SHIP'}")


if __name__ == "__main__":
    raise SystemExit(main())
