"""
Tests for regime-aware signal weighting (T04 of the roadmap).

The market regime (BULL / BEAR / LATERAL) now tilts how much each indicator
counts toward the overall signal, instead of being a separate additive
``reg_boost`` term:

  • LATERAL  → mean-reversion: RSI / Bollinger ×1.5, MACD / SMA-cross ×0.7
  • BULL/BEAR → trend-following: MACD / SMA-cross ×1.5, RSI / Bollinger ×0.7

These tests pin down (1) the per-(regime, indicator) multipliers, (2) that the
overall signal can *flip* between regimes for the same indicator readings, and
(3) that ``compute_signal_probability`` no longer applies the old additive
regime boost (the tilt lives entirely in the weights now).
"""

from __future__ import annotations

import pytest

from analysis.ml_signals import MarketContext, compute_signal_probability
from analysis.technical import (
    TechnicalSignal,
    aggregate_signals,
    regime_adjusted_weight,
)
from config.constants import (
    REGIME_WEIGHT_BOOST,
    REGIME_WEIGHT_DAMP,
    SIGNAL_STRENGTH_WEIGHTS,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _sig(indicator: str, signal: str, strength: str = "STRONG") -> TechnicalSignal:
    return TechnicalSignal(
        indicator=indicator,
        value=0.0,
        signal=signal,
        strength=strength,
        description=f"{indicator} {signal} {strength}",
    )


def _ctx(regime: str, risk_score: float = 0.0, confidence: float = 0.80) -> MarketContext:
    """Minimal MarketContext with a controllable regime and risk score."""
    return MarketContext(
        regime=regime,
        regime_confidence=confidence,
        volatility_level="LOW",
        annual_volatility=10.0,
        risk_score=risk_score,
    )


# ── 1. regime_adjusted_weight: the multiplier table ───────────────────────────


@pytest.mark.parametrize("strength,base", list(SIGNAL_STRENGTH_WEIGHTS.items()))
def test_lateral_boosts_meanrev_damps_trend(strength, base):
    # LATERAL: oscillators up, trend indicators down.
    assert regime_adjusted_weight("RSI", strength, "LATERAL") == pytest.approx(base * REGIME_WEIGHT_BOOST)
    assert regime_adjusted_weight("Bollinger Bands", strength, "LATERAL") == pytest.approx(base * REGIME_WEIGHT_BOOST)
    assert regime_adjusted_weight("MACD", strength, "LATERAL") == pytest.approx(base * REGIME_WEIGHT_DAMP)
    assert regime_adjusted_weight("Golden/Death Cross", strength, "LATERAL") == pytest.approx(
        base * REGIME_WEIGHT_DAMP
    )


@pytest.mark.parametrize("regime", ["BULL", "BEAR"])
@pytest.mark.parametrize("strength,base", list(SIGNAL_STRENGTH_WEIGHTS.items()))
def test_trending_boosts_trend_damps_meanrev(regime, strength, base):
    # BULL/BEAR: trend indicators up, oscillators down.
    assert regime_adjusted_weight("MACD", strength, regime) == pytest.approx(base * REGIME_WEIGHT_BOOST)
    assert regime_adjusted_weight("Golden/Death Cross", strength, regime) == pytest.approx(
        base * REGIME_WEIGHT_BOOST
    )
    assert regime_adjusted_weight("RSI", strength, regime) == pytest.approx(base * REGIME_WEIGHT_DAMP)
    assert regime_adjusted_weight("Bollinger Bands", strength, regime) == pytest.approx(base * REGIME_WEIGHT_DAMP)


@pytest.mark.parametrize("regime", ["BULL", "BEAR", "LATERAL"])
@pytest.mark.parametrize("indicator", ["Volumen", "GARCH Volatilidad", "HMM Régimen", "XGBoost ML"])
def test_unlisted_indicators_stay_neutral(regime, indicator):
    # Indicators with no entry in the table keep their base weight in every regime.
    for strength, base in SIGNAL_STRENGTH_WEIGHTS.items():
        assert regime_adjusted_weight(indicator, strength, regime) == pytest.approx(base)


@pytest.mark.parametrize("indicator", ["RSI", "MACD", "Bollinger Bands", "Golden/Death Cross", "Volumen"])
def test_none_regime_is_base_weight(indicator):
    # No MarketContext → neutral weighting → pre-T04 behaviour.
    for strength, base in SIGNAL_STRENGTH_WEIGHTS.items():
        assert regime_adjusted_weight(indicator, strength, None) == pytest.approx(base)


# ── 2. aggregate_signals: the overall signal can flip between regimes ─────────


def test_overall_flips_rsi_buy_vs_macd_sell_across_regimes():
    """Same readings — RSI STRONG BUY (oversold) + MACD STRONG SELL (bearish):
    LATERAL trusts the RSI mean-reversion (BUY); BULL trusts the MACD trend (SELL)."""
    signals = [_sig("RSI", "BUY", "STRONG"), _sig("MACD", "SELL", "STRONG")]

    lateral_overall, _, _ = aggregate_signals(signals, "LATERAL")
    bull_overall, _, _ = aggregate_signals(signals, "BULL")

    assert lateral_overall == "BUY"  # RSI 3×1.5=4.5  >  MACD 3×0.7=2.1
    assert bull_overall == "SELL"  # RSI 3×0.7=2.1  <  MACD 3×1.5=4.5
    assert lateral_overall != bull_overall


def test_aggregate_confidence_bounded_when_boosted():
    # All-boosted STRONG BUYs in LATERAL must not blow past 100% confidence.
    signals = [_sig("RSI", "BUY", "STRONG"), _sig("Bollinger Bands", "BUY", "STRONG")]
    overall, strength, confidence = aggregate_signals(signals, "LATERAL")
    assert overall == "BUY"
    assert strength == "STRONG"
    assert 0.0 <= confidence <= 100.0


def test_aggregate_none_regime_matches_unweighted():
    # With regime=None the tally is the plain strength weighting.
    signals = [_sig("RSI", "BUY", "STRONG"), _sig("MACD", "SELL", "MODERATE")]
    overall, _, _ = aggregate_signals(signals, None)
    assert overall == "BUY"  # 3 (RSI) > 2 (MACD)


def test_aggregate_empty_is_hold():
    assert aggregate_signals([], "BULL") == ("HOLD", "WEAK", 0.0)


# ── 3. compute_signal_probability: reg_boost is gone ──────────────────────────


def test_balanced_signals_give_half_regardless_of_regime():
    """With no directional edge and zero vol risk, prob must be exactly 0.5 in
    every regime. The old reg_boost would have pushed BULL/BEAR off 0.5."""
    signals = [_sig("RSI", "HOLD", "WEAK"), _sig("MACD", "HOLD", "WEAK")]
    for regime in ("BULL", "BEAR", "LATERAL"):
        prob = compute_signal_probability(signals, _ctx(regime, risk_score=0.0))
        assert prob == pytest.approx(0.50, abs=1e-9)


def test_probability_tilts_via_weights_not_additive_boost():
    """RSI BUY + MACD SELL: LATERAL leans buy (>0.5), BULL leans sell (<0.5),
    driven purely by the regime-tilted weights (risk_score=0 isolates the effect)."""
    signals = [_sig("RSI", "BUY", "STRONG"), _sig("MACD", "SELL", "STRONG")]

    p_lat = compute_signal_probability(signals, _ctx("LATERAL", risk_score=0.0))
    p_bull = compute_signal_probability(signals, _ctx("BULL", risk_score=0.0))

    assert p_lat > 0.5
    assert p_bull < 0.5


def test_only_vol_penalty_remains():
    """Consensus minus vol_penalty (risk_score × 0.08) is the *only* adjustment —
    no extra additive regime term. Uses neutral-weight indicators and a 3:1
    buy/sell split so raw_prob=0.75 sits away from the [0.05, 0.95] clip, making
    the subtraction observable exactly."""
    signals = [_sig("XGBoost ML", "BUY", "STRONG"), _sig("XGBoost ML", "SELL", "WEAK")]
    risk = 0.5
    # raw_prob = (buy - sell + total) / (2*total) = (3 - 1 + 4) / 8 = 0.75
    expected = 0.75 - risk * 0.08
    prob = compute_signal_probability(signals, _ctx("LATERAL", risk_score=risk))
    assert prob == pytest.approx(expected, abs=1e-9)


def test_empty_signals_default_half():
    assert compute_signal_probability([], _ctx("BULL")) == 0.50
