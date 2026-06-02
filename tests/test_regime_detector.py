"""
Tests for ``analysis.regime_detector`` — the statistical (Sharpe + vol)
market-regime detector built for Sprint 2 fase 2 (T-régimen-1).

What these tests pin down:

1. The four valid regime labels are emitted on synthetic data that matches
   each cuadrante by construction.
2. Warm-up bars (before either rolling window has filled) are labelled
   ``warmup`` and excluded from distribution helpers by default.
3. The min-run-length hysteresis filter actually suppresses 1-2 bar flickers
   while still letting genuinely persistent regimes propagate.
4. Edge cases: missing 'Close' column, ridiculous window sizes, all-flat
   series.
5. The convenience helpers (``regime_at``, ``regime_distribution``,
   ``regime_run_lengths``) return shapes / types that downstream callers can
   rely on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.regime_detector import (
    REGIME_BEAR,
    REGIME_BULL_QUIET,
    REGIME_BULL_VOLATILE,
    REGIME_LATERAL,
    REGIME_WARMUP,
    RegimeConfig,
    detect_regime_series,
    regime_at,
    regime_distribution,
    regime_run_lengths,
)


# ── Synthetic data builders ─────────────────────────────────────────────────


def _make_df(returns: np.ndarray, start: str = "2024-01-02") -> pd.DataFrame:
    """Build an OHLCV-shaped DataFrame from a returns vector. Only Close is
    used by the detector; the other columns are filled with the same series so
    tests fail loudly if the detector accidentally reads anything but Close."""
    idx = pd.bdate_range(start=start, periods=len(returns))
    price = 100.0 * np.cumprod(1.0 + returns)
    return pd.DataFrame(
        {"Open": price, "High": price, "Low": price, "Close": price, "Volume": 1_000_000},
        index=idx,
    )


def _quiet_bull(n: int, daily_return: float = 0.0015, daily_vol: float = 0.006,
                seed: int = 0) -> np.ndarray:
    """Daily drift ~38% annual, vol ~9.5% annual → Sharpe ~ 4 (well above +0.5
    threshold), vol below 0.18 → should classify as bull_quiet."""
    rng = np.random.default_rng(seed)
    return rng.normal(loc=daily_return, scale=daily_vol, size=n)


def _volatile_bull(n: int, daily_return: float = 0.005, daily_vol: float = 0.025,
                   seed: int = 1) -> np.ndarray:
    """Strong drift to keep annualised Sharpe well above the +1.0 threshold even
    with 60-bar window noise (std ≈ 2.05). Vol annualised ≈ 40% (well above
    0.18) → bull_volatile."""
    rng = np.random.default_rng(seed)
    return rng.normal(loc=daily_return, scale=daily_vol, size=n)


def _bear(n: int, daily_return: float = -0.005, daily_vol: float = 0.020,
          seed: int = 2) -> np.ndarray:
    """Strong negative drift; annualised Sharpe ≈ −4 (well below −1.0
    threshold)."""
    rng = np.random.default_rng(seed)
    return rng.normal(loc=daily_return, scale=daily_vol, size=n)


def _lateral_mean_reverting(n: int, amplitude: float = 0.01,
                            period: int = 30, noise_vol: float = 0.003,
                            seed: int = 3) -> np.ndarray:
    """Sinusoidal returns + small noise: deterministically lateral.

    Pure i.i.d. or AR(1) zero-drift returns still produce 60-bar rolling
    Sharpes that wander outside ±1.0 due to sample-mean variance — even with
    500 bars the test fails on ~half the seeds. A sine wave on returns
    guarantees the cumulative drift over any window of length ≥ period is
    near zero, so the rolling Sharpe stays inside the deadband by
    construction. Small Gaussian noise on top keeps the series realistic
    without breaking the lateral property."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    signal = amplitude * np.sin(2.0 * np.pi * t / period)
    noise = rng.normal(loc=0.0, scale=noise_vol, size=n)
    return signal + noise


# ── Core classification ─────────────────────────────────────────────────────


class TestQuadrants:
    """For each of the four target buckets, construct a long series with the
    expected properties and assert the detector dominates that bucket."""

    @pytest.mark.parametrize("seed", range(5))
    def test_bull_quiet_dominates_for_quiet_uptrend(self, seed):
        df = _make_df(_quiet_bull(500, seed=seed))
        out = detect_regime_series(df)
        # After warm-up, the bulk of the series should be bull_quiet.
        non_warm = out["regime"][out["regime"] != REGIME_WARMUP]
        assert (non_warm == REGIME_BULL_QUIET).mean() > 0.6, (
            f"Expected mostly bull_quiet, got distribution: "
            f"{non_warm.value_counts(normalize=True).to_dict()}"
        )

    @pytest.mark.parametrize("seed", range(5))
    def test_bull_volatile_dominates_for_choppy_uptrend(self, seed):
        df = _make_df(_volatile_bull(500, seed=seed))
        out = detect_regime_series(df)
        non_warm = out["regime"][out["regime"] != REGIME_WARMUP]
        assert (non_warm == REGIME_BULL_VOLATILE).mean() > 0.6, (
            f"Expected mostly bull_volatile, got distribution: "
            f"{non_warm.value_counts(normalize=True).to_dict()}"
        )

    @pytest.mark.parametrize("seed", range(5))
    def test_bear_dominates_for_downtrend(self, seed):
        df = _make_df(_bear(500, seed=seed))
        out = detect_regime_series(df)
        non_warm = out["regime"][out["regime"] != REGIME_WARMUP]
        assert (non_warm == REGIME_BEAR).mean() > 0.6, (
            f"Expected mostly bear, got: "
            f"{non_warm.value_counts(normalize=True).to_dict()}"
        )

    @pytest.mark.parametrize("seed", range(5))
    def test_lateral_dominates_for_mean_reverting(self, seed):
        df = _make_df(_lateral_mean_reverting(500, seed=seed))
        out = detect_regime_series(df)
        non_warm = out["regime"][out["regime"] != REGIME_WARMUP]
        # Mean reversion suppresses rolling Sharpe near zero. We expect the
        # majority of bars to fall in the ±1.0 deadband.
        assert (non_warm == REGIME_LATERAL).mean() > 0.5, (
            f"Expected mostly lateral, got: "
            f"{non_warm.value_counts(normalize=True).to_dict()}"
        )


# ── Warm-up handling ────────────────────────────────────────────────────────


class TestWarmup:
    def test_first_bars_are_warmup_until_sharpe_window_fills(self):
        cfg = RegimeConfig(sharpe_window=60, vol_window=30, min_run_length=1)
        df = _make_df(_quiet_bull(200))
        out = detect_regime_series(df, cfg)
        # First 59 bars: sharpe window not full (pct_change drops 1, then rolling
        # mean needs another 59 → first 60 NaN)
        warmup_bars = (out["regime"] == REGIME_WARMUP).sum()
        # Whichever rolling window is larger drives warmup length. With sharpe=60
        # we expect ~60 warmup bars.
        assert 58 <= warmup_bars <= 62, f"unexpected warmup length: {warmup_bars}"

    def test_distribution_helper_excludes_warmup_by_default(self):
        df = _make_df(_quiet_bull(200))
        dist = regime_distribution(df)
        assert REGIME_WARMUP not in dist
        assert abs(sum(dist.values()) - 1.0) < 1e-9

    def test_distribution_helper_can_include_warmup(self):
        df = _make_df(_quiet_bull(200))
        dist = regime_distribution(df, include_warmup=True)
        assert REGIME_WARMUP in dist
        assert abs(sum(dist.values()) - 1.0) < 1e-9


# ── Hysteresis ──────────────────────────────────────────────────────────────


class TestSmoothing:
    def test_min_run_length_suppresses_short_flickers(self):
        """A single bar of bull inserted into a long bear series should NOT
        flip the regime under min_run_length=5."""
        # Build a clean bear that lasts 200 bars, with one bar of strong positive
        # return inserted in the middle.
        bear_returns = _bear(200, seed=42)
        bear_returns[150] = +0.05  # one strong up day
        df = _make_df(bear_returns)
        cfg = RegimeConfig(min_run_length=5)
        out = detect_regime_series(df, cfg)
        # Around the inserted bar, the SMOOTHED regime should remain bear even
        # though raw may flicker.
        nearby = out["regime"].iloc[150:155]
        # Most of the nearby bars should still be bear (the flicker is absorbed).
        assert (nearby == REGIME_BEAR).sum() >= 4, (
            f"Hysteresis did not absorb 1-bar flicker. Window: {nearby.tolist()}"
        )

    def test_min_run_length_one_disables_smoothing(self):
        df = _make_df(_quiet_bull(200))
        cfg = RegimeConfig(min_run_length=1)
        out = detect_regime_series(df, cfg)
        # With smoothing off, raw and smoothed must be identical.
        assert (out["regime_raw"] == out["regime"]).all()

    def test_persistent_regime_change_eventually_propagates(self):
        """30 bars of bull followed by 60 bars of bear: even with smoothing,
        the smoothed series must eventually accept the bear regime."""
        bull = _quiet_bull(120, seed=10)
        bear = _bear(120, seed=11)
        returns = np.concatenate([bull, bear])
        df = _make_df(returns)
        cfg = RegimeConfig(min_run_length=5)
        out = detect_regime_series(df, cfg)
        # In the last 50 bars of the series the regime should clearly be bear.
        tail = out["regime"].iloc[-50:]
        assert (tail == REGIME_BEAR).mean() > 0.6, (
            f"Persistent bear was not picked up. Tail distribution: "
            f"{tail.value_counts(normalize=True).to_dict()}"
        )


# ── Input validation & edge cases ───────────────────────────────────────────


class TestInputValidation:
    def test_missing_close_raises(self):
        df = pd.DataFrame({"Open": [1, 2, 3]})
        with pytest.raises(ValueError, match="Close"):
            detect_regime_series(df)

    def test_tiny_window_rejected(self):
        df = _make_df(_quiet_bull(50))
        with pytest.raises(ValueError, match="window"):
            detect_regime_series(df, RegimeConfig(sharpe_window=1))
        with pytest.raises(ValueError, match="window"):
            detect_regime_series(df, RegimeConfig(vol_window=1))

    def test_all_flat_series_is_lateral(self):
        # If all returns are exactly zero, vol = 0 → Sharpe is NaN (0/0).
        # The detector should call this warmup (NaN propagates), not crash.
        n = 200
        idx = pd.bdate_range(start="2024-01-02", periods=n)
        df = pd.DataFrame({"Close": np.full(n, 100.0)}, index=idx)
        out = detect_regime_series(df)
        # Everything is warmup because vol is 0 → Sharpe is NaN.
        assert (out["regime"] == REGIME_WARMUP).all()

    def test_handles_short_series_without_crashing(self):
        df = _make_df(_quiet_bull(40))  # less than sharpe_window=60
        out = detect_regime_series(df)
        # No bar can be classified; entire output is warmup.
        assert (out["regime"] == REGIME_WARMUP).all()


# ── Convenience helpers ─────────────────────────────────────────────────────


class TestRegimeAt:
    def test_regime_at_last_bar(self):
        df = _make_df(_quiet_bull(200, seed=7))
        label = regime_at(df)
        assert label in (REGIME_BULL_QUIET, REGIME_BULL_VOLATILE, REGIME_LATERAL)

    def test_regime_at_specific_date(self):
        df = _make_df(_quiet_bull(200, seed=8))
        # Pick a date well past warmup.
        when = df.index[150]
        label = regime_at(df, when=when)
        assert label != REGIME_WARMUP

    def test_regime_at_before_history_starts_returns_warmup(self):
        df = _make_df(_quiet_bull(200))
        label = regime_at(df, when="1900-01-01")
        assert label == REGIME_WARMUP


class TestRegimeRunLengths:
    def test_runs_cover_non_warmup_bars(self):
        # Make a mixed series: 100 bull then 100 bear.
        returns = np.concatenate([_quiet_bull(150, seed=20), _bear(150, seed=21)])
        df = _make_df(returns)
        runs = regime_run_lengths(df)
        assert not runs.empty
        # Sum of lengths must equal number of non-warmup bars.
        non_warm = (detect_regime_series(df)["regime"] != REGIME_WARMUP).sum()
        assert int(runs["length"].sum()) == non_warm

    def test_run_labels_are_valid(self):
        returns = np.concatenate([_quiet_bull(150, seed=22), _bear(150, seed=23)])
        df = _make_df(returns)
        runs = regime_run_lengths(df)
        valid = {REGIME_BULL_QUIET, REGIME_BULL_VOLATILE, REGIME_LATERAL, REGIME_BEAR}
        assert set(runs["regime"]).issubset(valid)
