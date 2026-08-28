"""
Tests de la medición del armado del trailing — Tarea 54 (TRAIL-ARM), paso previo.

Pre-registro: ``docs/trail_arm_prereg_t54_2026-08-28.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  trade_excess_atrs       — el excedente máximo sobre la entrada, en ATRs, que es la
                            magnitud contra la que el gate compara el umbral
  differential_population — la población que un brazo **puede mover**: el intervalo
                            (k, base], no la acumulada, que la sobrestima
"""

from __future__ import annotations

from types import SimpleNamespace

from scripts.measure_trail_arm_t54 import (
    LIVE_MIN_EXCESS,
    differential_population,
    trade_excess_atrs,
)


def _bars(n: int = 40, *, pico_en: int | None = None, pico: float = 0.0):
    """Barras sintéticas con rango constante (ATR estable) y un pico opcional."""
    out = []
    for i in range(n):
        base = 100.0
        alto = base + 1.0
        if pico_en is not None and i == pico_en:
            alto = base + pico
        out.append((f"2026-01-{i + 1:02d}", base, alto, base - 1.0, base))
    return out


def _trade(**kw):
    d = {"ticker": "AAA", "entry_date": "2026-01-21", "exit_date": "2026-01-30",
         "ret": 0.05, "held_days": 9}
    d.update(kw)
    return SimpleNamespace(**d)


def test_the_excess_is_measured_in_atrs_over_the_entry_close():
    """El excedente es ``(HWM − close de entrada) / ATR(entrada)`` — la misma
    magnitud que ``gates.atr_exit_decision`` compara contra el umbral."""
    bars = _bars(pico_en=25, pico=6.0)          # +6.00 sobre el close de entrada
    res = SimpleNamespace(trades=[_trade()])
    rows = trade_excess_atrs(res, {"AAA": bars})
    assert len(rows) == 1
    # El ATR de un rango constante de 2.00 converge a 2.00 ⇒ 6.00 / 2.00 = 3.0.
    assert abs(rows[0]["excess_atrs"] - 3.0) < 0.05
    assert rows[0]["ret_pts"] == 5.0


def test_a_trade_that_never_rose_has_a_small_excess_not_a_negative_one():
    """El HWM se toma **desde la entrada**, así que el excedente nunca es negativo:
    el piso es el propio máximo del día de entrada. Un excedente chico es
    exactamente la población que hoy no arma el trailing."""
    res = SimpleNamespace(trades=[_trade()])
    rows = trade_excess_atrs(res, {"AAA": _bars()})
    assert rows[0]["excess_atrs"] >= 0.0
    assert rows[0]["excess_atrs"] < LIVE_MIN_EXCESS


def test_a_trade_without_bars_is_skipped_not_counted_as_zero():
    """Sin barras no hay medición: contarlo como 0 lo metería en la población que
    nunca arma, que es justo el número que la tarea existe para medir."""
    res = SimpleNamespace(trades=[_trade(ticker="ZZZ")])
    assert trade_excess_atrs(res, {"AAA": _bars()}) == []


def test_the_differential_population_is_the_interval_not_the_cumulative():
    """Bajar el umbral de 1.0 a k sólo cambia a los trades con excedente en
    ``(k, 1.0]``: los de arriba ya armaban y los de abajo siguen sin armar.
    La acumulada los sobrestima, y ése es el error que la 51 pagó por el otro eje."""
    excess = [0.1, 0.4, 0.6, 0.9, 1.2, 2.5]
    diff = {d["value"]: d["n_changed"] for d in differential_population(excess, [0.0, 0.5, 1.0])}
    assert diff[0.0] == 4        # 0.1, 0.4, 0.6, 0.9
    assert diff[0.5] == 2        # 0.6, 0.9
    assert diff[1.0] == 0        # es el baseline: no cambia a nadie


def test_raising_the_threshold_disarms_and_that_also_counts():
    """`k > base` no es un caso raro: **desarma** trades que hoy arman, y esa
    población también hay que declararla."""
    excess = [0.5, 1.2, 1.4, 3.0]
    d = differential_population(excess, [1.5])[0]
    assert d["n_changed"] == 2 and d["direction"] == "sube"
    assert d["share"] == 0.5


def test_the_share_is_over_all_trades_not_over_the_affected_ones():
    """El denominador es la cartera entera: es lo que hace comparable el 5% de la
    T13 entre brazos."""
    excess = [0.1] + [5.0] * 9
    d = differential_population(excess, [0.0])[0]
    assert d["n_changed"] == 1 and d["share"] == 0.1
