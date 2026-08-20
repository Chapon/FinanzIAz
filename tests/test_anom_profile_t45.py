"""
Tests offline del harness de ANOM-PROFILE — Tarea 45.
Pre-registro: ``docs/anom_profile_prereg_t45_2026-08-20.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  regime_criterion  — **C5′**: que la tolerancia se COMPUTA (crece cuando la muestra
                      se achica), que el gate va sobre el AGREGADO de stress, que una
                      ventana individual fea **NO** bloquea (el defecto que mató a la
                      T11b), y que el Δ se mide **contra el control time-matched** y no
                      contra cero — o sea que una ventana donde el mercado entero
                      pierde no produce un rechazo por sí sola
  merge_entries /   — población B (C8): deduplicación, orden cronológico y que el brazo
  make_prio_rank      priorizado cambia **el orden del día**, no el conjunto
  evaluate          — el AND de los ocho y cada caso partido del §6
  evaluate_sanity   — sanity fallado ⇒ corrida INVÁLIDA
"""

from __future__ import annotations

import pytest

from analysis.walkforward_power import BULL_NORMAL, detectable_mean_effect
from scripts.run_anom_profile_t45 import (
    ANALYZE_ARM,
    COMBINED_ARM,
    COMBINED_PRIO_ARM,
    POOLED,
    TOL_MATERIAL_PTS,
    _delta_samples_pooled,
    evaluate,
    evaluate_sanity,
    make_prio_rank,
    merge_entries,
    per_trade_pts,
    regime_criterion,
    trade_diff_share,
)

_STRESS = ("stress_2018q4", "stress_covid_2020", "stress_bear_2022")


class _T:
    def __init__(self, ret, regime, ticker="AAA", entry_date="2020-01-02"):
        self._ret = ret
        self.regime = regime
        self.ticker = ticker
        self.entry_date = entry_date

    @property
    def ret(self):
        return self._ret


class _Res:
    def __init__(self, trades):
        self.trades = trades


def _arm(by_regime: dict[str, list[float]]):
    """Brazo sintético: {régimen: [retornos en pts]} → PortfolioResult-like."""
    return _Res([_T(v / 100.0, r) for r, vs in by_regime.items() for v in vs])


def _control(by_regime: dict[str, list[float]]) -> dict[str, list[float]]:
    """El control de C5′ es el pool de trades del Monte Carlo, ya en pts."""
    return {r: list(vs) for r, vs in by_regime.items()}


def _split(vs, bull=None):
    n = len(vs) // 3
    out = {_STRESS[0]: vs[:n], _STRESS[1]: vs[n:2 * n], _STRESS[2]: vs[2 * n:]}
    out[BULL_NORMAL] = list(bull if bull is not None else [1.0] * 50)
    return out


# ── C5′ ──────────────────────────────────────────────────────────────────────


def test_tolerance_is_computed_not_constant():
    """La tolerancia efectiva = max(material, detectable). Con muestra chica lo
    detectable manda, y eso es lo que impide escribir un umbral que sólo puede
    fallar por ruido — el defecto que la 46 midió en el §6.5 de la T11b."""
    ruidoso = [10.0, -10.0] * 9          # σ grande, n=18 ⇒ detectable >> material
    out = regime_criterion(_control(_split(ruidoso)), _arm(_split(ruidoso)),
                           n_resamples=200, seed=1)
    assert out["detectable_pts"] > TOL_MATERIAL_PTS
    assert out["tolerance_pts"] == pytest.approx(out["detectable_pts"])


def test_tolerance_floors_at_the_material_threshold():
    tranquilo = [1.0, 1.1, 0.9, 1.05] * 60      # n=240, σ ~0.08
    out = regime_criterion(_control(_split(tranquilo)), _arm(_split(tranquilo)),
                           n_resamples=200, seed=1)
    assert out["detectable_pts"] < TOL_MATERIAL_PTS
    assert out["tolerance_pts"] == pytest.approx(TOL_MATERIAL_PTS)


def test_tolerance_grows_when_the_sample_shrinks():
    """Lo que hace honesto al criterio: menos trades ⇒ más tolerancia."""
    vals = [4.0, -4.0, 2.0, -2.0]
    grande = regime_criterion(_control(_split(vals * 30)), _arm(_split(vals * 30)),
                              n_resamples=100, seed=1)
    chico = regime_criterion(_control(_split(vals * 3)), _arm(_split(vals * 3)),
                             n_resamples=100, seed=1)
    assert chico["tolerance_pts"] > grande["tolerance_pts"]


def test_a_single_ugly_window_does_not_block():
    """EL defecto que mató a la T11b: rechazaba por `bear_2022` −2.01 pts con n=20,
    donde lo detectable era ±2.35. Acá el gate mira el agregado."""
    ctrl = _control({r: [0.0] * 30 for r in _STRESS} | {BULL_NORMAL: [1.0] * 50})
    cand = _arm({_STRESS[0]: [-0.5] * 30,          # la ventana fea
                 _STRESS[1]: [0.0] * 30, _STRESS[2]: [0.0] * 30,
                 BULL_NORMAL: [1.0] * 50})
    out = regime_criterion(ctrl, cand, n_resamples=300, seed=1)
    assert out["windows"][_STRESS[0]]["delta_pts"] == pytest.approx(-0.5)
    assert out["passes"] is True


def test_a_large_and_certain_loss_does_block():
    ctrl = _control({r: [0.0] * 40 for r in _STRESS} | {BULL_NORMAL: [1.0] * 50})
    cand = _arm({r: [-5.0] * 40 for r in _STRESS} | {BULL_NORMAL: [1.0] * 50})
    out = regime_criterion(ctrl, cand, n_resamples=300, seed=1)
    assert out["pooled_ci_high"] < -out["tolerance_pts"]
    assert out["passes"] is False


def test_delta_is_measured_against_the_control_not_against_zero():
    """La corrección de la 46 §3: un nivel negativo en una ventana de stress habla
    del MERCADO. Si el control pierde lo mismo que el candidato, el Δ es 0 y el
    criterio pasa, aunque el nivel sea feo en las dos puntas."""
    ctrl = _control({r: [-6.0] * 40 for r in _STRESS} | {BULL_NORMAL: [1.0] * 50})
    cand = _arm({r: [-6.0] * 40 for r in _STRESS} | {BULL_NORMAL: [1.0] * 50})
    out = regime_criterion(ctrl, cand, n_resamples=200, seed=1)
    assert out["windows"][POOLED]["mean_cand"] == pytest.approx(-6.0)
    assert out["pooled_delta_pts"] == pytest.approx(0.0)
    assert out["passes"] is True


def test_pooled_window_aggregates_the_three_stress_windows():
    ctrl = _control({_STRESS[0]: [1.0] * 10, _STRESS[1]: [2.0] * 10,
                     _STRESS[2]: [3.0] * 10, BULL_NORMAL: [0.0] * 10})
    cand = _arm({_STRESS[0]: [1.0] * 10, _STRESS[1]: [2.0] * 10,
                 _STRESS[2]: [3.0] * 10, BULL_NORMAL: [0.0] * 10})
    out = regime_criterion(ctrl, cand, n_resamples=100, seed=1)
    assert out["windows"][POOLED]["n_cand"] == 30
    assert out["windows"][BULL_NORMAL]["n_cand"] == 10


def test_detectable_uses_the_candidate_sample():
    """§4.1: lo que limita la resolución es el n del CANDIDATO, no el del control
    (que son los trades de las K carteras del Monte Carlo, ~500× más)."""
    vals = [3.0, -1.0, 2.0, 0.5] * 15
    ctrl = _control(_split(vals * 20))      # control enorme
    out = regime_criterion(ctrl, _arm(_split(vals)), n_resamples=100, seed=1)
    w = out["windows"][POOLED]
    assert w["n_control"] > w["n_cand"]
    assert w["detectable"] == pytest.approx(
        detectable_mean_effect(w["sd_pts"], w["n_cand"]))


def test_per_trade_pts_converts_to_points():
    res = _arm({BULL_NORMAL: [2.5], _STRESS[2]: [-1.5]})
    out = per_trade_pts(res)
    assert out[BULL_NORMAL] == [pytest.approx(2.5)]
    assert out[_STRESS[2]] == [pytest.approx(-1.5)]


def test_delta_samples_pooled_handles_a_huge_control():
    """Por qué existe la versión por tandas: el control tiene ~10⁵ trades y la
    matriz (n_resamples × n) de la 46 no entra en memoria."""
    xs = [0.0] * 60_000
    ys = [2.0] * 40
    s = _delta_samples_pooled(xs, ys, n_resamples=64, seed=1, chunk=16)
    assert len(s) == 64
    assert all(abs(v - 2.0) < 0.1 for v in s)


def test_delta_samples_pooled_is_empty_without_data():
    assert _delta_samples_pooled([], [1.0], n_resamples=10, seed=1) == []
    assert _delta_samples_pooled([1.0], [], n_resamples=10, seed=1) == []


# ── Población B (C8) ─────────────────────────────────────────────────────────


_BARS = {
    "AAA": [(f"2020-01-{d:02d}", 1.0, 1.0, 1.0, 1.0) for d in range(1, 6)],
    "BBB": [(f"2020-01-{d:02d}", 1.0, 1.0, 1.0, 1.0) for d in range(1, 6)],
}


def test_merge_deduplicates_and_sorts_chronologically():
    """Una entrada que las dos fuentes proponen el mismo día para el mismo ticker
    es UNA sola: dejarla duplicada ensuciaría el conteo de ofrecidas."""
    analyze = [("AAA", 3), ("BBB", 1)]
    anom = [("AAA", 3), ("AAA", 0)]
    out = merge_entries(analyze, anom, _BARS)
    assert out == [("AAA", 0), ("BBB", 1), ("AAA", 3)]


def test_merge_never_loses_an_entry_of_either_source():
    analyze = [("AAA", 1), ("BBB", 2)]
    anom = [("BBB", 4)]
    out = merge_entries(analyze, anom, _BARS)
    assert set(out) == set(analyze) | set(anom)


def test_prio_rank_only_reorders_the_day():
    """El brazo priorizado no cambia el conjunto de candidatos, sólo quién se queda
    con el slot — que es lo que lo hace interpretable como descriptivo."""
    rank = make_prio_rank({("BBB", "2020-01-02")})
    assert rank("BBB", "2020-01-02") == 1.0
    assert rank("AAA", "2020-01-02") == 0.0
    assert rank("BBB", "2020-01-03") == 0.0


def test_trade_diff_share_counts_by_ticker_and_date():
    base = _Res([_T(0.0, BULL_NORMAL, "AAA", "2020-01-02"),
                 _T(0.0, BULL_NORMAL, "BBB", "2020-01-03")])
    same = _Res([_T(0.0, BULL_NORMAL, "AAA", "2020-01-02"),
                 _T(0.0, BULL_NORMAL, "BBB", "2020-01-03")])
    other = _Res([_T(0.0, BULL_NORMAL, "AAA", "2020-01-02"),
                  _T(0.0, BULL_NORMAL, "CCC", "2020-01-03")])
    assert trade_diff_share(base, same) == pytest.approx(0.0)
    assert trade_diff_share(base, other) == pytest.approx(2 / 3)


def test_trade_diff_share_is_not_a_sanity_but_a_result():
    """Documenta la lección de la 38 §1: que la fuente nueva gane o no gane slots es
    un RESULTADO (media respuesta de C8), no una propiedad del instrumento. Si
    fuera un sanity, un 0% invalidaría la corrida en vez de contestar la pregunta."""
    empty = _Res([])
    assert trade_diff_share(empty, empty) == 0.0


# ── §6 — el AND de los ocho ──────────────────────────────────────────────────


class _Dsr:
    def __init__(self, v):
        self.deflated_sharpe = v


class _Pbo:
    def __init__(self, v):
        self.pbo = v


def _sum(cagr=0.10, sharpe=1.10, dd=0.13):
    return {"cagr": cagr, "sharpe": sharpe, "max_dd": dd, "accounting_ok": True,
            "n_taken": 100, "n_offered": 120}


_RB = {"cagr_p95": 0.06, "cagr_median": 0.03, "sharpe_p95": 1.00,
       "sharpe_median": 0.60, "maxdd_median": 0.12, "k": 500}
_C5_OK = {"passes": True, "tolerance_pts": 1.85, "material_pts": 1.00,
          "detectable_pts": 1.85, "pooled_delta_pts": 0.1, "pooled_ci_high": 1.2,
          "pooled_ci_low": -1.0, "windows": {}}
_LOTO_OK = {"dropped": "AAA", "cagr_without": 0.08, "survives": True}
_SENS_OK = {"c1": True, "c2": True}
_C8_OK = {"c8_cagr": True, "c8_boot": True}


def _ev(**over):
    kw = dict(cand_sum=_sum(), rb=_RB, dsr=_Dsr(0.9), pbo=_Pbo(0.3), c5=_C5_OK,
              loto=_LOTO_OK, sens=_SENS_OK, c8=_C8_OK)
    kw.update(over)
    return evaluate(kw["cand_sum"], kw["rb"], kw["dsr"], kw["pbo"], kw["c5"],
                    kw["loto"], kw["sens"], kw["c8"])


def test_ships_when_all_eight_pass():
    v = _ev()
    assert v["ship"] is True and "SHIP" in v["outcome"]


def test_no_ship_by_c8_says_which_of_the_two_things_happened():
    """El caso partido más informativo: hay que poder distinguir 'no aporta' de
    'nunca consigue slot' (§6)."""
    v = _ev(c8={"c8_cagr": False, "c8_boot": True})
    assert v["c8_additive"] is False and v["ship"] is False
    assert "NUNCA CONSIGUE SLOT" in v["outcome"]


def test_no_ship_by_c7_is_declared_as_fragile():
    v = _ev(sens={"c1": True, "c2": False})
    assert v["c7_sensitivity"] is False and v["ship"] is False
    assert "FRÁGIL" in v["outcome"]


def test_missing_runs_are_never_a_pass():
    assert _ev(sens=None)["c7_sensitivity"] is False
    assert _ev(c8=None)["c8_additive"] is False


def test_c5_rejection_says_it_means_something_now():
    v = _ev(c5=dict(_C5_OK, passes=False))
    assert v["c5_regime"] is False and v["ship"] is False
    assert "SÍ significa algo" in v["outcome"]


def test_the_five_criteria_reused_from_t11b_keep_their_thresholds():
    """C1/C2/C3/C4/C6 se reusan tal cual: mismos umbrales, misma aritmética."""
    assert _ev(cand_sum=_sum(cagr=0.059))["c1_vs_random"] is False   # < p95
    assert _ev(cand_sum=_sum(sharpe=0.99))["c1_vs_random"] is False  # Sharpe < p95
    assert _ev(cand_sum=_sum(cagr=0.0499))["c2_dcagr"] is False      # ΔCAGR < +2pp
    assert _ev(cand_sum=_sum(dd=0.181))["c3_maxdd"] is False         # > 1.5× mediana
    assert _ev(dsr=_Dsr(0.4))["c4_dsr_pbo"] is False
    assert _ev(pbo=_Pbo(0.6))["c4_dsr_pbo"] is False
    assert _ev(loto={"dropped": "AAA", "cagr_without": 0.01,
                     "survives": False})["c6_loto"] is False
    assert _ev(loto=None)["c6_loto"] is False


# ── §5 — sanity ──────────────────────────────────────────────────────────────


def _res_ok():
    class _R:
        equity_curve = [("2020-01-02", 100.0), ("2020-01-03", 110.0)]
        final_equity = 110.0
        trades: list = []
        n_taken = 0
        n_offered = 0
        exposure_share = 0.0
        total_return_pts = 0.1
        max_dd = 0.0
    return _R()


_REPRO_OK = {"live_ok": True, "legacy_ran": True, "legacy_ok": True}


def test_run_is_valid_when_every_sanity_passes():
    sa = evaluate_sanity({"a": _res_ok()}, _sum(cagr=0.0923),
                         _sum(cagr=1.05), _REPRO_OK)
    assert sa["valid"] is True


def test_a_failed_reproduction_invalidates_the_run():
    sa = evaluate_sanity({"a": _res_ok()}, _sum(cagr=0.0923), _sum(cagr=1.05),
                         dict(_REPRO_OK, live_ok=False))
    assert sa["valid"] is False and sa["checks"]["repro_live"] is False


def test_an_oracle_that_does_not_take_off_invalidates_the_run():
    """Si el harness no ve calidad de entrada, ningún veredicto vale."""
    sa = evaluate_sanity({"a": _res_ok()}, _sum(cagr=0.0923),
                         _sum(cagr=0.15), _REPRO_OK)      # +5.8 pp < +20
    assert sa["valid"] is False and sa["checks"]["oracle_takes_off"] is False


def test_skipping_the_legacy_reproduction_does_not_silently_pass_it():
    sa = evaluate_sanity({"a": _res_ok()}, _sum(cagr=0.0923), _sum(cagr=1.05),
                         {"live_ok": True, "legacy_ran": False})
    assert sa["checks"]["repro_legacy"] is None and sa["legacy_skipped"] is True


def test_population_b_arm_names_are_distinct():
    assert len({ANALYZE_ARM, COMBINED_ARM, COMBINED_PRIO_ARM}) == 3
