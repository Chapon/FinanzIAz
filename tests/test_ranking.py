"""
Tests for analysis.ranking (Sprint 4 / T05 — cross-sectional ranking).

Pure-function module: no DB, no settings, no engine.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.ranking import (
    NEUTRAL_PERCENTILE,
    blended_scores,
    combine_score,
    momentum_percentile,
)

# ── momentum_percentile ──────────────────────────────────────────────────────


class TestMomentumPercentile:
    def test_empty_input(self):
        assert momentum_percentile({}, lookback=60) == {}

    def test_single_ticker_is_neutral(self):
        """With only one rankable ticker there is no cross-section to compare against."""
        closes = {"A": pd.Series([100, 101, 102, 105, 110])}
        out = momentum_percentile(closes, lookback=4)
        assert out == {"A": NEUTRAL_PERCENTILE}

    def test_invalid_lookback_raises(self):
        with pytest.raises(ValueError):
            momentum_percentile({"A": pd.Series([1, 2, 3])}, lookback=0)
        with pytest.raises(ValueError):
            momentum_percentile({"A": pd.Series([1, 2, 3])}, lookback=-5)

    def test_basic_ordering(self):
        """Higher return ⇒ higher percentile. With 3 tickers, ranks are 0.0, 0.5, 1.0."""
        closes = {
            "WINNER": pd.Series([100, 100, 100, 100, 110]),  # +10%
            "MID": pd.Series([100, 100, 100, 100, 105]),  # +5%
            "LOSER": pd.Series([100, 100, 100, 100, 95]),  # -5%
        }
        out = momentum_percentile(closes, lookback=4)
        assert out["LOSER"] == pytest.approx(0.0)
        assert out["MID"] == pytest.approx(0.5)
        assert out["WINNER"] == pytest.approx(1.0)

    def test_ties_get_average_rank(self):
        """Ties share the average of the positions they would have occupied."""
        closes = {
            "A": pd.Series([100, 100, 100, 100, 105]),  # +5%
            "B": pd.Series([100, 100, 100, 100, 105]),  # +5% (tied with A)
            "C": pd.Series([100, 100, 100, 100, 110]),  # +10%
        }
        out = momentum_percentile(closes, lookback=4)
        # Ranks: A=1.5, B=1.5, C=3 → percentiles 0.25, 0.25, 1.0 with (rank-1)/(n-1)
        assert out["A"] == pytest.approx(0.25)
        assert out["B"] == pytest.approx(0.25)
        assert out["C"] == pytest.approx(1.0)

    def test_insufficient_history_is_neutral(self):
        """Tickers with fewer than lookback+1 closes get NEUTRAL_PERCENTILE."""
        closes = {
            "FULL_A": pd.Series([100, 101, 102, 103, 110]),  # +10%
            "FULL_B": pd.Series([100, 100, 100, 100, 95]),  # -5%
            "SHORT": pd.Series([100, 101]),  # 2 bars < 5 needed
        }
        out = momentum_percentile(closes, lookback=4)
        assert out["SHORT"] == NEUTRAL_PERCENTILE
        assert out["FULL_A"] == pytest.approx(1.0)
        assert out["FULL_B"] == pytest.approx(0.0)

    def test_nan_close_is_neutral(self):
        closes = {
            "GOOD": pd.Series([100, 100, 100, 100, 110]),
            "BAD": pd.Series([100, 100, 100, 100, 95]),
            "NAN": pd.Series([100, 100, float("nan"), 100, 100]),
        }
        out = momentum_percentile(closes, lookback=4)
        assert out["NAN"] == NEUTRAL_PERCENTILE
        # GOOD and BAD form the cross-section
        assert out["GOOD"] == pytest.approx(1.0)
        assert out["BAD"] == pytest.approx(0.0)

    def test_zero_or_negative_start_is_neutral(self):
        """Division by zero / negative price would corrupt the return."""
        closes = {
            "ZERO": pd.Series([0, 100, 100, 100, 110]),
            "NEG": pd.Series([-1, 100, 100, 100, 110]),
            "OK": pd.Series([100, 100, 100, 100, 95]),
        }
        out = momentum_percentile(closes, lookback=4)
        assert out["ZERO"] == NEUTRAL_PERCENTILE
        assert out["NEG"] == NEUTRAL_PERCENTILE
        # Only OK is rankable → single ticker → neutral
        assert out["OK"] == NEUTRAL_PERCENTILE

    def test_no_rankable_ticker_all_neutral(self):
        closes = {
            "SHORT_A": pd.Series([100, 101]),
            "SHORT_B": pd.Series([100, 102]),
        }
        out = momentum_percentile(closes, lookback=10)
        assert all(v == NEUTRAL_PERCENTILE for v in out.values())

    def test_only_last_lookback_plus_one_used(self):
        """Older history beyond lookback+1 must not influence the return."""
        # Inject a huge spike early that should be ignored.
        a = pd.Series([1, 999, 999, 100, 100, 100, 100, 110])  # last-5 ret: +10%
        b = pd.Series([1, 1, 1, 100, 100, 100, 100, 95])  # last-5 ret: -5%
        out = momentum_percentile({"A": a, "B": b}, lookback=4)
        assert out["A"] == pytest.approx(1.0)
        assert out["B"] == pytest.approx(0.0)


# ── combine_score ────────────────────────────────────────────────────────────


class TestCombineScore:
    def test_pure_absolute(self):
        assert combine_score(0.7, 0.2, weight=0.0) == pytest.approx(0.7)

    def test_pure_relative(self):
        assert combine_score(0.7, 0.2, weight=1.0) == pytest.approx(0.2)

    def test_equal_blend(self):
        assert combine_score(0.8, 0.4, weight=0.5) == pytest.approx(0.6)

    def test_invalid_weight_raises(self):
        with pytest.raises(ValueError):
            combine_score(0.5, 0.5, weight=-0.1)
        with pytest.raises(ValueError):
            combine_score(0.5, 0.5, weight=1.1)

    def test_clamped_to_unit_interval(self):
        # absolute > 1 should still be clamped after blend
        assert combine_score(1.5, 1.5, weight=0.5) == pytest.approx(1.0)
        # negative inputs clamp to 0
        assert combine_score(-0.2, -0.2, weight=0.5) == pytest.approx(0.0)

    def test_nan_inputs_coerced_to_neutral(self):
        # NaN absolute → neutral 0.5; weight=0 → output 0.5
        assert combine_score(float("nan"), 0.9, weight=0.0) == pytest.approx(NEUTRAL_PERCENTILE)
        assert combine_score(0.9, float("nan"), weight=1.0) == pytest.approx(NEUTRAL_PERCENTILE)

    def test_none_inputs_coerced_to_neutral(self):
        assert combine_score(None, 0.9, weight=0.0) == pytest.approx(NEUTRAL_PERCENTILE)


# ── blended_scores ───────────────────────────────────────────────────────────


class TestBlendedScores:
    def test_weight_zero_is_identity(self):
        """weight=0 ⇒ blended_scores equals the input strengths exactly."""
        strengths = {"A": 0.3, "B": 0.7, "C": 0.5}
        closes = {
            "A": pd.Series([100, 100, 100, 100, 110]),
            "B": pd.Series([100, 100, 100, 100, 95]),
            "C": pd.Series([100, 100, 100, 100, 105]),
        }
        out = blended_scores(strengths, closes, lookback=4, weight=0.0)
        for k, v in strengths.items():
            assert out[k] == pytest.approx(v)

    def test_weight_one_uses_only_percentile(self):
        strengths = {"WINNER": 0.1, "LOSER": 0.99}  # absolute disagrees with momentum
        closes = {
            "WINNER": pd.Series([100, 100, 100, 100, 110]),
            "LOSER": pd.Series([100, 100, 100, 100, 95]),
        }
        out = blended_scores(strengths, closes, lookback=4, weight=1.0)
        # weight=1.0 ⇒ output is pure cross-sectional percentile
        assert out["WINNER"] == pytest.approx(1.0)
        assert out["LOSER"] == pytest.approx(0.0)

    def test_blend_preserves_ranking_when_signals_agree(self):
        """When momentum aligns with strength, the blended ranking matches."""
        strengths = {"BEST": 0.9, "MID": 0.6, "WORST": 0.2}
        closes = {
            "BEST": pd.Series([100, 100, 100, 100, 120]),
            "MID": pd.Series([100, 100, 100, 100, 105]),
            "WORST": pd.Series([100, 100, 100, 100, 90]),
        }
        out = blended_scores(strengths, closes, lookback=4, weight=0.5)
        assert out["BEST"] > out["MID"] > out["WORST"]

    def test_missing_close_uses_neutral(self):
        """Strength present, close missing → blended against neutral 0.5."""
        strengths = {"A": 0.8, "B": 0.2, "MISSING": 0.6}
        closes = {
            "A": pd.Series([100, 100, 100, 100, 110]),
            "B": pd.Series([100, 100, 100, 100, 95]),
        }
        out = blended_scores(strengths, closes, lookback=4, weight=0.5)
        # MISSING is not in closes_by_ticker → percentile_lookup returns NEUTRAL
        assert out["MISSING"] == pytest.approx(0.5 * 0.6 + 0.5 * NEUTRAL_PERCENTILE)


# ── Determinism / mutation safety ────────────────────────────────────────────


class TestDeterminism:
    def test_no_mutation_of_inputs(self):
        closes = {
            "A": pd.Series([100, 100, 100, 100, 110]),
            "B": pd.Series([100, 100, 100, 100, 95]),
        }
        copy_a = closes["A"].copy()
        copy_b = closes["B"].copy()
        _ = momentum_percentile(closes, lookback=4)
        pd.testing.assert_series_equal(closes["A"], copy_a)
        pd.testing.assert_series_equal(closes["B"], copy_b)

    def test_repeatable_output(self):
        closes = {
            "A": pd.Series([100, 100, 100, 100, 110]),
            "B": pd.Series([100, 100, 100, 100, 95]),
            "C": pd.Series([100, 100, 100, 100, 105]),
        }
        a = momentum_percentile(closes, lookback=4)
        b = momentum_percentile(closes, lookback=4)
        assert a == b
