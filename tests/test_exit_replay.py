"""
Tests para analysis/exit_replay — T6.1 replay harness de exits.

Todo sintético/offline: barras generadas a mano, sin DB ni red.

Cubre:
  atr_series — semántica Wilder (seed SMA, recursión), None hasta period
  atr_exit — stop / trail (con supresión por min excess) / tp y precedencia
  replay_event — exit diferido, ATR gana el mismo día, cap, sin data → None,
                 seeding del HWM con closes entre entry y sell day
  simulate_variant — passthrough de atr_*, threshold por score, min_holding
  max_drawdown / adjusted_equity_curve — curvas simples
  build_report — kill criteria
"""

from __future__ import annotations

import pytest

from analysis.exit_replay import (
    AtrParams,
    SellEvent,
    adjusted_equity_curve,
    atr_exit,
    atr_series,
    build_report,
    max_drawdown,
    replay_event,
    simulate_variant,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


# Fechas hábiles sintéticas: usamos un calendario lineal D01..D60 (strings
# ordenables); el módulo solo compara/bisecta strings, no parsea fechas.
def _d(i: int) -> str:
    return f"2026-03-{i:02d}" if i <= 31 else f"2026-04-{i - 31:02d}"


def flat_bars(n: int, close: float = 100.0, tr: float = 2.0) -> list:
    """n barras con close constante y rango (H-L) = tr → ATR converge a tr."""
    return [(_d(i + 1), close, close + tr / 2, close - tr / 2, close) for i in range(n)]


def bars_with_closes(closes: list[float], tr: float = 2.0) -> list:
    return [(_d(i + 1), c, c + tr / 2, c - tr / 2, c) for i, c in enumerate(closes)]


def make_event(**kw) -> SellEvent:
    defaults = dict(
        order_id=1,
        ticker="AAA",
        sell_date=_d(20),
        sell_price=100.0,
        reason="analyze SELL (0.35)",
        signal_score=0.35,
        shares=10.0,
        avg_cost=95.0,
        entry_date=_d(17),
        entry_price=95.0,
        sell_commission=1.0,
        sell_slippage=1.0,
    )
    defaults.update(kw)
    return SellEvent(**defaults)


P = AtrParams()  # defaults engine: 14 / 2.0 / 4.0 / trail on


# ── atr_series ───────────────────────────────────────────────────────────────


class TestAtrSeries:
    def test_constant_tr_converges(self):
        bars = flat_bars(30, tr=2.0)
        atrs = atr_series(bars, period=14)
        assert atrs[13] is None
        assert atrs[14] == pytest.approx(2.0)
        assert atrs[-1] == pytest.approx(2.0)

    def test_too_few_bars(self):
        assert atr_series(flat_bars(10), period=14) == [None] * 10

    def test_wilder_recursion(self):
        # 15 barras tr=2, después una barra con tr=4:
        # ATR_15 = (13*2 + 4)/14
        bars = flat_bars(15, tr=2.0)
        c = 100.0
        bars.append((_d(16), c, c + 2.0, c - 2.0, c))
        atrs = atr_series(bars, period=14)
        assert atrs[15] == pytest.approx((13 * 2.0 + 4.0) / 14.0)


# ── atr_exit ─────────────────────────────────────────────────────────────────


class TestAtrExit:
    def test_hard_stop(self):
        r = atr_exit(current_price=90.9, avg_cost=95.0, high_water_mark=95.0, atr_value=2.0, p=P)
        assert r == "atr_stop"  # stop = 95 - 4 = 91

    def test_trail_suppressed_below_min_excess(self):
        # hwm apenas sobre entry (< 1 ATR de exceso) → trail no dispara
        r = atr_exit(current_price=92.5, avg_cost=95.0, high_water_mark=96.5, atr_value=2.0, p=P)
        assert r is None  # trail = 96.5-4 = 92.5 pero hwm <= 95+2

    def test_trail_fires_after_excess(self):
        # hwm = 100 (> 95+2) → trail = 96; precio 95.5 ≤ 96
        r = atr_exit(current_price=95.5, avg_cost=95.0, high_water_mark=100.0, atr_value=2.0, p=P)
        assert r == "atr_trail"

    def test_take_profit(self):
        r = atr_exit(current_price=103.1, avg_cost=95.0, high_water_mark=103.1, atr_value=2.0, p=P)
        assert r == "atr_tp"  # tp = 95 + 8 = 103

    def test_stop_precedence_over_tp(self):
        # entradas degeneradas: stop y tp imposibles a la vez salvo ATR raro;
        # validamos que con precio bajo gana stop aunque tp_mult=0 lo cubriera
        r = atr_exit(
            current_price=80.0, avg_cost=95.0, high_water_mark=95.0, atr_value=2.0, p=AtrParams(tp_mult=0.0)
        )
        assert r == "atr_stop"

    def test_degenerate_inputs(self):
        assert atr_exit(current_price=0.0, avg_cost=95.0, high_water_mark=None, atr_value=2.0, p=P) is None
        assert atr_exit(current_price=100.0, avg_cost=95.0, high_water_mark=None, atr_value=0.0, p=P) is None


# ── replay_event ─────────────────────────────────────────────────────────────


class TestReplayEvent:
    def test_deferred_exit_next_day(self):
        closes = [100.0] * 30
        closes[20] = 102.0  # D+1 (sell en idx 19 = _d(20)); < tp (95+4·2=103)
        bars = bars_with_closes(closes)
        ev = make_event()
        sim = replay_event(ev, bars, scheduled_exit_idx=20, cap_days=20, atr_p=P)
        assert sim is not None
        assert sim.exit_date == _d(21)
        assert sim.exit_price == 102.0
        assert sim.exit_reason == "deferred_signal_sell"
        # pnl_sim = 102*10 - 2 - 95*10 = 68; real = 100*10 - 2 - 950 = 48
        assert sim.pnl_sim == pytest.approx(68.0)
        assert sim.pnl_delta == pytest.approx(20.0)

    def test_deferred_exit_hits_tp_first(self):
        # mismo setup pero el rebote cruza el take-profit → atr_tp gana
        closes = [100.0] * 30
        closes[20] = 104.0  # ≥ tp 103
        bars = bars_with_closes(closes)
        ev = make_event()
        sim = replay_event(ev, bars, scheduled_exit_idx=20, cap_days=20, atr_p=P)
        assert sim.exit_reason == "atr_tp"
        assert sim.exit_price == 104.0

    def test_atr_wins_same_day(self):
        # crash en D+1 por debajo del hard stop (95 - 2*ATR)
        closes = [100.0] * 30
        closes[20] = 85.0
        bars = bars_with_closes(closes)
        ev = make_event()
        sim = replay_event(ev, bars, scheduled_exit_idx=20, cap_days=20, atr_p=P)
        assert sim.exit_reason == "atr_stop"
        assert sim.exit_price == 85.0

    def test_cap_reached(self):
        bars = bars_with_closes([100.0] * 50, tr=2.0)
        ev = make_event(avg_cost=99.0, entry_price=99.0)
        sim = replay_event(ev, bars, scheduled_exit_idx=None, cap_days=5, atr_p=P)
        assert sim.exit_reason == "cap_reached"
        assert sim.exit_date == _d(25)  # sell idx 19 → +5 barras

    def test_no_next_bar_returns_none(self):
        bars = bars_with_closes([100.0] * 20)  # última barra = sell day
        ev = make_event()
        assert replay_event(ev, bars, scheduled_exit_idx=None, cap_days=20, atr_p=P) is None

    def test_sell_day_not_in_bars_returns_none(self):
        bars = bars_with_closes([100.0] * 10)
        ev = make_event(sell_date=_d(25))
        assert replay_event(ev, bars, scheduled_exit_idx=None, cap_days=20, atr_p=P) is None

    def test_hwm_seeded_from_pre_sell_closes(self):
        # pico 110 antes del sell → trail = 110-4 = 106 → dispara D+1 (close 100)
        closes = [100.0] * 30
        closes[18] = 110.0  # entre entry (idx 16) y sell (idx 19)
        bars = bars_with_closes(closes)
        ev = make_event()
        sim = replay_event(ev, bars, scheduled_exit_idx=None, cap_days=20, atr_p=P)
        assert sim.exit_reason == "atr_trail"
        assert sim.exit_date == _d(21)


# ── simulate_variant ─────────────────────────────────────────────────────────


def _loader_for(bars):
    return lambda ticker: bars


class TestSimulateVariant:
    def test_atr_sells_passthrough(self):
        ev = make_event(reason="atr_trail @ 100.00 ≤ 101.00 (peak 110)", signal_score=None)
        sims = simulate_variant([ev], _loader_for(bars_with_closes([100.0] * 30)), "confirm_next_scan")
        assert not sims[0].modified
        assert sims[0].pnl_sim == pytest.approx(ev.pnl_real)

    def test_score_threshold_splits(self):
        bars = bars_with_closes([100.0] * 40)
        lo = make_event(order_id=1, signal_score=0.20, reason="analyze SELL (0.20)")
        hi = make_event(order_id=2, signal_score=0.40, reason="analyze SELL (0.40)")
        sims = simulate_variant([lo, hi], _loader_for(bars), "score_threshold", sell_threshold=0.25)
        assert not sims[0].modified  # 0.20 < 0.25 ejecuta igual
        assert sims[1].modified  # 0.40 se saltea → replay

    def test_min_holding_passthrough_when_old(self):
        bars = bars_with_closes([100.0] * 40)
        # entry idx 16, sell idx 19 → edad 3 ≥ 2 → pasa igual
        ev = make_event()
        sims = simulate_variant([ev], _loader_for(bars), "min_holding", min_holding_days=2)
        assert not sims[0].modified

    def test_min_holding_defers_young_position(self):
        closes = [100.0] * 40
        closes[19] = 103.0  # día del exit diferido (entry idx 16 + 3)
        bars = bars_with_closes(closes)
        ev = make_event(sell_date=_d(18), entry_date=_d(17))  # edad 1 < 3
        sims = simulate_variant([ev], _loader_for(bars), "min_holding", min_holding_days=3)
        assert sims[0].modified
        assert sims[0].exit_date == _d(20)  # idx 16 + 3 = 19
        assert sims[0].exit_reason == "deferred_signal_sell"

    def test_no_data_marks_skip(self):
        ev = make_event()
        sims = simulate_variant([ev], lambda t: None, "confirm_next_scan")
        assert not sims[0].modified
        assert sims[0].exit_reason == "no_data"

    def test_unknown_variant_raises(self):
        with pytest.raises(ValueError):
            simulate_variant([make_event()], lambda t: None, "yolo")


# ── métricas ─────────────────────────────────────────────────────────────────


class TestMetrics:
    def test_max_drawdown(self):
        curve = [(_d(i + 1), v) for i, v in enumerate([100, 110, 99, 105, 95])]
        assert max_drawdown(curve) == pytest.approx(1 - 95 / 110)

    def test_adjusted_curve_freezes_realized_delta(self):
        real = [(_d(i + 1), 1000.0) for i in range(10)]
        ev = make_event(sell_date=_d(3))
        from analysis.exit_replay import SimExit

        sim = SimExit(
            event=ev,
            modified=True,
            exit_date=_d(5),
            exit_price=104.0,
            exit_reason="deferred_signal_sell",
            pnl_sim=ev.pnl_real + 40.0,
            daily_delta=[(_d(4), 20.0), (_d(5), 40.0)],
        )
        adj = adjusted_equity_curve(real, [sim])
        assert adj[2][1] == 1000.0  # antes del replay
        assert adj[3][1] == 1020.0  # MTM día 1
        assert adj[4][1] == 1040.0  # MTM día 2 (exit)
        assert adj[9][1] == 1040.0  # delta realizado congelado

    def test_build_report_kill_criteria(self):
        bars = bars_with_closes([100.0] * 40)
        loader = _loader_for(bars)
        ev = make_event()
        from analysis.exit_replay import SimExit

        # delta enorme y DD plano → pasa
        sim = SimExit(
            event=ev,
            modified=True,
            exit_date=_d(25),
            exit_price=200.0,
            exit_reason="cap_reached",
            pnl_sim=ev.pnl_real + 2000.0,
            daily_delta=[(_d(21), 2000.0)],
        )
        real = [(_d(i + 1), 50_000.0) for i in range(40)]
        rep = build_report("test", [sim], real, initial_capital=50_000.0, bar_loader=loader)
        assert rep.pnl_delta_pts == pytest.approx(4.0)
        assert rep.passes_kill_criteria

        # delta chico → no pasa
        sim2 = SimExit(
            event=ev,
            modified=True,
            exit_date=_d(25),
            exit_price=100.5,
            exit_reason="cap_reached",
            pnl_sim=ev.pnl_real + 5.0,
            daily_delta=[(_d(21), 5.0)],
        )
        rep2 = build_report("test", [sim2], real, initial_capital=50_000.0, bar_loader=loader)
        assert not rep2.passes_kill_criteria
