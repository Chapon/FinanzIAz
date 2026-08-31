"""
Tests offline del harness de STOP-PRICE-REDECIDE — Tarea 47.
Pre-registro: ``docs/stop_price_redecide_prereg_t47_2026-08-19.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  regime_criterion — **C5′, el único criterio que cambia**: que la tolerancia se
                     COMPUTA (crece cuando la muestra se achica), que el gate va sobre
                     el AGREGADO de stress, y que **una ventana individual fea NO
                     bloquea** — que era exactamente el defecto de la 26b
  evaluate         — el AND de los siete y cada caso partido del §6, incluido el más
                     probable (pasa todo menos C7 ⇒ NO-SHIP por frágil)
"""

from __future__ import annotations

import pytest

from analysis.walkforward_power import BULL_NORMAL, detectable_mean_effect
from scripts.run_stop_price_redecide_t47 import (
    BASELINE_ARM,
    CANDIDATE_ARM,
    TOL_MATERIAL_PTS,
    evaluate,
    per_trade_pts,
    regime_criterion,
)


class _T:
    def __init__(self, ret, regime):
        self._ret = ret
        self.regime = regime

    @property
    def ret(self):
        return self._ret


class _Res:
    def __init__(self, trades):
        self.trades = trades


def _arm(by_regime: dict[str, list[float]]):
    """Brazo sintético: {régimen: [retornos en pts]} → PortfolioResult-like."""
    return _Res([_T(v / 100.0, r) for r, vs in by_regime.items() for v in vs])


# ── C5′ ──────────────────────────────────────────────────────────────────────


def _stress(base_vals, cand_vals):
    """Reparte los mismos valores entre las tres ventanas de stress."""

    def split(vs):
        n = len(vs) // 3
        return {
            "stress_2018q4": vs[:n],
            "stress_covid_2020": vs[n : 2 * n],
            "stress_bear_2022": vs[2 * n :],
            BULL_NORMAL: [1.0] * 50,
        }

    return _arm(split(base_vals)), _arm(split(cand_vals))


def test_tolerance_is_computed_not_constant():
    """La tolerancia efectiva = max(material, detectable). Con muestra chica lo
    detectable manda, y eso es lo que impide escribir un umbral que sólo puede
    fallar por ruido."""
    ruidoso = [10.0, -10.0] * 9  # σ grande, n=18 ⇒ detectable >> material
    base, cand = _stress(ruidoso, ruidoso)
    out = regime_criterion(base, cand, n_resamples=200, seed=1)
    assert out["detectable_pts"] > TOL_MATERIAL_PTS
    assert out["tolerance_pts"] == pytest.approx(out["detectable_pts"])


def test_tolerance_floors_at_the_material_threshold():
    """Con muestra grande y σ chica lo detectable baja mucho; ahí manda el umbral
    material, para que el criterio no se vuelva absurdamente fino."""
    tranquilo = [1.0, 1.1, 0.9, 1.05] * 60  # n=240, σ ~0.08
    base, cand = _stress(tranquilo, tranquilo)
    out = regime_criterion(base, cand, n_resamples=200, seed=1)
    assert out["detectable_pts"] < TOL_MATERIAL_PTS
    assert out["tolerance_pts"] == pytest.approx(TOL_MATERIAL_PTS)


def test_a_single_ugly_window_does_not_block():
    """EL defecto de la 26b: fallaba por −0.15 pts en una ventana de n=79 donde lo
    detectable era ±1.72. Acá el gate mira el agregado, así que una ventana fea con
    el resto sano no puede producir un rechazo."""
    base = _arm(
        {
            "stress_2018q4": [0.0] * 30,
            "stress_covid_2020": [0.0] * 30,
            "stress_bear_2022": [0.0] * 30,
            BULL_NORMAL: [1.0] * 50,
        }
    )
    cand = _arm(
        {
            "stress_2018q4": [-0.5] * 30,  # la ventana fea
            "stress_covid_2020": [0.0] * 30,
            "stress_bear_2022": [0.0] * 30,
            BULL_NORMAL: [1.0] * 50,
        }
    )
    out = regime_criterion(base, cand, n_resamples=300, seed=1)
    assert out["windows"]["stress_2018q4"]["delta_pts"] == pytest.approx(-0.5)
    assert out["passes"] is True


def test_a_large_and_certain_loss_does_block():
    """Y al revés: si el candidato pierde mucho y con certeza en el agregado, el
    criterio SÍ rechaza — este rechazo significa algo."""
    base = _arm(
        {r: [0.0] * 40 for r in ("stress_2018q4", "stress_covid_2020", "stress_bear_2022")}
        | {BULL_NORMAL: [1.0] * 50}
    )
    cand = _arm(
        {r: [-5.0] * 40 for r in ("stress_2018q4", "stress_covid_2020", "stress_bear_2022")}
        | {BULL_NORMAL: [1.0] * 50}
    )
    out = regime_criterion(base, cand, n_resamples=300, seed=1)
    assert out["pooled_ci_high"] < -out["tolerance_pts"]
    assert out["passes"] is False


def test_pooled_window_aggregates_the_three_stress_windows():
    base = _arm(
        {
            "stress_2018q4": [1.0] * 10,
            "stress_covid_2020": [2.0] * 10,
            "stress_bear_2022": [3.0] * 10,
            BULL_NORMAL: [0.0] * 10,
        }
    )
    out = regime_criterion(base, base, n_resamples=100, seed=1)
    assert out["windows"]["stress_POOLED"]["n_base"] == 30
    assert out["windows"][BULL_NORMAL]["n_base"] == 10


def test_detectable_matches_the_helper():
    vals = [3.0, -1.0, 2.0, 0.5] * 15
    base, cand = _stress(vals, vals)
    out = regime_criterion(base, cand, n_resamples=100, seed=1)
    w = out["windows"]["stress_POOLED"]
    assert w["detectable"] == pytest.approx(detectable_mean_effect(w["sd_pts"], w["n_base"]))


def test_per_trade_pts_converts_to_points():
    res = _arm({BULL_NORMAL: [2.5], "stress_bear_2022": [-1.5]})
    out = per_trade_pts(res)
    assert out[BULL_NORMAL] == [pytest.approx(2.5)]
    assert out["stress_bear_2022"] == [pytest.approx(-1.5)]


# ── §6 — el AND de los siete ─────────────────────────────────────────────────


class _Boot:
    def __init__(self, ci_low):
        self.ci_low = ci_low


def _sum(cagr=0.10, sharpe=1.0, dd=0.20):
    return {"cagr": cagr, "sharpe": sharpe, "max_dd": dd, "accounting_ok": True}


def _grid(delta=0.03):
    """Rejilla completa: los 5 múltiplos con ``close`` por encima de ``touch``."""
    out = {}
    for m in (1.0, 1.5, 2.0, 2.5, 3.0):
        out[f"touch_{m:.1f}"] = _sum()
        out[f"close_{m:.1f}"] = _sum(cagr=0.10 + delta)
    return out


_C5_OK = {
    "passes": True,
    "tolerance_pts": 1.0,
    "material_pts": 1.0,
    "detectable_pts": 0.9,
    "pooled_delta_pts": 0.1,
    "pooled_ci_high": 1.0,
    "pooled_ci_low": -0.8,
    "windows": {},
}
_SENS_OK = {"c1": True, "c3": True}


def test_ships_when_all_seven_pass():
    v = evaluate(_grid(), _C5_OK, _Boot(0.002), _SENS_OK)
    assert v["ship"] is True and "SHIP" in v["outcome"]


def test_the_most_likely_outcome_is_no_ship_by_c7():
    """Declarado ex ante: si el efecto sólo existe con 10 slots, es FRÁGIL."""
    v = evaluate(_grid(), _C5_OK, _Boot(0.002), {"c1": True, "c3": False})
    assert v["c7_sensitivity"] is False and v["ship"] is False
    assert "FRÁGIL" in v["outcome"]


def test_missing_sensitivity_run_is_not_a_pass():
    assert evaluate(_grid(), _C5_OK, _Boot(0.002), None)["c7_sensitivity"] is False


def test_c5_rejection_says_it_means_something_now():
    c5_bad = dict(_C5_OK, passes=False)
    v = evaluate(_grid(), c5_bad, _Boot(0.002), _SENS_OK)
    assert v["c5_regime"] is False and v["ship"] is False
    assert "SÍ significa algo" in v["outcome"]


def test_the_other_five_criteria_are_untouched_from_26b():
    """C1/C2/C3/C4/C6 se reusan tal cual: mismos umbrales, misma aritmética."""
    grid = _grid()
    grid[CANDIDATE_ARM] = _sum(cagr=0.1049)  # ΔCAGR < +0.50pp
    assert evaluate(grid, _C5_OK, _Boot(0.002), _SENS_OK)["c1_cagr"] is False
    grid[CANDIDATE_ARM] = _sum(cagr=0.13, dd=0.2201)  # maxDD > base+2pp
    assert evaluate(grid, _C5_OK, _Boot(0.002), _SENS_OK)["c2_maxdd"] is False
    grid[CANDIDATE_ARM] = _sum(cagr=0.13, sharpe=0.94)  # Sharpe < base−0.05
    assert evaluate(grid, _C5_OK, _Boot(0.002), _SENS_OK)["c4_sharpe"] is False
    assert evaluate(_grid(), _C5_OK, _Boot(-0.001), _SENS_OK)["c3_boot"] is False
    assert evaluate(_grid(delta=-0.01), _C5_OK, _Boot(0.002), _SENS_OK)["c6_consistency"] is False


def test_broken_accounting_never_ships():
    grid = _grid()
    grid[BASELINE_ARM] = dict(_sum(), accounting_ok=False)
    assert evaluate(grid, _C5_OK, _Boot(0.002), _SENS_OK)["ship"] is False
