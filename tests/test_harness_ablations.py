"""
Sprint-1 ablation divergence tests.

The Sprint-1 toggle wiring tests (``test_toggle_wiring.py``) prove that each
toggle is read at the right call site. These tests close the loop: they prove
the runner-level harness actually produces DIFFERENT metrics when a toggle is
flipped, which is the property Sprint 2 attribution depends on.

Three layers covered:

  1. ``portfolio_backtest`` hook — vol_overlay_fn changes trade outcomes
     when active. (correlation_filter_fn was removed in Sprint 3.)
  2. ``signal_from_analyze_stacked`` — signal output tracks ml_probability,
     so flipping any of hmm/xgb/stacking changes the signal stream.
  3. ``HarnessRunner`` end-to-end — flipping a portfolio-side toggle inside
     ``run_experiment`` produces different metrics for the same signal_fn.

The fixtures use synthetic deterministic data so the tests don't depend on
yfinance, the historical cache, or the trained ML models. Real ablation
results live in ``data/harness_results/`` after running ``scripts/harness.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.backtest import signal_from_analyze_stacked
from analysis.harness import ExperimentConfig, HarnessRunner
from analysis.portfolio_backtest import (
    AllocationMode,
    portfolio_backtest,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _synthetic_frame(rows: int, seed: int) -> pd.DataFrame:
    """Synthetic OHLCV with a stable trend + noise. ~250 rows = 1 calendar year."""
    rng = np.random.default_rng(seed)
    drift = 0.0008  # ~20% annualised
    noise = rng.normal(0.0, 0.012, rows)
    closes = 100.0 * np.cumprod(1.0 + drift + noise)
    df = pd.DataFrame(
        {
            "Open": closes * (1 - 0.001),
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": rng.integers(1_000_000, 5_000_000, rows),
        },
        index=pd.date_range("2024-01-02", periods=rows, freq="B"),
    )
    return df


@pytest.fixture
def synthetic_universe():
    """Four tickers, 300 daily bars each, aligned indices, different seeds."""
    rows = 300
    return {
        "AAA": _synthetic_frame(rows, seed=1),
        "BBB": _synthetic_frame(rows, seed=2),
        "CCC": _synthetic_frame(rows, seed=3),
        "DDD": _synthetic_frame(rows, seed=4),
    }


def _alternating_buy_signal_fn(buy_every: int = 10):
    """Signal_fn that says BUY every ``buy_every`` bars, HOLD otherwise.
    Deterministic and independent of the toggles — used to isolate the hooks."""
    counter = {"n": 0}

    def _fn(df_slice: pd.DataFrame) -> str:
        counter["n"] += 1
        return "BUY" if counter["n"] % buy_every == 1 else "HOLD"

    return _fn


# ── Layer 1: portfolio_backtest hooks ─────────────────────────────────────────


# ``test_correlation_filter_hook_reduces_trades`` removed in Sprint 3 along
# with the ``correlation_filter_fn`` parameter on portfolio_backtest. The pure
# math (``gates.select_uncorrelated_picks``) is still covered by
# ``tests/test_correlation_gate.py``.


def test_vol_overlay_hook_shrinks_exposure(synthetic_universe):
    """A vol_overlay_fn that returns factor=0.5 scales target weights by half,
    so the final equity must differ from the unscaled baseline."""
    tickers = list(synthetic_universe.keys())

    baseline = portfolio_backtest(
        signal_fn=lambda df: "BUY",
        tickers=tickers,
        data=synthetic_universe,
        allocation_mode=AllocationMode.EQUAL_WEIGHT,
        max_positions=4,
        warmup=50,
        step=5,
    )
    assert baseline is not None

    scaled = portfolio_backtest(
        signal_fn=lambda df: "BUY",
        tickers=tickers,
        data=synthetic_universe,
        allocation_mode=AllocationMode.EQUAL_WEIGHT,
        max_positions=4,
        warmup=50,
        step=5,
        vol_overlay_fn=lambda weights, rets: 0.5,
    )
    assert scaled is not None

    # Half-sized positions on a positive-trend synthetic must yield a different
    # final equity (typically smaller absolute P&L magnitude).
    assert abs(scaled.final_equity - baseline.final_equity) > 1.0, (
        f"vol_overlay 0.5 should shift equity vs baseline ({baseline.final_equity}); got {scaled.final_equity}"
    )


def test_vol_overlay_factor_one_is_noop(synthetic_universe):
    """A vol_overlay_fn returning 1.0 must not change the backtest result."""
    tickers = list(synthetic_universe.keys())

    baseline = portfolio_backtest(
        signal_fn=lambda df: "BUY",
        tickers=tickers,
        data=synthetic_universe,
        allocation_mode=AllocationMode.EQUAL_WEIGHT,
        max_positions=4,
        warmup=50,
        step=5,
    )
    no_op = portfolio_backtest(
        signal_fn=lambda df: "BUY",
        tickers=tickers,
        data=synthetic_universe,
        allocation_mode=AllocationMode.EQUAL_WEIGHT,
        max_positions=4,
        warmup=50,
        step=5,
        vol_overlay_fn=lambda weights, rets: 1.0,
    )
    assert baseline is not None and no_op is not None
    assert abs(baseline.final_equity - no_op.final_equity) < 1e-6


# ── Layer 2: signal_from_analyze_stacked threshold logic ──────────────────────


def test_signal_from_analyze_stacked_uses_probability_when_available():
    """The factory returns BUY/SELL/HOLD based on ml_probability vs thresholds.

    The factory imports ``analyze_stacked`` lazily (at factory-call time) and
    captures it in the closure — so we must build ``fn`` INSIDE the patch
    context for the mock to take effect.
    """
    fake_result = MagicMock()
    fake_result.overall_signal = "HOLD"  # would say HOLD without probability
    df = pd.DataFrame({"Close": np.linspace(100, 110, 60)})

    fake_result.ml_probability = 0.70
    with patch("analysis.technical.analyze_stacked", return_value=fake_result):
        fn = signal_from_analyze_stacked(buy_threshold=0.55, sell_threshold=0.45)
        assert fn(df) == "BUY"

    fake_result.ml_probability = 0.30
    with patch("analysis.technical.analyze_stacked", return_value=fake_result):
        fn = signal_from_analyze_stacked(buy_threshold=0.55, sell_threshold=0.45)
        assert fn(df) == "SELL"

    fake_result.ml_probability = 0.50  # neutral band
    with patch("analysis.technical.analyze_stacked", return_value=fake_result):
        fn = signal_from_analyze_stacked(buy_threshold=0.55, sell_threshold=0.45)
        assert fn(df) == "HOLD"


def test_signal_from_analyze_stacked_falls_back_to_overall_signal():
    """When ml_probability is None, the factory uses overall_signal."""
    fake_result = MagicMock()
    fake_result.ml_probability = None
    fake_result.overall_signal = "BUY"
    df = pd.DataFrame({"Close": np.linspace(100, 110, 60)})

    with patch("analysis.technical.analyze_stacked", return_value=fake_result):
        fn = signal_from_analyze_stacked()
        assert fn(df) == "BUY"


def test_signal_from_analyze_stacked_none_returns_hold():
    """analyze_stacked -> None (too few rows etc.) must return HOLD."""
    df = pd.DataFrame({"Close": np.linspace(100, 110, 60)})
    with patch("analysis.technical.analyze_stacked", return_value=None):
        fn = signal_from_analyze_stacked()
        assert fn(df) == "HOLD"


# ── Layer 3: HarnessRunner end-to-end divergence ──────────────────────────────


# ``test_runner_correlation_gate_ablation_diverges`` removed in Sprint 3 —
# the toggle was eliminated. See docs/sprint2_kill_criteria.md (Enmienda 2).


def test_runner_vol_overlay_ablation_diverges(synthetic_universe):
    """Same divergence contract for the vol_overlay toggle: ON with a very
    tight target should shrink exposure, OFF should leave it alone.
    """
    tickers = list(synthetic_universe.keys())
    runner = HarnessRunner(
        data=synthetic_universe,
        tickers=tickers,
        initial_capital=50_000.0,
        warmup=50,
        step=5,
        verbose=False,
    )
    signal_fn = lambda df: "BUY"

    # Force a very tight vol target so the overlay engages aggressively
    from config.settings_manager import settings as _real

    original_get = _real.get

    def patched_get(key, fallback=None):
        if key == "vol_target_portfolio_annual":
            return 0.001  # essentially 0.1% — always engages
        return original_get(key, fallback)

    snap = runner.snapshot_toggles()
    try:
        with patch.object(_real, "get", side_effect=patched_get):
            on_cfg = ExperimentConfig(
                name="overlay_on",
                hmm_enabled=False,
                stacking_enabled=False,
                xgb_signal_enabled=False,
                vol_overlay_enabled=True,
            )
            off_cfg = ExperimentConfig(
                name="overlay_off",
                hmm_enabled=False,
                stacking_enabled=False,
                xgb_signal_enabled=False,
                vol_overlay_enabled=False,
            )
            m_on = runner.run_experiment(on_cfg, signal_fn)
            m_off = runner.run_experiment(off_cfg, signal_fn)
    finally:
        runner.restore_toggles(snap)

    assert abs(m_on.period_return - m_off.period_return) > 0.01, (
        f"vol_overlay ablation should produce DIFFERENT period_return; "
        f"got on={m_on.period_return} off={m_off.period_return}"
    )


def test_runner_uses_singleton_settings():
    """Regression guard: ``HarnessRunner.settings_manager`` must be the same
    object as ``config.settings_manager.settings`` so that ``set()`` is visible
    to ``_toggle()`` in analysis.technical."""
    from config.settings_manager import settings as singleton

    runner = HarnessRunner(
        data={"AAA": _synthetic_frame(60, seed=1)},
        tickers=["AAA"],
    )
    assert runner.settings_manager is singleton, (
        "Runner must share the singleton so toggle writes are visible to readers."
    )
