"""
Unit tests for ``paper_trading.gates`` — the pure gate module shared by the
live engine and the Sprint-1 harness.

Each test pins one behavioural contract; together they back the regression
guarantee that ``engine.py`` and ``strategies.py`` still produce identical
output after the extract refactor.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from paper_trading.gates import (
    ATR_EXIT_REASONS,
    CorrelationSkip,
    VolOverlayResult,
    adv_capped_notional,
    atr_exit_decision,
    compute_vol_overlay,
    is_atr_forced_exit_reason,
    is_within_earnings_blackout,
    recent_adv_dollars,
    select_uncorrelated_picks,
)


# ── is_atr_forced_exit_reason ──────────────────────────────────────────────────


class TestIsAtrForcedExitReason:
    def test_none_is_not_forced(self):
        assert is_atr_forced_exit_reason(None) is False

    def test_empty_is_not_forced(self):
        assert is_atr_forced_exit_reason("") is False

    def test_atr_stop_is_forced(self):
        assert is_atr_forced_exit_reason("atr_stop @ 100") is True

    def test_atr_tp_is_forced(self):
        assert is_atr_forced_exit_reason("atr_tp @ 100") is True

    def test_atr_trail_is_forced(self):
        assert is_atr_forced_exit_reason("atr_trail @ ...") is True

    def test_analyze_sell_is_not_forced(self):
        assert is_atr_forced_exit_reason("analyze SELL (0.34)") is False

    def test_reasons_constant_complete(self):
        assert set(ATR_EXIT_REASONS) == {"atr_stop", "atr_tp", "atr_trail"}


# ── atr_exit_decision ──────────────────────────────────────────────────────────


class TestAtrExitDecision:
    def test_stop_fires_when_price_below_stop_level(self):
        reason, level = atr_exit_decision(
            current_price=89.0, avg_cost=100.0, high_water_mark=110.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is not None
        assert reason.startswith("atr_stop")
        assert level == 90.0

    def test_no_exit_inside_band(self):
        # price=105 mid-band: stop=90, trail=100 (hwm 110 - 2*5), tp=120. No fire.
        reason, level = atr_exit_decision(
            current_price=105.0, avg_cost=100.0, high_water_mark=110.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is None
        assert level is None

    def test_take_profit_fires(self):
        reason, level = atr_exit_decision(
            current_price=121.0, avg_cost=100.0, high_water_mark=121.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is not None
        assert reason.startswith("atr_tp")
        assert level == 120.0

    def test_trail_fires_when_price_below_peak_band(self):
        reason, level = atr_exit_decision(
            current_price=109.0, avg_cost=100.0, high_water_mark=120.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is not None
        assert reason.startswith("atr_trail")
        assert level == 110.0

    def test_trail_suppressed_when_hwm_too_close_to_entry(self):
        reason, level = atr_exit_decision(
            current_price=95.0, avg_cost=100.0, high_water_mark=104.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is None
        assert level is None

    def test_trail_disabled_only_stop_and_tp(self):
        reason, level = atr_exit_decision(
            current_price=109.0, avg_cost=100.0, high_water_mark=120.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=False,
        )
        assert reason is None
        assert level is None

    def test_stop_wins_over_trail_when_both_eligible(self):
        reason, _ = atr_exit_decision(
            current_price=89.0, avg_cost=100.0, high_water_mark=120.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is not None and reason.startswith("atr_stop")

    def test_no_hwm_uses_avg_cost_as_baseline(self):
        reason, _ = atr_exit_decision(
            current_price=95.0, avg_cost=100.0, high_water_mark=None,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is None

    def test_non_finite_inputs_return_none(self):
        reason, level = atr_exit_decision(
            current_price=float("nan"), avg_cost=100.0, high_water_mark=110.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is None and level is None

    def test_zero_price_returns_none(self):
        reason, _ = atr_exit_decision(
            current_price=0.0, avg_cost=100.0, high_water_mark=110.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is None

    def test_zero_atr_returns_none(self):
        reason, _ = atr_exit_decision(
            current_price=80.0, avg_cost=100.0, high_water_mark=110.0,
            atr_value=0.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert reason is None

    def test_reason_format_carries_diagnostic(self):
        reason, _ = atr_exit_decision(
            current_price=80.0, avg_cost=100.0, high_water_mark=110.0,
            atr_value=5.0, stop_mult=2.0, tp_mult=4.0, trail_enabled=True,
        )
        assert "@" in reason
        assert "ATR" in reason


# ── is_within_earnings_blackout ────────────────────────────────────────────────


class TestIsWithinEarningsBlackout:
    def test_no_date_means_no_blackout(self):
        assert is_within_earnings_blackout(None, datetime(2026, 5, 26), 3) is False

    def test_disabled_when_days_zero(self):
        assert is_within_earnings_blackout(datetime(2026, 5, 27), datetime(2026, 5, 26), 0) is False

    def test_disabled_when_days_negative(self):
        assert is_within_earnings_blackout(datetime(2026, 5, 27), datetime(2026, 5, 26), -1) is False

    def test_inside_window_before_earnings(self):
        assert is_within_earnings_blackout(
            datetime(2026, 5, 28), datetime(2026, 5, 26, 15, 30), 3,
        ) is True

    def test_inside_window_after_earnings(self):
        assert is_within_earnings_blackout(
            datetime(2026, 5, 24), datetime(2026, 5, 26), 3,
        ) is True

    def test_outside_window(self):
        assert is_within_earnings_blackout(
            datetime(2026, 5, 31), datetime(2026, 5, 26), 3,
        ) is False

    def test_at_boundary_inclusive(self):
        assert is_within_earnings_blackout(
            datetime(2026, 5, 29), datetime(2026, 5, 26), 3,
        ) is True

    def test_same_day_intraday_time_ignored(self):
        assert is_within_earnings_blackout(
            datetime(2026, 5, 26, 8, 0), datetime(2026, 5, 26, 16, 30), 1,
        ) is True


# ── select_uncorrelated_picks ──────────────────────────────────────────────────


def _ret(seed: int, n: int = 60) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0, 0.01, size=n))


class TestSelectUncorrelatedPicks:
    def test_zero_free_slots_returns_empty(self):
        accepted, skipped = select_uncorrelated_picks(
            ["AAPL", "MSFT"], [], 0, lambda t: None, threshold=0.5,
        )
        assert accepted == [] and skipped == []

    def test_threshold_one_disables_gate(self):
        accepted, skipped = select_uncorrelated_picks(
            ["AAPL", "MSFT", "NVDA"], ["GOOGL"], 2, lambda t: None, threshold=1.0,
        )
        assert accepted == ["AAPL", "MSFT"]
        assert skipped == []

    def test_missing_returns_always_accepted(self):
        accepted, skipped = select_uncorrelated_picks(
            ["AAPL", "MSFT"], ["GOOGL"], 2, lambda t: None, threshold=0.3,
        )
        assert accepted == ["AAPL", "MSFT"]
        assert skipped == []

    def test_skips_when_correlation_exceeds_threshold(self):
        rets = {t: _ret(i) for i, t in enumerate(["AAPL", "MSFT", "GOOGL"])}
        accepted, skipped = select_uncorrelated_picks(
            ["AAPL", "MSFT"], ["GOOGL"], 2,
            returns_provider=lambda t: rets.get(t),
            threshold=0.5,
            mean_corr_fn=lambda c, h: 0.9,
        )
        assert accepted == []
        assert {s.ticker for s in skipped} == {"AAPL", "MSFT"}
        assert all(s.avg_correlation == 0.9 for s in skipped)

    def test_accepts_below_threshold(self):
        rets = {t: _ret(i) for i, t in enumerate(["AAPL", "MSFT", "GOOGL"])}
        accepted, skipped = select_uncorrelated_picks(
            ["AAPL", "MSFT"], ["GOOGL"], 2,
            returns_provider=lambda t: rets.get(t),
            threshold=0.5,
            mean_corr_fn=lambda c, h: 0.2,
        )
        assert accepted == ["AAPL", "MSFT"]
        assert skipped == []

    def test_compares_against_accepted_picks_not_just_held(self):
        rets = {t: _ret(i) for i, t in enumerate(["AAPL", "MSFT"])}
        seen_compare_sets = []

        def mean_corr(cand, held):
            seen_compare_sets.append(len(held))
            return 0.1

        accepted, _ = select_uncorrelated_picks(
            ["AAPL", "MSFT"], [], 2,
            returns_provider=lambda t: rets.get(t),
            threshold=0.5,
            mean_corr_fn=mean_corr,
        )
        assert accepted == ["AAPL", "MSFT"]
        assert seen_compare_sets == [1]

    def test_partial_fill_respects_slot_cap(self):
        rets = {t: _ret(i) for i, t in enumerate(["AAPL", "MSFT", "NVDA", "TSLA"])}
        accepted, _ = select_uncorrelated_picks(
            ["AAPL", "MSFT", "NVDA", "TSLA"], [], 2,
            returns_provider=lambda t: rets.get(t),
            threshold=0.5,
            mean_corr_fn=lambda c, h: 0.1,
        )
        assert len(accepted) == 2
        assert accepted == ["AAPL", "MSFT"]


# ── compute_vol_overlay ────────────────────────────────────────────────────────


class TestComputeVolOverlay:
    def test_zero_target_disables_overlay(self):
        result = compute_vol_overlay({"AAPL": 0.5}, None, vol_target_annual=0.0)
        assert result.factor == 1.0
        assert result.sigma is None
        assert result.scaled_weights == {"AAPL": 0.5}

    def test_negative_target_disables_overlay(self):
        result = compute_vol_overlay({"AAPL": 0.5}, None, vol_target_annual=-0.1)
        assert result.factor == 1.0

    def test_empty_weights_returns_unity(self):
        result = compute_vol_overlay({}, None, vol_target_annual=0.20)
        assert result.factor == 1.0
        assert result.sigma is None
        assert result.scaled_weights == {}

    def test_below_target_returns_unity(self):
        def apply_fn(w, ret_df, vt):
            return dict(w), 0.10, 1.0

        result = compute_vol_overlay(
            {"AAPL": 0.5, "MSFT": 0.5}, None, vol_target_annual=0.20, apply_fn=apply_fn,
        )
        assert result.factor == 1.0
        assert result.sigma == 0.10

    def test_above_target_scales_down(self):
        def apply_fn(w, ret_df, vt):
            scaled = {t: v * 0.667 for t, v in w.items()}
            return scaled, 0.30, 0.667

        result = compute_vol_overlay(
            {"AAPL": 0.5, "MSFT": 0.5}, None, vol_target_annual=0.20, apply_fn=apply_fn,
        )
        assert result.factor == pytest.approx(0.667)
        assert result.sigma == pytest.approx(0.30)
        assert result.scaled_weights["AAPL"] == pytest.approx(0.5 * 0.667)

    def test_none_sigma_handled(self):
        def apply_fn(w, ret_df, vt):
            return dict(w), None, 1.0

        result = compute_vol_overlay(
            {"AAPL": 0.5}, None, vol_target_annual=0.20, apply_fn=apply_fn,
        )
        assert result.factor == 1.0
        assert result.sigma is None


# ── recent_adv_dollars (T10) ───────────────────────────────────────────────────


def _ohlcv(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": volumes,
        },
        index=idx,
    )


class TestRecentAdvDollars:
    def test_none_history_returns_none(self):
        assert recent_adv_dollars(None) is None

    def test_zero_lookback_returns_none(self):
        df = _ohlcv([100.0] * 5, [1000.0] * 5)
        assert recent_adv_dollars(df, lookback_days=0) is None

    def test_missing_volume_column_returns_none(self):
        df = _ohlcv([100.0] * 5, [1000.0] * 5).drop(columns=["Volume"])
        assert recent_adv_dollars(df) is None

    def test_missing_close_column_returns_none(self):
        df = _ohlcv([100.0] * 5, [1000.0] * 5).drop(columns=["Close"])
        assert recent_adv_dollars(df) is None

    def test_simple_mean_dollar_volume(self):
        # Close=10, Volume=100 → dollar vol 1000 every day.
        df = _ohlcv([10.0] * 5, [100.0] * 5)
        assert recent_adv_dollars(df, lookback_days=5) == pytest.approx(1000.0)

    def test_only_uses_trailing_window(self):
        # 10 days; last 3 have dollar vol 2000, earlier ones 100.
        closes = [1.0] * 7 + [10.0] * 3
        vols = [100.0] * 7 + [200.0] * 3
        df = _ohlcv(closes, vols)
        # tail(3): 10*200 = 2000 each → mean 2000.
        assert recent_adv_dollars(df, lookback_days=3) == pytest.approx(2000.0)

    def test_nan_rows_dropped(self):
        df = _ohlcv([10.0, np.nan, 10.0], [100.0, 100.0, 100.0])
        # Only two finite rows of 1000 → mean 1000.
        assert recent_adv_dollars(df, lookback_days=3) == pytest.approx(1000.0)

    def test_all_nan_returns_none(self):
        df = _ohlcv([np.nan, np.nan], [100.0, 100.0])
        assert recent_adv_dollars(df) is None

    def test_zero_volume_returns_none(self):
        df = _ohlcv([10.0] * 5, [0.0] * 5)
        assert recent_adv_dollars(df) is None


# ── adv_capped_notional (T10) ──────────────────────────────────────────────────


class TestAdvCappedNotional:
    def test_disabled_when_cap_zero(self):
        assert adv_capped_notional(5000.0, 1_000_000.0, 0.0) == (5000.0, False)

    def test_disabled_when_cap_negative(self):
        assert adv_capped_notional(5000.0, 1_000_000.0, -0.1) == (5000.0, False)

    def test_failopen_when_adv_none(self):
        assert adv_capped_notional(5000.0, None, 0.05) == (5000.0, False)

    def test_failopen_when_adv_zero(self):
        assert adv_capped_notional(5000.0, 0.0, 0.05) == (5000.0, False)

    def test_failopen_when_notional_nonpositive(self):
        assert adv_capped_notional(0.0, 1_000_000.0, 0.05) == (0.0, False)

    def test_failopen_when_notional_nonfinite(self):
        out, capped = adv_capped_notional(float("inf"), 1_000_000.0, 0.05)
        assert capped is False

    def test_order_under_ceiling_unchanged(self):
        # ceiling = 0.05 * 1_000_000 = 50_000; order 5000 fits.
        assert adv_capped_notional(5000.0, 1_000_000.0, 0.05) == (5000.0, False)

    def test_order_at_ceiling_not_capped(self):
        assert adv_capped_notional(50_000.0, 1_000_000.0, 0.05) == (50_000.0, False)

    def test_order_above_ceiling_trimmed(self):
        out, capped = adv_capped_notional(80_000.0, 1_000_000.0, 0.05)
        assert capped is True
        assert out == pytest.approx(50_000.0)


# ── Parity smoke test: gates produce same answers as the engine wrapper ────────


class TestEngineParity:
    """End-to-end parity check — the engine wrapper's behaviour is preserved.

    Imports the wrapper functions and asserts they produce identical results
    to the gate functions on the same inputs. This is the regression
    guardrail against accidental drift in the wrappers.
    """

    def test_engine_is_atr_forced_exit_matches_gates(self):
        try:
            from paper_trading.engine import _is_atr_forced_exit
        except ImportError:
            pytest.skip("engine import not available in this environment")
        for reason in ("atr_stop @ x", "atr_tp", "atr_trail", "analyze BUY", None, ""):
            assert _is_atr_forced_exit(reason) == is_atr_forced_exit_reason(reason)

    def test_engine_earnings_blackout_matches_gates(self):
        try:
            from paper_trading.engine import _earnings_blackout_hit
        except ImportError:
            pytest.skip("engine import not available in this environment")
        cases = [
            (datetime(2026, 5, 27), datetime(2026, 5, 26), 3),
            (None, datetime(2026, 5, 26), 3),
            (datetime(2026, 5, 30), datetime(2026, 5, 26), 2),
        ]
        for ed, sa, days in cases:
            assert _earnings_blackout_hit(ed, sa, days) == is_within_earnings_blackout(ed, sa, days)
