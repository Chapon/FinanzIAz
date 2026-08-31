"""
Tests de los helpers de potencia de régimen — Tarea 46.
Ref: ``docs/regime_power_t46_2026-08-19.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  detectable_mean_effect   — el número que faltaba para declarar una tolerancia
                             honesta: baja con √n, sube con σ, y es consistente con
                             ``n_for_mean_effect`` (son la misma fórmula dada vuelta)
  sign_stability           — P(signo) ≈ 50% cuando la media es ruido y ≈ 100% cuando
                             el efecto es grande: la lectura directa de "¿este criterio
                             está tirando una moneda?"
  block_sign_stability     — versión de cartera: **compone** en vez de promediar
  block_delta_sign_stability — pareada: los mismos bloques a los dos brazos, así el
                             ruido común se cancela (que es lo que la hace útil)
  per_trade_by_regime      — el agrupador que alimenta todo lo anterior
"""

from __future__ import annotations

import math

import pytest

from analysis.walkforward_power import (
    BULL_NORMAL,
    achieved_power_mean,
    block_delta_sign_stability,
    block_sign_stability,
    detectable_mean_effect,
    n_for_mean_effect,
    sign_stability,
)
from scripts.run_regime_power_t46 import per_trade_by_regime

# ── detectable_mean_effect ───────────────────────────────────────────────────


def test_detectable_effect_shrinks_with_n_and_grows_with_sigma():
    assert detectable_mean_effect(5.0, 400) < detectable_mean_effect(5.0, 20)
    assert detectable_mean_effect(10.0, 100) > detectable_mean_effect(5.0, 100)


def test_detectable_effect_scales_as_one_over_sqrt_n():
    """Cuadruplicar la muestra parte el efecto detectable al medio."""
    assert detectable_mean_effect(5.0, 400) == pytest.approx(detectable_mean_effect(5.0, 100) / 2.0, rel=1e-9)


def test_detectable_effect_is_the_inverse_of_n_for_mean_effect():
    """Son la misma fórmula dada vuelta: si el efecto detectable con n=79 y σ=5.45 es
    E, entonces detectar E/σ pide n=79."""
    sd, n = 5.45, 79
    e = detectable_mean_effect(sd, n)
    assert n_for_mean_effect(e / sd) == pytest.approx(n, abs=1)


def test_detectable_effect_matches_the_published_numbers():
    """Los números del §2 del doc, para que un cambio de fórmula no pase inadvertido."""
    assert detectable_mean_effect(5.45, 79) == pytest.approx(1.72, abs=0.01)
    assert detectable_mean_effect(6.66, 63) == pytest.approx(2.35, abs=0.01)
    assert detectable_mean_effect(6.82, 407) == pytest.approx(0.95, abs=0.01)


def test_degenerate_inputs_are_infinite_not_zero():
    """Sin muestra o sin dispersión no se detecta *nada* — devolver 0 diría lo
    contrario y haría pasar cualquier criterio."""
    assert math.isinf(detectable_mean_effect(5.0, 1))
    assert math.isinf(detectable_mean_effect(0.0, 100))


def test_power_for_the_published_tolerance_is_alpha():
    """EL número de la tarea: con σ≈5.45 y n=79, la potencia para detectar 0.05 pts
    es ~5% = α. El criterio rechaza al nivel del azar."""
    assert achieved_power_mean(0.05 / 5.45, 79) == pytest.approx(0.05, abs=0.01)


# ── sign_stability ───────────────────────────────────────────────────────────


def test_sign_stability_is_a_coin_flip_when_the_mean_is_noise():
    xs = [5.0, -5.0] * 20  # media exactamente 0 salvo redondeo
    out = sign_stability(xs, n_resamples=500)
    assert 0.35 <= out["p_same_sign"] <= 0.65


def test_sign_stability_is_certain_when_the_effect_is_large():
    xs = [10.0, 11.0, 9.0, 10.5] * 10  # media ~10, σ chica
    out = sign_stability(xs, n_resamples=500)
    assert out["p_same_sign"] == 1.0
    assert out["ci_low"] > 0


def test_sign_stability_reports_the_observed_mean_and_a_two_sided_ci():
    xs = [1.0, 2.0, 3.0, 4.0]
    out = sign_stability(xs, n_resamples=500)
    assert out["mean"] == pytest.approx(2.5)
    assert out["ci_low"] < 2.5 < out["ci_high"]
    assert out["n"] == 4


def test_sign_stability_needs_at_least_two_values():
    assert sign_stability([])["p_same_sign"] is None
    assert sign_stability([1.0])["p_same_sign"] is None


def test_sign_stability_is_deterministic_by_seed():
    xs = [1.0, -0.5, 2.0, -1.0, 0.5]
    a = sign_stability(xs, n_resamples=200, seed=7)
    b = sign_stability(xs, n_resamples=200, seed=7)
    assert a == b
    assert sign_stability(xs, n_resamples=200, seed=8) != a


# ── versiones de cartera ─────────────────────────────────────────────────────


def test_block_sign_stability_compounds_instead_of_averaging():
    """El retorno de una ventana es un producto, no un promedio: con +10% y −10% el
    resultado observado tiene que ser negativo (0.99−1), no cero."""
    out = block_sign_stability([0.10, -0.10], block=1, n_resamples=200)
    assert out["ret"] == pytest.approx(0.99 - 1.0)


def test_block_sign_stability_is_certain_for_a_one_sided_window():
    out = block_sign_stability([-0.01] * 60, block=20, n_resamples=300)
    assert out["ret"] < 0 and out["p_same_sign"] == 1.0


def test_block_delta_is_paired_so_common_market_noise_cancels():
    """Dos brazos con el MISMO ruido de mercado y un shift constante: el Δ tiene que
    salir estable aunque cada serie por separado sea puro ruido. Es exactamente por
    esto que el criterio se mide pareado."""
    import random

    rng = random.Random(3)
    market = [rng.gauss(0.0, 0.02) for _ in range(200)]
    a = market
    b = [m + 0.001 for m in market]  # el candidato gana 10 pb por día
    out = block_delta_sign_stability(a, b, block=20, n_resamples=300)
    assert out["delta"] > 0
    assert out["p_same_sign"] == 1.0


def test_block_delta_sees_no_difference_between_identical_arms():
    rets = [0.01, -0.02, 0.03] * 20
    out = block_delta_sign_stability(rets, list(rets), block=10, n_resamples=200)
    assert out["delta"] == pytest.approx(0.0, abs=1e-12)
    assert out["p_same_sign"] == pytest.approx(0.5)


def test_block_delta_needs_two_points():
    assert block_delta_sign_stability([0.1], [0.2])["p_same_sign"] is None


# ── el agrupador ─────────────────────────────────────────────────────────────


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


def test_per_trade_by_regime_converts_to_points_and_keeps_every_regime():
    res = _Res([_T(0.05, "stress_bear_2022"), _T(-0.02, BULL_NORMAL)])
    out = per_trade_by_regime(res)
    assert out["stress_bear_2022"] == [pytest.approx(5.0)]
    assert out[BULL_NORMAL] == [pytest.approx(-2.0)]
    assert out["stress_2018q4"] == []  # las vacías existen, no desaparecen
