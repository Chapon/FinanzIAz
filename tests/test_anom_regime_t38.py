"""
Tests offline del harness de ANOM-REGIME — Tarea 38.
Pre-registro: ``docs/anom_regime_prereg_t38_2026-08-19.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  evaluate              — el AND de los siete criterios (§6) y **cada caso partido
                          resuelto ex ante**, incluido el que define la tarea: si el
                          gate no arregla el bear es NO-SHIP aunque gane retorno
  C2                    — que se mide a nivel CARTERA por ventana de régimen y exige
                          mejora ESTRICTA en bear_2022 y 2018Q4; y que la tolerancia
                          de −0.50pp es la declarada
  gate_bites            — §5.4: el gate muerde por trades **o** por capital, que es lo
                          que hace falta porque ``G_half`` achica el tamaño sin cambiar
                          necesariamente qué tickets se toman
  detector PIT          — §5.5: ``is_risk_off(d)`` no mira la barra de ``d`` ni
                          ninguna posterior
  el gate no sale       — §5.6: el ``entry_filter`` jamás se consulta para salir
  oráculo con eval_mode — tarea 44: el oráculo puntúa con la misma mecánica de salida
                          que los brazos que valida
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from analysis.exit_replay import AtrParams
from analysis.market_regime import build_regime_series, make_entry_filter
from analysis.portfolio_sim import simulate_portfolio
from analysis.risk_sizing import precompute_oracle_returns
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import BULL_NORMAL
from scripts.run_anom_regime_t38 import (
    C2_STRICT_REGIMES,
    CANDIDATE_ARM,
    GATE_ARMS,
    deployed_capital,
    evaluate,
    gate_bites,
    regime_trade_counts,
)

_D0 = date(2026, 1, 5)


def _d(i: int) -> str:
    return (_D0 + timedelta(days=i)).isoformat()


# ── §6 — la regla de decisión ────────────────────────────────────────────────


class _Boot:
    def __init__(self, ci_low: float):
        self.ci_low = ci_low


def _sum(cagr=0.10, sharpe=1.0, dd=0.20):
    return {"cagr": cagr, "sharpe": sharpe, "max_dd": dd, "accounting_ok": True}


_RB = {"sharpe_p95": 0.60, "cagr_p95": 0.05}
_GOOD_SENS = {"c1_sign": True, "c2_bear": True}
# El baseline sangra en los dos regímenes malos; el candidato los mejora.
_REG_BASE = {BULL_NORMAL: 0.50, "stress_2018q4": -0.10, "stress_covid_2020": 0.05, "stress_bear_2022": -0.20}
_REG_CAND = {BULL_NORMAL: 0.50, "stress_2018q4": -0.04, "stress_covid_2020": 0.05, "stress_bear_2022": -0.05}


_UNSET = object()


def _ev(base=None, cand=None, reg_base=None, reg_cand=None, boot=None, pbo=0.30, sens=_UNSET):
    return evaluate(
        base or _sum(),
        cand or _sum(cagr=0.12),
        reg_base or _REG_BASE,
        reg_cand or _REG_CAND,
        boot or _Boot(0.001),
        _RB,
        pbo,
        _GOOD_SENS if sens is _UNSET else sens,
    )


def test_ships_when_all_seven_pass():
    v = _ev()
    assert v["ship"] is True
    assert "APAGADO detrás de un flag" in v["outcome"]


def test_c1_only_requires_not_costing_return():
    """El gate no existe para agregar retorno, existe para sacar el crash-risk.
    Empatar en CAGR alcanza; perder aunque sea un poco, no."""
    assert _ev(cand=_sum(cagr=0.10))["c1_cagr"] is True  # empate exacto
    assert _ev(cand=_sum(cagr=0.0999))["c1_cagr"] is False


def test_c2_is_the_criterion_that_does_the_work():
    """Si el gate no arregla el bear, no sirve para nada: ése era el ÚNICO motivo
    por el que T11b no shipeó."""
    reg_cand = dict(_REG_CAND, stress_bear_2022=-0.20)  # igual que el baseline
    v = _ev(reg_cand=reg_cand)
    assert v["c1_cagr"] is True
    assert v["c2_strict"] is False and v["c2_regime"] is False
    assert v["ship"] is False
    assert "C2" in v["outcome"] and "ÚNICO motivo" in v["outcome"]


def test_c2_strict_covers_both_bad_regimes():
    for r in C2_STRICT_REGIMES:
        reg_cand = dict(_REG_CAND)
        reg_cand[r] = _REG_BASE[r]  # sin mejora estricta
        assert _ev(reg_cand=reg_cand)["c2_strict"] is False


def test_c2_tolerance_is_half_a_point_in_the_other_regimes():
    ok = dict(_REG_CAND, stress_covid_2020=_REG_BASE["stress_covid_2020"] - 0.0049)
    bad = dict(_REG_CAND, stress_covid_2020=_REG_BASE["stress_covid_2020"] - 0.0051)
    assert _ev(reg_cand=ok)["c2_tolerance"] is True
    assert _ev(reg_cand=bad)["c2_tolerance"] is False


def test_split_case_gate_fixes_the_bear_but_costs_return():
    """Se reporta CUÁNTO cuesta: es el precio del seguro, y con el número se puede
    volver con otro factor en un pre-registro propio."""
    v = _ev(cand=_sum(cagr=0.08))
    assert v["c2_regime"] is True and v["c1_cagr"] is False
    assert v["ship"] is False
    assert "precio del seguro" in v["outcome"]


def test_maxdd_cannot_worsen():
    assert _ev(cand=_sum(cagr=0.12, dd=0.2001))["c3_maxdd"] is False
    assert _ev(cand=_sum(cagr=0.12, dd=0.20))["c3_maxdd"] is True


def test_sharpe_must_beat_both_the_baseline_and_the_random_p95():
    assert _ev(cand=_sum(cagr=0.12, sharpe=0.99))["c4_sharpe"] is False  # < baseline
    assert _ev(base=_sum(sharpe=0.50), cand=_sum(cagr=0.12, sharpe=0.55))["c4_sharpe"] is False  # < p95 azar


def test_bootstrap_floor_allows_a_small_negative():
    """C5 no pide ganar: pide **no destruir valor**."""
    assert _ev(boot=_Boot(-0.0049))["c5_bootstrap"] is True
    assert _ev(boot=_Boot(-0.0051))["c5_bootstrap"] is False


def test_pbo_and_sensitivity_gates():
    assert _ev(pbo=0.51)["c6_pbo"] is False
    assert _ev(pbo=None)["c6_pbo"] is False
    assert _ev(sens={"c1_sign": True, "c2_bear": False})["c7_sensitivity"] is False
    assert _ev(sens=None)["c7_sensitivity"] is False  # sin corrida NO pasa


def test_broken_accounting_never_ships():
    bad = _sum(cagr=0.12)
    bad["accounting_ok"] = False
    assert _ev(cand=bad)["ship"] is False


# ── §5.4 — el gate muerde ────────────────────────────────────────────────────


class _T:
    def __init__(self, ticker, entry_date, invested, regime=BULL_NORMAL, size_factor=1.0):
        self.ticker = ticker
        self.entry_date = entry_date
        self.invested = invested
        self.regime = regime
        self.size_factor = size_factor


class _Res:
    def __init__(self, trades):
        self.trades = trades


def test_gate_bites_by_capital_even_with_identical_trades():
    """``G_half`` achica el tamaño: puede tomar EXACTAMENTE los mismos tickets y aun
    así morder. Medir sólo el solapamiento de trades lo daría por inerte."""
    base = _Res([_T("AAA", _d(1), 1000.0), _T("BBB", _d(2), 1000.0)])
    cand = _Res([_T("AAA", _d(1), 500.0, size_factor=0.5), _T("BBB", _d(2), 1000.0)])
    b = gate_bites(base, cand)
    assert b["trade_diff"] == 0.0
    assert b["capital_diff"] == pytest.approx(0.25)
    assert b["ok"] is True


def test_scaled_share_is_descriptive_and_sees_what_the_criterion_misses():
    """El simulador **redespliega el cash liberado**, así que la suma de lo invertido
    puede quedar casi igual aunque el gate haya mordido en cada risk-off. El
    descriptivo lo ve; el criterio congelado no. (Lección T34 §7.5, aplicada antes
    de correr.)"""
    base = _Res([_T("AAA", _d(1), 1000.0), _T("BBB", _d(2), 1000.0)])
    # Mismo capital total, pero la mitad entró achicada.
    cand = _Res([_T("AAA", _d(1), 500.0, size_factor=0.5), _T("BBB", _d(2), 1500.0)])
    b = gate_bites(base, cand)
    assert b["ok"] is False  # el criterio congelado no lo ve…
    assert b["capital_diff"] == pytest.approx(0.0)
    assert b["scaled_trade_share"] == pytest.approx(0.5)  # …el descriptivo sí
    assert b["scaled_capital_share"] == pytest.approx(0.25)


def test_gate_that_changes_nothing_fails_the_sanity():
    base = _Res([_T("AAA", _d(1), 1000.0), _T("BBB", _d(2), 1000.0)])
    assert gate_bites(base, _Res(list(base.trades)))["ok"] is False


def test_deployed_capital_sums_invested():
    assert deployed_capital(_Res([_T("A", _d(1), 10.0), _T("B", _d(2), 5.0)])) == 15.0


def test_regime_trade_counts_reports_every_regime():
    res = _Res([_T("A", _d(1), 10.0, "stress_bear_2022")])
    counts = regime_trade_counts(res)
    assert counts["stress_bear_2022"] == 1
    assert counts[BULL_NORMAL] == 0 and counts["stress_2018q4"] == 0


# ── §5.5 — el detector es point-in-time ──────────────────────────────────────


def _spy(closes: list[float]):
    return [(_d(i), c, c, c, c) for i, c in enumerate(closes)]


def test_regime_detector_does_not_look_at_the_current_bar_or_later():
    """Serie sintética: 200 barras planas y después una caída. El día en que el SPY
    perfora la SMA200 NO puede estar marcado risk-off — la decisión se toma con la
    información anterior a la barra."""
    closes = [100.0] * 200 + [50.0] * 5
    series = build_regime_series(_spy(closes))
    caida = _d(200)
    assert series.is_risk_off(caida) is False  # la barra de D no cuenta
    assert series.is_risk_off(_d(201)) is True  # al día siguiente sí

    # Y truncar el futuro no cambia ninguna respuesta anterior.
    corta = build_regime_series(_spy(closes[:202]))
    assert [corta.is_risk_off(_d(i)) for i in range(1, 202)] == [
        series.is_risk_off(_d(i)) for i in range(1, 202)
    ]


def test_regime_detector_fails_open_without_history():
    series = build_regime_series(_spy([100.0] * 50))
    assert series.is_risk_off(_d(40)) is False


# ── §5.6 — el gate no toca salidas ───────────────────────────────────────────


def _bars(n: int, start: float, step: float):
    out, px = [], start
    for i in range(n):
        out.append((_d(i), px, px * 1.02, px * 0.98, px))
        px += step
    return out


def test_entry_filter_is_never_consulted_to_exit():
    """Invariante §2 de R2, re-verificada: el filtro sólo se llama con fechas de
    ENTRADA. Si se lo consultara para salir aparecerían fechas posteriores."""
    bars_by = {"AAA": _bars(40, 100.0, 1.0)}
    seen: list[str] = []

    def spy_filter(_ticker, date_iso):
        seen.append(date_iso)
        return 1.0

    res = simulate_portfolio(
        [("AAA", 5)],
        bars_by,
        {"AAA": {}},
        max_positions=1,
        initial_capital=10_000.0,
        cap_days=10,
        atr_p=AtrParams(),
        so_params=ScaleOutParams(),
        costs=CostModel(),
        entry_filter=spy_filter,
        allow_reentry_while_open=False,
    )
    assert res.n_taken == 1
    assert seen == [bars_by["AAA"][5][0]]


def test_hard_gate_suppresses_entries_but_the_cycle_still_exits():
    """Un gate que devuelve 0.0 no toma la posición; no puede dejarla colgada."""
    bars_by = {"AAA": _bars(40, 100.0, 1.0)}
    res = simulate_portfolio(
        [("AAA", 5)],
        bars_by,
        {"AAA": {}},
        max_positions=1,
        initial_capital=10_000.0,
        cap_days=10,
        atr_p=AtrParams(),
        so_params=ScaleOutParams(),
        costs=CostModel(),
        entry_filter=lambda _t, _d: 0.0,
        allow_reentry_while_open=False,
    )
    assert res.n_taken == 0 and res.trades == []


def test_make_entry_filter_covers_every_arm_of_the_prereg():
    """Los cinco brazos del §2 tienen que ser construibles con el overlay ya
    shipeado — el candidato primario no pide mecanismo nuevo."""
    series = build_regime_series(_spy([100.0] * 200 + [50.0] * 5))
    for name, cfg in GATE_ARMS.items():
        filt = make_entry_filter(
            series, mode=cfg["mode"], confirm_days=cfg.get("confirm_days", 5), factor=cfg.get("factor", 0.5)
        )
        assert 0.0 <= filt("AAA", _d(203)) <= 1.0, name
    # Y el primario es exactamente el overlay de T20: 0.50 en risk-off, 1.0 fuera.
    half = make_entry_filter(series, mode=GATE_ARMS[CANDIDATE_ARM]["mode"])
    assert half("AAA", _d(203)) == 0.5
    assert half("AAA", _d(100)) == 1.0


# ── Tarea 44 — el oráculo puntúa con la mecánica de los brazos que valida ─────


def test_oracle_scores_with_the_same_eval_mode_as_the_arms():
    """La 26b sumó el eje close/touch a ``replay_cycle`` pero no llegó al oráculo:
    un harness con los brazos en ``touch`` tenía el oráculo puntuando al ``close``.
    Es la misma mitad de defecto que arregló la T33, en el otro eje."""
    # Barra que perfora el stop por el mínimo y se recupera al close: es
    # exactamente el caso en que las dos reglas difieren.
    bars = [(_d(i), 100.0, 101.0, 99.0, 100.0) for i in range(40)]
    bars[22] = (_d(22), 100.0, 101.0, 60.0, 100.0)  # perfora por el mínimo, cierra arriba
    bars_by = {"AAA": bars}
    kw = dict(atr_p=AtrParams(), so_params=ScaleOutParams(), cap_days=15, costs=CostModel())
    al_close = precompute_oracle_returns([("AAA", 20)], bars_by, {"AAA": {}}, eval_mode="close", **kw)
    al_toque = precompute_oracle_returns([("AAA", 20)], bars_by, {"AAA": {}}, eval_mode="touch", **kw)
    assert al_close != al_toque
    # Default = "close": preserva el comportamiento de todo lo ya publicado.
    assert precompute_oracle_returns([("AAA", 20)], bars_by, {"AAA": {}}, **kw) == al_close
