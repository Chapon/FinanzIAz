"""
Tests for T09 correlation math — kept as vestigial after Sprint 3.

Pure unit tests of ``analysis.portfolio_risk`` (``mean_correlation`` and
``diversification_ratio``) — high/low/negative correlation, the empty and
insufficient-overlap edge cases, and the diversification metric on a
perfectly-correlated vs an uncorrelated book.

Sprint 3 (2026-05-29): the integration tests that exercised the wiring in
``paper_trading.strategies`` and the harness were removed because the wiring
itself was removed (the gate never rejected a candidate in any realistic
setup). The pure functions live in ``paper_trading.gates.select_uncorrelated_picks``
and ``analysis.portfolio_risk`` and are kept for future re-introduction.
See ``docs/sprint2_kill_criteria.md`` Enmienda 2 for the full rationale.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_risk import (
    book_concentration,
    book_mean_correlation,
    daily_returns,
    diversification_ratio,
    mean_correlation,
    returns_frame,
)
from config.settings_manager import settings

# ── Synthetic return / price builders ──────────────────────────────────────────


def _prices_from_returns(rets: np.ndarray, start: float = 100.0) -> pd.Series:
    """Close series whose pct_change reproduces ``rets`` (up to rounding)."""
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=len(rets) + 1, freq="B")
    close = start * np.cumprod(np.concatenate([[1.0], 1.0 + rets]))
    return pd.Series(close, index=idx)


def _correlated_book(rows: int = 120, seed: int = 0):
    """Return a dict of Close-only frames sharing a common factor.

    AAPL, MSFT, GOOGL all load positively on the same factor (high mutual
    correlation); GLD loads negatively (anti-correlated with the cluster).
    """
    rng = np.random.default_rng(seed)
    factor = rng.normal(0.0, 0.02, rows)

    def with_noise(load: float, noise: float, s: int) -> pd.DataFrame:
        nrng = np.random.default_rng(s)
        rets = load * factor + nrng.normal(0.0, noise, rows)
        return pd.DataFrame({"Close": _prices_from_returns(rets)})

    return {
        "AAPL": with_noise(1.0, 0.002, 1),
        "MSFT": with_noise(1.0, 0.002, 2),
        "GOOGL": with_noise(1.0, 0.002, 3),
        "GLD": with_noise(-1.0, 0.002, 4),
    }


# ── Pure: mean_correlation ──────────────────────────────────────────────────


def test_mean_correlation_high_for_common_factor():
    book = _correlated_book()
    cand = daily_returns(book["GOOGL"]["Close"])
    held = [daily_returns(book["AAPL"]["Close"]), daily_returns(book["MSFT"]["Close"])]
    assert mean_correlation(cand, held) > 0.9


def test_mean_correlation_negative_for_hedge():
    book = _correlated_book()
    cand = daily_returns(book["GLD"]["Close"])
    held = [daily_returns(book["AAPL"]["Close"]), daily_returns(book["MSFT"]["Close"])]
    assert mean_correlation(cand, held) < -0.5


def test_mean_correlation_none_when_no_held():
    book = _correlated_book()
    cand = daily_returns(book["AAPL"]["Close"])
    assert mean_correlation(cand, []) is None


def test_mean_correlation_none_when_insufficient_overlap():
    book = _correlated_book()
    cand = daily_returns(book["AAPL"]["Close"])
    short = daily_returns(book["MSFT"]["Close"]).tail(5)  # < MIN_CORRELATION_OBS
    assert mean_correlation(cand, [short]) is None


def test_mean_correlation_skips_constant_series():
    book = _correlated_book()
    cand = daily_returns(book["AAPL"]["Close"])
    flat = pd.Series(0.0, index=cand.index)  # zero variance → undefined corr
    assert mean_correlation(cand, [flat]) is None


# ── Pure: diversification_ratio ─────────────────────────────────────────────


def test_diversification_ratio_one_for_identical_series():
    r = daily_returns(_correlated_book()["AAPL"]["Close"])
    df = pd.DataFrame({"A": r, "B": r})  # identical → no diversification
    assert diversification_ratio(df) == pytest.approx(1.0, abs=1e-6)


def test_diversification_ratio_above_one_for_uncorrelated():
    rng = np.random.default_rng(7)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=120, freq="B")
    df = pd.DataFrame(
        {"A": rng.normal(0, 0.02, 120), "B": rng.normal(0, 0.02, 120)},
        index=idx,
    )
    # Two independent vols of equal size → ratio ≈ sqrt(2).
    assert diversification_ratio(df) > 1.2


def test_diversification_ratio_degenerate_inputs():
    assert diversification_ratio(pd.DataFrame()) == 1.0


# ── Pure: book_mean_correlation (V2) ────────────────────────────────────────


def test_book_mean_correlation_high_for_common_factor():
    book = _correlated_book()
    rf = returns_frame(["AAPL", "MSFT", "GOOGL"], lambda t: book[t])
    assert book_mean_correlation(rf) > 0.9


def test_book_mean_correlation_lower_with_hedge():
    book = _correlated_book()
    rf = returns_frame(["AAPL", "MSFT", "GLD"], lambda t: book[t])
    # GLD anti-correla con el cluster → promedio par-a-par cae por debajo del cluster puro.
    assert book_mean_correlation(rf) < 0.5


def test_book_mean_correlation_none_single_or_empty():
    book = _correlated_book()
    rf1 = returns_frame(["AAPL"], lambda t: book[t])
    assert book_mean_correlation(rf1) is None
    assert book_mean_correlation(pd.DataFrame()) is None
    assert book_mean_correlation(None) is None


# ── Pure: book_concentration (V2) ───────────────────────────────────────────


def _positions():
    # MU domina el book (60%); pesos que se ven a simple vista.
    return [
        {"ticker": "MU", "market_value": 6000.0, "unrealized_pnl": 800.0},
        {"ticker": "AAPL", "market_value": 3000.0, "unrealized_pnl": -200.0},
        {"ticker": "TJX", "market_value": 1000.0, "unrealized_pnl": 50.0},
    ]


def test_book_concentration_weights_and_top():
    c = book_concentration(_positions())
    assert c["n"] == 3
    assert c["total_value"] == pytest.approx(10000.0)
    assert c["top_ticker"] == "MU"
    assert c["top_weight"] == pytest.approx(0.6)
    # HHI = 0.6²+0.3²+0.1² = 0.46 ; nombres efectivos = 1/0.46 ≈ 2.17
    assert c["hhi"] == pytest.approx(0.46)
    assert c["effective_names"] == pytest.approx(1 / 0.46)
    # weights ordenados desc
    assert [w["ticker"] for w in c["weights"]] == ["MU", "AAPL", "TJX"]


def test_book_concentration_pnl_ex_best_worst():
    c = book_concentration(_positions())
    # total unrealized = 800 - 200 + 50 = 650
    assert c["total_unrealized_pnl"] == pytest.approx(650.0)
    assert c["best_ticker"] == "MU" and c["worst_ticker"] == "AAPL"
    assert c["pnl_ex_best"] == pytest.approx(650.0 - 800.0)   # sin MU: -150
    assert c["pnl_ex_worst"] == pytest.approx(650.0 - (-200.0))  # sin AAPL: 850


def test_book_concentration_sectors_grouped():
    sectors = {"MU": "Technology", "AAPL": "Technology", "TJX": "Consumer"}
    c = book_concentration(_positions(), sector_of=lambda t: sectors.get(t))
    by = {s["sector"]: s["weight"] for s in c["sectors"]}
    assert by["Technology"] == pytest.approx(0.9)   # MU 0.6 + AAPL 0.3
    assert by["Consumer"] == pytest.approx(0.1)
    # el sector más pesado va primero
    assert c["sectors"][0]["sector"] == "Technology"


def test_book_concentration_missing_sector_grouped_as_sin_dato():
    c = book_concentration(_positions(), sector_of=lambda t: None)
    assert c["sectors"][0]["sector"] == "Sin dato"
    assert c["sectors"][0]["weight"] == pytest.approx(1.0)


def test_book_concentration_empty_and_zero_value():
    assert book_concentration([])["n"] == 0
    z = book_concentration([{"ticker": "X", "market_value": 0.0, "unrealized_pnl": 0.0}])
    assert z["n"] == 1 and z["total_value"] == 0.0 and z["weights"] == []


# ── Integration helpers ─────────────────────────────────────────────────────


def _account(**overrides):
    base = dict(
        cash=100_000.0,
        max_positions=5,
        allocation_mode="signal_weighted",  # plain equal-slice sizing
        fixed_amount=5_000.0,
        commission=0.0,
        drift_threshold=0.25,
        monthly_rebalance=False,
        last_monthly_rebalance=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_analyze(monkeypatch, table: dict[str, tuple[str, float | None]]):
    import analysis.technical as technical

    def fake_analyze(ticker, df, *a, **k):
        if ticker not in table:
            return None
        sig, prob = table[ticker]
        return SimpleNamespace(overall_signal=sig, ml_probability=prob)

    monkeypatch.setattr(technical, "analyze", fake_analyze)

# Integration tests for ``analyze_single`` / ``portfolio_engine`` correlation
# wiring were removed in Sprint 3 — see docs/sprint2_kill_criteria.md (Enmienda 2).
# The pure math (above) is preserved as the function is kept in
# ``paper_trading.gates.select_uncorrelated_picks`` for future re-introduction.

# Drop the autouse fixture too — there is no ``max_avg_correlation`` setting
# to restore anymore.
