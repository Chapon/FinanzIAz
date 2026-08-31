"""
Tests offline del harness de la decisión del ranking — Tarea 21.
Pre-registro: ``docs/ranking_prereg_t21_2026-08-12.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  evaluate            — la regla §4, y sobre todo **el caso partido resuelto ex ante**
                        (más CAGR pero peor drawdown ⇒ NO-SHIP, opción (a)), que es
                        exactamente lo que la T9 dejó sin especificar
  build_rank_fns      — B1 rankea por score; B0 es None (alfabético); B2 deshace la
                        vol_penalty; el oráculo mira el futuro; los random son
                        deterministas por semilla y estables dentro de una corrida
  trade_overlap       — el sanity §5.4 ("el ranking muerde")
  sensibilidad        — con slots escasos, ordenar por score cambia quién entra
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from analysis.exit_replay import AtrParams
from analysis.portfolio_sim import simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams
from scripts.run_ranking_t21 import (
    ANTI_ORACLE_ARM,
    BASELINE_ARM,
    CANDIDATE_ARM,
    DIAGNOSTIC_ARM,
    ORACLE_ARM,
    VOL_PENALTY_COEF,
    build_rank_fns,
    evaluate,
    trade_overlap,
)

_D0 = date(2026, 1, 5)


def _d(i: int) -> str:
    return (_D0 + timedelta(days=i)).isoformat()


class _Boot:
    def __init__(self, ci_low: float):
        self.ci_low = ci_low


def _sum(cagr=0.10, sharpe=1.0, dd=0.20):
    return {"cagr": cagr, "sharpe": sharpe, "max_dd": dd, "accounting_ok": True}


# ── La regla §4 ──────────────────────────────────────────────────────────────


def test_ships_when_all_four_pass():
    s = {BASELINE_ARM: _sum(), CANDIDATE_ARM: _sum(cagr=0.11)}
    v = evaluate(s, _Boot(0.002))
    assert v["ship"] is True
    assert "opción (b)" in v["outcome"]


def test_split_case_is_resolved_ex_ante_as_option_a():
    """MÁS CAGR pero drawdown materialmente peor ⇒ NO-SHIP por regla, no por juicio.

    Es el caso exacto que dejó colgada a la T9 (rendía menos pero con 6,1 pts
    menos de maxDD, y la regla no decía qué hacer)."""
    s = {BASELINE_ARM: _sum(dd=0.20), CANDIDATE_ARM: _sum(cagr=0.15, dd=0.25)}
    v = evaluate(s, _Boot(0.002))
    assert v["c1_cagr"] is True
    assert v["c2_maxdd"] is False
    assert v["ship"] is False
    assert "caso partido" in v["outcome"]
    assert "OPCIÓN (a)" in v["outcome"]


def test_maxdd_tolerance_is_three_points():
    base = _sum(dd=0.20)
    assert evaluate({BASELINE_ARM: base, CANDIDATE_ARM: _sum(cagr=0.11, dd=0.229)}, _Boot(0.002))["c2_maxdd"]
    assert not evaluate({BASELINE_ARM: base, CANDIDATE_ARM: _sum(cagr=0.11, dd=0.231)}, _Boot(0.002))[
        "c2_maxdd"
    ]


def test_no_ship_when_cagr_does_not_improve():
    s = {BASELINE_ARM: _sum(), CANDIDATE_ARM: _sum(cagr=0.102, dd=0.15)}
    v = evaluate(s, _Boot(0.002))
    assert v["c1_cagr"] is False and v["ship"] is False
    assert "caso partido" not in v["outcome"]


def test_bootstrap_gate_blocks_a_good_looking_delta():
    s = {BASELINE_ARM: _sum(), CANDIDATE_ARM: _sum(cagr=0.13)}
    v = evaluate(s, _Boot(-0.001))
    assert v["c1_cagr"] is True and v["c3_bootstrap"] is False and v["ship"] is False


def test_sharpe_floor_blocks():
    s = {BASELINE_ARM: _sum(sharpe=1.0), CANDIDATE_ARM: _sum(cagr=0.12, sharpe=0.90)}
    assert evaluate(s, _Boot(0.002))["ship"] is False


# ── build_rank_fns ───────────────────────────────────────────────────────────


def _fixtures():
    # La brecha de score (0.05) es menor que el máximo de la penalidad (0.08 ·
    # risk_score ≤ 0.08): es la condición para que deshacerla pueda dar vuelta el
    # orden. Con brechas mayores la vol_penalty no reordena nada.
    score_by = {"AAA": {_d(1): 0.65}, "BBB": {_d(1): 0.70}}
    risk_by = {"AAA": {_d(1): 1.00}, "BBB": {_d(1): 0.00}}
    realized = {("AAA", _d(1)): 0.30, ("BBB", _d(1)): -0.10}
    return score_by, risk_by, realized


def test_b1_ranks_by_score_and_b0_is_uninformed():
    score_by, risk_by, realized = _fixtures()
    arms = build_rank_fns(score_by, risk_by, realized, n_random=0, seed=1)
    b1 = arms[BASELINE_ARM]
    assert b1("BBB", _d(1)) > b1("AAA", _d(1))
    assert arms[CANDIDATE_ARM] is None  # None ⇒ alfabético en portfolio_sim


def test_b2_undoes_the_vol_penalty_and_can_flip_the_order():
    """AAA tiene score más bajo pero riesgo alto: al devolverle la penalidad pasa
    adelante. Si ``risk_score`` fuese una constante diaria esto no podría pasar y
    el brazo B2 no tendría sentido."""
    score_by, risk_by, realized = _fixtures()
    arms = build_rank_fns(score_by, risk_by, realized, n_random=0, seed=1)
    b2 = arms[DIAGNOSTIC_ARM]
    assert b2("AAA", _d(1)) == pytest.approx(0.65 + VOL_PENALTY_COEF * 1.0)
    assert b2("BBB", _d(1)) == pytest.approx(0.70)
    assert b2("AAA", _d(1)) > b2("BBB", _d(1))


def test_b2_absent_without_the_precompute():
    score_by, _risk, realized = _fixtures()
    arms = build_rank_fns(score_by, {}, realized, n_random=0, seed=1)
    assert DIAGNOSTIC_ARM not in arms


def test_partial_risk_coverage_disables_b2(tmp_path, monkeypatch):
    """Con cobertura parcial el brazo B2 rankearía unos tickers por ``raw_prob`` y
    otros por ``score`` — un brazo que no es ni uno ni otro. Tiene que no existir."""
    import scripts.run_ranking_t21 as mod

    def fake_path(ticker, period, warmup):
        return tmp_path / f"{ticker}.json"

    def fake_load(path):
        import json

        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    monkeypatch.setattr(mod, "_risk_path", fake_path)
    monkeypatch.setattr(mod, "_load_risk", fake_load)

    import json

    (tmp_path / "AAA.json").write_text(json.dumps({"complete": True, "risk": {_d(1): 0.5}}), encoding="utf-8")

    partial, cov = mod.load_risk_scores(["AAA", "BBB", "CCC"], "10y", 250)
    assert partial == {} and cov == pytest.approx(1 / 3)

    for t in ("BBB", "CCC"):
        (tmp_path / f"{t}.json").write_text(
            json.dumps({"complete": True, "risk": {_d(1): 0.5}}), encoding="utf-8"
        )
    full, cov = mod.load_risk_scores(["AAA", "BBB", "CCC"], "10y", 250)
    assert set(full) == {"AAA", "BBB", "CCC"} and cov == 1.0


def test_incomplete_artifact_does_not_count_as_coverage(tmp_path, monkeypatch):
    """Un artefacto a medio escribir (``complete=False``) no cuenta: el precómputo
    guarda parcial cada N fechas y leerlo daría un B2 con agujeros."""
    import json

    import scripts.run_ranking_t21 as mod

    monkeypatch.setattr(mod, "_risk_path", lambda t, p, w: tmp_path / f"{t}.json")
    monkeypatch.setattr(
        mod, "_load_risk", lambda path: json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    )
    (tmp_path / "AAA.json").write_text(
        json.dumps({"complete": False, "risk": {_d(1): 0.5}}), encoding="utf-8"
    )
    out, cov = mod.load_risk_scores(["AAA"], "10y", 250)
    assert out == {} and cov == 0.0


def test_oracle_and_anti_oracle_look_at_the_future():
    score_by, risk_by, realized = _fixtures()
    arms = build_rank_fns(score_by, risk_by, realized, n_random=0, seed=1)
    o, a = arms[ORACLE_ARM], arms[ANTI_ORACLE_ARM]
    assert o("AAA", _d(1)) > o("BBB", _d(1))  # AAA rindió más
    assert a("AAA", _d(1)) < a("BBB", _d(1))


def test_random_arms_are_deterministic_and_stable_within_a_run():
    score_by, risk_by, realized = _fixtures()
    a1 = build_rank_fns(score_by, risk_by, realized, n_random=3, seed=7)
    a2 = build_rank_fns(score_by, risk_by, realized, n_random=3, seed=7)
    f1, f2 = a1["B0r_random_0"], a2["B0r_random_0"]
    assert f1("AAA", _d(1)) == f2("AAA", _d(1))  # reproducible por semilla
    assert f1("AAA", _d(1)) == f1("AAA", _d(1))  # estable dentro del brazo
    assert a1["B0r_random_1"]("AAA", _d(1)) != f1("AAA", _d(1))


# ── Sanity §5.4 y sensibilidad del harness ──────────────────────────────────


class _FakeRes:
    def __init__(self, trades):
        self.trades = trades


class _T:
    def __init__(self, ticker, entry_date):
        self.ticker, self.entry_date = ticker, entry_date


def test_trade_overlap_measures_difference():
    a = _FakeRes([_T("AAA", _d(1)), _T("BBB", _d(2))])
    assert trade_overlap(a, _FakeRes([_T("AAA", _d(1)), _T("BBB", _d(2))])) == 0.0
    assert trade_overlap(a, _FakeRes([_T("CCC", _d(1)), _T("DDD", _d(2))])) == 1.0
    assert trade_overlap(_FakeRes([]), _FakeRes([])) == 0.0


def _ramp(n, start, step):
    out = []
    for i in range(n):
        c = start + i * step
        out.append((_d(i), c, c + 1.0, c - 1.0, c))
    return out


def test_ranking_decides_who_enters_when_slots_are_scarce():
    """Con 1 solo slot y dos candidatos el mismo día, el orden decide quién entra —
    es la condición sin la cual la tarea 21 no tendría nada que medir."""
    bars_by = {"AAA": _ramp(30, 100.0, 0.1), "BBB": _ramp(30, 100.0, 0.1)}
    sigs_by = {"AAA": {}, "BBB": {}}
    entries = [("AAA", 1), ("BBB", 1)]
    common = dict(
        max_positions=1,
        initial_capital=10_000.0,
        cap_days=20,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        allow_reentry_while_open=False,
    )

    prefer_bbb = simulate_portfolio(
        entries,
        bars_by,
        sigs_by,
        atr_p=AtrParams(),
        rank_score=lambda t, d: 1.0 if t == "BBB" else 0.0,
        **common,
    )
    alphabetical = simulate_portfolio(entries, bars_by, sigs_by, atr_p=AtrParams(), rank_score=None, **common)
    assert [t.ticker for t in prefer_bbb.trades] == ["BBB"]
    assert [t.ticker for t in alphabetical.trades] == ["AAA"]
    assert trade_overlap(prefer_bbb, alphabetical) == 1.0
