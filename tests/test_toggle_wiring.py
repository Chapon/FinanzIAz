"""
Sprint-1 toggle wiring tests.

Verifies that the five validation-stack toggles actually short-circuit their
target code paths in the engine. Each toggle has two tests:

  * default ON preserves current behaviour (functions are called)
  * OFF bypasses the corresponding code path (functions are NOT called)

The toggles, sites and bypass mechanisms:

  hmm_enabled              technical.analyze              hmm_on guard
  xgb_signal_enabled       technical.analyze              xgb_on guard
  stacking_enabled         technical.analyze_stacked      early return
  vol_overlay_enabled      strategies._portfolio_vol_target  returns 0.0

  (correlation_gate_enabled removed in Sprint 3 — see docs/sprint2_kill_criteria.md.)

These tests are intentionally cheap (no DB, no scan loop) -- they prove the
toggle is read at the right site, not that the resulting backtest diverges.
The divergence check lives in scripts/harness.py ablations.

The two strategies-side toggles are tested via in-test replicas of the helpers
rather than by importing paper_trading.strategies directly, because that module
pulls SQLAlchemy through database.models and the sandbox has no SQLAlchemy.
The replicas MUST stay in sync with the real helpers -- if you change one,
change both.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_df(rows: int = 250, seed: int = 7) -> pd.DataFrame:
    """Synthetic OHLCV with enough rows to exercise every indicator branch."""
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(0.05, 1.0, rows))
    closes = np.clip(closes, 1.0, None)
    df = pd.DataFrame(
        {
            "Open": closes * (1 + rng.normal(0, 0.005, rows)),
            "High": closes * (1 + np.abs(rng.normal(0, 0.01, rows))),
            "Low": closes * (1 - np.abs(rng.normal(0, 0.01, rows))),
            "Close": closes,
            "Volume": rng.integers(1_000_000, 5_000_000, rows),
        },
        index=pd.date_range("2024-01-01", periods=rows, freq="B"),
    )
    return df


def _toggle_settings(overrides):
    """Patch settings.get() so the listed overrides take effect; other keys
    fall through to the real settings store."""
    from config.settings_manager import settings as _real

    def _patched_get(key, fallback=None):
        if key in overrides:
            return overrides[key]
        return _real.get(key, fallback)

    return patch.object(_real, "get", side_effect=_patched_get)


# ---------------------------------------------------------------------------
# 1. hmm_enabled
# ---------------------------------------------------------------------------


def test_hmm_enabled_default_calls_hmm():
    """Default ON: detect_market_regime_hmm + train_hmm_signal are invoked."""
    from analysis import technical

    df = _make_df()
    with (
        patch("analysis.ml_signals.detect_market_regime_hmm", return_value=None) as m_regime,
        patch("analysis.ml_signals.train_hmm_signal", return_value=None) as m_signal,
    ):
        technical.analyze("TEST", df, enable_xgboost=True)
        assert m_regime.called, "HMM regime detector must be called when hmm_enabled=True"
        assert m_signal.called, "HMM forward signal must be called when hmm_enabled=True"


def test_hmm_enabled_off_skips_hmm():
    """OFF: neither HMM site is called; rule-based regime fallback is used."""
    from analysis import technical

    df = _make_df()
    with (
        _toggle_settings({"hmm_enabled": False}),
        patch("analysis.ml_signals.detect_market_regime_hmm", return_value=None) as m_regime,
        patch("analysis.ml_signals.train_hmm_signal", return_value=None) as m_signal,
        patch("analysis.ml_signals.detect_market_regime", return_value=None) as m_rule,
    ):
        technical.analyze("TEST", df, enable_xgboost=True)
        assert not m_regime.called, "HMM regime detector must NOT be called when hmm_enabled=False"
        assert not m_signal.called, "HMM forward signal must NOT be called when hmm_enabled=False"
        assert m_rule.called, "Rule-based regime fallback must be used when HMM is off"


# ---------------------------------------------------------------------------
# 2. xgb_signal_enabled
# ---------------------------------------------------------------------------


def test_xgb_signal_enabled_default_calls_xgb():
    """Default ON: train_xgboost_signal is invoked once."""
    from analysis import technical

    df = _make_df()
    with patch("analysis.ml_signals.train_xgboost_signal", return_value=None) as m_xgb:
        technical.analyze("TEST", df, enable_xgboost=True)
        assert m_xgb.called, "XGBoost signal must be trained when xgb_signal_enabled=True"


def test_xgb_signal_enabled_off_skips_xgb():
    """OFF: train_xgboost_signal is NOT invoked."""
    from analysis import technical

    df = _make_df()
    with (
        _toggle_settings({"xgb_signal_enabled": False}),
        patch("analysis.ml_signals.train_xgboost_signal", return_value=None) as m_xgb,
    ):
        technical.analyze("TEST", df, enable_xgboost=True)
        assert not m_xgb.called, "XGBoost must NOT be trained when xgb_signal_enabled=False"


# ---------------------------------------------------------------------------
# 3. stacking_enabled
# ---------------------------------------------------------------------------


def test_stacking_enabled_default_attempts_combiner():
    """Default ON: train_stacking_combiner is reached. We patch it to a no-op
    so the test stays fast and independent of sklearn / row counts."""
    from analysis import technical

    df = _make_df()
    with patch("analysis.ml_signals.train_stacking_combiner", return_value=None) as m_stack:
        result = technical.analyze_stacked("TEST", df, enable_xgboost=True)
        assert result is not None
        assert m_stack.called, "Stacking combiner must be attempted when stacking_enabled=True"


def test_stacking_enabled_off_returns_heuristic():
    """OFF: train_stacking_combiner is NOT called; result keeps the heuristic source."""
    from analysis import technical

    df = _make_df()
    with (
        _toggle_settings({"stacking_enabled": False}),
        patch("analysis.ml_signals.train_stacking_combiner", return_value=None) as m_stack,
    ):
        result = technical.analyze_stacked("TEST", df, enable_xgboost=True)
        assert result is not None
        assert not m_stack.called, "Stacking must NOT be attempted when stacking_enabled=False"
        assert result.ml_probability_source == "heuristic"


# ---------------------------------------------------------------------------
# Sprint 3: ``correlation_gate_enabled`` was removed (config, wiring, ablation
# flag) after attribution found the gate never rejected a candidate in any
# realistic setup. The pure math function ``gates.select_uncorrelated_picks``
# is kept and tested in ``tests/test_correlation_gate.py`` for future reuse.
# The toggle-wiring tests that lived here are intentionally gone.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. vol_overlay_enabled (via in-test replica + gates-level end-to-end)
# ---------------------------------------------------------------------------


def _portfolio_vol_target_replica(settings_get):
    """In-test mirror of paper_trading.strategies._portfolio_vol_target.

    If you change the real helper, update this replica too.
    """
    if not bool(settings_get("vol_overlay_enabled", True)):
        return 0.0
    return float(settings_get("vol_target_portfolio_annual"))


def test_vol_overlay_enabled_default_uses_setting():
    """Default ON: helper returns the real vol_target_portfolio_annual."""
    from config.settings_manager import settings as _real

    real_target = float(_real.get("vol_target_portfolio_annual"))
    assert _portfolio_vol_target_replica(_real.get) == pytest.approx(real_target)


def test_vol_overlay_enabled_off_returns_zero():
    """OFF: helper returns 0.0."""
    from config.settings_manager import settings as _real

    def _patched(key, fallback=None):
        if key == "vol_overlay_enabled":
            return False
        return _real.get(key, fallback)

    assert _portfolio_vol_target_replica(_patched) == 0.0


def test_vol_overlay_off_factor_is_one():
    """End-to-end on the real overlay: vol_target_annual=0 short-circuits to
    factor=1.0 without invoking apply_fn."""
    from paper_trading import gates

    called = []

    def fake_apply(weights, returns_df, vt):
        called.append(("apply", vt))
        return weights, 0.5, 0.5  # would scale heavily if it ran

    result = gates.compute_vol_overlay(
        combined_weights={"AAA": 0.4, "BBB": 0.6},
        returns_df=None,
        vol_target_annual=0.0,
        apply_fn=fake_apply,
    )
    assert result.factor == 1.0
    assert result.sigma is None
    assert called == [], "apply_fn must NOT be called when vol_target_annual <= 0"
