"""
Tests for isotonic calibration of train_xgboost_signal (T02 of the roadmap).

The calibration goal is that ``predict_proba`` outputs match empirical
frequencies — when the model says 0.65, the realised 5d-up rate in the
validation set should be near 0.65.

What these tests verify
-----------------------
1. With enough validation samples (≥ MIN_CALIBRATION_ROWS), the cached
   model is a CalibratedClassifierCV (i.e. calibration was applied).
2. With too few validation samples, the cached model is the raw
   XGBClassifier (graceful fallback, no crash).
3. The end-to-end signal still returns a TechnicalSignal whose value is
   a valid probability in [0,1] — calibration shouldn't change the API.
4. On a synthetic OOS dataset, the calibrated model's Brier score is
   ≤ raw model's Brier score (calibration shouldn't make things worse).

Notes
-----
* These tests will be skipped if either xgboost or sklearn is missing,
  so they don't pollute CI on minimal envs.
* We use the ``ohlcv_factory`` fixture (in conftest.py) so the input
  series is deterministic across runs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# Skip the whole module if the optional ML stack isn't available.
xgb = pytest.importorskip("xgboost")
sk_cal = pytest.importorskip("sklearn.calibration")

from analysis import ml_signals
from analysis.ml_signals import (
    MIN_CALIBRATION_ROWS,
    _XGB_CACHE,
    clear_ml_cache,
    train_xgboost_signal,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _last_cached_model():
    """Return the most recently inserted model from the XGB cache.

    The cache is a dict; we only insert one model per test run, so taking
    any value works as long as the cache was populated.
    """
    if not _XGB_CACHE:
        return None
    # Pick any entry — typically the only one in a single-call test.
    model, _val_acc, _train_acc = next(iter(_XGB_CACHE.values()))
    return model


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_calibration_applied_with_enough_val_samples(ohlcv_factory):
    """With ~600 rows of synthetic OHLCV, the 80/20 split gives ~120 val
    samples — above MIN_CALIBRATION_ROWS — so the cached model should be a
    CalibratedClassifierCV instance (not the raw XGBClassifier)."""
    clear_ml_cache()
    df = ohlcv_factory(rows=600, seed=7)

    result = train_xgboost_signal(df)
    assert result is not None, "train_xgboost_signal returned None on healthy synthetic data"
    assert 0.0 <= result.value <= 1.0

    cached = _last_cached_model()
    assert cached is not None, "cache should have been populated"
    assert isinstance(cached, sk_cal.CalibratedClassifierCV), (
        f"Expected CalibratedClassifierCV with {MIN_CALIBRATION_ROWS}+ val samples, "
        f"got {type(cached).__name__}"
    )


def test_calibration_falls_back_when_val_too_small(ohlcv_factory, monkeypatch):
    """When the validation slice is smaller than MIN_CALIBRATION_ROWS, the
    cached model should be the raw XGBClassifier (graceful fallback, no
    crash). We bump MIN_CALIBRATION_ROWS instead of shrinking the dataset
    so we don't fight the feature-lookback NaN dropouts at small row
    counts (training itself has its own min-rows gate).
    """
    clear_ml_cache()
    # Make the calibration threshold artificially high so any normal-sized
    # synthetic series triggers the fallback path.
    monkeypatch.setattr(ml_signals, "MIN_CALIBRATION_ROWS", 10_000)
    df = ohlcv_factory(rows=500, seed=11)

    result = train_xgboost_signal(df)
    assert result is not None, "Expected training to succeed with 500 rows"

    cached = _last_cached_model()
    assert cached is not None
    assert isinstance(cached, xgb.XGBClassifier), (
        f"Expected raw XGBClassifier with calibration disabled by threshold, "
        f"got {type(cached).__name__}"
    )


def test_signal_contract_unchanged(ohlcv_factory):
    """Public contract: train_xgboost_signal returns a TechnicalSignal with
    a probability ``value`` in [0,1] and a non-empty description. The
    calibration is internal and shouldn't break callers."""
    clear_ml_cache()
    df = ohlcv_factory(rows=500, seed=3)

    result = train_xgboost_signal(df)
    assert result is not None
    assert result.indicator == "XGBoost ML"
    assert 0.0 <= result.value <= 1.0
    assert result.signal in {"BUY", "SELL", "HOLD"}
    assert result.strength in {"STRONG", "MODERATE", "WEAK"}
    assert result.description  # non-empty


def test_calibration_does_not_worsen_brier_score(ohlcv_factory, monkeypatch):
    """Brier score (mean squared error of predict_proba vs label) on an OOS
    chunk of a longer synthetic series. Calibrated Brier should be ≤ raw
    Brier within a small tolerance — isotonic should improve or match.

    This is a sanity check, not a tight bound: on a noisy synthetic series
    the improvement can be small (or zero) and the test tolerates that.
    """
    # We need direct access to the raw model and the calibrated model.
    # Easiest path: re-run the relevant chunk of train_xgboost_signal
    # manually so we can compare. Reusing the public API only exposes one
    # of the two, depending on whether calibration was applied.
    from analysis.ml_signals import (
        _build_features,
        _build_labels,
        MIN_TRAINING_ROWS,
    )

    df = ohlcv_factory(rows=800, seed=17, drift=0.001, vol=0.012)
    features = _build_features(df)
    labels = _build_labels(df)
    combined = pd.concat([features, labels.rename("label")], axis=1).dropna()
    if len(combined) < MIN_TRAINING_ROWS + 100:
        pytest.skip("Not enough labelled rows for the Brier-score comparison")

    # Split: 70% train / 15% calib / 15% test (held out from both).
    n = len(combined)
    n_tr = int(n * 0.70)
    n_cal = int(n * 0.15)
    cols = [c for c in features.columns if c in combined.columns]

    X = combined[cols].values.astype(np.float32)
    y = combined["label"].values.astype(int)
    X_tr, y_tr = X[:n_tr], y[:n_tr]
    X_cal, y_cal = X[n_tr : n_tr + n_cal], y[n_tr : n_tr + n_cal]
    X_te, y_te = X[n_tr + n_cal :], y[n_tr + n_cal :]

    if len(np.unique(y_cal)) < 2 or len(np.unique(y_te)) < 2:
        pytest.skip("Synthetic split happened to be one-class; re-seed if persistent")

    raw = xgb.XGBClassifier(
        n_estimators=120,
        max_depth=3,
        learning_rate=0.05,
        random_state=42,
        eval_metric="logloss",
        verbosity=0,
    )
    raw.fit(X_tr, y_tr)

    cal = sk_cal.CalibratedClassifierCV(estimator=raw, cv="prefit", method="isotonic")
    cal.fit(X_cal, y_cal)

    p_raw = raw.predict_proba(X_te)[:, 1]
    p_cal = cal.predict_proba(X_te)[:, 1]
    brier_raw = float(np.mean((p_raw - y_te) ** 2))
    brier_cal = float(np.mean((p_cal - y_te) ** 2))

    # Calibration should not make things meaningfully worse. A tiny
    # tolerance lets noise pass; meaningful regression fails the test.
    assert brier_cal <= brier_raw + 0.02, (
        f"Calibrated Brier {brier_cal:.4f} > raw {brier_raw:.4f} + 0.02 tolerance"
    )


def test_cache_hit_after_calibration(ohlcv_factory):
    """A second call on the same DataFrame should hit the cache and return
    the same probability — verifying the calibrated model is what got
    cached and is reused (not re-trained from scratch)."""
    clear_ml_cache()
    df = ohlcv_factory(rows=500, seed=23)

    first = train_xgboost_signal(df)
    assert first is not None
    cached_after_first = _last_cached_model()

    second = train_xgboost_signal(df)
    assert second is not None
    cached_after_second = _last_cached_model()

    # Cache key is deterministic on the same df → same object instance.
    assert cached_after_first is cached_after_second
    assert abs(first.value - second.value) < 1e-9


def test_calibration_skipped_when_sklearn_missing(ohlcv_factory, monkeypatch):
    """Simulate the optional-dep failure: with _CALIBRATION_OK=False, the
    cached model must be the raw XGBClassifier and the function still
    returns a valid signal."""
    clear_ml_cache()
    monkeypatch.setattr(ml_signals, "_CALIBRATION_OK", False)

    df = ohlcv_factory(rows=600, seed=29)
    result = train_xgboost_signal(df)
    assert result is not None

    cached = _last_cached_model()
    assert isinstance(cached, xgb.XGBClassifier), (
        f"With _CALIBRATION_OK=False, expected raw model; got {type(cached).__name__}"
    )
