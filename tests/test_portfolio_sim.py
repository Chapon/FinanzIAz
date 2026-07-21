"""
Tests del simulador de cartera — enabler de la Tarea 8 (R2).

Existe porque el harness de la Tarea 7 daba capital ilimitado y eso inflaba a
cualquier variante que retuviera más tiempo (ver scaleout_trailing_t7 §8.3).
Todo sintético/offline.

Cubre:
  slots finitos     — la entrada sin slot se pierde (no se encola)
  capital finito    — el sizing sale del cash disponible
  reciclado de cash — una salida libera capital para entradas posteriores
  entry_filter      — suprime (0.0) y escala (0.5) el tamaño
  invariante        — el filtro NUNCA cambia la salida de una posición abierta
  contadores        — offered / taken / filtered / no_slot cuadran
"""

from __future__ import annotations

import pytest

from analysis.exit_replay import AtrParams
from analysis.portfolio_sim import simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams

NO_COST = CostModel(commission=0.0, slippage=0.0)
NO_ATR = AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False)  # solo cap


def _d(i: int) -> str:
    from datetime import date, timedelta

    return (date(2020, 1, 1) + timedelta(days=i)).isoformat()


def _flat_bars(n: int, close: float = 100.0) -> list:
    return [(_d(i), close, close, close, close) for i in range(n)]


def _ramp_bars(n: int, start: float = 100.0, step: float = 1.0) -> list:
    return [(_d(i), start + i * step, start + i * step,
             start + i * step, start + i * step) for i in range(n)]


def _sim(entries, bars_by, sigs_by=None, **kw):
    kw.setdefault("atr_p", NO_ATR)
    kw.setdefault("costs", NO_COST)
    kw.setdefault("so_params", ScaleOutParams())
    kw.setdefault("cap_days", 10)
    return simulate_portfolio(entries, bars_by, sigs_by or {}, **kw)


# ── Slots finitos ────────────────────────────────────────────────────────────


def test_entry_without_free_slot_is_dropped_not_queued():
    """5 slots, 8 entradas el mismo día ⇒ se toman 5 y se pierden 3."""
    bars = _flat_bars(40)
    bars_by = {f"T{i}": bars for i in range(8)}
    entries = [(f"T{i}", 5) for i in range(8)]
    res = _sim(entries, bars_by, max_positions=5)
    assert res.n_taken == 5
    assert res.n_no_slot == 3
    assert res.n_offered == 8


def test_slot_frees_up_after_exit():
    """Con cap 10, una entrada muy posterior encuentra el slot liberado."""
    bars = _flat_bars(80)
    bars_by = {"A": bars, "B": bars}
    entries = [("A", 5), ("B", 40)]   # B entra mucho despues del exit de A
    res = _sim(entries, bars_by, max_positions=1, cap_days=10)
    assert res.n_taken == 2
    assert res.n_no_slot == 0


def test_second_entry_blocked_while_first_still_open():
    bars = _flat_bars(40)
    bars_by = {"A": bars, "B": bars}
    entries = [("A", 5), ("B", 7)]    # B llega mientras A sigue abierta
    res = _sim(entries, bars_by, max_positions=1, cap_days=20)
    assert res.n_taken == 1
    assert res.n_no_slot == 1


# ── Capital finito y reciclado ───────────────────────────────────────────────


def test_position_size_comes_from_available_cash():
    bars = _flat_bars(40)
    res = _sim([("A", 5)], {"A": bars}, max_positions=5, initial_capital=50_000.0)
    # 1 entrada con 5 slots libres ⇒ un quinto del cash
    assert res.trades[0].invested == pytest.approx(10_000.0)


def test_profit_is_recycled_into_later_entries():
    """Una salida ganadora agranda el capital disponible para la próxima entrada."""
    bars = _ramp_bars(80, start=100.0, step=2.0)
    bars_by = {"A": bars, "B": bars}
    res = _sim([("A", 5), ("B", 40)], bars_by, max_positions=1,
               cap_days=10, initial_capital=10_000.0)
    assert res.n_taken == 2
    # la segunda entrada invierte mas que la primera porque hubo ganancia
    assert res.trades[1].invested > res.trades[0].invested
    assert res.final_equity > 10_000.0


def test_equity_reflects_a_losing_run():
    bars = _ramp_bars(40, start=100.0, step=-1.0)
    res = _sim([("A", 5)], {"A": bars}, max_positions=1, initial_capital=10_000.0)
    assert res.final_equity < 10_000.0
    assert res.total_return_pts < 0


# ── entry_filter ─────────────────────────────────────────────────────────────


def test_filter_zero_suppresses_the_entry():
    bars = _flat_bars(40)
    res = _sim([("A", 5)], {"A": bars}, max_positions=5,
               entry_filter=lambda _t, _d: 0.0)
    assert res.n_taken == 0
    assert res.n_filtered == 1
    assert res.final_equity == pytest.approx(50_000.0)  # nunca se invirtio


def test_filter_half_halves_the_notional():
    bars = _flat_bars(40)
    full = _sim([("A", 5)], {"A": bars}, max_positions=5)
    half = _sim([("A", 5)], {"A": bars}, max_positions=5,
                entry_filter=lambda _t, _d: 0.5)
    assert half.trades[0].invested == pytest.approx(full.trades[0].invested / 2)
    assert half.trades[0].size_factor == 0.5


def test_filter_can_depend_on_the_date():
    bars = _flat_bars(60)
    bars_by = {"A": bars, "B": bars}
    blocked = _d(5)
    res = _sim([("A", 5), ("B", 30)], bars_by, max_positions=5, cap_days=10,
               entry_filter=lambda _t, d: 0.0 if d == blocked else 1.0)
    assert res.n_filtered == 1
    assert res.n_taken == 1
    assert res.trades[0].ticker == "B"


# ── Invariante: el filtro no toca las salidas ────────────────────────────────


def test_filter_never_changes_the_exit_of_a_position_that_was_opened():
    """Invariante §2 del pre-registro: el gate solo afecta ENTRADAS.

    Una posición que se abre en los dos brazos tiene que salir igual, aunque el
    filtro haya suprimido otras entradas.
    """
    bars = _ramp_bars(80, start=100.0, step=1.0)
    bars_by = {"A": bars, "B": bars}
    entries = [("A", 5), ("B", 40)]
    base = _sim(entries, bars_by, max_positions=5, cap_days=10)
    # filtro que bloquea solo la entrada de B
    gated = _sim(entries, bars_by, max_positions=5, cap_days=10,
                 entry_filter=lambda t, _d: 0.0 if t == "B" else 1.0)
    a_base = next(t for t in base.trades if t.ticker == "A")
    a_gated = next(t for t in gated.trades if t.ticker == "A")
    assert a_gated.exit_date == a_base.exit_date
    assert a_gated.ret == pytest.approx(a_base.ret)
    assert all(t.ticker != "B" for t in gated.trades)


# ── Contadores y bordes ──────────────────────────────────────────────────────


def test_counters_add_up():
    bars = _flat_bars(40)
    bars_by = {f"T{i}": bars for i in range(6)}
    entries = [(f"T{i}", 5) for i in range(6)]
    res = _sim(entries, bars_by, max_positions=2,
               entry_filter=lambda t, _d: 0.0 if t == "T0" else 1.0)
    assert res.n_offered == 6
    assert res.n_taken + res.n_filtered + res.n_no_slot + res.n_no_cash == res.n_offered


def test_no_entries_gives_flat_result():
    res = _sim([], {}, max_positions=5, initial_capital=1234.0)
    assert res.n_offered == 0
    assert res.final_equity == pytest.approx(1234.0)
    assert res.equity_curve == []
    assert res.max_dd == 0.0


def test_unknown_ticker_is_skipped():
    res = _sim([("NOPE", 5)], {"A": _flat_bars(40)}, max_positions=5)
    assert res.n_taken == 0
