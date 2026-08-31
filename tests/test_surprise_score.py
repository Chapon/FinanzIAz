"""Offline tests for the v0 surprise score (Sprint 5 · T-CAT-5a).

Pure / synthetic — no network, no DB. Covers the surprise-pct math, the
directional aggregation, fail-soft behaviour, the JSON-roundtrip loader, and the
integration point: ``imminent_catalyst`` lets a usable surprise profile override
the (neutral) reaction-mean direction so the exit-veto can actually fire.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from analysis.impact_score import imminent_catalyst
from analysis.surprise_score import (
    DEFAULT_BUILD_INTERVAL_DAYS,
    MIN_QUARTERS,
    SURPRISE_CAP,
    SurpriseProfile,
    build_due,
    build_surprise_profile,
    make_surprise_loader,
    surprise_pct,
)

# ── surprise_pct ──────────────────────────────────────────────────────────────


def test_surprise_pct_basic_beat_and_miss():
    assert surprise_pct(1.0, 1.10) == pytest.approx(0.10)
    assert surprise_pct(2.0, 1.80) == pytest.approx(-0.10)


def test_surprise_pct_uses_abs_estimate_for_negative_consensus():
    # estimate -0.20, reported -0.10 → beat by +0.10/0.20 = +0.5 (capped)
    assert surprise_pct(-0.20, -0.10) == pytest.approx(0.5)


def test_surprise_pct_clips_outliers():
    assert surprise_pct(0.01, 5.0) == pytest.approx(SURPRISE_CAP)
    assert surprise_pct(0.01, -5.0) == pytest.approx(-SURPRISE_CAP)


def test_surprise_pct_missing_or_zero_estimate_is_none():
    assert surprise_pct(None, 1.0) is None
    assert surprise_pct(1.0, None) is None
    assert surprise_pct(0.0, 1.0) is None
    assert surprise_pct(float("nan"), 1.0) is None


# ── build_surprise_profile ────────────────────────────────────────────────────


def _rows(surprises, base_est=1.0):
    """Build (period, est, reported) rows yielding the given surprise fractions."""
    return [(f"2025-q{i}", base_est, base_est * (1 + s)) for i, s in enumerate(surprises)]


def test_consistent_beater_is_positive_directional():
    prof = build_surprise_profile("MRVL", _rows([0.05, 0.08, 0.06, 0.10, 0.07]))
    assert prof.is_usable
    assert prof.direction == 1
    assert prof.directional_score > 0
    assert prof.beat_rate == 1.0
    assert prof.mean_surprise > 0


def test_consistent_misser_is_negative_directional():
    prof = build_surprise_profile("WMT", _rows([-0.04, -0.06, -0.05, -0.03, -0.07]))
    assert prof.is_usable
    assert prof.direction == -1
    assert prof.directional_score < 0
    assert prof.miss_rate == 1.0


def test_insufficient_history_is_neutral():
    prof = build_surprise_profile("XYZ", _rows([0.05, 0.05]))  # < MIN_QUARTERS
    assert prof.n_quarters < MIN_QUARTERS
    assert not prof.is_usable
    assert prof.direction == 0
    assert prof.directional_score == 0.0


def test_mixed_record_damps_toward_zero():
    # 4 small beats but one huge miss flips the mean negative → terms disagree
    prof = build_surprise_profile("MIX", _rows([0.02, 0.02, 0.02, 0.02, -0.50]))
    assert prof.is_usable
    assert abs(prof.directional_score) < 0.5  # damped


def test_last_surprise_takes_most_recent_first_row():
    prof = build_surprise_profile("T", _rows([0.11, 0.01, 0.02, 0.03]))
    assert prof.last_surprise == pytest.approx(0.11)


def test_empty_or_none_rows_neutral_and_failsoft():
    assert build_surprise_profile("A", None).direction == 0
    assert build_surprise_profile("A", []).n_quarters == 0
    # malformed rows are skipped, not raised
    prof = build_surprise_profile("A", [("bad",), None, ("2025", 1.0, 1.05)])
    assert prof.n_quarters == 1


def test_rows_with_unreported_quarters_are_excluded():
    rows = [*_rows([0.05, 0.05, 0.05, 0.05]), ("2026-q1", 1.0, None)]
    prof = build_surprise_profile("A", rows)
    assert prof.n_quarters == 4


# ── make_surprise_loader ──────────────────────────────────────────────────────


def test_loader_roundtrips_profile_dict():
    prof = build_surprise_profile("MRVL", _rows([0.05, 0.08, 0.06, 0.10]))
    loader = make_surprise_loader({"MRVL": prof.to_dict()})
    got = loader("MRVL")
    assert isinstance(got, SurpriseProfile)
    assert got.direction == 1
    assert loader("UNKNOWN") is None


def test_loader_accepts_profile_objects():
    prof = build_surprise_profile("MRVL", _rows([0.05, 0.08, 0.06, 0.10]))
    loader = make_surprise_loader({"MRVL": prof})
    assert loader("MRVL") is prof


# ── integration: imminent_catalyst direction precedence ───────────────────────

ASOF = datetime(2026, 6, 11)
SOON = datetime(2026, 6, 12)  # 1 business day out → imminent


def _earnings_loader(_ticker):
    return SOON


def test_surprise_profile_overrides_neutral_reaction():
    # No reaction table → reaction direction is neutral (0). A usable positive
    # surprise profile must flip the signal to +1 so the veto can fire.
    loader = make_surprise_loader(
        {
            "MRVL": build_surprise_profile("MRVL", _rows([0.05, 0.08, 0.06, 0.10, 0.07])),
        }
    )
    sig = imminent_catalyst(
        "MRVL",
        ASOF,
        reaction_table=None,
        earnings_loader=_earnings_loader,
        surprise_loader=loader,
    )
    assert sig is not None
    assert sig.basis == "surprise"
    assert sig.expected_direction == 1
    assert sig.score > 0


def test_negative_surprise_profile_yields_negative_direction():
    loader = make_surprise_loader(
        {
            "WMT": build_surprise_profile("WMT", _rows([-0.04, -0.06, -0.05, -0.03, -0.07])),
        }
    )
    sig = imminent_catalyst(
        "WMT",
        ASOF,
        reaction_table=None,
        earnings_loader=_earnings_loader,
        surprise_loader=loader,
    )
    assert sig is not None
    assert sig.basis == "surprise"
    assert sig.expected_direction == -1


def test_no_surprise_loader_keeps_reaction_basis():
    sig = imminent_catalyst(
        "MRVL",
        ASOF,
        reaction_table=None,
        earnings_loader=_earnings_loader,
        surprise_loader=None,
    )
    assert sig is not None
    assert sig.basis == "reaction"
    assert sig.expected_direction == 0  # neutral mean, no veto


def test_unusable_profile_falls_back_to_reaction():
    loader = make_surprise_loader(
        {
            "XYZ": build_surprise_profile("XYZ", _rows([0.05, 0.05])),  # too few quarters
        }
    )
    sig = imminent_catalyst(
        "XYZ",
        ASOF,
        reaction_table=None,
        earnings_loader=_earnings_loader,
        surprise_loader=loader,
    )
    assert sig is not None
    assert sig.basis == "reaction"


def test_surprise_loader_failsoft_on_raise():
    def _boom(_ticker):
        raise RuntimeError("loader down")

    sig = imminent_catalyst(
        "MRVL",
        ASOF,
        reaction_table=None,
        earnings_loader=_earnings_loader,
        surprise_loader=_boom,
    )
    assert sig is not None
    assert sig.basis == "reaction"  # degraded gracefully


# ── build_due (weekly rebuild cadence) ────────────────────────────────────────

NOW = datetime(2026, 6, 12, 12, 0, 0)


def test_build_due_when_never_built():
    assert build_due(None, NOW) is True
    assert build_due("", NOW) is True


def test_build_due_on_garbage_timestamp():
    assert build_due("not-a-date", NOW) is True


def test_build_not_due_within_interval():
    last = (NOW - timedelta(days=3)).isoformat()
    assert build_due(last, NOW) is False


def test_build_due_after_interval():
    last = (NOW - timedelta(days=DEFAULT_BUILD_INTERVAL_DAYS, hours=1)).isoformat()
    assert build_due(last, NOW) is True


def test_build_due_exactly_at_interval_boundary():
    last = (NOW - timedelta(days=DEFAULT_BUILD_INTERVAL_DAYS)).isoformat()
    assert build_due(last, NOW) is True  # >= boundary counts as due


def test_build_due_respects_custom_interval():
    last = (NOW - timedelta(days=2)).isoformat()
    assert build_due(last, NOW, interval_days=1) is True
    assert build_due(last, NOW, interval_days=5) is False
