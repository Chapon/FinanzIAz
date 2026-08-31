"""Tests para el fill realista de exit_replay (mirror stdlib de model_exit_fill_price)."""

from __future__ import annotations

import pytest

from analysis.exit_replay import AtrParams, _atr_trigger_level, _exit_fill_price


# ── _atr_trigger_level ────────────────────────────────────────────────────────
def test_trigger_level_stop():
    p = AtrParams(stop_mult=2.0)
    # stop = avg_cost - stop_mult*atr = 100 - 2*5 = 90
    assert _atr_trigger_level("atr_stop", avg_cost=100.0, hwm=120.0, atr_value=5.0, p=p) == pytest.approx(
        90.0
    )


def test_trigger_level_trail_uses_hwm():
    p = AtrParams(stop_mult=2.0)
    # trail = hwm - stop_mult*atr = 120 - 10 = 110
    assert _atr_trigger_level("atr_trail", avg_cost=100.0, hwm=120.0, atr_value=5.0, p=p) == pytest.approx(
        110.0
    )


def test_trigger_level_tp():
    p = AtrParams(tp_mult=4.0)
    # tp = avg_cost + tp_mult*atr = 100 + 20 = 120
    assert _atr_trigger_level("atr_tp", avg_cost=100.0, hwm=100.0, atr_value=5.0, p=p) == pytest.approx(120.0)


def test_trigger_level_unknown_reason():
    assert _atr_trigger_level("cap_reached", avg_cost=100.0, hwm=100.0, atr_value=5.0, p=AtrParams()) is None


# ── _exit_fill_price ──────────────────────────────────────────────────────────
def _bar(o, h, l, c):
    return ("2026-05-21", o, h, l, c)


def test_fill_stop_gap_open():
    # open 88 <= level 90 → gap → fill = open (no el close 85)
    assert _exit_fill_price("atr_stop", 90.0, _bar(88.0, 89.0, 84.0, 85.0)) == pytest.approx(88.0)


def test_fill_stop_intraday_touch():
    # open 92 > level 90 pero low 88 <= 90 → touch → fill = level (no el close 89)
    assert _exit_fill_price("atr_stop", 90.0, _bar(92.0, 93.0, 88.0, 89.0)) == pytest.approx(90.0)


def test_fill_stop_fallback_close():
    # ni gap ni touch (low 91 > level 90) → close
    assert _exit_fill_price("atr_stop", 90.0, _bar(92.0, 93.0, 91.0, 91.5)) == pytest.approx(91.5)


def test_fill_tp_gap_up():
    # open 122 >= level 120 → fill open
    assert _exit_fill_price("atr_tp", 120.0, _bar(122.0, 123.0, 121.0, 122.5)) == pytest.approx(122.0)


def test_fill_tp_touch():
    # open 118 < level 120 pero high 121 >= 120 → fill level
    assert _exit_fill_price("atr_tp", 120.0, _bar(118.0, 121.0, 117.0, 119.0)) == pytest.approx(120.0)


def test_fill_degenerate_level():
    assert _exit_fill_price("atr_stop", None, _bar(88.0, 89.0, 84.0, 85.0)) == pytest.approx(85.0)
