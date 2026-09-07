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


from scripts.run_sizing_exposure_t10_t20 import (
    regime_metric_discriminates,
    regime_source_ok_desde,
)


def _bars_llanos(n: int, precio: float = 100.0) -> list[tuple]:
    """n barras subiendo suave: el ciclo llega al cap con P/L != 0.

    **Tiene que moverse.** Con barras planas el P/L es 0 en los dos brazos y
    `pnl_pts` da 0 = 0: el test pasaria por degenerado, "demostrando" que la metrica
    nueva tampoco discrimina. Es el mismo modo de fallar que el guard de la 110
    (la referencia salia de la misma poblacion que chequeaba).
    """
    return [(_d(i), precio + i, precio + i, precio + i, precio + i) for i in range(n)]


# ── El criterio 4 de la T20: ni evaluable ni evaluado — Tarea 120 ────────────


def _dos_brazos():
    """Baseline vs un brazo que sólo cambia el TAMAÑO. Mismos trades, mismo `ret`."""
    bars = _bars_llanos(80)
    bars_by = {"AAA": bars, "BBB": bars}
    sigs = {"AAA": {}, "BBB": {}}
    comun = dict(
        max_positions=5,
        initial_capital=100_000.0,
        cap_days=20,
        atr_p=NO_ATR,
        so_params=ScaleOutParams(),
        costs=NO_COST,
        regime_of=lambda _d: "bull_normal",
    )
    base = simulate_portfolio([("AAA", 30), ("BBB", 31)], bars_by, sigs, **comun)
    chico = simulate_portfolio(
        [("AAA", 30), ("BBB", 31)], bars_by, sigs, size_weight=lambda _t, _d: 0.5, **comun
    )
    return base, chico


def test_el_ret_medio_por_trade_NO_puede_discriminar_un_brazo_de_tamano():
    """El corazón de la tarea 120: la métrica con la que el criterio 4 se reportaba es
    ciega al eje que la T20 puso bajo test.

    Los brazos de sizing/régimen no cambian **qué** trades se toman, cambian **cuánto**
    se invierte. El `ret` de cada ciclo es invariante al notional, así que la tabla
    sale idéntica en los siete brazos — y una tabla idéntica no es un resultado: es un
    instrumento que no mide el eje.
    """
    base, chico = _dos_brazos()
    assert base.trades and chico.trades
    assert not regime_metric_discriminates(base, chico, "mean_ret_pts")


def test_la_contribucion_al_capital_SI_discrimina():
    """La contraprueba, y es la que hace que la tarea tenga sentido: si la métrica
    nueva tampoco distinguiera, el criterio seguiría siendo inevaluable y sólo
    habríamos cambiado el texto."""
    base, chico = _dos_brazos()
    assert regime_metric_discriminates(base, chico, "pnl_pts")


def test_C4_implementa_el_texto_congelado_al_pie_de_la_letra():
    """§5.4: falla **sólo** cuando el beneficio es positivo en UNA ventana y no
    positivo en el resto. Es deliberadamente laxo y se implementa así: apretar en
    septiembre un umbral congelado en julio es lo que la regla 2 prohíbe."""
    ok, det = regime_source_ok_desde({"a": 1.0, "b": -1.0, "c": 0.0, "d": -2.0})
    assert not ok and det["solo_en"] == "a"
    # Positivo en dos ⇒ pasa (no viene de "una sola ventana").
    ok, det = regime_source_ok_desde({"a": 1.0, "b": 2.0, "c": -1.0, "d": 0.0})
    assert ok and det["solo_en"] is None
    # Ningún positivo ⇒ pasa: no hay beneficio del que preguntar de dónde viene,
    # y C1 ya lo habrá frenado. Que C4 lo frene también sería contarlo dos veces.
    ok, _ = regime_source_ok_desde({"a": -1.0, "b": 0.0, "c": -2.0, "d": 0.0})
    assert ok


def test_C4_esta_CABLEADO_a_la_decision_y_no_solo_impreso():
    """El hallazgo de la tarea: `passes_local` miraba beneficio + riesgo + integridad
    y el régimen se imprimía al costado, así que la T20 declaró SHIP sobre cuatro
    criterios **evaluando tres**. Este test fija que el cuarto entre a la decisión.
    """
    import ast
    from pathlib import Path

    txt = (Path(__file__).resolve().parent.parent / "scripts" / "run_sizing_exposure_t10_t20.py").read_text(
        encoding="utf-8"
    )
    arbol = ast.parse(txt)
    asignaciones = [
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Assign)
        and any(
            isinstance(t, ast.Subscript) and getattr(t.slice, "value", None) == "passes_local"
            for t in nodo.targets
        )
    ]
    assert asignaciones, "no encuentro la asignación de passes_local"
    usados = {n.id for n in ast.walk(asignaciones[-1].value) if isinstance(n, ast.Name)}
    assert "regime_ok" in usados, "el criterio 4 volvió a quedar fuera de la decisión"
