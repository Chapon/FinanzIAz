"""
Tests for T10 — portfolio-level volatility targeting overlay.

Two layers:

1. Pure unit tests of ``analysis.portfolio_risk`` (``annualized_portfolio_vol``,
   ``apply_portfolio_vol_overlay``, ``returns_frame``) — the σ = sqrt(wᵀΣw)·√252
   estimate, the scale-down when σ exceeds target (and the ~40 % reduction the
   roadmap calls for at σ=20 % / target=12 %), the no-leverage rule when σ is
   below target, and the ``≤ 0`` disable switch.

2. Integration tests that the two live strategies (``analyze_single`` and
   ``portfolio_engine``) shrink a high-σ book's BUY dollars when the overlay is
   on versus off. ``analyze()`` is monkeypatched so these stay deterministic.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_risk import (
    annualized_portfolio_vol,
    apply_portfolio_vol_overlay,
    returns_frame,
)
from config.constants import TRADING_DAYS_PER_YEAR
from config.settings_manager import settings

ANNUALIZE = float(np.sqrt(TRADING_DAYS_PER_YEAR))


# ── Builders with a controllable annualised σ ────────────────────────────────


def _returns_with_sigma(annual_sigma: float, rows: int = 160) -> pd.Series:
    """Alternating ±s daily returns whose annualised vol ≈ ``annual_sigma``."""
    s = annual_sigma / ANNUALIZE
    vals = np.array([s if i % 2 == 0 else -s for i in range(rows)])
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="B")
    return pd.Series(vals, index=idx)


def _frame(**series: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(series)


def _close_with_sigma(annual_sigma: float, rows: int = 160, start: float = 100.0) -> pd.DataFrame:
    """Close-only OHLCV frame whose realised daily vol maps to ``annual_sigma``."""
    rng = np.random.default_rng(int(annual_sigma * 1000))
    rets = rng.normal(0.0, annual_sigma / ANNUALIZE, rows)
    close = start * np.exp(np.cumsum(rets))
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="B")
    return pd.DataFrame({"Close": close}, index=idx)


# ── Pure: annualized_portfolio_vol ───────────────────────────────────────────


def test_single_asset_sigma_matches_input():
    df = _frame(A=_returns_with_sigma(0.20))
    sigma = annualized_portfolio_vol({"A": 1.0}, df)
    assert sigma == pytest.approx(0.20, abs=0.01)


def test_sigma_zero_for_degenerate_inputs():
    assert annualized_portfolio_vol({}, pd.DataFrame()) == 0.0
    df = _frame(A=_returns_with_sigma(0.20))
    assert annualized_portfolio_vol({"A": 0.0}, df) == 0.0  # all-zero weights


def test_two_uncorrelated_lowers_sigma_vs_weighted_avg():
    rng = np.random.default_rng(11)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=200, freq="B")
    df = _frame(
        A=pd.Series(rng.normal(0, 0.02, 200), index=idx),
        B=pd.Series(rng.normal(0, 0.02, 200), index=idx),
    )
    # Equal-weight σ of two independent ~equal-vol names < the single-name σ.
    sigma_book = annualized_portfolio_vol({"A": 0.5, "B": 0.5}, df)
    sigma_solo = annualized_portfolio_vol({"A": 1.0}, df)
    assert sigma_book < sigma_solo


# ── Pure: apply_portfolio_vol_overlay ────────────────────────────────────────


def test_overlay_scales_down_high_vol_book_about_40pct():
    """σ≈20 %, target 12 % → factor≈0.6 (≈40 % less exposure)."""
    df = _frame(A=_returns_with_sigma(0.20))
    scaled, sigma, factor = apply_portfolio_vol_overlay({"A": 1.0}, df, 0.12)
    assert sigma == pytest.approx(0.20, abs=0.01)
    assert factor == pytest.approx(0.12 / sigma, rel=1e-6)
    assert 0.55 < factor < 0.65
    assert scaled["A"] == pytest.approx(1.0 * factor)


def test_overlay_does_not_leverage_low_vol_book():
    """σ≈8 %, target 12 % → no scaling (long-only, never scales up)."""
    df = _frame(A=_returns_with_sigma(0.08))
    scaled, sigma, factor = apply_portfolio_vol_overlay({"A": 1.0}, df, 0.12)
    assert sigma == pytest.approx(0.08, abs=0.01)
    assert factor == 1.0
    assert scaled["A"] == pytest.approx(1.0)


def test_overlay_disabled_when_target_non_positive():
    df = _frame(A=_returns_with_sigma(0.40))
    scaled, sigma, factor = apply_portfolio_vol_overlay({"A": 1.0}, df, 0.0)
    assert factor == 1.0 and sigma is None
    assert scaled == {"A": 1.0}
    scaled2, sigma2, factor2 = apply_portfolio_vol_overlay({"A": 1.0}, df, None)
    assert factor2 == 1.0 and sigma2 is None


def test_overlay_no_estimate_does_not_scale():
    """Empty returns → σ unknown → leave weights as-is."""
    scaled, sigma, factor = apply_portfolio_vol_overlay({"A": 1.0}, pd.DataFrame(), 0.12)
    assert factor == 1.0
    assert scaled == {"A": 1.0}


# ── Pure: returns_frame ──────────────────────────────────────────────────────


def test_returns_frame_drops_tickers_without_history():
    book = {"A": _close_with_sigma(0.2), "B": _close_with_sigma(0.3)}
    hp = lambda t: book.get(t)  # noqa: E731
    df = returns_frame(["A", "B", "MISSING"], hp)
    assert set(df.columns) == {"A", "B"}
    assert not df.empty


# ── Integration helpers ─────────────────────────────────────────────────────


def _account(**overrides):
    base = dict(
        cash=100_000.0,
        max_positions=5,
        allocation_mode="signal_weighted",
        fixed_amount=5_000.0,
        commission=0.0,
        drift_threshold=0.25,
        monthly_rebalance=False,
        last_monthly_rebalance=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_analyze(monkeypatch, table):
    import analysis.technical as technical

    def fake_analyze(ticker, df, *a, **k):
        if ticker not in table:
            return None
        sig, prob = table[ticker]
        return SimpleNamespace(overall_signal=sig, ml_probability=prob)

    monkeypatch.setattr(technical, "analyze", fake_analyze)


@pytest.fixture(autouse=True)
def _restore_settings():
    # Sprint 3: ``max_avg_correlation`` and the correlation_gate wiring were
    # removed, so we only need to snapshot/restore the vol-target setting.
    keys = ("vol_target_portfolio_annual",)
    saved = {k: settings.get(k) for k in keys}
    yield
    for k, v in saved.items():
        settings.set(k, v)


# ── Integration: analyze_single ─────────────────────────────────────────────


def test_analyze_single_overlay_shrinks_high_vol_buys(monkeypatch):
    from paper_trading.strategies import generate_trades_analyze_single

    _patch_analyze(monkeypatch, {"HV": ("BUY", 0.60)})
    book = {"HV": _close_with_sigma(0.40)}  # very high vol → big scale-down
    hp = lambda t: book.get(t)  # noqa: E731
    prices = {"HV": float(book["HV"]["Close"].iloc[-1])}

    def run():
        return generate_trades_analyze_single(
            account=_account(),
            watchlist=["HV"],
            positions=[],
            prices=prices,
            history_provider=hp,
        )

    settings.set("vol_target_portfolio_annual", 0.0)  # overlay off
    off = run()
    settings.set("vol_target_portfolio_annual", 0.12)  # overlay on
    on = run()

    d_off = {t.ticker: t.target_dollars for t in off if t.side == "BUY"}
    d_on = {t.ticker: t.target_dollars for t in on if t.side == "BUY"}
    assert "HV" in d_off and "HV" in d_on
    assert d_on["HV"] < d_off["HV"] * 0.6  # ~σ 0.40 / target 0.12 ⇒ factor ≈ 0.30


def test_analyze_single_overlay_keeps_low_vol_buys(monkeypatch):
    from paper_trading.strategies import generate_trades_analyze_single

    _patch_analyze(monkeypatch, {"LV": ("BUY", 0.60)})
    book = {"LV": _close_with_sigma(0.08)}  # below target → untouched
    hp = lambda t: book.get(t)  # noqa: E731
    prices = {"LV": float(book["LV"]["Close"].iloc[-1])}

    def run():
        return generate_trades_analyze_single(
            account=_account(),
            watchlist=["LV"],
            positions=[],
            prices=prices,
            history_provider=hp,
        )

    settings.set("vol_target_portfolio_annual", 0.0)
    off = {t.ticker: t.target_dollars for t in run() if t.side == "BUY"}
    settings.set("vol_target_portfolio_annual", 0.12)
    on = {t.ticker: t.target_dollars for t in run() if t.side == "BUY"}
    assert on["LV"] == pytest.approx(off["LV"])


# ── Integration: portfolio_engine ───────────────────────────────────────────


def test_portfolio_engine_overlay_shrinks_high_vol_book(monkeypatch):
    from paper_trading.strategies import generate_trades_portfolio_engine

    _patch_analyze(monkeypatch, {"HV": ("BUY", 0.70)})
    book = {"HV": _close_with_sigma(0.40)}
    hp = lambda t: book.get(t)  # noqa: E731
    prices = {"HV": float(book["HV"]["Close"].iloc[-1])}

    def run():
        return generate_trades_portfolio_engine(
            account=_account(allocation_mode="equal_weight"),
            watchlist=["HV"],
            positions=[],
            prices=prices,
            history_provider=hp,
        )

    settings.set("vol_target_portfolio_annual", 0.0)
    off = {t.ticker: t.target_dollars for t in run() if t.side == "BUY"}
    settings.set("vol_target_portfolio_annual", 0.12)
    on = {t.ticker: t.target_dollars for t in run() if t.side == "BUY"}
    assert "HV" in off and "HV" in on
    assert on["HV"] < off["HV"] * 0.6
