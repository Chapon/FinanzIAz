"""
Tests offline del harness de EVENT-TIMESTOP — Tarea 51.
Pre-registro: ``docs/event_timestop_prereg_t51_2026-08-28.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  cap_for_all / cap_for_keys — que el tope se aplica a quien corresponde y que la
                               función es PURA (no depende del orden de las llamadas)
  oracle_cap_keys            — que los oráculos quedan igualados en tasa con el
                               candidato, y que miran el retorno realizado
  population_share           — el sanity de la T13 reusado: qué fracción del baseline
                               alcanza el tope, con y sin condicionar al evento
  dose_response              — C6: unimodalidad con tolerancia y el rechazo del pico
                               aislado (la firma del sobreajuste al N que motivó la tarea)
  evaluate_b / evaluate_a    — el AND de cada candidato, y C9 (A tiene que ganarle a B)
  outcome_of                 — cada desenlace del §6 resuelto ex ante, incluido
                               «sin población», que NO es un NO-SHIP
"""

from __future__ import annotations

from types import SimpleNamespace

from scripts.run_event_timestop_t51 import (
    BASE_CAP,
    KILL_A_OVER_B,
    NEIGHBOUR_SHARE,
    SANITY_MIN_POPULATION,
    cap_for_all,
    cap_for_keys,
    dose_response,
    evaluate_a,
    evaluate_b,
    oracle_cap_keys,
    outcome_of,
    population_share,
)


# ── El tope por posición ─────────────────────────────────────────────────────


def test_cap_for_all_caps_every_position():
    f = cap_for_all(12)
    assert f("AAPL", "2024-01-02") == 12
    assert f("MSFT", "2020-06-30") == 12


def test_cap_for_keys_only_caps_the_event_and_leaves_the_rest_alone():
    """La condición es la clave ``(ticker, fecha)``: el mismo ticker entrando otro
    día NO lleva el tope corto."""
    keys = {("AAPL", "2024-01-02")}
    f = cap_for_keys(keys, 15)
    assert f("AAPL", "2024-01-02") == 15
    assert f("AAPL", "2024-03-05") == BASE_CAP
    assert f("MSFT", "2024-01-02") == BASE_CAP


def test_cap_for_keys_is_pure():
    """T39 §5.7: el resultado no puede depender del orden de las llamadas ni del
    estado de la cartera, o los brazos dejan de ser comparables."""
    keys = {("A", "2024-01-02"), ("B", "2024-01-03")}
    f = cap_for_keys(keys, 20)
    first = [f(t, d) for t, d in [("A", "2024-01-02"), ("B", "2024-01-03"), ("C", "x")]]
    second = [f(t, d) for t, d in [("C", "x"), ("B", "2024-01-03"), ("A", "2024-01-02")]]
    assert first == [20, 20, BASE_CAP]
    assert second == [BASE_CAP, 20, 20]


# ── Oráculos igualados en tasa ───────────────────────────────────────────────


_CANDS = {"2024-01-02": ["A", "B", "C", "D"], "2024-01-03": ["E", "F"]}
_N_BY_DATE = {"2024-01-02": 2, "2024-01-03": 1}
_REALIZED = {
    ("A", "2024-01-02"): 0.30, ("B", "2024-01-02"): -0.20,
    ("C", "2024-01-02"): 0.05, ("D", "2024-01-02"): -0.40,
    ("E", "2024-01-03"): 0.10, ("F", "2024-01-03"): -0.10,
}


def test_the_oracle_caps_the_worst_and_is_rate_matched():
    keys = oracle_cap_keys(_CANDS, _N_BY_DATE, _REALIZED, worst=True)
    assert keys == {("D", "2024-01-02"), ("B", "2024-01-02"), ("F", "2024-01-03")}
    assert len(keys) == sum(_N_BY_DATE.values())


def test_the_anti_oracle_caps_the_best_at_the_same_rate():
    """El oráculo tiene que poder moverse en las DOS direcciones del eje — la
    lección que costó la corrida de la T26."""
    keys = oracle_cap_keys(_CANDS, _N_BY_DATE, _REALIZED, worst=False)
    assert keys == {("A", "2024-01-02"), ("C", "2024-01-02"), ("E", "2024-01-03")}
    assert len(keys) == sum(_N_BY_DATE.values())


# ── §5.2 — el sanity de población de la T13 ──────────────────────────────────


def _trade(ticker, entry_date, held):
    return SimpleNamespace(ticker=ticker, entry_date=entry_date, held_days=held)


def _res(trades):
    return SimpleNamespace(trades=trades)


def test_population_counts_the_trades_that_reach_the_cap():
    res = _res([_trade("A", "d1", 5), _trade("B", "d1", 25), _trade("C", "d1", 30)])
    assert population_share(res, 20) == 2 / 3
    assert population_share(res, 40) == 0.0


def test_population_of_the_event_arm_only_counts_event_trades():
    """El brazo condicionado puede quedarse sin población aunque el incondicional
    tenga de sobra: es exactamente el riesgo que el §5.2 existe para detectar."""
    res = _res([_trade("A", "d1", 25), _trade("B", "d1", 25), _trade("C", "d1", 25)])
    assert population_share(res, 20) == 1.0
    assert population_share(res, 20, {("A", "d1")}) == 1 / 3


def test_population_below_the_threshold_is_the_t13_diagnosis():
    """0,5% fue el número de la T13. Con el umbral de ≥5% eso es «sin población»."""
    trades = [_trade(f"T{i}", "d1", 5) for i in range(199)] + [_trade("Z", "d1", 30)]
    assert population_share(_res(trades), 20) < SANITY_MIN_POPULATION


# ── §4 — C6, dosis-respuesta ─────────────────────────────────────────────────


def test_a_monotone_curve_passes():
    """Si el tope corto es mejor cuanto más corto, la curva baja con N: una sola
    dirección, sin cambios."""
    d = {10: 0.040, 15: 0.030, 20: 0.020, 30: 0.010, 40: 0.005, 60: 0.000}
    out = dose_response(d, 10)
    assert out["unimodal"] and out["no_isolated_peak"] and out["passes"]


def test_an_interior_optimum_passes_if_the_neighbours_hold():
    """Un óptimo interior es esperable —un tope demasiado corto corta ganadores—
    mientras los vecinos conserven la mitad del efecto."""
    d = {10: 0.020, 15: 0.030, 20: 0.040, 30: 0.025, 40: 0.010, 60: 0.000}
    out = dose_response(d, 20)
    assert out["passes"] and out["neighbour_kept"] >= NEIGHBOUR_SHARE


def test_an_isolated_peak_at_twenty_fails():
    """EL caso que C6 existe para rechazar: el efecto vive SÓLO en el N=20 que
    motivó la tarea. Eso es sobreajuste al número, no un mecanismo."""
    d = {10: 0.000, 15: 0.001, 20: 0.040, 30: 0.001, 40: 0.000, 60: 0.000}
    out = dose_response(d, 20)
    assert out["unimodal"]                     # sube y baja una sola vez
    assert not out["no_isolated_peak"]         # pero los vecinos no conservan nada
    assert not out["passes"]


def test_a_sawtooth_curve_is_not_unimodal():
    d = {10: 0.040, 15: 0.000, 20: 0.040, 30: 0.000, 40: 0.040, 60: 0.000}
    assert not dose_response(d, 10)["unimodal"]


def test_ties_within_tolerance_do_not_count_as_direction_changes():
    """±0.20 pp es ruido de la grilla, no un cambio de dirección."""
    d = {10: 0.0400, 15: 0.0395, 20: 0.0390, 30: 0.0200, 40: 0.0100, 60: 0.0000}
    assert dose_response(d, 10)["unimodal"]


def test_a_curve_with_no_positive_effect_never_passes():
    """Sin efecto positivo en N* no hay dosis-respuesta que declarar."""
    d = {10: -0.010, 15: -0.020, 20: -0.030, 30: -0.040, 40: -0.050, 60: -0.060}
    assert not dose_response(d, 10)["passes"]


# ── §6 — la regla de decisión ────────────────────────────────────────────────


def _sum(cagr=0.05, max_dd=0.40):
    return {"cagr": cagr, "max_dd": max_dd, "accounting_ok": True}


def _boot(ci_low=0.01):
    return SimpleNamespace(observed=0.02, ci_low=ci_low, ci_high=0.05, p_value=0.01)


_C6_OK = {"passes": True}
_C8_OK = {"passes": True}
_SENS_OK = {"b_c1": True, "b_c4": True, "a_c1": True, "a_c4": True}


def test_candidate_b_ships_when_every_criterion_holds():
    v = evaluate_b(_sum(0.030), _sum(0.050), _boot(), _C6_OK, _C8_OK, _SENS_OK)
    assert v["ship"]


def test_candidate_b_needs_the_bootstrap_not_just_the_point_estimate():
    v = evaluate_b(_sum(0.030), _sum(0.050), _boot(ci_low=-0.001), _C6_OK, _C8_OK,
                   _SENS_OK)
    assert v["c1_dcagr"] and not v["c4_boot_base"] and not v["ship"]


def test_candidate_b_without_dose_response_does_not_ship():
    v = evaluate_b(_sum(0.030), _sum(0.050), _boot(), {"passes": False}, _C8_OK,
                   _SENS_OK)
    assert not v["ship"]


def test_candidate_a_must_beat_the_unconditional_arm():
    """C9 — la jerarquía declarada en el §6: si A no le gana a B, el efecto no es
    del evento y lo que shipea es B."""
    controls = [_sum(0.030) for _ in range(20)]
    v = evaluate_a(_sum(0.030), _sum(0.050), _sum(0.050), controls, _boot(),
                   _boot(), _boot(), _C6_OK, _C8_OK, _SENS_OK)
    assert v["dcagr_over_b"] < KILL_A_OVER_B
    assert not v["c9_beats_uncond"] and not v["ship"]


def test_candidate_a_must_beat_the_rate_matched_control():
    """C2 — el criterio que mató a la 49: ganarle al baseline no alcanza si
    cualquier subconjunto igualado en tasa hace lo mismo."""
    controls = [_sum(0.060) for _ in range(20)]
    v = evaluate_a(_sum(0.030), _sum(0.050), _sum(0.040), controls, _boot(),
                   _boot(), _boot(), _C6_OK, _C8_OK, _SENS_OK)
    assert not v["c2_vs_control"] and not v["ship"]


def test_candidate_a_ships_when_it_beats_base_control_and_the_uncond_arm():
    controls = [_sum(0.030) for _ in range(20)]
    v = evaluate_a(_sum(0.030), _sum(0.070), _sum(0.050), controls, _boot(),
                   _boot(), _boot(), _C6_OK, _C8_OK, _SENS_OK)
    assert v["c2_vs_control"] and v["c9_beats_uncond"] and v["ship"]


# ── §6 — los desenlaces ──────────────────────────────────────────────────────


_POP_OK = {"b_ok": True, "a_ok": True}


def test_no_population_is_not_a_no_ship():
    """La corrección que la tarea 57 tuvo que hacer, fijada en un test: sin
    población el brazo está SIN PODER, y decir «no funciona» es leer al revés lo
    que la T13 publicó."""
    out = outcome_of({"ship": False}, {"ship": False},
                     {"b_ok": False, "a_ok": False})
    assert "SIN POBLACIÓN" in out and "no refutado" in out
    assert "NO-SHIP" not in out


def test_shipping_a_warns_about_the_wiring_cost():
    """§7: el detector no corre en el engine vivo, así que un SHIP de A no es
    cableable sin construir esa cañería."""
    out = outcome_of({"ship": True, "c1_dcagr": True}, {"ship": True}, _POP_OK)
    assert "SHIP A" in out and "cañería" in out


def test_shipping_b_says_it_was_the_tenure_not_the_event():
    out = outcome_of({"ship": False, "c1_dcagr": True}, {"ship": True}, _POP_OK)
    assert "SHIP B" in out and "no era el evento" in out.lower()


def test_both_failing_c1_refutes_the_hypothesis_with_power():
    out = outcome_of({"ship": False, "c1_dcagr": False, "c6_dose": True},
                     {"ship": False, "c1_dcagr": False, "c6_dose": True}, _POP_OK)
    assert "refutada CON PODER" in out
