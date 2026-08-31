"""
Tests offline del harness ``scripts.run_insider_cluster_replay_t12`` (Tarea 12).
Pre-registro: ``docs/insider_cluster_prereg_t12_2026-07-24.md``.

Cubren las piezas PURAS del harness (sin Parquet, sin red, sin DB):
1. ``events_to_entries`` — mapeo evento→entrada point-in-time (scan ≥ event_date,
   fill a la rueda siguiente), dominio operable ``[warmup+1, n-2]`` y el
   **refractario de 20 ruedas** aplicado en el harness (§2).
2. Mapeo de un ``event_date`` que cae fin de semana → primera barra ≥ fecha, +1.
3. ``build_arm_entries`` — join transacciones×barras + lookup de ranking por $.
4. Desempate de slot por monto en dólares vía ``simulate_portfolio`` (§4.2): con un
   solo slot, el cluster de mayor $ se queda con la entrada.
5. ``gate_blocks`` — gate de conteo mínimo (§3.3).
"""

from __future__ import annotations

from datetime import date, timedelta

from analysis.insider_cluster import ClusterEvent, ClusterParams, InsiderTx
from analysis.portfolio_sim import simulate_portfolio
from analysis.scaleout_replay import CostModel
from scripts.run_insider_cluster_replay_t12 import (
    build_arm_entries,
    events_to_entries,
    gate_blocks,
    make_rank_score,
)

# ── Builders sintéticos ──────────────────────────────────────────────────────


def _weekday_dates(start: str, n: int) -> list[str]:
    """``n`` fechas de días hábiles consecutivos desde ``start`` (ISO)."""
    out: list[str] = []
    d = date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:  # lun-vie
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bars(dates: list[str], price: float = 100.0):
    """Barras planas (OHLC = price) para una lista de fechas."""
    return [(d, price, price, price, price) for d in dates]


def _ev(ticker: str, event_date: str, dollars: float = 1000.0, n_ins: int = 3):
    return ClusterEvent(
        ticker=ticker, event_date=event_date, n_insiders=n_ins, total_dollars=dollars, has_officer=False
    )


# ── events_to_entries ────────────────────────────────────────────────────────


def test_entry_is_next_bar_after_event_on_trading_day():
    dates = _weekday_dates("2022-01-03", 300)  # lun 03-ene
    ev = _ev("ABC", dates[260])  # evento en una barra concreta
    out = events_to_entries([ev], dates, warmup=250, cap_days=20)
    assert out == [(261, 1000.0)]  # scan=260 → entry=261


def test_event_on_weekend_maps_to_first_bar_on_or_after():
    dates = _weekday_dates("2022-01-03", 300)
    # Elegir un viernes y poner el evento el sábado siguiente.
    fri = next(d for d in dates[255:] if date.fromisoformat(d).weekday() == 4)
    fri_idx = dates.index(fri)
    sat = (date.fromisoformat(fri) + timedelta(days=1)).isoformat()
    out = events_to_entries([_ev("ABC", sat)], dates, warmup=250, cap_days=20)
    # scan = primera barra ≥ sábado = el lunes (fri_idx+1); entry = fri_idx+2.
    assert out == [(fri_idx + 2, 1000.0)]


def test_refractory_blocks_second_event_within_20_rows():
    dates = _weekday_dates("2022-01-03", 320)
    evs = [_ev("ABC", dates[260]), _ev("ABC", dates[265])]  # 5 ruedas después
    out = events_to_entries(evs, dates, warmup=250, cap_days=20)
    assert out == [(261, 1000.0)]  # el 2do cae en refractario


def test_refractory_allows_event_after_20_rows():
    dates = _weekday_dates("2022-01-03", 340)
    evs = [_ev("ABC", dates[260]), _ev("ABC", dates[285])]  # 25 ruedas → ambos
    out = events_to_entries(evs, dates, warmup=250, cap_days=20)
    assert out == [(261, 1000.0), (286, 1000.0)]


def test_entry_before_warmup_is_dropped():
    dates = _weekday_dates("2022-01-03", 300)
    out = events_to_entries([_ev("ABC", dates[10])], dates, warmup=250, cap_days=20)
    assert out == []  # entry=11 < warmup+1


def test_event_needs_a_bar_after_entry():
    dates = _weekday_dates("2022-01-03", 300)
    # scan en la última barra → entry = n (fuera de rango, no hay barra posterior).
    out = events_to_entries([_ev("ABC", dates[-1])], dates, warmup=250, cap_days=20)
    assert out == []
    # penúltima barra: entry = n-1 > n-2 → también se descarta (borde superior).
    out2 = events_to_entries([_ev("ABC", dates[-2])], dates, warmup=250, cap_days=20)
    assert out2 == []


def test_event_after_last_bar_is_dropped():
    dates = _weekday_dates("2022-01-03", 300)
    future = (date.fromisoformat(dates[-1]) + timedelta(days=30)).isoformat()
    assert events_to_entries([_ev("ABC", future)], dates, warmup=250, cap_days=20) == []


def test_dollars_carried_through_for_ranking():
    dates = _weekday_dates("2022-01-03", 300)
    out = events_to_entries([_ev("ABC", dates[260], dollars=54321.0)], dates, warmup=250, cap_days=20)
    assert out == [(261, 54321.0)]


# ── build_arm_entries + ranking ──────────────────────────────────────────────


def _cluster_txs(ticker: str, dates: tuple[str, str, str], dollars_each=(1000, 1000, 1000)):
    """3 insiders distintos comprando → un cluster (C=3/W=15 default)."""
    return [
        InsiderTx(
            issuer_ticker=ticker,
            filing_date=d,
            owner_cik=str(i + 1),
            trans_code="P",
            acq_disp="A",
            shares=dollars_each[i] / 10.0,
            price=10.0,
            accession=f"{ticker}-{i}",
            is_officer=False,
            is_director=False,
        )
        for i, d in enumerate(dates)
    ]


def test_build_arm_entries_joins_and_ranks():
    dates = _weekday_dates("2022-01-03", 300)
    # Cluster que cruza a C=3 en dates[260] (3 filings dentro de 15 días).
    trio = (dates[258], dates[259], dates[260])
    txs_by = {"ABC": _cluster_txs("ABC", trio, dollars_each=(1000, 2000, 3000))}
    bars_by = {"ABC": _bars(dates)}
    entries, rank = build_arm_entries(txs_by, bars_by, ClusterParams(), warmup=250, cap_days=20)
    assert entries == [("ABC", 261)]
    # total_dollars = suma de las 3 compras en la ventana = 6000, indexado por
    # (ticker, fecha_de_entrada).
    assert rank[("ABC", dates[261])] == 6000.0


def test_dollar_ranking_wins_the_only_slot():
    """§4.2: dos clusters compiten el mismo día por un único slot → gana el de más $."""
    dates = _weekday_dates("2022-01-03", 300)
    trio = (dates[258], dates[259], dates[260])
    txs_by = {
        "LOWDOL": _cluster_txs("LOWDOL", trio, dollars_each=(100, 100, 100)),  # 300
        "HIGHDOL": _cluster_txs("HIGHDOL", trio, dollars_each=(9000, 9000, 9000)),  # 27000
    }
    bars_by = {"LOWDOL": _bars(dates, 100.0), "HIGHDOL": _bars(dates, 50.0)}
    entries, rank = build_arm_entries(txs_by, bars_by, ClusterParams(), warmup=250, cap_days=20)
    # Ambos entran el mismo día (261) → compiten por el único slot.
    assert sorted(entries) == [("HIGHDOL", 261), ("LOWDOL", 261)]
    res = simulate_portfolio(
        entries,
        bars_by,
        {"LOWDOL": {}, "HIGHDOL": {}},
        max_positions=1,
        initial_capital=50_000.0,
        cap_days=20,
        costs=CostModel(),
        rank_score=make_rank_score(rank),
    )
    assert res.n_taken == 1
    assert res.trades[0].ticker == "HIGHDOL"  # el de mayor monto se queda el slot


# ── gate de conteo mínimo (§3.3) ─────────────────────────────────────────────


def test_gate_blocks_below_minimum():
    assert gate_blocks(100, 150, force=False) is True
    assert gate_blocks(150, 150, force=False) is False  # ≥ min pasa
    assert gate_blocks(200, 150, force=False) is False


def test_gate_force_overrides():
    assert gate_blocks(1, 150, force=True) is False
