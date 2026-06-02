"""
Tests for ``scripts.regime_attribution`` — post-hoc attribution analyzer for
T-régimen-2 (Sprint 2 fase 2).

What's pinned down:

1. Pure analytical primitives (equity → daily returns → annualised Sharpe →
   slicing by régime → ΔSharpe table → per-feature verdict).
2. End-to-end ``attribution_for_window`` over synthetic data with KNOWN
   ground-truth régimes — verifies the slicing routes returns into the right
   buckets and that an ablation that helps in one régime / hurts in another
   gets a ``switch`` verdict.
3. IO: ``load_variant_equity`` reads the CSV layout the patched harness
   produces, raises useful errors when the layout is missing.

These tests are runnable in the project's sandbox (no pytest dependency); use
the same stub-pytest harness as ``tests/test_regime_detector.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# scripts/ is sibling to tests/; add repo root so import works regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.regime_attribution import (
    NON_WARMUP_REGIMES,
    RegimeSharpe,
    annualised_sharpe,
    attribution_for_window,
    build_proxy_returns,
    compute_variant_regime_sharpe,
    delta_sharpe_table,
    equity_to_daily_returns,
    format_table,
    load_variant_equity,
    slice_returns_by_regime,
    verdict_for_feature,
)
from analysis.regime_detector import (
    REGIME_BEAR,
    REGIME_BULL_QUIET,
    REGIME_BULL_VOLATILE,
    REGIME_LATERAL,
    REGIME_WARMUP,
)


# ── Builders ────────────────────────────────────────────────────────────────


def _make_equity(returns: np.ndarray, start: str = "2024-01-02",
                 initial: float = 50_000.0) -> pd.Series:
    """Build an equity curve from a daily-returns vector."""
    idx = pd.bdate_range(start=start, periods=len(returns) + 1)
    # equity_0 = initial, then compounded
    eq = np.empty(len(returns) + 1)
    eq[0] = initial
    eq[1:] = initial * np.cumprod(1.0 + returns)
    return pd.Series(eq, index=idx, name="equity")


def _gauss(n: int, loc: float, scale: float, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(loc=loc, scale=scale, size=n)


# ── Primitives ──────────────────────────────────────────────────────────────


class TestPrimitives:
    def test_equity_to_daily_returns_drops_first_nan(self):
        eq = pd.Series([100, 110, 121], index=pd.bdate_range("2024-01-02", periods=3))
        r = equity_to_daily_returns(eq)
        assert len(r) == 2
        # 110/100-1 = 0.10, 121/110-1 = 0.10
        assert pytest.approx(r.iloc[0], rel=1e-9) == 0.10
        assert pytest.approx(r.iloc[1], rel=1e-9) == 0.10

    def test_annualised_sharpe_with_known_values(self):
        # Constant positive return → sharpe = inf (std=0). We return NaN.
        r = pd.Series([0.001] * 60)
        assert np.isnan(annualised_sharpe(r))

    def test_annualised_sharpe_handles_short_series(self):
        assert np.isnan(annualised_sharpe(pd.Series([0.01])))
        assert np.isnan(annualised_sharpe(pd.Series([], dtype=float)))

    def test_annualised_sharpe_sign(self):
        rng = np.random.default_rng(0)
        # Positive drift → positive sharpe
        r_up = pd.Series(rng.normal(0.001, 0.01, 200))
        s_up = annualised_sharpe(r_up)
        assert s_up > 0
        # Negative drift → negative sharpe
        r_dn = pd.Series(rng.normal(-0.001, 0.01, 200))
        s_dn = annualised_sharpe(r_dn)
        assert s_dn < 0


class TestSlicing:
    def test_slice_returns_groups_by_regime(self):
        # 4-day series, each day with a distinct régime label.
        idx = pd.bdate_range("2024-01-02", periods=4)
        rets = pd.Series([0.01, -0.02, 0.005, -0.003], index=idx)
        regs = pd.Series([REGIME_BULL_QUIET, REGIME_BEAR, REGIME_LATERAL,
                          REGIME_BULL_VOLATILE], index=idx)
        sliced = slice_returns_by_regime(rets, regs)
        assert sliced[REGIME_BULL_QUIET].iloc[0] == pytest.approx(0.01)
        assert sliced[REGIME_BEAR].iloc[0] == pytest.approx(-0.02)
        assert sliced[REGIME_LATERAL].iloc[0] == pytest.approx(0.005)
        assert sliced[REGIME_BULL_VOLATILE].iloc[0] == pytest.approx(-0.003)
        # Each bucket has exactly one observation; the other three are empty.
        for r in NON_WARMUP_REGIMES:
            assert len(sliced[r]) == 1

    def test_warmup_bars_excluded(self):
        idx = pd.bdate_range("2024-01-02", periods=3)
        rets = pd.Series([0.01, 0.01, 0.01], index=idx)
        regs = pd.Series([REGIME_WARMUP, REGIME_BULL_QUIET, REGIME_WARMUP], index=idx)
        sliced = slice_returns_by_regime(rets, regs)
        # Only the middle bar should make it.
        assert len(sliced[REGIME_BULL_QUIET]) == 1
        assert sum(len(v) for v in sliced.values()) == 1


# ── Per-variant Sharpe ──────────────────────────────────────────────────────


class TestComputeVariantRegimeSharpe:
    def test_sharpe_per_regime_matches_manual(self):
        # Mix 100 bars of bull (high positive Sharpe) + 100 bars of bear (high
        # negative Sharpe), label each segment with its régime.
        bull = _gauss(100, 0.002, 0.01, seed=1)
        bear = _gauss(100, -0.002, 0.01, seed=2)
        rets = np.concatenate([bull, bear])
        eq = _make_equity(rets)
        idx = eq.index
        regs = pd.Series(index=idx, dtype="object")
        # First bar of eq has no return, so regimes for returns start at idx[1]
        # Easiest: set whole index, but slicing uses return index.
        regs.iloc[: 101] = REGIME_BULL_QUIET
        regs.iloc[101:] = REGIME_BEAR

        out = compute_variant_regime_sharpe(eq, regs, variant_name="v")
        # bull_quiet should be strongly positive, bear strongly negative.
        assert out.sharpe_by_regime[REGIME_BULL_QUIET] > 1.0
        assert out.sharpe_by_regime[REGIME_BEAR] < -1.0
        # The other two buckets had zero bars → NaN.
        for empty in (REGIME_BULL_VOLATILE, REGIME_LATERAL):
            assert np.isnan(out.sharpe_by_regime[empty])
            assert out.n_by_regime[empty] == 0
        # Overall should be near zero (cancellation).
        assert abs(out.sharpe_overall) < 1.5


# ── ΔSharpe table & verdicts ────────────────────────────────────────────────


class TestDeltaSharpeTable:
    def _make_three_variants(self, base_sharpe, ablation_sharpe):
        return {
            "baseline": RegimeSharpe(
                variant="baseline",
                sharpe_by_regime=dict(base_sharpe),
                n_by_regime={r: 50 for r in NON_WARMUP_REGIMES},
                sharpe_overall=float(np.nanmean(list(base_sharpe.values()))),
                n_overall=200,
            ),
            "no_feature_x": RegimeSharpe(
                variant="no_feature_x",
                sharpe_by_regime=dict(ablation_sharpe),
                n_by_regime={r: 50 for r in NON_WARMUP_REGIMES},
                sharpe_overall=float(np.nanmean(list(ablation_sharpe.values()))),
                n_overall=200,
            ),
        }

    def test_baseline_row_is_all_zero(self):
        d = self._make_three_variants(
            {REGIME_BULL_QUIET: 1.0, REGIME_BULL_VOLATILE: 0.5,
             REGIME_LATERAL: 0.0, REGIME_BEAR: -1.0},
            {REGIME_BULL_QUIET: 1.2, REGIME_BULL_VOLATILE: 0.4,
             REGIME_LATERAL: 0.1, REGIME_BEAR: -0.8},
        )
        delta = delta_sharpe_table(d)
        for reg in NON_WARMUP_REGIMES:
            assert delta.loc["baseline", reg] == pytest.approx(0.0)

    def test_delta_signs_correct(self):
        # Ablation is *better* in bull (Δ > 0 → feature hurts there)
        # and *worse* in bear (Δ < 0 → feature helps there).
        d = self._make_three_variants(
            {REGIME_BULL_QUIET: 1.0, REGIME_BULL_VOLATILE: 0.5,
             REGIME_LATERAL: 0.0, REGIME_BEAR: -1.0},
            {REGIME_BULL_QUIET: 1.5, REGIME_BULL_VOLATILE: 0.7,
             REGIME_LATERAL: 0.0, REGIME_BEAR: -1.5},
        )
        delta = delta_sharpe_table(d)
        assert delta.loc["no_feature_x", REGIME_BULL_QUIET] == pytest.approx(0.5)
        assert delta.loc["no_feature_x", REGIME_BEAR] == pytest.approx(-0.5)


class TestVerdict:
    def _row(self, **vals):
        # Fill missing regimes with NaN so dropna behaves naturally.
        defaults = {r: float("nan") for r in NON_WARMUP_REGIMES}
        defaults.update(vals)
        return pd.Series(defaults)

    def test_kill_all_when_all_deltas_positive(self):
        row = self._row(bull_quiet=0.3, bull_volatile=0.2, lateral=0.1, bear=0.4)
        assert verdict_for_feature(row) == "kill_all"

    def test_keep_all_when_all_deltas_negative(self):
        row = self._row(bull_quiet=-0.3, bull_volatile=-0.2, lateral=-0.1, bear=-0.4)
        assert verdict_for_feature(row) == "keep_all"

    def test_switch_when_signs_disagree(self):
        # Feature helps in bull (Δ < 0) but hurts in bear (Δ > 0)
        row = self._row(bull_quiet=-0.4, lateral=0.0, bear=+0.3)
        assert verdict_for_feature(row) == "switch"

    def test_no_effect_when_all_inside_tolerance(self):
        row = self._row(bull_quiet=0.02, lateral=-0.01, bear=0.03)
        assert verdict_for_feature(row, tolerance=0.05) == "no_effect"

    def test_undetermined_when_all_nan(self):
        assert verdict_for_feature(self._row()) == "undetermined"


# ── End-to-end with synthetic harness output ────────────────────────────────


def _write_harness_layout(tmp_dir: Path, variants: dict[str, pd.Series]) -> Path:
    """Mirror the layout that ``HarnessRunner.save_results`` produces."""
    window = tmp_dir / "win"
    results = window / "results"
    results.mkdir(parents=True)
    for name, eq in variants.items():
        df = pd.DataFrame({"equity": eq.values}, index=eq.index)
        df.index.name = "date"
        df.to_csv(results / f"{name}.equity.csv")
        # Also write the JSON the runner writes (we don't read it, but it
        # documents the shape).
        (results / f"{name}.json").write_text(json.dumps({"config": {"name": name}}))
    return window


class TestLoadVariantEquity:
    def test_loads_all_equity_csvs(self, tmp_path):
        v = {
            "baseline": _make_equity(_gauss(50, 0.001, 0.01, seed=1)),
            "no_hmm": _make_equity(_gauss(50, 0.002, 0.01, seed=2)),
        }
        window = _write_harness_layout(tmp_path, v)
        loaded = load_variant_equity(window)
        assert set(loaded.keys()) == {"baseline", "no_hmm"}
        for name in loaded:
            assert isinstance(loaded[name], pd.Series)
            assert loaded[name].index.is_monotonic_increasing
            assert len(loaded[name]) == 51  # initial + 50 return bars

    def test_raises_if_no_equity_csvs(self, tmp_path):
        window = tmp_path / "win"
        (window / "results").mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="re-run"):
            load_variant_equity(window)

    def test_raises_if_no_results_dir(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="no results"):
            load_variant_equity(tmp_path / "missing")


class TestEndToEnd:
    def test_attribution_routes_returns_by_regime(self, tmp_path):
        # Build a baseline + an ablation where the ablation does BETTER in
        # bull and WORSE in bear → switch verdict expected.
        rng = np.random.default_rng(123)
        # ~250 bull bars then ~250 bear bars; long enough to give detector
        # enough material in both régimes
        bull_base = rng.normal(0.0015, 0.006, 250)
        bear_base = rng.normal(-0.005, 0.020, 250)
        bull_abl = bull_base + 0.0010  # ablation outperforms in bull
        bear_abl = bear_base - 0.0010  # ablation underperforms in bear
        baseline_rets = np.concatenate([bull_base, bear_base])
        ablation_rets = np.concatenate([bull_abl, bear_abl])
        variants = {
            "baseline": _make_equity(baseline_rets),
            "no_feature_x": _make_equity(ablation_rets),
        }
        window = _write_harness_layout(tmp_path, variants)
        report = attribution_for_window(window)
        # Sanity: régime distribution shows both bull and bear represented.
        dist = report["regime_distribution"]
        assert REGIME_BULL_QUIET in dist or REGIME_BULL_VOLATILE in dist
        assert REGIME_BEAR in dist
        # The ΔSharpe in bear and bull buckets should disagree in sign
        delta = report["delta_sharpe"]["no_feature_x"]
        bull_keys = [REGIME_BULL_QUIET, REGIME_BULL_VOLATILE]
        bull_delta_max = max([delta[k] for k in bull_keys if delta[k] == delta[k]] or [0.0])
        bear_delta = delta.get(REGIME_BEAR, float("nan"))
        # Expect ablation_in_bull better → Δ > 0 in some bull bucket
        # Expect ablation_in_bear worse → Δ < 0 in bear
        assert bull_delta_max > 0.0
        assert bear_delta < 0.0
        # Verdict should be switch
        assert report["verdicts"]["no_feature_x"] == "switch"

    def test_format_table_is_string(self, tmp_path):
        # Run a tiny end-to-end to make sure format_table doesn't crash.
        v = {
            "baseline": _make_equity(_gauss(200, 0.001, 0.01, seed=1)),
            "no_x": _make_equity(_gauss(200, 0.001, 0.01, seed=2)),
        }
        window = _write_harness_layout(tmp_path, v)
        report = attribution_for_window(window)
        text = format_table(report)
        assert isinstance(text, str)
        assert "Window:" in text
        assert "ΔSharpe" in text


# ── Proxy fallback ──────────────────────────────────────────────────────────


class TestProxyFallback:
    def test_fallback_proxy_uses_equal_weight_average(self):
        idx = pd.bdate_range("2024-01-02", periods=10)
        a = pd.Series(np.linspace(100, 110, 10), index=idx)
        b = pd.Series(np.linspace(100, 120, 10), index=idx)
        proxy = build_proxy_returns({"a": a, "b": b})
        # 9 daily returns expected (pct_change drops the first)
        assert len(proxy) == 9
        # Both inputs are pure trend → daily returns are all positive.
        assert (proxy > 0).all()

    def test_explicit_proxy_overrides_fallback(self):
        idx = pd.bdate_range("2024-01-02", periods=5)
        proxy_series = pd.Series([100.0, 105.0, 110.25, 115.76, 121.55], index=idx)
        a = pd.Series([100.0] * 5, index=idx)  # flat — would give zero returns
        result = build_proxy_returns({"a": a}, proxy_series=proxy_series)
        # Returns should come from proxy_series (~5% daily), NOT from `a` (flat).
        assert result.iloc[0] == pytest.approx(0.05, rel=1e-3)
