"""
Tests for T06 conviction × volatility sizing.

Two layers:

1. Pure unit tests of ``_compute_target_weights`` for the new
   ``VOL_TARGET`` and ``KELLY_FRACTIONAL`` modes — the per-name vol target,
   the Kelly edge/variance formula, the per-ticker hard cap + scale-down, the
   "skip ticker without calibrated prob" rule, and dropping negative edge.

2. Integration tests that the two live strategies (``analyze_single`` and
   ``portfolio_engine``) actually wire those modes through, sizing the calmer
   name larger and skipping uncalibrated names under Kelly. ``analyze()`` is
   monkeypatched so these stay fast and deterministic (no indicators / network).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_backtest import AllocationMode, _compute_target_weights
from config.settings_manager import settings


# ── Helpers ───────────────────────────────────────────────────────────────────


def _series(daily_vol: float, rows: int = 120, seed: int = 0, start: float = 100.0) -> pd.DataFrame:
    """A Close-only OHLCV frame whose realised vol scales with ``daily_vol``."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, daily_vol, rows)
    close = start * np.exp(np.cumsum(rets))
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="B")
    return pd.DataFrame({"Close": close}, index=idx)


def _account(**overrides):
    base = dict(
        cash=100_000.0,
        max_positions=5,
        allocation_mode="vol_target",
        fixed_amount=5_000.0,
        commission=0.0,
        drift_threshold=0.25,
        monthly_rebalance=False,
        last_monthly_rebalance=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_analyze(monkeypatch, table: dict[str, tuple[str, float | None]]):
    """Patch analysis.technical.analyze to return canned (signal, ml_prob)."""
    import analysis.technical as technical

    def fake_analyze(ticker, df, *a, **k):
        if ticker not in table:
            return None
        sig, prob = table[ticker]
        return SimpleNamespace(overall_signal=sig, ml_probability=prob)

    monkeypatch.setattr(technical, "analyze", fake_analyze)


# ── Pure: VOL_TARGET ────────────────────────────────────────────────────────


def test_vol_target_more_capital_to_calm():
    """σ=0.40 vs σ=0.10 → the calm name gets exactly 4× the weight."""
    w = _compute_target_weights(
        ["VOL", "CALM"],
        strengths={},
        vols={"VOL": 0.40, "CALM": 0.10},
        mode=AllocationMode.VOL_TARGET,
        vol_target_annual=0.20,
        max_weight=1.0,  # disable the cap so the raw ratio shows through
    )
    assert w["CALM"] > w["VOL"] > 0
    assert abs(w["CALM"] / w["VOL"] - 4.0) < 1e-9


def test_vol_target_cap_binds():
    """With the default 25 % cap, very-low-vol names are clipped, not unbounded."""
    w = _compute_target_weights(
        ["A", "B"],
        strengths={},
        vols={"A": 0.05, "B": 0.05},
        mode=AllocationMode.VOL_TARGET,
        vol_target_annual=0.20,
        max_weight=0.25,
    )
    assert w["A"] == pytest.approx(0.25)
    assert w["B"] == pytest.approx(0.25)


def test_vol_target_scale_down_when_total_exceeds_one():
    """5 names all hitting the cap (sum 1.25) get scaled to 0.20 each (sum 1.0)."""
    tickers = [f"T{i}" for i in range(5)]
    w = _compute_target_weights(
        tickers,
        strengths={},
        vols={t: 0.05 for t in tickers},
        mode=AllocationMode.VOL_TARGET,
        vol_target_annual=0.20,
        max_weight=0.25,
    )
    assert sum(w.values()) == pytest.approx(1.0)
    for t in tickers:
        assert w[t] == pytest.approx(0.20)


def test_vol_target_zero_vol_uses_fallback():
    """A ticker with unknown σ borrows the median vol instead of exploding."""
    w = _compute_target_weights(
        ["A", "B"],
        strengths={},
        vols={"A": 0.0, "B": 0.20},
        mode=AllocationMode.VOL_TARGET,
        vol_target_annual=0.20,
        max_weight=1.0,
    )
    assert np.isfinite(w["A"]) and w["A"] > 0
    assert w["A"] == pytest.approx(w["B"])  # A inherits B's vol as the fallback


# ── Pure: KELLY_FRACTIONAL ──────────────────────────────────────────────────


def test_kelly_basic_formula():
    """p=0.55, σ=0.20 (var 0.04), f=0.25 → 0.25 · 0.10/0.04 = 0.625."""
    w = _compute_target_weights(
        ["A"],
        strengths={},
        vols={"A": 0.20},
        mode=AllocationMode.KELLY_FRACTIONAL,
        probs={"A": 0.55},
        kelly_fraction=0.25,
        max_weight=1.0,
    )
    assert w["A"] == pytest.approx(0.625)


def test_kelly_cap_binds():
    """Same edge but the default cap clips the weight to 25 %."""
    w = _compute_target_weights(
        ["A"],
        strengths={},
        vols={"A": 0.20},
        mode=AllocationMode.KELLY_FRACTIONAL,
        probs={"A": 0.55},
        kelly_fraction=0.25,
        max_weight=0.25,
    )
    assert w["A"] == pytest.approx(0.25)


def test_kelly_skips_uncalibrated():
    """A ticker without a calibrated probability gets no allocation."""
    w = _compute_target_weights(
        ["A", "B"],
        strengths={},
        vols={"A": 0.20, "B": 0.20},
        mode=AllocationMode.KELLY_FRACTIONAL,
        probs={"A": 0.60, "B": None},
        kelly_fraction=0.25,
        max_weight=1.0,
    )
    assert "A" in w and w["A"] > 0
    assert w.get("B", 0.0) == 0.0


def test_kelly_drops_negative_edge():
    """p < 0.5 → negative edge → dropped (long-only)."""
    w = _compute_target_weights(
        ["A"],
        strengths={},
        vols={"A": 0.20},
        mode=AllocationMode.KELLY_FRACTIONAL,
        probs={"A": 0.40},
        kelly_fraction=0.25,
        max_weight=1.0,
    )
    assert w.get("A", 0.0) == 0.0


def test_kelly_higher_prob_gets_more():
    """Same variance, higher prob ⇒ larger weight."""
    w = _compute_target_weights(
        ["HI", "LO"],
        strengths={},
        vols={"HI": 0.20, "LO": 0.20},
        mode=AllocationMode.KELLY_FRACTIONAL,
        probs={"HI": 0.62, "LO": 0.54},
        kelly_fraction=0.25,
        max_weight=1.0,
    )
    assert w["HI"] > w["LO"] > 0


def test_empty_active_returns_empty():
    assert _compute_target_weights([], {}, {}, AllocationMode.VOL_TARGET) == {}
    assert _compute_target_weights([], {}, {}, AllocationMode.KELLY_FRACTIONAL) == {}


# ── Integration: analyze_single ─────────────────────────────────────────────


def test_analyze_single_vol_target_sizes_calm_larger(monkeypatch):
    from paper_trading.strategies import generate_trades_analyze_single

    settings.set("max_position_weight", 1.0)  # let the vol ratio show
    settings.set("vol_target_annual", 0.20)

    _patch_analyze(monkeypatch, {"CALM": ("BUY", 0.60), "VOL": ("BUY", 0.60)})
    dfs = {"CALM": _series(0.004, seed=1), "VOL": _series(0.040, seed=2)}

    trades = generate_trades_analyze_single(
        account=_account(allocation_mode="vol_target"),
        watchlist=["CALM", "VOL"],
        positions=[],
        prices={"CALM": 100.0, "VOL": 100.0},
        history_provider=lambda t: dfs.get(t),
    )

    by_t = {tr.ticker: tr for tr in trades if tr.side == "BUY"}
    assert set(by_t) == {"CALM", "VOL"}
    assert by_t["CALM"].target_dollars > by_t["VOL"].target_dollars * 1.5
    assert "vol_target" in by_t["CALM"].reason


def test_analyze_single_kelly_skips_uncalibrated(monkeypatch):
    from paper_trading.strategies import generate_trades_analyze_single

    settings.set("max_position_weight", 1.0)
    settings.set("kelly_fraction", 0.25)

    # GOOD has a calibrated prob; NOPROB has none → must be skipped under Kelly.
    _patch_analyze(monkeypatch, {"GOOD": ("BUY", 0.65), "NOPROB": ("BUY", None)})
    dfs = {"GOOD": _series(0.02, seed=3), "NOPROB": _series(0.02, seed=4)}

    trades = generate_trades_analyze_single(
        account=_account(allocation_mode="kelly_fractional"),
        watchlist=["GOOD", "NOPROB"],
        positions=[],
        prices={"GOOD": 100.0, "NOPROB": 100.0},
        history_provider=lambda t: dfs.get(t),
    )

    bought = {tr.ticker for tr in trades if tr.side == "BUY"}
    assert "GOOD" in bought
    assert "NOPROB" not in bought


# ── Integration: portfolio_engine ───────────────────────────────────────────


def test_portfolio_engine_vol_target_sizes_calm_larger(monkeypatch):
    from paper_trading.strategies import generate_trades_portfolio_engine

    settings.set("max_position_weight", 1.0)
    settings.set("vol_target_annual", 0.20)

    _patch_analyze(monkeypatch, {"CALM": ("BUY", 0.60), "VOL": ("BUY", 0.60)})
    dfs = {"CALM": _series(0.004, seed=5), "VOL": _series(0.040, seed=6)}

    trades = generate_trades_portfolio_engine(
        account=_account(allocation_mode="vol_target", max_positions=5),
        watchlist=["CALM", "VOL"],
        positions=[],
        prices={"CALM": 100.0, "VOL": 100.0},
        history_provider=lambda t: dfs.get(t),
    )

    buys = {tr.ticker: tr.target_dollars for tr in trades if tr.side == "BUY"}
    assert set(buys) == {"CALM", "VOL"}
    assert buys["CALM"] > buys["VOL"] * 1.5
