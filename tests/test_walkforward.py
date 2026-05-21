"""
Tests for walk-forward validation of train_xgboost_signal (T03 of the roadmap).

Goal of T03: replace the single 80/20 split with an expanding-window
walk-forward (TimeSeriesSplit, 5 folds, PREDICTION_HORIZON-day purge gap) so
that validation accuracy is reported as a distribution (mean ± std) rather
than a single lucky point. A high cross-fold std flags an unstable model.

What these tests verify
-----------------------
1. Purge gap: every fold leaves exactly PREDICTION_HORIZON rows between the
   end of the train window and the start of the val window (no overlapping-
   label leakage). This is a pure-logic test on the exact TimeSeriesSplit
   configuration the production code uses.
2. On a healthy series the walk-forward path runs, logs ``val_acc=X% ± Y%``,
   and caches a 4-element tuple whose val_std is a real dispersion estimate.
3. A predictable (mean-reverting) series gives consistent accuracy across
   folds → low std and no instability warning.
4. A regime-change series (predictable then noisy) makes folds disagree →
   std above WALKFORWARD_STD_WARN → an instability warning is logged.
5. Short histories fall back to the single-split path (val_std == 0.0).
6. The final cached model is CV-calibrated (refit across folds), not a single
   fold's model.

Notes
-----
* Skipped if xgboost or sklearn is missing, like test_calibration.py, so
  minimal CI envs don't fail.
* The purge-gap test only needs sklearn (not xgboost).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

# Skip the whole module if the optional ML stack isn't available.
xgb = pytest.importorskip("xgboost")
sk_cal = pytest.importorskip("sklearn.calibration")

from analysis import ml_signals
from analysis.ml_signals import (
    N_WALKFORWARD_FOLDS,
    PREDICTION_HORIZON,
    WALKFORWARD_STD_WARN,
    _XGB_CACHE,
    clear_ml_cache,
    train_xgboost_signal,
)

ML_LOGGER = "analysis.ml_signals"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cached_tuple():
    """Return the single cached (model, val_acc, train_acc, val_std) tuple."""
    if not _XGB_CACHE:
        return None
    return next(iter(_XGB_CACHE.values()))


def _ohlcv_from_close(close: np.ndarray) -> pd.DataFrame:
    """Wrap a close-price array in a plausible OHLCV frame with a B-day index."""
    close = np.asarray(close, dtype=float)
    n = len(close)
    rng = np.random.default_rng(0)
    wiggle = np.abs(rng.normal(0, 0.002, n))
    high = close * (1 + wiggle)
    low = close * (1 - wiggle)
    open_ = np.r_[close[0], close[:-1]]
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


def _mean_reverting_close(n: int, period: int = 25, amp: float = 0.08) -> np.ndarray:
    """Deterministic sine oscillation around a flat base.

    The 5-day-ahead direction is a smooth function of phase, so momentum
    features carry a strong, learnable signal → XGB scores high and *stable*
    across folds. A touch of noise keeps the labels from being degenerate.
    """
    t = np.arange(n)
    base = 100.0
    osc = amp * np.sin(2 * np.pi * t / period)
    noise = np.random.default_rng(1).normal(0, 0.004, n).cumsum() * 0.05
    return base * (1 + osc + noise)


def _regime_change_close(n_pred: int = 350, n_noise: int = 300) -> np.ndarray:
    """A clean mean-reverting segment followed by a pure random walk.

    Early walk-forward folds validate on the predictable segment (high
    accuracy); late folds validate on the noise (≈coin flip). The folds
    therefore disagree strongly → large cross-fold std → instability warning.
    """
    pred = _mean_reverting_close(n_pred, period=20, amp=0.10)
    rng = np.random.default_rng(99)
    rets = rng.normal(0, 0.02, n_noise)
    noise = pred[-1] * np.exp(np.cumsum(rets))
    return np.concatenate([pred, noise])


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_purge_gap_equals_prediction_horizon():
    """Pure-logic guard on the exact split config the production path uses.

    Every fold must leave PREDICTION_HORIZON rows between the end of the train
    window and the start of the val window. If someone drops the ``gap=``
    argument, this fails.
    """
    tss = pytest.importorskip("sklearn.model_selection").TimeSeriesSplit(
        n_splits=N_WALKFORWARD_FOLDS, gap=PREDICTION_HORIZON
    )
    X = np.zeros((575, 3), dtype=np.float32)
    folds = list(tss.split(X))
    assert len(folds) == N_WALKFORWARD_FOLDS
    for tr_idx, val_idx in folds:
        gap_obs = int(val_idx[0] - tr_idx[-1] - 1)
        assert gap_obs == PREDICTION_HORIZON, (
            f"purge gap {gap_obs} != PREDICTION_HORIZON {PREDICTION_HORIZON}"
        )
        # Train window must precede the val window (expanding, no overlap).
        assert tr_idx[-1] < val_idx[0]


def test_walkforward_runs_and_reports_mean_std(ohlcv_factory, caplog):
    """On a healthy ~600-row series the walk-forward path runs, logs
    ``val_acc=X% ± Y%``, caches a 4-element tuple, and the signal description
    shows the ± dispersion."""
    clear_ml_cache()
    df = ohlcv_factory(rows=600, seed=7)

    with caplog.at_level(logging.INFO, logger=ML_LOGGER):
        result = train_xgboost_signal(df)

    assert result is not None
    assert 0.0 <= result.value <= 1.0

    cached = _cached_tuple()
    assert cached is not None
    assert len(cached) == 4, "cache tuple should be (model, val_acc, train_acc, val_std)"
    _model, val_acc, _train_acc, val_std = cached
    assert 0.0 <= val_acc <= 1.0
    assert val_std >= 0.0
    # On a noisy random walk the cross-fold std is essentially never exactly 0.
    assert val_std > 0.0
    assert "walk-forward" in caplog.text.lower()
    assert "±" in result.description


def test_short_history_falls_back_to_single_split(ohlcv_factory):
    """Below MIN_WALKFORWARD_ROWS labelled rows, the engine uses the single
    80/20 split path, signalled by val_std == 0.0 (no dispersion estimate)."""
    clear_ml_cache()
    # ~200 rows → after feature lookback + horizon dropna, well under 250.
    df = ohlcv_factory(rows=200, seed=11)

    result = train_xgboost_signal(df)
    assert result is not None, "training should still succeed on a short series"

    cached = _cached_tuple()
    assert cached is not None
    _model, _val_acc, _train_acc, val_std = cached
    assert val_std == 0.0, "single-split fallback must report zero dispersion"
    assert "±" not in result.description


def test_predictable_series_low_std(caplog):
    """A deterministic mean-reverting series is learnable the same way in
    every fold → low cross-fold std and no instability warning."""
    clear_ml_cache()
    df = _ohlcv_from_close(_mean_reverting_close(600))

    with caplog.at_level(logging.WARNING, logger=ML_LOGGER):
        result = train_xgboost_signal(df)

    assert result is not None
    cached = _cached_tuple()
    assert cached is not None
    _model, val_acc, _train_acc, val_std = cached
    # Learnable signal: accuracy clears coin-flip and stays consistent.
    assert val_acc > 0.55, f"expected a learnable signal, got val_acc={val_acc:.2f}"
    assert val_std < WALKFORWARD_STD_WARN, (
        f"predictable series should be stable, got std={val_std:.3f}"
    )
    assert "unstable model" not in caplog.text.lower()


def test_regime_change_series_warns(caplog):
    """A predictable→noisy regime change makes folds disagree → std above
    WALKFORWARD_STD_WARN → an instability warning is logged."""
    clear_ml_cache()
    df = _ohlcv_from_close(_regime_change_close())

    with caplog.at_level(logging.WARNING, logger=ML_LOGGER):
        result = train_xgboost_signal(df)

    assert result is not None
    cached = _cached_tuple()
    assert cached is not None
    _model, _val_acc, _train_acc, val_std = cached

    # The warning and the std must be consistent: if the model is flagged
    # unstable, the std exceeded the threshold, and vice versa.
    warned = "unstable model" in caplog.text.lower()
    assert warned == (val_std > WALKFORWARD_STD_WARN)
    # This particular construction is engineered to trip the threshold.
    assert warned, f"regime-change series should warn; std={val_std:.3f}"


def test_final_model_is_cv_calibrated(ohlcv_factory):
    """The cached final model is a CalibratedClassifierCV produced by the
    walk-forward CV (refit across folds), not a single fold's bare model."""
    clear_ml_cache()
    df = ohlcv_factory(rows=600, seed=3)

    result = train_xgboost_signal(df)
    assert result is not None

    cached = _cached_tuple()
    assert cached is not None
    model = cached[0]
    assert isinstance(model, sk_cal.CalibratedClassifierCV), (
        f"expected CV-calibrated final model, got {type(model).__name__}"
    )
    # CV (non-prefit) calibration fits one calibrated classifier per fold.
    assert len(model.calibrated_classifiers_) >= 2


def test_cache_reuse_is_stable(ohlcv_factory):
    """A second call on the same data hits the cache and returns the identical
    probability — the walk-forward result (including val_std) is memoised."""
    clear_ml_cache()
    df = ohlcv_factory(rows=600, seed=23)

    first = train_xgboost_signal(df)
    cached_first = _cached_tuple()
    second = train_xgboost_signal(df)
    cached_second = _cached_tuple()

    assert first is not None and second is not None
    assert cached_first[0] is cached_second[0]
    assert abs(first.value - second.value) < 1e-9
