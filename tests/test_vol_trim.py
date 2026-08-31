"""
Tests for T09 — active de-risking of the *held* book (vol-overlay trims).

The T10 overlay (``test_vol_targeting.py``) only scales NEW buys. T09 adds the
missing half: when ``vol_overlay_trim_enabled`` is on and the currently-held
book's annualised σ exceeds ``vol_target_portfolio_annual``, ``analyze_single``
emits partial-SELL *trims* so existing positions return toward target — even on
scans with no new entries.

Two layers:

1. Pure predicate ``paper_trading.gates.is_vol_trim_reason`` — used by the engine
   to let a trim bypass the min-holding gate (mirrors the ATR forced-exit stance).
2. Integration over ``generate_trades_analyze_single``: toggle gating, trim
   magnitude (= ``shares × (1 − factor)``), hysteresis below target, the dust
   floor, exclusion of names already being force-sold, and the overlay-disabled
   short-circuit. ``analyze()`` is monkeypatched so these stay deterministic.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_risk import apply_portfolio_vol_overlay, returns_frame
from config.constants import TRADING_DAYS_PER_YEAR
from config.settings_manager import settings
from paper_trading.gates import VOL_TRIM_REASON_PREFIX, is_vol_trim_reason

ANNUALIZE = float(np.sqrt(TRADING_DAYS_PER_YEAR))


# ── Pure: is_vol_trim_reason ─────────────────────────────────────────────────


def test_is_vol_trim_reason_matches_prefix():
    assert is_vol_trim_reason("vol_trim σ=27%>12% ×0.44") is True
    assert is_vol_trim_reason(VOL_TRIM_REASON_PREFIX) is True


def test_is_vol_trim_reason_rejects_others():
    assert is_vol_trim_reason("atr_stop @ 90.0 ≤ 88.0") is False
    assert is_vol_trim_reason("analyze SELL (0.20)") is False
    assert is_vol_trim_reason(None) is False
    assert is_vol_trim_reason("") is False


# ── Builders ─────────────────────────────────────────────────────────────────


def _close_with_sigma(annual_sigma: float, rows: int = 200, start: float = 100.0, seed=None) -> pd.DataFrame:
    """Close-only frame whose realised daily vol maps to ``annual_sigma``."""
    rng = np.random.default_rng(seed if seed is not None else int(annual_sigma * 1000))
    rets = rng.normal(0.0, annual_sigma / ANNUALIZE, rows)
    close = start * np.exp(np.cumsum(rets))
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="B")
    return pd.DataFrame({"Close": close}, index=idx)


def _pos(ticker: str, shares: float, price: float) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker,
        shares=float(shares),
        avg_cost=float(price),
        high_water_mark=float(price),
        opened_at=None,
    )


def _account(cash: float = 0.0, **overrides) -> SimpleNamespace:
    base = dict(
        cash=cash,
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
    keys = (
        "vol_target_portfolio_annual",
        "vol_overlay_trim_enabled",
        "paper_min_trade_dollars",
    )
    saved = {k: settings.get(k) for k in keys}
    # Sensible defaults for the trim path; individual tests override as needed.
    settings.set("vol_target_portfolio_annual", 0.12)
    settings.set("paper_min_trade_dollars", 50.0)
    yield
    for k, v in saved.items():
        settings.set(k, v)


@pytest.fixture
def high_vol_book():
    """Two independent high-σ names held at 100 shares each."""
    book = {"HV1": _close_with_sigma(0.40, seed=1), "HV2": _close_with_sigma(0.40, seed=2)}
    hp = lambda t: book.get(t)
    prices = {t: float(df["Close"].iloc[-1]) for t, df in book.items()}
    positions = [_pos("HV1", 100, prices["HV1"]), _pos("HV2", 100, prices["HV2"])]
    return book, hp, prices, positions


def _trims(trades):
    return [t for t in trades if is_vol_trim_reason(t.reason)]


# ── Integration: analyze_single active trim ──────────────────────────────────


def test_trim_off_by_default(monkeypatch, high_vol_book):
    """Toggle off (default) → no trims even on an over-σ book."""
    from paper_trading.strategies import generate_trades_analyze_single

    _, hp, prices, positions = high_vol_book
    _patch_analyze(monkeypatch, {"HV1": ("HOLD", 0.5), "HV2": ("HOLD", 0.5)})
    settings.set("vol_overlay_trim_enabled", False)
    trades = generate_trades_analyze_single(_account(), [], positions, prices, hp)
    assert _trims(trades) == []


def test_trim_emitted_for_overvol_book_without_buys(monkeypatch, high_vol_book):
    """Toggle on + over-σ held book + no candidates → partial-SELL trims."""
    from paper_trading.strategies import generate_trades_analyze_single

    _, hp, prices, positions = high_vol_book
    _patch_analyze(monkeypatch, {"HV1": ("HOLD", 0.5), "HV2": ("HOLD", 0.5)})
    settings.set("vol_overlay_trim_enabled", True)
    trades = generate_trades_analyze_single(_account(), [], positions, prices, hp)
    trims = _trims(trades)
    assert len(trims) == 2
    assert all(t.side == "SELL" for t in trims)
    assert all(t.target_dollars > 0 for t in trims)
    assert all(0 < t.target_shares < 100 for t in trims)


def test_trim_magnitude_matches_factor(monkeypatch, high_vol_book):
    """Each trim sells exactly ``shares × (1 − factor)`` toward the σ target."""
    from paper_trading.strategies import generate_trades_analyze_single

    _, hp, prices, positions = high_vol_book
    _patch_analyze(monkeypatch, {"HV1": ("HOLD", 0.5), "HV2": ("HOLD", 0.5)})
    settings.set("vol_overlay_trim_enabled", True)

    pv = sum(p.shares * prices[p.ticker] for p in positions)
    held_w = {p.ticker: (p.shares * prices[p.ticker]) / pv for p in positions}
    _, _sigma, factor = apply_portfolio_vol_overlay(held_w, returns_frame(["HV1", "HV2"], hp), 0.12)

    trades = generate_trades_analyze_single(_account(), [], positions, prices, hp)
    by_ticker = {t.ticker: t.target_shares for t in _trims(trades)}
    for t in ("HV1", "HV2"):
        assert by_ticker[t] == pytest.approx(100 * (1 - factor), abs=0.5)


def test_no_trim_when_book_under_target(monkeypatch):
    """Hysteresis: a low-σ book sits within target → factor ≈ 1 → no trims."""
    from paper_trading.strategies import generate_trades_analyze_single

    book = {"LV1": _close_with_sigma(0.06, seed=3), "LV2": _close_with_sigma(0.06, seed=4)}
    hp = lambda t: book.get(t)
    prices = {t: float(df["Close"].iloc[-1]) for t, df in book.items()}
    positions = [_pos("LV1", 100, prices["LV1"]), _pos("LV2", 100, prices["LV2"])]
    _patch_analyze(monkeypatch, {"LV1": ("HOLD", 0.5), "LV2": ("HOLD", 0.5)})
    settings.set("vol_overlay_trim_enabled", True)
    trades = generate_trades_analyze_single(_account(), [], positions, prices, hp)
    assert _trims(trades) == []


def test_dust_floor_suppresses_trims(monkeypatch, high_vol_book):
    """Trims below ``paper_min_trade_dollars`` are skipped as dust."""
    from paper_trading.strategies import generate_trades_analyze_single

    _, hp, prices, positions = high_vol_book
    _patch_analyze(monkeypatch, {"HV1": ("HOLD", 0.5), "HV2": ("HOLD", 0.5)})
    settings.set("vol_overlay_trim_enabled", True)
    settings.set("paper_min_trade_dollars", 1_000_000.0)  # everything is dust
    trades = generate_trades_analyze_single(_account(), [], positions, prices, hp)
    assert _trims(trades) == []


def test_forced_exit_not_double_trimmed(monkeypatch, high_vol_book):
    """A name with a SELL signal is fully closed, not also vol-trimmed."""
    from paper_trading.strategies import generate_trades_analyze_single

    _, hp, prices, positions = high_vol_book
    _patch_analyze(monkeypatch, {"HV1": ("SELL", 0.2), "HV2": ("HOLD", 0.5)})
    settings.set("vol_overlay_trim_enabled", True)
    trades = generate_trades_analyze_single(_account(), [], positions, prices, hp)

    hv1_sells = [t for t in trades if t.ticker == "HV1" and t.side == "SELL"]
    assert any("analyze SELL" in t.reason for t in hv1_sells)
    assert not any(t.ticker == "HV1" for t in _trims(trades))
    assert any(t.ticker == "HV2" for t in _trims(trades))


def test_no_trim_when_overlay_disabled(monkeypatch, high_vol_book):
    """vol_target_portfolio_annual = 0 disables the overlay → no trims even ON."""
    from paper_trading.strategies import generate_trades_analyze_single

    _, hp, prices, positions = high_vol_book
    _patch_analyze(monkeypatch, {"HV1": ("HOLD", 0.5), "HV2": ("HOLD", 0.5)})
    settings.set("vol_overlay_trim_enabled", True)
    settings.set("vol_target_portfolio_annual", 0.0)
    trades = generate_trades_analyze_single(_account(), [], positions, prices, hp)
    assert _trims(trades) == []


def test_trim_shares_never_exceed_position(monkeypatch):
    """Even at extreme σ the trim is capped at the held share count."""
    from paper_trading.strategies import generate_trades_analyze_single

    book = {"XV": _close_with_sigma(1.20, seed=9)}  # σ ≫ target → factor → 0
    hp = lambda t: book.get(t)
    prices = {"XV": float(book["XV"]["Close"].iloc[-1])}
    positions = [_pos("XV", 50, prices["XV"])]
    _patch_analyze(monkeypatch, {"XV": ("HOLD", 0.5)})
    settings.set("vol_overlay_trim_enabled", True)
    trades = generate_trades_analyze_single(_account(), [], positions, prices, hp)
    trims = _trims(trades)
    assert trims and all(0 < t.target_shares <= 50 for t in trims)
