"""
Tests offline del harness de RANK-NEUTRAL — Tarea 39.
Pre-registro: ``docs/rank_neutral_prereg_t39_2026-08-19.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  rank_policy          — §5.7: la política es una **función pura** (no depende del
                         orden de llamada) y **estable entre corridas** (blake2b, no
                         ``hash()``, que está randomizado por proceso). Y el contraste
                         que arma el bracket del §4.2: ``neutral_rank`` rota por fecha,
                         ``fixed_rank`` no.
  build_arms           — el baseline rankea por score, el invertido es su opuesto
                         exacto, los oráculos miran el futuro, y **la semilla que se
                         cablearía (12345) es la de ``N_rot_0``**
  evaluate             — el AND de los seis criterios del §6 y **cada caso partido
                         resuelto ex ante**, incluido el que la T21 pisó (bootstrap)
  aligned_daily        — equivalencia exacta con el helper publicado de la T23
  policy_series        — §4.1: la serie de la política es el promedio de las semillas
  regime_window_returns— §6 C5: retorno de CARTERA por ventana de régimen, con el cash
                         contando 0 (medirlo por trade dejaría pasar a un brazo que no
                         juega)
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from analysis.exit_replay import AtrParams
from analysis.portfolio_sim import simulate_portfolio
from analysis.rank_policy import fixed_rank, neutral_rank
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import BULL_NORMAL, regime_window_returns
from scripts.run_rank_neutral_t39 import (
    ANTI_ORACLE_ARM,
    BASELINE_ARM,
    INVERTED_ARM,
    ORACLE_ARM,
    ROT_SEED_BASE,
    aligned_daily,
    build_arms,
    buy_candidates_by_date,
    evaluate,
    fix_name,
    policy_series,
    rank_autocorr,
    rot_name,
)
from scripts.run_tp_cal_replay_t23 import aligned_returns

_D0 = date(2026, 1, 5)


def _d(i: int) -> str:
    return (_D0 + timedelta(days=i)).isoformat()


# ── §5.7 — la política es pura y estable ─────────────────────────────────────


def test_neutral_rank_is_pure_and_independent_of_call_order():
    """El defecto de la T21 (tarea 40): allá el valor salía del **orden de las
    llamadas**. Acá dos recorridos distintos tienen que dar lo mismo, bit a bit."""
    pares = [(_d(i), t) for i in range(5) for t in ("AAA", "BBB", "CCC")]
    directo = {p: neutral_rank(7, *p) for p in pares}
    inverso = {p: neutral_rank(7, *p) for p in reversed(pares)}
    assert directo == inverso
    # Y no cambia por llamarla de nuevo en otro contexto.
    assert all(neutral_rank(7, d, t) == v for (d, t), v in directo.items())


def test_neutral_rank_is_stable_across_runs():
    """Golden value: si cambia, cambia **lo que se shipearía**. ``hash()`` de Python
    está randomizado por proceso y daría un orden distinto en cada scan."""
    assert neutral_rank(12345, "2026-08-19", "AAPL") == pytest.approx(0.9932980858800138, abs=1e-15)
    assert fixed_rank(54321, "AAPL") == pytest.approx(0.8325241622012335, abs=1e-15)


def test_neutral_rank_depends_on_the_three_arguments():
    base = neutral_rank(1, _d(0), "AAA")
    assert neutral_rank(2, _d(0), "AAA") != base  # semilla
    assert neutral_rank(1, _d(1), "AAA") != base  # fecha ⇒ ROTA
    assert neutral_rank(1, _d(0), "BBB") != base  # ticker


def test_fixed_rank_ignores_the_date():
    """Es el contraste que arma el bracket del §4.2: ``P_fix`` es máximamente
    persistente (apuesta a nombres fijos), ``N_rot`` no persiste nada."""
    assert fixed_rank(3, "AAA") == fixed_rank(3, "AAA")
    vals = {neutral_rank(3, _d(i), "AAA") for i in range(10)}
    assert len(vals) == 10  # el rotado cambia todos los días


def test_values_are_in_unit_interval_and_spread_out():
    xs = [neutral_rank(11, _d(i % 50), f"T{i}") for i in range(2000)]
    assert all(0.0 <= x < 1.0 for x in xs)
    assert len(set(xs)) == len(xs)  # sin colisiones
    assert 0.45 < sum(xs) / len(xs) < 0.55  # uniformidad gruesa


# ── §2 — brazos ──────────────────────────────────────────────────────────────


def _fixtures():
    score_by = {"AAA": {_d(1): 0.65}, "BBB": {_d(1): 0.70}}
    realized = {("AAA", _d(1)): 0.30, ("BBB", _d(1)): -0.10}
    return score_by, realized


def test_baseline_ranks_by_score_and_inverted_is_its_exact_opposite():
    score_by, realized = _fixtures()
    arms = build_arms(score_by, realized, n_seeds=1)
    b1, inv = arms[BASELINE_ARM], arms[INVERTED_ARM]
    assert b1("BBB", _d(1)) > b1("AAA", _d(1))
    assert inv("AAA", _d(1)) == pytest.approx(-b1("AAA", _d(1)))
    assert inv("AAA", _d(1)) > inv("BBB", _d(1))


def test_oracle_and_anti_oracle_look_at_the_future():
    score_by, realized = _fixtures()
    arms = build_arms(score_by, realized, n_seeds=1)
    o, a = arms[ORACLE_ARM], arms[ANTI_ORACLE_ARM]
    assert o("AAA", _d(1)) > o("BBB", _d(1))  # AAA rindió más
    assert a("AAA", _d(1)) < a("BBB", _d(1))


def test_shipped_seed_is_the_one_declared_in_the_prereg():
    """§2 congela ``12345`` como la semilla que se cablearía, y es la de ``N_rot_0``.
    Si alguien cambia la base, el doc deja de describir lo que se shipea."""
    assert ROT_SEED_BASE == 12345
    score_by, realized = _fixtures()
    arms = build_arms(score_by, realized, n_seeds=3)
    assert arms[rot_name(0)]("AAA", _d(1)) == neutral_rank(12345, _d(1), "AAA")
    assert arms[rot_name(2)]("AAA", _d(1)) == neutral_rank(12347, _d(1), "AAA")


def test_each_seed_gets_its_own_closure():
    """El bug clásico del ``lambda`` en loop: todos los brazos capturando el último k."""
    score_by, realized = _fixtures()
    arms = build_arms(score_by, realized, n_seeds=4)
    vals = {arms[rot_name(k)]("AAA", _d(1)) for k in range(4)}
    assert len(vals) == 4
    fixed = {arms[fix_name(k)]("AAA", _d(1)) for k in range(4)}
    assert len(fixed) == 4


def test_fixed_arms_do_not_rotate_but_rotated_ones_do():
    score_by, realized = _fixtures()
    arms = build_arms(score_by, realized, n_seeds=1)
    f, n = arms[fix_name(0)], arms[rot_name(0)]
    assert f("AAA", _d(1)) == f("AAA", _d(9))
    assert n("AAA", _d(1)) != n("AAA", _d(9))


# ── §6 — la regla de decisión ────────────────────────────────────────────────


class _Boot:
    def __init__(self, ci_low: float):
        self.ci_low = ci_low


def _sum(cagr=0.10, sharpe=1.0, dd=0.20):
    return {"cagr": cagr, "sharpe": sharpe, "max_dd": dd, "accounting_ok": True}


def _seeds(cagrs, dd=0.20):
    return [_sum(cagr=c, dd=dd) for c in cagrs]


_GOOD_REGIME = {BULL_NORMAL: 0.02, "stress_2018q4": 0.01, "stress_covid_2020": 0.00, "stress_bear_2022": 0.03}
_GOOD_SENS = {"c1_sign": True, "c2": True}


def test_ships_when_all_six_pass():
    v = evaluate(_sum(), _seeds([0.12, 0.13, 0.14]), _Boot(0.002), _GOOD_REGIME, _GOOD_SENS)
    assert v["ship"] is True
    assert "SHIP" in v["outcome"] and "12345" in v["outcome"]


def test_split_case_more_return_worse_drawdown():
    """El caso que la T9 dejó sin especificar (allá el score tenía 6,1 pts MENOS de
    maxDD) y que la T21 vio dado vuelta. La dirección es desconocida: por eso el
    umbral está declarado antes."""
    v = evaluate(_sum(dd=0.20), _seeds([0.15, 0.16, 0.17], dd=0.25), _Boot(0.002), _GOOD_REGIME, _GOOD_SENS)
    assert v["c1_cagr"] is True and v["c3_maxdd"] is False
    assert v["ship"] is False and "caso partido" in v["outcome"]


def test_c2_requires_every_seed_to_win():
    """Se cablea UNA semilla elegida a ciegas: si el resultado depende de cuál toca,
    no hay política validada."""
    v = evaluate(_sum(cagr=0.10), _seeds([0.09, 0.13, 0.14]), _Boot(0.002), _GOOD_REGIME, _GOOD_SENS)
    assert v["c1_cagr"] is True and v["c2_all_seeds"] is False
    assert v["ship"] is False
    assert "2/3" in v["outcome"] and "lead" in v["outcome"]


def test_bootstrap_gate_blocks_a_good_looking_delta():
    """Precedente directo: es exactamente lo que le pasó al alfabético en la T21."""
    v = evaluate(_sum(), _seeds([0.13, 0.14, 0.15]), _Boot(-0.001), _GOOD_REGIME, _GOOD_SENS)
    assert v["c1_cagr"] and v["c2_all_seeds"] and v["c3_maxdd"]
    assert v["c4_bootstrap"] is False and v["ship"] is False
    assert "T21" in v["outcome"]


def test_regime_gate_blocks_when_one_window_bleeds():
    bad = dict(_GOOD_REGIME, stress_bear_2022=-0.0051)
    v = evaluate(_sum(), _seeds([0.13, 0.14, 0.15]), _Boot(0.002), bad, _GOOD_SENS)
    assert v["c5_regime"] is False and v["ship"] is False and "C5" in v["outcome"]


def test_regime_tolerance_is_half_a_point():
    ok = dict(_GOOD_REGIME, stress_bear_2022=-0.0049)
    v = evaluate(_sum(), _seeds([0.13, 0.14, 0.15]), _Boot(0.002), ok, _GOOD_SENS)
    assert v["c5_regime"] is True


def test_sensitivity_gate_blocks_and_missing_run_is_not_a_pass():
    v = evaluate(
        _sum(), _seeds([0.13, 0.14, 0.15]), _Boot(0.002), _GOOD_REGIME, {"c1_sign": True, "c2": False}
    )
    assert v["c6_sensitivity"] is False and v["ship"] is False and "C6" in v["outcome"]
    # Sin corrida de sensibilidad C6 NO se da por pasado.
    v2 = evaluate(_sum(), _seeds([0.13, 0.14, 0.15]), _Boot(0.002), _GOOD_REGIME, None)
    assert v2["c6_sensitivity"] is False and v2["ship"] is False


def test_no_ship_when_the_deficit_does_not_clear_the_threshold():
    v = evaluate(_sum(cagr=0.10), _seeds([0.102, 0.103, 0.104]), _Boot(0.002), _GOOD_REGIME, _GOOD_SENS)
    assert v["c1_cagr"] is False and v["ship"] is False
    assert "caducidad parcial" in v["outcome"]


def test_c1_threshold_is_half_a_point_on_the_median():
    base = _sum(cagr=0.10)
    assert (
        evaluate(base, _seeds([0.104, 0.1051, 0.106]), _Boot(0.002), _GOOD_REGIME, _GOOD_SENS)["c1_cagr"]
        is True
    )
    assert (
        evaluate(base, _seeds([0.103, 0.1049, 0.106]), _Boot(0.002), _GOOD_REGIME, _GOOD_SENS)["c1_cagr"]
        is False
    )


def test_maxdd_tolerance_is_three_points_on_the_median():
    base = _sum(dd=0.20)
    assert (
        evaluate(base, _seeds([0.13, 0.14, 0.15], dd=0.229), _Boot(0.002), _GOOD_REGIME, _GOOD_SENS)[
            "c3_maxdd"
        ]
        is True
    )
    assert (
        evaluate(base, _seeds([0.13, 0.14, 0.15], dd=0.231), _Boot(0.002), _GOOD_REGIME, _GOOD_SENS)[
            "c3_maxdd"
        ]
        is False
    )


def test_broken_accounting_never_ships():
    seeds = _seeds([0.13, 0.14, 0.15])
    seeds[1]["accounting_ok"] = False
    v = evaluate(_sum(), seeds, _Boot(0.002), _GOOD_REGIME, _GOOD_SENS)
    assert v["ship"] is False


# ── §4.1 — series diarias ────────────────────────────────────────────────────


class _Res:
    def __init__(self, curve, initial=100.0):
        self.equity_curve = curve
        self.initial_capital = initial


def test_aligned_daily_coincide_con_aligned_returns():
    """Mismo cálculo que el helper publicado de la T23; lo único que agrega es la
    fecha, que es lo que necesita el C5."""
    results = {
        "a": _Res([(_d(0), 100.0), (_d(1), 110.0), (_d(3), 99.0)]),
        "b": _Res([(_d(0), 100.0), (_d(2), 105.0), (_d(3), 101.0)]),
    }
    flat = aligned_returns(results, ["a", "b"])
    dated = aligned_daily(results, ["a", "b"])
    for arm in ("a", "b"):
        assert [r for _, r in dated[arm]] == flat[arm]
    assert [d for d, _ in dated["a"]] == [_d(1), _d(2), _d(3)]


def test_policy_series_is_the_mean_across_seeds():
    daily = {
        "s0": [(_d(1), 0.10), (_d(2), -0.02)],
        "s1": [(_d(1), 0.00), (_d(2), 0.06)],
    }
    pol = policy_series(daily, ["s0", "s1"])
    assert pol == [(_d(1), pytest.approx(0.05)), (_d(2), pytest.approx(0.02))]
    assert policy_series(daily, []) == []


# ── §6 C5 — retorno de cartera por ventana de régimen ────────────────────────


def test_regime_window_returns_compound_inside_each_window():
    pairs = [("2018-10-05", 0.10), ("2018-11-05", -0.10), ("2021-06-01", 0.05)]
    out = regime_window_returns(pairs)
    assert out["stress_2018q4"] == pytest.approx(1.10 * 0.90 - 1.0)
    assert out[BULL_NORMAL] == pytest.approx(0.05)
    assert out["stress_bear_2022"] == 0.0  # sin días en la muestra


def test_cash_days_count_as_zero_not_as_absent():
    """La razón de ser del helper (§4 de la T38): un brazo que deja de operar en el
    bear tiene ~cero trades ahí. Medido por trade pasaría el criterio sin hacer
    nada; medido a nivel cartera se lo premia sólo si evitó la caída."""
    quieto = [("2022-03-01", 0.0), ("2022-04-01", 0.0)]
    invertido = [("2022-03-01", -0.10), ("2022-04-01", -0.10)]
    assert regime_window_returns(quieto)["stress_bear_2022"] == 0.0
    assert regime_window_returns(invertido)["stress_bear_2022"] < 0.0
    # …y castigado si se pierde la recuperación.
    assert (
        regime_window_returns(quieto)["stress_bear_2022"]
        < regime_window_returns([("2022-03-01", 0.10)])["stress_bear_2022"]
    )


def test_regime_windows_partition_the_sample():
    """Componer los cuatro regímenes reconstruye el retorno total: ninguna barra se
    cuenta dos veces ni se pierde."""
    pairs = [
        ("2018-10-05", 0.03),
        ("2020-03-02", -0.07),
        ("2022-05-05", 0.02),
        ("2024-01-04", 0.01),
        ("2019-07-07", -0.01),
    ]
    out = regime_window_returns(pairs)
    total = 1.0
    for r in pairs:
        total *= 1.0 + r[1]
    prod = 1.0
    for v in out.values():
        prod *= 1.0 + v
    assert prod == pytest.approx(total)


# ── §4.2 — el bracket de persistencia ────────────────────────────────────────


def test_rank_autocorr_brackets_the_two_extremes():
    """Las dos puntas del bracket, medidas con el mismo estadístico: el orden fijo
    no rota (ρ=1) y el rotado no persiste nada (ρ≈0). El ``buy_score`` cae en el
    medio, y ese número es el que dice a cuál punta se parece."""
    pool = {_d(i): ["AAA", "BBB", "CCC", "DDD", "EEE"] for i in range(60)}
    fijo = rank_autocorr(lambda t, d: fixed_rank(9, t), pool)
    rotado = rank_autocorr(lambda t, d: neutral_rank(9, d, t), pool)
    assert fijo == pytest.approx(1.0)
    assert abs(rotado) < 0.25


def test_rank_autocorr_takes_a_lag():
    """El mecanismo que el bracket mide es la concentración del book, y eso se juega
    al **horizonte de tenencia**, no a un día: una clave con autocorrelación diaria
    alta que se desarma en una semana no concentra nada. Por eso el lag se mide, no
    se extrapola."""
    pool = {_d(i): ["AAA", "BBB", "CCC", "DDD", "EEE"] for i in range(60)}
    fijo = lambda t, d: fixed_rank(9, t)
    assert rank_autocorr(fijo, pool, lag=8) == pytest.approx(1.0)
    assert abs(rank_autocorr(lambda t, d: neutral_rank(9, d, t), pool, lag=8)) < 0.25

    # Una clave que alterna entre dos órdenes: correlaciona perfecto a lag par y
    # perfecto-negativo a lag impar. Es el caso que distingue "medir" de "asumir AR(1)".
    def alterna(t, d):
        par = sorted(pool).index(d) % 2 == 0
        base = fixed_rank(9, t)
        return base if par else -base

    assert rank_autocorr(alterna, pool, lag=2) == pytest.approx(1.0)
    assert rank_autocorr(alterna, pool, lag=1) == pytest.approx(-1.0)


def test_rank_autocorr_needs_three_common_names():
    """Con menos de tres candidatos comunes el rho no significa nada; el helper
    saltea el par en vez de inventar un número."""
    pool = {_d(0): ["AAA", "BBB"], _d(1): ["AAA", "BBB"]}
    assert rank_autocorr(lambda t, d: fixed_rank(1, t), pool) is None


def test_buy_candidates_by_date_only_takes_buy_days_in_domain():
    bars = {"AAA": [(_d(i), 10.0, 10.0, 10.0, 10.0) for i in range(6)]}
    sigs = {"AAA": {_d(1): "BUY", _d(3): "BUY", _d(5): "BUY", _d(4): "SELL"}}
    # warmup=2 ⇒ arranca en el índice 2; el último índice (5) queda fuera porque
    # hace falta una barra posterior para el ciclo.
    out = buy_candidates_by_date(bars, sigs, 2)
    assert out == {_d(3): ["AAA"]}


# ── Comportamiento sobre el simulador ────────────────────────────────────────


def _bars(n: int, start: float, step: float):
    out = []
    px = start
    for i in range(n):
        out.append((_d(i), px, px * 1.01, px * 0.99, px))
        px += step
    return out


def test_the_rotated_policy_changes_who_takes_the_slot():
    """Sanity §5.5 en miniatura: con un solo slot y dos candidatos el mismo día, el
    orden es lo único que decide, y el rotado no elige siempre al mismo."""
    bars_by = {"AAA": _bars(40, 100.0, 1.0), "BBB": _bars(40, 50.0, -0.2)}
    sigs = {t: {} for t in bars_by}
    entries = [("AAA", 5), ("BBB", 5)]
    common = dict(
        max_positions=1,
        initial_capital=10_000.0,
        cap_days=10,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        allow_reentry_while_open=False,
    )

    def _taken(fn):
        res = simulate_portfolio(entries, bars_by, sigs, atr_p=AtrParams(), rank_score=fn, **common)
        return {t.ticker for t in res.trades}

    score = _taken(lambda t, d: 1.0 if t == "AAA" else 0.0)
    assert score == {"AAA"}
    # Con semillas distintas la política elige distinto: el orden muerde.
    elegidos = {frozenset(_taken(lambda t, d, _s=s: neutral_rank(_s, d, t))) for s in range(12345, 12365)}
    assert len(elegidos) == 2
