"""Unit tests for the R1 drawdown circuit breaker (pure detector).

Offline: no DB, no network. Exercises the rolling-window peak, the trigger
boundary, the fail-safe paths, and the live-account scenario that motivated the
pre-registered 15 % / 90d threshold.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from paper_trading.dd_breaker import (
    compute_drawdown_state,
    format_breaker_warning,
)

NOW = datetime(2026, 7, 8, 12, 0, 0)


def _snap(days_ago: float, equity: float) -> tuple[datetime, float]:
    return (NOW - timedelta(days=days_ago), equity)


def test_ascending_curve_no_drawdown():
    """A strictly rising equity curve is never in drawdown."""
    snaps = [_snap(80, 100.0), _snap(40, 110.0), _snap(5, 120.0)]
    st = compute_drawdown_state(130.0, snaps, threshold_pct=0.15, window_days=90, now=NOW)
    assert st.drawdown_pct == 0.0
    assert st.triggered is False
    assert st.peak_at is None  # current equity is the peak


def test_valley_triggers_at_threshold():
    """Peak 100 → current 85 = 15% DD arms at a 15% threshold (>=)."""
    snaps = [_snap(60, 100.0), _snap(10, 90.0)]
    st = compute_drawdown_state(85.0, snaps, threshold_pct=0.15, window_days=90, now=NOW)
    assert st.drawdown_pct == 0.15
    assert st.triggered is True
    assert st.peak_equity == 100.0
    assert st.peak_at == snaps[0][0]


def test_just_below_threshold_does_not_trigger():
    snaps = [_snap(30, 100.0)]
    st = compute_drawdown_state(85.5, snaps, threshold_pct=0.15, window_days=90, now=NOW)
    assert abs(st.drawdown_pct - 0.145) < 1e-9
    assert st.triggered is False


def test_rolling_window_ignores_stale_peak():
    """A peak older than window_days must not count (rolling, not all-time)."""
    snaps = [
        _snap(120, 200.0),  # stale high, outside the 90d window
        _snap(30, 100.0),  # in-window peak
    ]
    st = compute_drawdown_state(90.0, snaps, threshold_pct=0.15, window_days=90, now=NOW)
    # Peak is the in-window 100, not the stale 200 → DD 10%, not 55%.
    assert st.peak_equity == 100.0
    assert abs(st.drawdown_pct - 0.10) < 1e-9
    assert st.triggered is False
    assert st.n_snapshots_in_window == 1


def test_no_snapshots_never_triggers():
    st = compute_drawdown_state(50.0, [], threshold_pct=0.15, window_days=90, now=NOW)
    assert st.drawdown_pct == 0.0
    assert st.triggered is False
    assert st.peak_equity == 50.0


def test_current_is_new_high():
    """Current equity above every snapshot ⇒ no drawdown, peak_at None."""
    snaps = [_snap(50, 100.0), _snap(10, 110.0)]
    st = compute_drawdown_state(120.0, snaps, threshold_pct=0.15, window_days=90, now=NOW)
    assert st.drawdown_pct == 0.0
    assert st.triggered is False
    assert st.peak_at is None


def test_nonpositive_peak_fails_safe():
    """Corrupt/zero equities never arm the breaker (no div-by-zero)."""
    snaps = [_snap(30, 0.0), _snap(10, -5.0)]
    st = compute_drawdown_state(0.0, snaps, threshold_pct=0.15, window_days=90, now=NOW)
    assert st.drawdown_pct == 0.0
    assert st.triggered is False


def test_none_equities_ignored():
    snaps = [_snap(40, None), _snap(20, 100.0), _snap(5, None)]
    st = compute_drawdown_state(80.0, snaps, threshold_pct=0.15, window_days=90, now=NOW)
    assert st.peak_equity == 100.0
    assert st.n_snapshots_in_window == 1
    assert st.triggered is True  # 20% DD


def test_live_account_scenario_does_not_trigger_at_15pct():
    """The 2026-07-07 live state (~9.5% DD) must NOT arm at the chosen 15%.

    Validates the pre-registered threshold: peak 54_415 (14/5), equity 49_257.
    """
    snaps = [_snap(55, 54_415.0), _snap(20, 51_000.0)]
    st = compute_drawdown_state(49_257.0, snaps, threshold_pct=0.15, window_days=90, now=NOW)
    assert abs(st.drawdown_pct - 0.0948) < 5e-4
    assert st.triggered is False  # 9.5% < 15% → still open, as intended
    # …and a 9% threshold WOULD have armed it (sanity of the arithmetic).
    st9 = compute_drawdown_state(49_257.0, snaps, threshold_pct=0.09, window_days=90, now=NOW)
    assert st9.triggered is True


def test_threshold_zero_arms_on_any_loss():
    """threshold 0 is the strictest setting (any drawdown arms), not a no-op."""
    snaps = [_snap(10, 100.0)]
    st = compute_drawdown_state(99.0, snaps, threshold_pct=0.0, window_days=90, now=NOW)
    assert st.triggered is True


def test_format_warning_mentions_numbers():
    snaps = [_snap(60, 100.0)]
    st = compute_drawdown_state(80.0, snaps, threshold_pct=0.15, window_days=90, now=NOW)
    msg = format_breaker_warning(st)
    assert "20.0%" in msg  # drawdown
    assert "15.0%" in msg  # threshold
    assert "90d" in msg
    assert "manual" in msg.lower()
