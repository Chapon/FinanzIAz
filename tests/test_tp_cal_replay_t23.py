"""
Tests offline del harness ``scripts.run_tp_cal_replay_t23`` (Tarea 23, TP-CAL).
Pre-registro: ``docs/tp_cal_prereg_t23_2026-08-11.md``.

Cubren las piezas PURAS (sin Parquet, sin red, sin DB):
1. ``buy_entries`` — extrae los eventos ``analyze BUY`` en el dominio ``[warmup, n-2]``.
2. ``evaluate`` — el AND de los 6 kill-criteria (§5): ship cuando todos pasan; no-ship
   si falla DD, régimen, o DSR/PBO; el candidato = mejor Sharpe entre los candidatos.
3. Sensibilidad: en una serie monótonamente alcista, aflojar el TP deja correr al
   ganador (retorno no-decreciente 2.0 → 4.0 → 6.0 → sin-TP) — confirma que el harness
   detecta el efecto del ``tp_mult`` (el sanity del pre-registro).
"""

from __future__ import annotations

from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import STRESS_REGIMES
from scripts.run_tp_cal_replay_t23 import (
    BASELINE_ARM,
    DECISION_ARMS,
    SANITY_ARM,
    SANITY_TP,
    buy_entries,
    evaluate,
    run_arm,
    summarise,
)

_REG_NAMES = ["bull_normal"] + [r.name for r in STRESS_REGIMES]


# ── buy_entries ──────────────────────────────────────────────────────────────


def _bars(dates, prices):
    return [(d, p, p, p, p) for d, p in zip(dates, prices)]


def test_buy_entries_extracts_buy_in_domain():
    dates = [f"2022-01-{i:02d}" for i in range(1, 11)]  # 10 barras
    bars_by = {"ABC": _bars(dates, [100.0] * 10)}
    # BUY en idx 3 y 6; SELL/HOLD en otros. warmup=2 → dominio [2, 8].
    sigs_by = {"ABC": {dates[3]: "BUY", dates[5]: "SELL", dates[6]: "BUY", dates[9]: "BUY"}}
    out = buy_entries(bars_by, sigs_by, warmup=2)
    assert out == [("ABC", 3), ("ABC", 6)]  # idx 9 fuera del dominio (n-2=8); SELL no cuenta


def test_buy_entries_respects_warmup_lower_bound():
    dates = [f"2022-02-{i:02d}" for i in range(1, 11)]
    bars_by = {"ABC": _bars(dates, [100.0] * 10)}
    sigs_by = {"ABC": {dates[1]: "BUY", dates[5]: "BUY"}}
    out = buy_entries(bars_by, sigs_by, warmup=3)
    assert out == [("ABC", 5)]  # idx 1 < warmup=3 → descartada


# ── evaluate (kill-criteria §5) ──────────────────────────────────────────────


def _summ(cagr, sharpe, max_dd, p5):
    return {"cagr": cagr, "sharpe": sharpe, "max_dd": max_dd, "p5_trade": p5,
            "accounting_ok": True, "n_taken": 100, "n_offered": 100,
            "exposure": 0.5, "tp_share": 0.1, "total_return_pts": 0.0}


def _reg(vals):
    return {name: {"n": 20, "mean_ret_pts": v} for name, v in zip(_REG_NAMES, vals)}


def _base_case(**over):
    """Un caso donde TODO pasa; los kwargs pisan brazos puntuales."""
    summaries = {
        "TP_4.0": _summ(0.10, 0.80, 0.20, -0.07),
        "TP_6.0": _summ(0.115, 0.83, 0.20, -0.07),   # +1.5pp CAGR, DD igual, p5 igual
        "TP_off": _summ(0.114, 0.82, 0.20, -0.07),
    }
    regimes = {
        "TP_4.0": _reg([0.20, -0.30, 0.90, -0.10]),
        "TP_6.0": _reg([0.24, -0.28, 0.95, -0.10]),  # Δ ≥ 0 en todos
        "TP_off": _reg([0.24, -0.28, 0.95, -0.10]),
    }
    summaries.update(over.get("summaries", {}))
    regimes.update(over.get("regimes", {}))
    return summaries, regimes


def test_evaluate_ships_when_all_pass():
    summaries, regimes = _base_case()
    v = evaluate(summaries, regimes, dsr=0.9, pbo=0.3)
    assert v["candidate"] == "TP_6.0"      # mejor Sharpe entre candidatos
    assert v["ship"] is True
    assert all(v[k] for k in ("c1_cagr", "c2_sharpe", "c3_dd", "c4_p5", "c5_regime", "c6_dsr_pbo"))


def test_evaluate_noship_when_dd_worse():
    summaries, regimes = _base_case(
        summaries={"TP_6.0": _summ(0.115, 0.83, 0.26, -0.07),   # maxDD 26% > 20%+0.5
                   "TP_off": _summ(0.114, 0.82, 0.27, -0.07)})
    v = evaluate(summaries, regimes, dsr=0.9, pbo=0.3)
    assert v["c3_dd"] is False and v["ship"] is False


def test_evaluate_noship_when_regime_hurts():
    summaries, regimes = _base_case(
        regimes={"TP_6.0": _reg([0.24, -0.28, 0.95, -0.40])})  # bear Δ = -0.30 < -0.05
    v = evaluate(summaries, regimes, dsr=0.9, pbo=0.3)
    assert v["c5_regime"] is False and v["ship"] is False


def test_evaluate_noship_when_dcagr_too_small():
    summaries, regimes = _base_case(
        summaries={"TP_6.0": _summ(0.101, 0.83, 0.20, -0.07),   # +0.1pp < +0.30pp
                   "TP_off": _summ(0.1005, 0.82, 0.20, -0.07)})
    v = evaluate(summaries, regimes, dsr=0.9, pbo=0.3)
    assert v["c1_cagr"] is False and v["ship"] is False


def test_evaluate_noship_when_dsr_pbo_fails():
    summaries, regimes = _base_case()
    assert evaluate(summaries, regimes, dsr=0.4, pbo=0.3)["ship"] is False   # DSR bajo
    assert evaluate(summaries, regimes, dsr=0.9, pbo=0.6)["ship"] is False   # PBO alto


def test_evaluate_candidate_is_best_sharpe():
    summaries, regimes = _base_case(
        summaries={"TP_6.0": _summ(0.115, 0.70, 0.20, -0.07),
                   "TP_off": _summ(0.130, 0.90, 0.20, -0.07)})  # TP_off mejor Sharpe
    v = evaluate(summaries, regimes, dsr=0.9, pbo=0.3)
    assert v["candidate"] == "TP_off"


# ── Sensibilidad: TP más flojo deja correr al ganador ────────────────────────


def test_looser_tp_lets_winner_run_on_monotonic_riser():
    # Serie 2%/barra alcista: aflojar el TP retiene más y captura más suba.
    n = 50
    dates = [f"2021-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]
    bars_by, sigs_by = {}, {}
    bars = []
    for i in range(n):
        base = 100.0 * (1.02 ** i)
        bars.append((dates[i], base, base * 1.012, base * 0.996, base * 1.006))
    bars_by["RUN"] = bars
    sigs_by["RUN"] = {dates[20]: "BUY"}   # una entrada BUY en idx 20
    entries = buy_entries(bars_by, sigs_by, warmup=15)
    assert entries == [("RUN", 20)]
    common = dict(max_positions=5, initial_capital=50_000.0, cap_days=20,
                  so_params=ScaleOutParams(), costs=CostModel(),
                  allow_reentry_while_open=False)
    rets = {}
    for name, tp in {**DECISION_ARMS, SANITY_ARM: SANITY_TP}.items():
        res = run_arm(entries, bars_by, sigs_by, tp, common)
        rets[name] = summarise(res)["total_return_pts"]
    # monótono: 2.0 <= 4.0 <= 6.0 <= sin-TP (aflojar deja correr)
    assert rets[SANITY_ARM] <= rets["TP_4.0"] + 1e-9
    assert rets["TP_4.0"] <= rets["TP_6.0"] + 1e-9
    assert rets["TP_6.0"] <= rets["TP_off"] + 1e-9
    # y el sanity rinde ESTRICTAMENTE menos que el baseline (lo que exige el harness)
    assert rets[SANITY_ARM] < rets["TP_4.0"]
