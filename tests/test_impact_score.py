"""
Tests for the Impact Score heuristic (Sprint 5 · T-CAT-4).

Pure / offline: synthetic reaction tables and a fake earnings loader. Covers the
score factors, the M2 ``entry="next_open"`` forward return, the imminent-catalyst
signal, and the exit-veto helper (Gate 2c logic, flag and eligibility).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from analysis.catalyst_reaction import forward_return
from analysis.impact_score import (
    EVENT_PRIORS,
    CatalystSignal,
    exit_veto_block,
    imminent_catalyst,
    score_event,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _reaction_table(mean, count, *, ticker="NVDA", event="earnings_results", horizon=5):
    """Minimal reaction table with one (ticker, event) stat at one horizon."""
    stat = {"count": count, "mean": mean, "std": 0.0, "hit_rate": 0.5}
    h = str(horizon)
    return {
        "horizons": [horizon],
        "by_event": {event: {h: stat}},
        "by_ticker_event": {f"{ticker}|{event}": {h: stat}},
    }


# ── direction ─────────────────────────────────────────────────────────────────


def test_direction_follows_measured_reaction_over_sentiment():
    # reaction is positive but the headline sentiment says negative → reaction wins
    table = _reaction_table(mean=0.04, count=20)
    s = score_event("NVDA", "earnings_results", "negative", 0.9, reaction_table=table)
    assert s.direction == 1
    assert s.basis == "reaction"
    assert s.value > 0


def test_direction_falls_back_to_sentiment_without_history():
    s = score_event("XYZ", "earnings_results", "negative", 0.9, reaction_table=None)
    assert s.direction == -1
    assert s.basis == "prior"
    # magnitude uses the event prior
    assert s.magnitude == pytest.approx(EVENT_PRIORS["earnings_results"])


# ── magnitude ─────────────────────────────────────────────────────────────────


def test_magnitude_saturates_large_moves():
    big = score_event(
        "NVDA", "earnings_results", "positive", 1.0, reaction_table=_reaction_table(mean=0.50, count=20)
    )
    assert big.magnitude < 1.0  # tanh never reaches 1
    assert big.magnitude > 0.9  # but a 50% move is near the ceiling


def test_magnitude_small_move_is_small():
    tiny = score_event(
        "NVDA", "earnings_results", "positive", 1.0, reaction_table=_reaction_table(mean=0.001, count=20)
    )
    assert tiny.magnitude < 0.05


def test_prior_used_when_count_zero():
    table = _reaction_table(mean=0.04, count=0)
    s = score_event("NVDA", "mna", "positive", 0.9, reaction_table=table)
    assert s.basis == "prior"
    assert s.magnitude == pytest.approx(EVENT_PRIORS["mna"])


# ── confidence / sample weighting ─────────────────────────────────────────────


def test_low_sample_reduces_confidence_weight():
    low = score_event(
        "NVDA", "earnings_results", "positive", 1.0, reaction_table=_reaction_table(mean=0.04, count=2)
    )
    high = score_event(
        "NVDA", "earnings_results", "positive", 1.0, reaction_table=_reaction_table(mean=0.04, count=20)
    )
    assert low.confidence_weight < high.confidence_weight
    assert low.confidence_weight >= 0.4  # floor respected


# ── relevance ─────────────────────────────────────────────────────────────────


def test_relevance_boosts_large_dollar_events():
    table = _reaction_table(mean=0.04, count=20)
    with_rel = score_event(
        "NVDA",
        "partnership_contract",
        "positive",
        0.9,
        reaction_table=table,
        headline="NVDA wins $5 billion contract",
        market_cap=10e9,
    )
    no_rel = score_event(
        "NVDA",
        "partnership_contract",
        "positive",
        0.9,
        reaction_table=table,
        headline="NVDA wins a contract",
        market_cap=10e9,
    )
    assert with_rel.relevance_weight > no_rel.relevance_weight
    assert no_rel.relevance_weight == pytest.approx(1.0)
    assert with_rel.relevance_weight > 1.3


# ── fail-soft ─────────────────────────────────────────────────────────────────


def test_fail_soft_inputs_do_not_raise():
    s = score_event("ABC", None, None, None, reaction_table={}, market_cap=None)
    assert s.direction == 0
    assert s.relevance_weight == pytest.approx(1.0)
    assert -1.5 <= s.value <= 1.5


def test_off_taxonomy_event_uses_default_prior():
    s = score_event("ABC", "not_a_real_type", "positive", 0.5, reaction_table=None)
    assert s.magnitude == pytest.approx(0.10)  # _PRIOR_DEFAULT


# ── M2: forward_return entry="next_open" ──────────────────────────────────────


def _ohlcv_with_gap():
    """5 sessions; day index 1 has an overnight gap up between its close and the
    next open, so close-to-close and next-open entries diverge."""
    idx = pd.date_range("2026-01-05", periods=6, freq="B")
    close = [100.0, 100.0, 110.0, 112.0, 114.0, 116.0]
    open_ = [100.0, 100.0, 108.0, 111.0, 113.0, 115.0]
    return pd.DataFrame({"Open": open_, "Close": close}, index=idx)


def test_forward_return_close_default_unchanged():
    df = _ohlcv_with_gap()
    # event on day 0 (2026-01-05); close-to-close over 2 bars
    r = forward_return(df, datetime(2026, 1, 5), 2)
    assert r == pytest.approx(110.0 / 100.0 - 1.0)


def test_forward_return_next_open_uses_next_session_open():
    df = _ohlcv_with_gap()
    # event on day 0; next_open enters at Open[1]=100, exits at Close[0+2]=110
    r = forward_return(df, datetime(2026, 1, 5), 2, entry="next_open")
    assert r == pytest.approx(110.0 / 100.0 - 1.0)
    # with the gap, an event on day 1 diverges: close entry=Close[1]=100,
    # next_open entry=Open[2]=108, both exiting at Close[3]=112
    r_close = forward_return(df, datetime(2026, 1, 6), 2)
    r_open = forward_return(df, datetime(2026, 1, 6), 2, entry="next_open")
    assert r_close != pytest.approx(r_open)
    assert r_close == pytest.approx(112.0 / 100.0 - 1.0)
    assert r_open == pytest.approx(112.0 / 108.0 - 1.0)


def test_forward_return_next_open_missing_open_column():
    df = _ohlcv_with_gap().drop(columns=["Open"])
    assert forward_return(df, datetime(2026, 1, 5), 2, entry="next_open") is None


# ── imminent_catalyst ─────────────────────────────────────────────────────────


def _earnings_loader(date):
    def _load(ticker):
        return date

    return _load


def test_imminent_catalyst_positive_within_window():
    table = _reaction_table(mean=0.04, count=20)
    asof = datetime(2026, 6, 11)
    sig = imminent_catalyst(
        "NVDA",
        asof,
        reaction_table=table,
        earnings_loader=_earnings_loader(datetime(2026, 6, 12)),
        horizon_bdays=3,
    )
    assert sig is not None
    assert sig.kind == "earnings"
    assert sig.expected_direction == 1
    assert sig.score > 0
    assert sig.days_until == 1


def test_imminent_catalyst_outside_window_returns_none():
    table = _reaction_table(mean=0.04, count=20)
    asof = datetime(2026, 6, 11)
    sig = imminent_catalyst(
        "NVDA",
        asof,
        reaction_table=table,
        earnings_loader=_earnings_loader(datetime(2026, 6, 30)),
        horizon_bdays=3,
    )
    assert sig is None


def test_imminent_catalyst_no_history_direction_zero():
    asof = datetime(2026, 6, 11)
    sig = imminent_catalyst(
        "ZZZ",
        asof,
        reaction_table=None,
        earnings_loader=_earnings_loader(datetime(2026, 6, 12)),
        horizon_bdays=3,
    )
    assert sig is not None
    assert sig.expected_direction == 0  # no upside evidence → won't veto


def test_imminent_catalyst_no_earnings_returns_none():
    sig = imminent_catalyst(
        "NVDA",
        datetime(2026, 6, 11),
        reaction_table=None,
        earnings_loader=_earnings_loader(None),
        horizon_bdays=3,
    )
    assert sig is None


def test_imminent_catalyst_loader_raises_is_fail_soft():
    def _boom(ticker):
        raise RuntimeError("calendar down")

    sig = imminent_catalyst(
        "NVDA", datetime(2026, 6, 11), reaction_table=None, earnings_loader=_boom, horizon_bdays=3
    )
    assert sig is None


# ── exit_veto_block (Gate 2c logic) ───────────────────────────────────────────


_POS_SIGNAL = CatalystSignal("earnings", 1, 1, 0.6, 0.55)
_SCAN = datetime(2026, 6, 11)


def _veto(**kw):
    base = dict(
        reason="signal_exit",
        signal_score=0.40,
        ticker="NVDA",
        scan_at=_SCAN,
        signal=_POS_SIGNAL,
        enabled=True,
        gray_low=0.25,
        gray_high=0.50,
        veto_min_score=0.30,
    )
    base.update(kw)
    return exit_veto_block(**base)


def test_veto_blocks_gray_zone_sell_with_positive_imminent():
    assert _veto() is not None


def test_veto_off_when_flag_disabled():
    assert _veto(enabled=False) is None


def test_veto_off_without_signal():
    assert _veto(signal=None) is None


def test_veto_skips_high_conviction_sell():
    # score above the gray-zone ceiling → the model is confident, execute
    assert _veto(signal_score=0.80) is None


def test_veto_skips_below_gray_low():
    # below gray_low = high-conviction sell (T6.4 bypass band), execute
    assert _veto(signal_score=0.10) is None


def test_veto_skips_risk_exits():
    assert _veto(reason="atr_stop") is None
    assert _veto(reason="vol_trim_overlay") is None


def test_veto_skips_negative_catalyst():
    neg = CatalystSignal("earnings", 1, -1, 0.6, 0.55)
    assert _veto(signal=neg) is None


def test_veto_skips_when_signal_score_below_min():
    weak = CatalystSignal("earnings", 1, 1, 0.1, 0.10)
    assert _veto(signal=weak) is None


def test_veto_skips_none_signal_score():
    assert _veto(signal_score=None) is None
