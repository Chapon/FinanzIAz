"""
Tests para analysis/scaleout_replay — Tarea 7 (scale-out parcial + trailing).

Todo sintético/offline: barras generadas a mano, señal PIT como dict, sin DB ni
red. Pre-registro: docs/scaleout_trailing_t7_2026-07-20.md.

Cubre:
  AtrParams.trail_mult   — split trailing/stop, back-compat (None → stop_mult)
  CostModel              — la fricción se cobra en las dos puntas
  replay_cycle baseline  — sell_fraction=1.0 reproduce el cierre total de hoy
  scale-out              — vende la fracción, el remanente sigue vivo bajo ATR
  segundo flip           — cierra el remanente (no vende mitades eternamente)
  Gate 2b                — el SELL prematuro se difiere salvo score < bypass
  HWM no se resetea      — el trailing del remanente usa el HWM del ciclo
  jerarquía A4           — en los extremos manda el nivel (cierre entero)
  cap / MAE / MFE
"""

from __future__ import annotations

import pytest

from analysis.exit_replay import AtrParams, atr_exit
from analysis.scaleout_replay import (
    CostModel,
    ScaleOutParams,
    replay_cycle,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _d(i: int) -> str:
    """Calendario lineal sintético D01.. (solo se comparan strings)."""
    return f"2026-03-{i:02d}" if i <= 31 else f"2026-04-{i - 31:02d}"


def flat_bars(n: int, close: float = 100.0, tr: float = 2.0) -> list:
    """n barras con close constante y rango (H-L) = tr → ATR converge a tr."""
    return [(_d(i + 1), close, close + tr / 2, close - tr / 2, close) for i in range(n)]


def ramp_bars(n: int, start: float = 100.0, step: float = 1.0, tr: float = 2.0) -> list:
    """n barras con close subiendo ``step`` por día."""
    out = []
    for i in range(n):
        c = start + i * step
        out.append((_d(i + 1), c, c + tr / 2, c - tr / 2, c))
    return out


NO_COST = CostModel(commission=0.0, slippage=0.0)


# ── AtrParams.trail_mult (split trailing vs stop) ────────────────────────────


def test_trail_mult_default_is_backcompat():
    """Sin fijar trail_mult, el trailing usa stop_mult — comportamiento histórico."""
    p = AtrParams(stop_mult=2.0)
    assert p.effective_trail_mult == 2.0


def test_trail_mult_overrides_only_the_trail():
    p = AtrParams(stop_mult=2.0, trail_mult=3.0)
    assert p.effective_trail_mult == 3.0
    assert p.stop_mult == 2.0  # el stop duro NO se movió (A1 quedó NO-SHIP)


def test_wider_trail_does_not_fire_where_narrow_one_does():
    """Mismo escenario: trail 2.0 dispara, trail 3.0 aguanta."""
    # HWM 120, avg_cost 100, ATR 5 → trail@2.0 = 110 ; trail@3.0 = 105
    common = dict(current_price=108.0, avg_cost=100.0, high_water_mark=120.0,
                  atr_value=5.0)
    assert atr_exit(**common, p=AtrParams(stop_mult=2.0)) == "atr_trail"
    assert atr_exit(**common, p=AtrParams(stop_mult=2.0, trail_mult=3.0)) is None


# ── CostModel ────────────────────────────────────────────────────────────────


def test_costs_charged_on_both_sides():
    c = CostModel(commission=0.001, slippage=0.0005)
    # comprar 10 a 100 = 1000 bruto + 0.15% = 1001.5
    assert c.buy_cost(10, 100.0) == pytest.approx(1001.5)
    # vender 10 a 100 = 1000 bruto − 0.15% = 998.5
    assert c.sell_proceeds(10, 100.0) == pytest.approx(998.5)


# ── Baseline: sell_fraction=1.0 reproduce el engine de hoy ───────────────────


def test_baseline_signal_sell_closes_everything():
    bars = flat_bars(30)
    # flip a SELL en el día 10 (índice 9), ya pasada la histéresis
    signals = {_d(10): "SELL"}
    res = replay_cycle(
        bars, 0, signals,
        params=ScaleOutParams(sell_fraction=1.0),
        atr_p=AtrParams(), costs=NO_COST,
    )
    assert res is not None
    assert len(res.legs) == 1
    assert res.legs[0].reason == "signal_full"
    assert res.legs[0].shares == pytest.approx(res.shares)


def test_scaleout_sells_only_the_fraction_and_keeps_the_rest():
    bars = flat_bars(30)
    signals = {_d(10): "SELL"}
    res = replay_cycle(
        bars, 0, signals,
        params=ScaleOutParams(sell_fraction=0.5),
        atr_p=AtrParams(), costs=NO_COST,
    )
    assert res is not None
    assert res.legs[0].reason == "signal_partial"
    assert res.legs[0].shares == pytest.approx(res.shares * 0.5)
    # el remanente sigue vivo hasta el cap
    assert res.legs[-1].reason == "cap_reached"
    assert res.legs[-1].shares == pytest.approx(res.shares * 0.5)


def test_second_flip_closes_the_remnant():
    """Un SELL crónico no puede ir vendiendo mitades para siempre."""
    bars = flat_bars(30)
    signals = {_d(10): "SELL", _d(12): "SELL"}
    res = replay_cycle(
        bars, 0, signals,
        params=ScaleOutParams(sell_fraction=0.5),
        atr_p=AtrParams(), costs=NO_COST,
    )
    assert [l.reason for l in res.legs] == ["signal_partial", "signal_full"]
    assert res.legs[1].date == _d(12)
    assert sum(l.shares for l in res.legs) == pytest.approx(res.shares)


# ── Gate 2b (histéresis T6.4) ────────────────────────────────────────────────


def test_premature_signal_sell_is_deferred():
    """SELL en el día 2 con min_age 3 → se ignora; el ciclo llega al cap."""
    bars = flat_bars(30)
    signals = {_d(2): "SELL"}
    res = replay_cycle(
        bars, 0, signals,
        params=ScaleOutParams(sell_fraction=0.5, min_age_bdays=3),
        atr_p=AtrParams(), costs=NO_COST,
    )
    assert [l.reason for l in res.legs] == ["cap_reached"]


def test_low_score_bypasses_hysteresis():
    """Score < bypass_score ⇒ el SELL prematuro sí ejecuta (convicción de salir)."""
    bars = flat_bars(30)
    signals = {_d(2): "SELL"}
    res = replay_cycle(
        bars, 0, signals,
        params=ScaleOutParams(sell_fraction=0.5, min_age_bdays=3, bypass_score=0.25),
        atr_p=AtrParams(), costs=NO_COST,
        scores={_d(2): 0.10},
    )
    assert res.legs[0].reason == "signal_partial"
    assert res.legs[0].date == _d(2)


# ── El HWM no se resetea en el scale-out ─────────────────────────────────────


def test_hwm_not_reset_by_scaleout():
    """Tras el parcial, el trailing del remanente usa el HWM del ciclo entero.

    El precio sube a ~129, flipea SELL, y después cae. Con el HWM alto el trailing
    tiene que disparar en la caída; si el scale-out lo hubiera reseteado al precio
    del parcial, el remanente sobreviviría hasta el cap.

    El TP se desactiva (``tp_mult`` enorme) para aislar el trailing: con el TP vivo
    una rampa larga sale por ``atr_tp`` apenas el ATR queda disponible (índice 14) y
    el escenario no llega a probar nada.
    """
    up = ramp_bars(30, start=100.0, step=1.0, tr=2.0)     # 100 → 129
    down = []
    for k in range(10):
        c = 129.0 - (k + 1) * 3.0
        down.append((_d(31 + k), c, c + 1.0, c - 1.0, c))
    bars = up + down
    signals = {_d(30): "SELL"}
    res = replay_cycle(
        bars, 0, signals,
        params=ScaleOutParams(sell_fraction=0.5),
        atr_p=AtrParams(tp_mult=1e9), costs=NO_COST, cap_days=39,
    )
    assert res.legs[0].reason == "signal_partial"
    assert res.legs[-1].reason == "atr_trail", (
        f"el remanente debía salir por trailing, salió por {res.legs[-1].reason}"
    )
    # y salió antes del cap, no arrastrado hasta el final
    assert res.legs[-1].date < _d(40)


# ── Jerarquía nivel-vs-señal (gap A4) ────────────────────────────────────────


def test_a4_signal_never_sells_levels_rule():
    """gap A4 'los niveles mandan' = sell_fraction 0.0: la señal no vende nunca."""
    bars = flat_bars(30)
    signals = {_d(10): "SELL", _d(12): "SELL", _d(15): "SELL"}
    res = replay_cycle(
        bars, 0, signals,
        params=ScaleOutParams(sell_fraction=0.0),
        atr_p=AtrParams(), costs=NO_COST,
    )
    # ningún tramo por señal: solo el cap (o un nivel, si hubiera disparado)
    assert [l.reason for l in res.legs] == ["cap_reached"]


def test_a4_levels_still_close_the_whole_position():
    """Con sell_fraction=0.0 los niveles siguen cerrando entero (no son parciales)."""
    # rampa: el TP (avg_cost + 4×ATR ≈ 108) dispara apenas hay ATR (índice 14)
    bars = ramp_bars(40, start=100.0, step=1.0, tr=2.0)
    signals = {_d(20): "SELL"}
    res = replay_cycle(
        bars, 0, signals,
        params=ScaleOutParams(sell_fraction=0.0),
        atr_p=AtrParams(), costs=NO_COST,
    )
    assert len(res.legs) == 1
    assert res.legs[0].reason == "atr_tp"
    assert res.legs[0].shares == pytest.approx(res.shares)


# ── Cap, MAE/MFE, bordes ─────────────────────────────────────────────────────


def test_cap_closes_position():
    bars = flat_bars(60)
    res = replay_cycle(bars, 0, {}, params=ScaleOutParams(),
                       atr_p=AtrParams(), costs=NO_COST, cap_days=20)
    assert res.legs[-1].reason == "cap_reached"
    assert res.legs[-1].date == _d(21)


def test_mfe_and_mae_tracked():
    bars = ramp_bars(15, start=100.0, step=1.0, tr=1.0)
    res = replay_cycle(bars, 0, {}, params=ScaleOutParams(),
                       atr_p=AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False),
                       costs=NO_COST, cap_days=10)
    assert res.mfe > 0.09          # subió ~10%
    assert res.mae == pytest.approx(0.0)


def test_returns_none_without_enough_bars():
    assert replay_cycle([], 0, {}, params=ScaleOutParams(), atr_p=AtrParams()) is None
    bars = flat_bars(3)
    assert replay_cycle(bars, 2, {}, params=ScaleOutParams(), atr_p=AtrParams()) is None


def test_signal_on_a_date_without_bar_is_ignored():
    """Una señal en una fecha que no es barra (feriado, dato faltante) no hace nada."""
    bars = flat_bars(30)
    res = replay_cycle(bars, 0, {"2026-03-10T00:00": "SELL", "1999-01-01": "SELL"},
                       params=ScaleOutParams(sell_fraction=0.5),
                       atr_p=AtrParams(), costs=NO_COST)
    assert [l.reason for l in res.legs] == ["cap_reached"]


def test_proportional_costs_do_not_penalise_splitting_the_exit():
    """Con costos **proporcionales**, partir la salida en dos no cuesta nada extra.

    0.15%·X + 0.15%·Y = 0.15%·(X+Y). Es la verdad del modelo de costos de la cuenta
    viva (commission 0.1% + slippage 0.05%, ambos % del notional), y contradice la
    intuición de que "un fill más = más fricción": esa intuición solo vale con
    comisión fija por ticket o mínimo por operación.
    """
    bars = flat_bars(30)
    signals = {_d(10): "SELL"}
    costs = CostModel(commission=0.001, slippage=0.0005)
    base = replay_cycle(bars, 0, signals, params=ScaleOutParams(sell_fraction=1.0),
                        atr_p=AtrParams(), costs=costs)
    scaled = replay_cycle(bars, 0, signals, params=ScaleOutParams(sell_fraction=0.5),
                          atr_p=AtrParams(), costs=costs)
    assert len(base.legs) == 1
    assert len(scaled.legs) == 2          # efectivamente son dos fills
    # ...y aun así, con precio plano, el retorno es idéntico
    assert scaled.ret == pytest.approx(base.ret)
