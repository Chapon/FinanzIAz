"""
Tests del harness del **bloque 10 + 20** (sizing por riesgo + escalado por régimen).

Cubre las tres piezas nuevas, todo offline/sintético:
  * ``analysis/risk_sizing.py`` — vol realizada, pesos por modo, métricas de cartera.
  * el hook ``size_weight`` de ``portfolio_sim.simulate_portfolio`` (con pesos
    inyectados, para testear el mecanismo de sizing sin acoplarlo a la vol).
  * el modo ``scale`` de ``market_regime.make_entry_filter`` (sweep del factor).
"""

from __future__ import annotations

import pytest

from analysis.exit_replay import AtrParams
from analysis.market_regime import RegimeSeries, make_entry_filter
from analysis.portfolio_sim import simulate_portfolio
from analysis.risk_sizing import (
    cagr,
    make_size_weight,
    realized_vol,
    sharpe_annual,
)
from analysis.scaleout_replay import CostModel, ScaleOutParams

NO_COST = CostModel(commission=0.0, slippage=0.0)
NO_ATR = AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False)  # solo cap_days


def _d(i: int) -> str:
    from datetime import date, timedelta

    return (date(2020, 1, 1) + timedelta(days=i)).isoformat()


def _flat_bars(n: int, close: float = 100.0) -> list:
    return [(_d(i), close, close, close, close) for i in range(n)]


def _osc_bars(n: int, lo: float = 100.0, hi: float = 102.0) -> list:
    out = []
    for i in range(n):
        p = hi if i % 2 else lo
        out.append((_d(i), p, p, p, p))
    return out


def _sim(entries, bars_by, sigs_by=None, **kw):
    kw.setdefault("atr_p", NO_ATR)
    kw.setdefault("costs", NO_COST)
    kw.setdefault("so_params", ScaleOutParams())
    kw.setdefault("cap_days", 10)
    return simulate_portfolio(entries, bars_by, sigs_by or {}, **kw)


# ── risk_sizing: vol realizada ────────────────────────────────────────────────
def test_realized_vol_flat_is_none():
    assert realized_vol(_flat_bars(70), 65, lookback=60) is None


def test_realized_vol_positive_on_moves():
    v = realized_vol(_osc_bars(70), 65, lookback=60)
    assert v is not None and v > 0


def test_realized_vol_insufficient_bars_is_none():
    assert realized_vol(_flat_bars(30), 10, lookback=60) is None


# ── risk_sizing: pesos por modo ───────────────────────────────────────────────
def test_make_size_weight_vol_target():
    sigma = {("A", "d"): 0.10, ("B", "d"): 0.40}
    vt = make_size_weight("vol_target", sigma, vol_target=0.20)
    assert vt("A", "d") == pytest.approx(2.0)  # 0.20/0.10, cap 2.0
    assert vt("B", "d") == pytest.approx(0.5)  # 0.20/0.40


def test_make_size_weight_inverse_vol_clamps_and_falls_back():
    sigma = {("A", "d"): 0.10, ("B", "d"): 0.40}  # mediana global = 0.25
    iv = make_size_weight("inverse_vol", sigma)
    assert iv("A", "d") == pytest.approx(2.0)  # 0.25/0.10=2.5 → clamp 2.0
    assert iv("B", "d") == pytest.approx(0.625)  # 0.25/0.40
    assert iv("Z", "zz") == pytest.approx(1.0)  # σ ausente → mediana/mediana


def test_make_size_weight_equal_and_oracle():
    eq = make_size_weight("equal", {})
    assert eq("A", "d") == 1.0
    o = make_size_weight("oracle", {}, oracle_returns={("A", "d"): 0.25})
    assert o("A", "d") == pytest.approx(2.0)  # 1 + 4·0.25, cap 2.0
    assert o("B", "d") == 1.0  # sin dato → neutral


# ── risk_sizing: métricas de cartera ──────────────────────────────────────────
def test_cagr_doubling_over_a_year():
    curve = [(f"2020-{i:03d}", 100.0 * (2 ** (i / 251))) for i in range(252)]
    assert cagr(curve) == pytest.approx(1.0, rel=0.02)


def test_sharpe_none_on_flat_curve():
    assert sharpe_annual([(f"d{i}", 100.0) for i in range(10)]) is None


# ── portfolio_sim: el hook size_weight escala el notional ─────────────────────
def test_size_weight_none_is_equal_weight():
    """Sin size_weight, dos entradas del mismo día reciben cash/free_slots iguales."""
    bars = _flat_bars(40)
    res = _sim([("A", 5), ("B", 5)], {"A": bars, "B": bars}, max_positions=5, initial_capital=50_000.0)
    inv = {t.ticker: t.invested for t in res.trades}
    assert inv["A"] == pytest.approx(inv["B"], rel=1e-6)


def test_size_weight_scales_notional_by_risk_weight():
    """A pesa 2× y B 0.5× → A invierte más que B (max_weight alto = sin tope)."""
    bars = _flat_bars(40)
    sw = lambda t, _d: {"A": 2.0, "B": 0.5}[t]
    res = _sim(
        [("A", 5), ("B", 5)],
        {"A": bars, "B": bars},
        max_positions=4,
        size_weight=sw,
        max_weight=1.0,
        initial_capital=50_000.0,
    )
    inv = {t.ticker: t.invested for t in res.trades}
    assert inv["A"] > inv["B"]


def test_size_weight_capped_by_max_weight():
    """Un peso enorme se topa a max_weight de la equity."""
    bars = _flat_bars(40)
    res = _sim(
        [("A", 5)],
        {"A": bars},
        max_positions=1,
        size_weight=lambda _t, _d: 5.0,
        max_weight=0.25,
        initial_capital=50_000.0,
    )
    assert res.trades[0].invested <= 0.25 * 50_000.0 + 1.0


# ── market_regime: modo scale (sweep del factor de la tarea 20) ───────────────
def test_make_entry_filter_scale_applies_factor_in_risk_off():
    s = RegimeSeries(dates=["2020-01-01", "2020-01-02"], risk_off=[True, True], streak=[1, 2])
    f = make_entry_filter(s, mode="scale", factor=0.3)
    assert f("X", "2020-01-03") == pytest.approx(0.3)  # día previo risk-off
    assert f("X", "2019-12-31") == 1.0  # sin historia → risk-on
