"""Tests para gates.model_exit_fill_price — fill realista de salidas por nivel (T01)."""
from __future__ import annotations

import pytest

from paper_trading.gates import model_exit_fill_price


# ── Stops / trailing (se vende al caer bajo el nivel) ─────────────────────────
def test_stop_gap_open_fills_at_open():
    # La barra abrió 121.99, por debajo del nivel 124.46 → gap → fill = open.
    fill = model_exit_fill_price(
        reason="atr_stop @ ...", trigger_level=124.46,
        bar_open=121.99, bar_high=122.50, bar_low=121.50, current_price=121.99,
    )
    assert fill == pytest.approx(121.99)


def test_stop_intraday_touch_fills_at_level():
    # Abrió 126 (sobre el nivel) pero el mínimo 124.0 tocó el nivel 124.46
    # → el stop se ejecuta en el nivel, no en el cierre peor.
    fill = model_exit_fill_price(
        reason="atr_stop @ ...", trigger_level=124.46,
        bar_open=126.0, bar_high=126.5, bar_low=124.0, current_price=124.20,
    )
    assert fill == pytest.approx(124.46)


def test_trail_gap_open_fills_at_open():
    fill = model_exit_fill_price(
        reason="atr_trail @ ...", trigger_level=314.72,
        bar_open=310.0, bar_high=312.0, bar_low=309.0, current_price=313.98,
    )
    assert fill == pytest.approx(310.0)


def test_stop_fallback_to_current_when_no_bar():
    fill = model_exit_fill_price(
        reason="atr_stop @ ...", trigger_level=100.0,
        bar_open=None, bar_high=None, bar_low=None, current_price=97.5,
    )
    assert fill == pytest.approx(97.5)


def test_stop_low_above_level_falls_back():
    # Caso degenerado: el mínimo nunca tocó el nivel (low 101 > level 100) y no
    # hubo gap (open 102) → no hay precio realista en el nivel → current_price.
    fill = model_exit_fill_price(
        reason="atr_stop @ ...", trigger_level=100.0,
        bar_open=102.0, bar_high=103.0, bar_low=101.0, current_price=99.0,
    )
    assert fill == pytest.approx(99.0)


# ── Take-profit (se vende al subir sobre el nivel) ────────────────────────────
def test_tp_gap_up_fills_at_open():
    # Abrió 110, por encima del nivel TP 104 → gap a favor → fill = open.
    fill = model_exit_fill_price(
        reason="atr_tp @ ...", trigger_level=104.0,
        bar_open=110.0, bar_high=111.0, bar_low=109.0, current_price=110.0,
    )
    assert fill == pytest.approx(110.0)


def test_tp_intraday_touch_fills_at_level():
    # Abrió 100 (bajo el nivel) y el máximo 105 tocó el TP 104 → fill = nivel.
    fill = model_exit_fill_price(
        reason="atr_tp @ ...", trigger_level=104.0,
        bar_open=100.0, bar_high=105.0, bar_low=99.0, current_price=103.5,
    )
    assert fill == pytest.approx(104.0)


# ── Guardas ───────────────────────────────────────────────────────────────────
def test_degenerate_level_returns_current():
    assert model_exit_fill_price(
        reason="atr_stop", trigger_level=0.0,
        bar_open=10.0, bar_high=11.0, bar_low=9.0, current_price=8.0,
    ) == pytest.approx(8.0)


def test_nonpositive_bar_values_ignored():
    # open/low no positivos se ignoran → cae a current_price.
    fill = model_exit_fill_price(
        reason="atr_stop", trigger_level=50.0,
        bar_open=0.0, bar_high=float("nan"), bar_low=-1.0, current_price=48.0,
    )
    assert fill == pytest.approx(48.0)
