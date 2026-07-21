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

Extensiones de la Tarea 9 (ver ``docs/meta_labeling_t9_2026-07-21.md`` §7):
  rank_score        — decide quién se queda con el slot escaso, dentro del día
  orden estable     — empates alfabéticos, sin depender del orden de llegada
  invariante        — el ranking tampoco cambia salidas
  re-entrada        — un ticker en cartera no se reabre (como el engine)
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


# ── Ranking entre candidatos del mismo día (Tarea 9) ─────────────────────────
#
# R2 declaró este orden como "no modelado". Para la Tarea 9 es *la variable bajo
# estudio*: con max_positions=5 y 41 tickers hay días con más candidatos que
# slots, y quién se queda con el último lo decide el ranking.


def test_without_rank_score_the_order_is_alphabetical():
    """El default sigue siendo el comportamiento de R2 = el brazo B0_neutral."""
    bars = _flat_bars(40)
    bars_by = {t: bars for t in ("CCC", "AAA", "BBB")}
    entries = [(t, 5) for t in ("CCC", "AAA", "BBB")]
    res = _sim(entries, bars_by, max_positions=2)
    assert [t.ticker for t in res.trades] == ["AAA", "BBB"]


def test_rank_score_decides_who_gets_the_scarce_slot():
    """Mismo día, 3 candidatos, 1 slot: entra el de score más alto."""
    bars = _flat_bars(40)
    bars_by = {t: bars for t in ("AAA", "BBB", "CCC")}
    entries = [(t, 5) for t in ("AAA", "BBB", "CCC")]
    scores = {"AAA": 0.1, "BBB": 0.9, "CCC": 0.5}
    res = _sim(entries, bars_by, max_positions=1,
               rank_score=lambda t, _d: scores[t])
    assert [t.ticker for t in res.trades] == ["BBB"]
    assert res.n_no_slot == 2


def test_rank_score_ties_break_alphabetically_and_deterministically():
    """Con scores discretos los empates son frecuentes: el desempate tiene que
    ser estable, no depender del orden de llegada."""
    bars = _flat_bars(40)
    bars_by = {t: bars for t in ("ZZZ", "AAA")}
    forward = _sim([("ZZZ", 5), ("AAA", 5)], bars_by, max_positions=1,
                   rank_score=lambda _t, _d: 0.5)
    backward = _sim([("AAA", 5), ("ZZZ", 5)], bars_by, max_positions=1,
                    rank_score=lambda _t, _d: 0.5)
    assert [t.ticker for t in forward.trades] == ["AAA"]
    assert [t.ticker for t in backward.trades] == ["AAA"]


def test_rank_score_does_not_reorder_across_days():
    """El ranking compite DENTRO del día. Un candidato de mañana con score alto
    no puede adelantarse al de hoy — eso sería mirar el futuro."""
    bars = _flat_bars(60)
    bars_by = {"A": bars, "B": bars}
    res = _sim([("A", 5), ("B", 6)], bars_by, max_positions=1, cap_days=30,
               rank_score=lambda t, _d: 1.0 if t == "B" else 0.0)
    assert [t.ticker for t in res.trades] == ["A"]
    assert res.n_no_slot == 1


def test_rank_score_never_changes_the_exit_of_a_shared_position():
    """Invariante §2 de la Tarea 9: el ranking solo cambia QUIÉN entra, nunca
    cómo sale el que entró."""
    bars = _ramp_bars(80, start=100.0, step=1.0)
    bars_by = {"AAA": bars, "BBB": bars}
    entries = [("AAA", 5), ("BBB", 5)]
    base = _sim(entries, bars_by, max_positions=2, cap_days=10)
    ranked = _sim(entries, bars_by, max_positions=2, cap_days=10,
                  rank_score=lambda t, _d: 1.0 if t == "BBB" else 0.0)
    base_by = {t.ticker: t for t in base.trades}
    for t in ranked.trades:
        assert t.exit_date == base_by[t.ticker].exit_date
        assert t.ret == pytest.approx(base_by[t.ticker].ret)


# ── Un ticker no se reabre mientras está en cartera (Tarea 9) ────────────────


def test_ticker_already_open_is_not_reentered():
    """Espeja el engine: ``if t in held_tickers ... continue``. Sin esto, el
    simulador podía tener la misma posición dos veces y sobre-contar la señal."""
    bars = _flat_bars(60)
    res = _sim([("A", 5), ("A", 7)], {"A": bars}, max_positions=5, cap_days=30)
    assert res.n_taken == 1
    assert res.n_already_open == 1


def test_reentry_allowed_after_the_position_closed():
    """La regla es 'mientras está abierta', no 'una sola vez por ticker'."""
    bars = _flat_bars(80)
    res = _sim([("A", 5), ("A", 40)], {"A": bars}, max_positions=5, cap_days=10)
    assert res.n_taken == 2
    assert res.n_already_open == 0


def test_reentry_can_be_re_enabled_for_reproducibility():
    """R2 quedó cerrado y publicado con el comportamiento viejo: su runner lo
    pinea con este flag para seguir reproduciendo sus números."""
    bars = _flat_bars(60)
    res = _sim([("A", 5), ("A", 7)], {"A": bars}, max_positions=5, cap_days=30,
               allow_reentry_while_open=True)
    assert res.n_taken == 2
    assert res.n_already_open == 0


def test_counters_add_up_with_the_new_rejection_reason():
    bars = _flat_bars(60)
    bars_by = {"A": bars, "B": bars}
    res = _sim([("A", 5), ("A", 7), ("B", 5)], bars_by, max_positions=1, cap_days=30)
    assert res.n_offered == 3
    assert (res.n_taken + res.n_filtered + res.n_no_slot
            + res.n_no_cash + res.n_already_open) == res.n_offered
