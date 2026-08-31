"""
Tests del harness ``scripts/run_anomaly_replay_t11b.py`` (Tarea 11, Brazo B).

Cubre los helpers no-triviales del runner, todo offline/sintético (sin Parquet,
sin red): el dominio de la grilla operable, el alineado de retornos para PBO/DSR,
el baseline Monte Carlo time-matched (determinismo + forma) y el leave-one-ticker-out.
La carga de Parquet y la corrida completa se validan aparte (corrida manual).
"""

from __future__ import annotations

from datetime import date, timedelta

from analysis.exit_replay import AtrParams
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import regime_for_date
from scripts.run_anomaly_replay_t11b import (
    aligned_returns,
    loto_edge,
    make_runner,
    operable_entries,
    random_baseline,
)

NO_ATR = AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False)  # solo cap_days
NO_COST = CostModel(commission=0.0, slippage=0.0)


def _d(i: int) -> str:
    return (date(2020, 1, 1) + timedelta(days=i)).isoformat()


def _rising_bars(n: int, start: float = 100.0, step: float = 1.0) -> list:
    """Serie monótona creciente → toda entrada long cierra en ganancia."""
    return [(_d(i), start + step * i, start + step * i, start + step * i, start + step * i) for i in range(n)]


def _common(**kw):
    base = dict(
        max_positions=5,
        initial_capital=50_000.0,
        cap_days=10,
        atr_p=NO_ATR,
        so_params=ScaleOutParams(),
        costs=NO_COST,
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
    )
    base.update(kw)
    return base


# ── operable_entries: dominio ────────────────────────────────────────────────


def test_operable_entries_domain():
    bars_by = {"AAA": _rising_bars(20)}
    ops = operable_entries(bars_by, warmup=5)
    # idx ∈ [warmup+1, n-2] = [6, 18]
    idxs = sorted(i for _, i in ops)
    assert idxs[0] == 6 and idxs[-1] == 18 and len(ops) == 13


def test_operable_entries_multi_ticker():
    bars_by = {"AAA": _rising_bars(20), "BBB": _rising_bars(15)}
    ops = operable_entries(bars_by, warmup=5)
    a = [i for t, i in ops if t == "AAA"]
    b = [i for t, i in ops if t == "BBB"]
    assert len(a) == 13 and len(b) == 8  # [6..18] y [6..13]


# ── aligned_returns: matriz rectangular para PBO/DSR ─────────────────────────


def test_aligned_returns_rectangular():
    bars_by = {"AAA": _rising_bars(40)}
    run = make_runner(bars_by, {}, _common())
    results = {"arm1": run([("AAA", 6)]), "arm2": run([("AAA", 10)])}
    rets = aligned_returns(results, ["arm1", "arm2"])
    lens = {len(v) for v in rets.values()}
    assert len(lens) == 1  # todas las series del mismo largo (rectangular)
    assert all(isinstance(x, float) for v in rets.values() for x in v)


# ── random_baseline: determinismo + forma ────────────────────────────────────


def test_random_baseline_deterministic_and_shaped():
    bars_by = {"AAA": _rising_bars(60), "BBB": _rising_bars(60)}
    run = make_runner(bars_by, {}, _common())
    ops = operable_entries(bars_by, warmup=5)
    by_month: dict[str, list] = {}
    for ti in ops:
        by_month.setdefault(bars_by[ti[0]][ti[1]][0][:7], []).append(ti)
    count_by_month = {m: 2 for m in by_month}  # 2 entradas por mes

    d1 = random_baseline(run, bars_by, count_by_month, by_month, k_random=5, seed0=7)
    d2 = random_baseline(run, bars_by, count_by_month, by_month, k_random=5, seed0=7)
    assert d1 == d2  # mismo seed → idéntico
    assert len(d1["cagr"]) == len(d1["sharpe"]) == len(d1["max_dd"]) == 5


def test_random_baseline_different_seed_differs():
    bars_by = {"AAA": _rising_bars(60), "BBB": _rising_bars(60)}
    run = make_runner(bars_by, {}, _common())
    ops = operable_entries(bars_by, warmup=5)
    by_month: dict[str, list] = {}
    for ti in ops:
        by_month.setdefault(bars_by[ti[0]][ti[1]][0][:7], []).append(ti)
    count_by_month = {m: 3 for m in by_month}
    d1 = random_baseline(run, bars_by, count_by_month, by_month, k_random=8, seed0=1)
    d2 = random_baseline(run, bars_by, count_by_month, by_month, k_random=8, seed0=999)
    assert d1["cagr"] != d2["cagr"]  # distinto seed → muestreo distinto


# ── loto_edge: saca el ticker de mayor aporte ────────────────────────────────


def test_loto_edge_drops_top_contributor():
    bars_by = {"AAA": _rising_bars(60)}  # único ticker → dropearlo vacía la cartera
    run = make_runner(bars_by, {}, _common())
    entries = [("AAA", 10), ("AAA", 30)]
    out = loto_edge(run, entries, random_median_cagr=-1.0)
    assert out is not None
    assert out["dropped"] == "AAA"
    assert out["cagr_without"] == 0.0  # sin entradas no hay curva
    assert out["survives"] is True  # 0.0 > -1.0
