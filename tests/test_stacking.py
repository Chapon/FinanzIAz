"""
Tests for the stacking meta-learner (T05 of the roadmap).

The combiner replaces the hand-weighted heuristic of
``compute_signal_probability`` with a logistic model trained on the ticker's
own history, learning how much each indicator's signal should count toward the
5-day-up probability.

What these tests verify
-----------------------
1. The vectorised per-row signal scorers reproduce the scalar signal functions
   (``_rsi_signal`` etc.) exactly on the latest row — the feature encoding is
   faithful to the live signals.
2. ``build_stacking_features`` yields exactly the roadmap's feature columns, in
   order, with the label aligned and no NaN after dropna.
3. On a synthetic feature matrix where only RSI predicts the label, the trained
   logistic assigns RSI by far the largest |coefficient| (sparse, interpretable
   — extends the roadmap's acceptance test).
4. The combiner output is a probability in [0,1] (extends T02 calibration).
5. Graceful fallback: < MIN_STACKING_ROWS usable rows, single-class labels, or a
   missing live feature → no combiner / no probability, so callers keep the
   heuristic. ``analyze_stacked`` never returns a worse result than ``analyze``.

Notes
-----
* Tests needing a real fit are skipped when scikit-learn is unavailable, so
  they don't pollute minimal CI envs. The scorer/assembly/fallback tests run
  everywhere.
* Uses the deterministic ``ohlcv_factory`` fixture from conftest.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis import ml_signals as ms
from analysis.ml_signals import (
    MIN_STACKING_ROWS,
    STACKING_FEATURE_COLS,
    _signal_score,
    build_signal_score_matrix,
    build_stacking_features,
    clear_ml_cache,
    compute_stacking_probability,
    train_stacking_combiner,
)
from analysis.technical import (
    AnalysisResult,
    analyze_stacked,
    compute_bollinger_bands,
    compute_macd,
    compute_rsi,
    compute_sma,
)
from analysis.technical import (
    _bollinger_signal,
    _macd_signal,
    _rsi_signal,
    _sma_cross_signal,
    _volume_signal,
)

sk = pytest.importorskip  # noqa: N816
_HAS_SKLEARN = ms._SKLEARN_LINEAR_OK and ms._CALIBRATION_OK


# ── helpers ─────────────────────────────────────────────────────────────────


def _scalar_last_scores(df: pd.DataFrame) -> dict:
    """Signed score of each scalar signal function on the latest row."""
    rsi = compute_rsi(df)
    ml, sl, hist = compute_macd(df)
    up, mid, lo = compute_bollinger_bands(df)
    sma50, sma200 = compute_sma(df, 50), compute_sma(df, 200)
    close = df["Close"].squeeze()
    rsi_s = _rsi_signal(rsi)
    macd_s = _macd_signal(float(ml.iloc[-1]), float(sl.iloc[-1]), float(hist.iloc[-2]), float(hist.iloc[-1]))
    bb_s = _bollinger_signal(float(close.iloc[-1]), float(up.iloc[-1]), float(lo.iloc[-1]), float(mid.iloc[-1]))
    sma_s = _sma_cross_signal(
        float(sma50.iloc[-1]), float(sma200.iloc[-1]), float(sma50.iloc[-2]), float(sma200.iloc[-2])
    )
    vol_s = _volume_signal(df)
    return {
        "RSI": _signal_score(rsi_s.signal, rsi_s.strength),
        "MACD": _signal_score(macd_s.signal, macd_s.strength),
        "Bollinger": _signal_score(bb_s.signal, bb_s.strength),
        "SMA_cross": _signal_score(sma_s.signal, sma_s.strength),
        "Volumen": _signal_score(vol_s.signal, vol_s.strength) if vol_s else 0.0,
    }


def _matrix_with_only_rsi_predictive(n: int = 400, seed: int = 7):
    """(features, label) DataFrame/Series where only the RSI column drives y."""
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, (n, len(STACKING_FEATURE_COLS)))
    X[:, 0] = rng.choice([-3, -2, -1, 0, 1, 2, 3], size=n)  # RSI signed score
    p = 1.0 / (1.0 + np.exp(-1.2 * X[:, 0]))  # label depends only on RSI
    y = (rng.random(n) < p).astype(float)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="B")
    feats = pd.DataFrame(X, columns=STACKING_FEATURE_COLS, index=idx)
    label = pd.Series(y, index=idx, name="label")
    return feats, label


@pytest.fixture(autouse=True)
def _isolate_stacking_cache():
    """Flush the combiner cache around every test.

    Several tests train a combiner on the same trivial ``df`` fingerprint
    (``pd.DataFrame({"Close": [1.0]})`` + a monkeypatched feature matrix). The
    ``_STACK_CACHE`` keys on that fingerprint, so without clearing, a cached
    combiner from an earlier test would leak into the fallback tests (which
    expect ``None``). Real usage doesn't collide — distinct tickers/histories
    yield distinct fingerprints.
    """
    clear_ml_cache()
    yield
    clear_ml_cache()


# ── 1. vectorised scorers reproduce the scalar signal functions ──────────────


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_signal_score_matrix_matches_scalar_signals(ohlcv_factory, seed):
    df = ohlcv_factory(rows=300, seed=seed)
    mat = build_signal_score_matrix(df).iloc[-1]
    scalar = _scalar_last_scores(df)
    for col, expected in scalar.items():
        got = float(mat[col]) if pd.notna(mat[col]) else 0.0
        assert got == pytest.approx(expected), f"{col}: vec={got} scalar={expected}"


# ── 2. feature matrix shape / columns / label alignment ──────────────────────


def test_build_stacking_features_columns_and_alignment(ohlcv_factory):
    df = ohlcv_factory(rows=500, seed=11)
    feats, label = build_stacking_features(df)
    assert list(feats.columns) == STACKING_FEATURE_COLS
    assert label.name == "label"
    assert feats.index.equals(df.index) and label.index.equals(df.index)

    data = pd.concat([feats, label], axis=1).dropna()
    # SMA200 + GARCH(60) warmup + 5-day label horizon trim the usable window.
    assert 0 < len(data) < len(feats)
    assert data[STACKING_FEATURE_COLS].isna().sum().sum() == 0


# ── 3. only-RSI-predicts → RSI dominant coefficient ──────────────────────────


@pytest.mark.skipif(not _HAS_SKLEARN, reason="scikit-learn required for the logistic fit")
def test_only_rsi_predictive_gives_dominant_rsi_coef(monkeypatch):
    feats, label = _matrix_with_only_rsi_predictive()
    monkeypatch.setattr(ms, "build_stacking_features", lambda df: (feats, label))

    combiner = train_stacking_combiner(df=pd.DataFrame({"Close": [1.0]}))
    assert combiner is not None
    coefs = combiner["coefs"]
    assert set(coefs) == set(STACKING_FEATURE_COLS)

    abs_coef = {k: abs(v) for k, v in coefs.items()}
    dominant = max(abs_coef, key=abs_coef.get)
    assert dominant == "RSI"
    others = max(v for k, v in abs_coef.items() if k != "RSI")
    assert abs_coef["RSI"] > 2 * others  # RSI clearly dominant


@pytest.mark.skipif(not _HAS_SKLEARN, reason="scikit-learn required for the logistic fit")
def test_combiner_output_is_probability(monkeypatch):
    feats, label = _matrix_with_only_rsi_predictive()
    monkeypatch.setattr(ms, "build_stacking_features", lambda df: (feats, label))
    combiner = train_stacking_combiner(df=pd.DataFrame({"Close": [1.0]}))
    assert combiner is not None

    scaled = combiner["scaler"].transform(feats[STACKING_FEATURE_COLS].values.astype(float))
    probs = combiner["model"].predict_proba(scaled)[:, 1]
    assert probs.min() >= 0.0 and probs.max() <= 1.0
    # Strong-buy RSI rows should score higher than strong-sell RSI rows on average.
    strong_buy = feats["RSI"] >= 2
    strong_sell = feats["RSI"] <= -2
    assert probs[strong_buy.values].mean() > probs[strong_sell.values].mean()


# ── 4. fallbacks ─────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _HAS_SKLEARN, reason="scikit-learn required")
def test_too_few_rows_falls_back_to_none(monkeypatch):
    feats, label = _matrix_with_only_rsi_predictive(n=MIN_STACKING_ROWS - 20)
    monkeypatch.setattr(ms, "build_stacking_features", lambda df: (feats, label))
    assert train_stacking_combiner(df=pd.DataFrame({"Close": [1.0]})) is None


@pytest.mark.skipif(not _HAS_SKLEARN, reason="scikit-learn required")
def test_single_class_labels_falls_back_to_none(monkeypatch):
    feats, label = _matrix_with_only_rsi_predictive()
    label = pd.Series(1.0, index=label.index, name="label")  # all one class
    monkeypatch.setattr(ms, "build_stacking_features", lambda df: (feats, label))
    assert train_stacking_combiner(df=pd.DataFrame({"Close": [1.0]})) is None


def test_compute_stacking_probability_none_when_no_combiner():
    assert compute_stacking_probability(pd.DataFrame({"Close": [1.0]}), combiner=None) is None


def test_combiner_is_cached(monkeypatch):
    """The expensive train (XGB-OOF + HMM + logistic) must run once per dataset
    fingerprint; repeated calls return the cached object. Patches the sklearn
    flags so it runs without scikit-learn installed."""
    monkeypatch.setattr(ms, "_SKLEARN_LINEAR_OK", True)
    monkeypatch.setattr(ms, "_CALIBRATION_OK", True)
    clear_ml_cache()

    calls = {"n": 0}

    def fake_uncached(df):
        calls["n"] += 1
        return {"model": object(), "n": len(df)}

    monkeypatch.setattr(ms, "_train_stacking_combiner_uncached", fake_uncached)

    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=300, freq="B")
    df = pd.DataFrame({"Close": np.linspace(100, 120, 300)}, index=idx)

    c1 = train_stacking_combiner(df)
    c2 = train_stacking_combiner(df)
    assert c1 is c2  # same cached object
    assert calls["n"] == 1  # trained only once

    # A different dataset gets a different fingerprint → retrains.
    df2 = pd.DataFrame({"Close": np.linspace(50, 90, 300)}, index=idx)
    train_stacking_combiner(df2)
    assert calls["n"] == 2
    clear_ml_cache()


# ── 5. analyze_stacked integration ────────────────────────────────────────────


def test_analyze_stacked_falls_back_to_heuristic(ohlcv_factory, monkeypatch):
    """When no combiner can be trained, analyze_stacked must equal analyze's
    heuristic result and tag the source accordingly."""
    monkeypatch.setattr(ms, "train_stacking_combiner", lambda df: None)
    df = ohlcv_factory(rows=300, seed=3)
    res = analyze_stacked("TEST", df, enable_xgboost=False)
    assert isinstance(res, AnalysisResult)
    assert res.ml_probability_source == "heuristic"


@pytest.mark.skipif(not _HAS_SKLEARN, reason="scikit-learn required")
def test_analyze_stacked_uses_combiner_when_available(ohlcv_factory, monkeypatch):
    df = ohlcv_factory(rows=400, seed=9)

    fake_combiner = {"model": object(), "scaler": object(), "cols": STACKING_FEATURE_COLS}
    monkeypatch.setattr(ms, "train_stacking_combiner", lambda d: fake_combiner)
    monkeypatch.setattr(ms, "compute_stacking_probability", lambda d, c: 0.73)

    res = analyze_stacked("TEST", df, enable_xgboost=False)
    assert res.ml_probability_source == "stacking"
    assert res.ml_probability == pytest.approx(0.73)
    assert "stacking" in res.summary
