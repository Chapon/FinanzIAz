"""
Tests offline del harness de PRIO-EVENT — Tarea 49.
Pre-registro: ``docs/prio_event_prereg_t49_2026-08-20.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  rate_matched_priority — **el control que le faltaba a la 45**: que queda igualado
                          en tasa día por día, que es una función PURA (no depende
                          del orden de las llamadas) y que semillas distintas eligen
                          conjuntos distintos
  restrict_to_pool      — que el candidato **no puede** priorizar una entrada que el
                          engine no ofrece (la corrección al descriptivo de la 45)
  make_prio             — que la prioridad domina al score, y que el score sigue
                          ordenando dentro de cada grupo
  oracle_prio_keys      — que los oráculos están igualados en tasa (sanity duro)
  evaluate              — el AND de los siete y cada caso partido del §6
  evaluate_sanity       — sanity fallado ⇒ corrida INVÁLIDA
"""

from __future__ import annotations

import pytest

from analysis.rank_policy import neutral_rank, rate_matched_priority
from scripts.run_prio_event_t49 import (
    ANTI_ORACLE_ARM,
    BASELINE_ARM,
    CANDIDATE_ARM,
    KILL_MIN_DCAGR,
    ORACLE_ARM,
    PRIO_BOOST,
    candidates_by_date,
    control_name,
    count_by_date,
    evaluate,
    evaluate_sanity,
    keys_of,
    make_prio,
    oracle_prio_keys,
    restrict_to_pool,
)

_CANDS = {
    "2020-01-02": ["AAA", "BBB", "CCC", "DDD"],
    "2020-01-03": ["AAA", "EEE"],
    "2020-01-06": ["FFF", "GGG", "HHH"],
}


# ── El control igualado en tasa ──────────────────────────────────────────────


def test_control_matches_the_rate_day_by_day():
    """EL punto de la tarea: el control tiene que priorizar la MISMA cantidad en
    los MISMOS días, si no no controla nada."""
    n = {"2020-01-02": 2, "2020-01-03": 1, "2020-01-06": 3}
    keys = rate_matched_priority(_CANDS, n, 60_000)
    assert count_by_date(keys) == n
    for t, d in keys:
        assert t in _CANDS[d]


def test_control_is_a_pure_function_of_seed_date_ticker():
    """T39 §5.7 / tarea 40: el defecto del brazo aleatorio de la T21 era que su
    valor dependía del orden de las llamadas del `sorted()` del día."""
    n = {"2020-01-02": 2, "2020-01-06": 1}
    a = rate_matched_priority(_CANDS, n, 60_000)
    revuelto = {d: list(reversed(ts)) for d, ts in _CANDS.items()}
    b = rate_matched_priority(revuelto, dict(reversed(list(n.items()))), 60_000)
    assert a == b


def test_control_seeds_pick_different_sets():
    """Si las semillas no mueven nada, la 'distribución' de C2 es una ilusión
    (sanity §5.7)."""
    n = {"2020-01-02": 2, "2020-01-06": 1}
    sets = {frozenset(rate_matched_priority(_CANDS, n, 60_000 + k)) for k in range(20)}
    assert len(sets) > 1


def test_control_takes_the_top_of_the_pure_key():
    n = {"2020-01-02": 1}
    ((t, d),) = rate_matched_priority(_CANDS, n, 123)
    best = max(_CANDS["2020-01-02"], key=lambda x: neutral_rank(123, "2020-01-02", x))
    assert (t, d) == (best, "2020-01-02")


def test_control_survives_days_without_pool_or_with_zero():
    n = {"2020-01-02": 0, "1999-01-01": 3}
    assert rate_matched_priority(_CANDS, n, 1) == set()


def test_control_never_asks_for_more_than_the_pool_has():
    n = {"2020-01-03": 99}
    keys = rate_matched_priority(_CANDS, n, 1)
    assert len(keys) == 2  # el pool de ese día tiene 2


# ── La re-ordenación pura ────────────────────────────────────────────────────


_BARS = {t: [(f"2020-01-{d:02d}", 1.0, 1.0, 1.0, 1.0) for d in range(1, 8)] for t in ("AAA", "BBB", "CCC")}


def test_candidate_cannot_prioritise_outside_the_engine_pool():
    """La corrección al descriptivo de la 45: allá el pool era la UNIÓN, así que el
    brazo mezclaba 'prioriza' con 'agrega candidatos nuevos'."""
    pool = [("AAA", 1), ("BBB", 2)]
    anom = [("AAA", 1), ("CCC", 3)]  # CCC no está en el pool del engine
    assert restrict_to_pool(anom, pool) == [("AAA", 1)]


def test_restrict_keeps_order_and_drops_nothing_that_is_in_the_pool():
    pool = [("AAA", 1), ("BBB", 2), ("CCC", 3)]
    anom = [("CCC", 3), ("AAA", 1)]
    assert restrict_to_pool(anom, pool) == [("CCC", 3), ("AAA", 1)]


def test_candidates_by_date_and_keys_are_consistent():
    entries = [("AAA", 1), ("BBB", 1), ("CCC", 3)]
    cbd = candidates_by_date(entries, _BARS)
    assert cbd["2020-01-02"] == ["AAA", "BBB"]
    assert keys_of(entries, _BARS) == {("AAA", "2020-01-02"), ("BBB", "2020-01-02"), ("CCC", "2020-01-04")}


# ── La clave de orden ────────────────────────────────────────────────────────


_SCORES = {"AAA": {"2020-01-02": 0.10}, "BBB": {"2020-01-02": 0.90}, "CCC": {"2020-01-02": 0.50}}


def test_priority_dominates_the_score():
    """Un candidato priorizado con el PEOR score tiene que entrar antes que uno sin
    priorizar con el mejor — si no, la intervención no es un cambio de turno."""
    rank = make_prio({("AAA", "2020-01-02")}, _SCORES)
    assert rank("AAA", "2020-01-02") > rank("BBB", "2020-01-02")
    assert rank("AAA", "2020-01-02") == pytest.approx(PRIO_BOOST + 0.10)


def test_the_score_still_orders_inside_each_group():
    """El fondo sigue siendo el `buy_score` vivo: la tarea cambia quién va primero,
    no la clave de todos."""
    rank = make_prio({("AAA", "2020-01-02"), ("CCC", "2020-01-02")}, _SCORES)
    assert rank("CCC", "2020-01-02") > rank("AAA", "2020-01-02")  # priorizados
    assert rank("BBB", "2020-01-02") > 0.0  # el resto


def test_unknown_score_falls_back_to_zero_not_to_a_crash():
    rank = make_prio(set(), _SCORES)
    assert rank("ZZZ", "1999-01-01") == 0.0


# ── Los oráculos, igualados en tasa ─────────────────────────────────────────


def test_oracles_are_rate_matched_too():
    """Si el oráculo pudiera priorizar más que el candidato, el sanity §5.4 sería
    trivial y no diría nada del instrumento."""
    n = {"2020-01-02": 2}
    realized = {
        ("AAA", "2020-01-02"): 0.5,
        ("BBB", "2020-01-02"): -0.3,
        ("CCC", "2020-01-02"): 0.1,
        ("DDD", "2020-01-02"): -0.9,
    }
    best = oracle_prio_keys(_CANDS, n, realized, best=True)
    worst = oracle_prio_keys(_CANDS, n, realized, best=False)
    assert count_by_date(best) == n and count_by_date(worst) == n
    assert best == {("AAA", "2020-01-02"), ("CCC", "2020-01-02")}
    assert worst == {("DDD", "2020-01-02"), ("BBB", "2020-01-02")}


# ── §6 — el AND de los siete ────────────────────────────────────────────────


class _Boot:
    def __init__(self, ci_low):
        self.ci_low = ci_low
        self.ci_high = ci_low + 0.05
        self.p_value = 0.01


def _sum(cagr=0.10, sharpe=0.6, dd=0.40):
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": dd,
        "accounting_ok": True,
        "n_taken": 2800,
        "n_offered": 143096,
        "mean_held_days": 30.0,
    }


_C6_OK = {
    "passes": True,
    "tolerance_pts": 1.85,
    "material_pts": 1.00,
    "detectable_pts": 1.85,
    "pooled_delta_pts": 0.3,
    "pooled_ci_high": 1.4,
    "pooled_ci_low": -0.9,
    "windows": {},
}
_CONTROLS = [_sum(cagr=0.02 + 0.001 * k) for k in range(20)]  # p95 ~0.039
_SENS_OK = {"c1": True, "c2": True}


def _ev(**over):
    kw = dict(
        base=_sum(cagr=0.037),
        cand=_sum(cagr=0.079),
        controls=_CONTROLS,
        boot_base=_Boot(0.002),
        boot_ctrl=_Boot(0.001),
        c6=_C6_OK,
        sens=_SENS_OK,
    )
    kw.update(over)
    return evaluate(
        kw["base"], kw["cand"], kw["controls"], kw["boot_base"], kw["boot_ctrl"], kw["c6"], kw["sens"]
    )


def test_ships_when_all_seven_pass():
    v = _ev()
    assert v["ship"] is True and "SHIP" in v["outcome"]


def test_the_case_the_task_exists_for_beats_the_baseline_but_not_the_control():
    """El desenlace que la 45 no podía distinguir: si el candidato le gana al
    desempate vivo pero NO al control igualado en tasa, el +4.21 pp era
    DESORDENAR, no EL EVENTO."""
    altos = [_sum(cagr=0.085 + 0.001 * k) for k in range(20)]
    v = _ev(controls=altos, boot_ctrl=_Boot(-0.004))
    assert v["c1_dcagr"] is True and v["c4_boot_base"] is True
    assert v["c2_vs_control"] is False and v["ship"] is False
    assert "DESORDENAR, no EL EVENTO" in v["outcome"]


def test_no_ship_by_c7_names_the_shrinking_effect():
    v = _ev(sens={"c1": True, "c2": False})
    assert v["c7_sensitivity"] is False and v["ship"] is False
    assert "ENCOGE" in v["outcome"]


def test_missing_sensitivity_is_not_a_pass():
    assert _ev(sens=None)["c7_sensitivity"] is False


def test_no_ship_by_c6_regime():
    v = _ev(c6=dict(_C6_OK, passes=False))
    assert v["c6_regime"] is False and v["ship"] is False
    assert "C6" in v["outcome"]


def test_each_remaining_criterion_can_block_on_its_own():
    assert _ev(cand=_sum(cagr=0.0419))["c1_dcagr"] is False  # < +0.50pp
    assert _ev(cand=_sum(cagr=0.079, dd=0.4301))["c3_maxdd"] is False
    assert _ev(boot_base=_Boot(-0.001))["c4_boot_base"] is False
    assert _ev(boot_ctrl=_Boot(-0.001))["c5_boot_control"] is False


def test_the_dcagr_threshold_is_the_declared_one():
    """El umbral es +0.50 pp sobre el baseline, ni mas ni menos."""
    apenas_abajo = _sum(cagr=0.037 + KILL_MIN_DCAGR * 0.9)
    apenas_arriba = _sum(cagr=0.037 + KILL_MIN_DCAGR * 1.1)
    assert _ev(cand=apenas_abajo)["c1_dcagr"] is False
    assert _ev(cand=apenas_arriba)["c1_dcagr"] is True


def test_broken_accounting_never_ships():
    roto = dict(_sum(cagr=0.079), accounting_ok=False)
    assert _ev(cand=roto)["ship"] is False


def test_an_empty_control_band_is_never_a_pass():
    assert _ev(controls=[])["c2_vs_control"] is False


# ── §5 — sanity ──────────────────────────────────────────────────────────────


def _summaries(oracle=0.15, anti=0.01, base=0.037):
    s = {
        BASELINE_ARM: _sum(cagr=base),
        CANDIDATE_ARM: _sum(cagr=0.079),
        ORACLE_ARM: _sum(cagr=oracle),
        ANTI_ORACLE_ARM: _sum(cagr=anti),
    }
    for k in range(20):
        s[control_name(k)] = _CONTROLS[k]
    return s


_REPRO_OK = {"t45_ok": True, "t33_ok": True}


def test_run_is_valid_when_every_sanity_passes():
    sa = evaluate_sanity(_summaries(), _CONTROLS, 0.35, 0.30, _REPRO_OK)
    assert sa["valid"] is True


def test_an_oracle_that_does_not_see_good_turns_invalidates_the_run():
    """ENMIENDA §5.4': el oraculo tiene que salirse de la banda ENTERA del control
    (p95 ~0.039 con estos 20 controles), no superar al baseline por +5 pp -- ese
    umbral era el de un oraculo de potencia completa (T21), no de uno igualado en
    tasa."""
    sa = evaluate_sanity(_summaries(oracle=0.030), _CONTROLS, 0.35, 0.30, _REPRO_OK)
    assert sa["checks"]["oracle_sees_good_turns"] is False and sa["valid"] is False


def test_the_oracle_sanity_is_read_against_the_control_band_not_the_baseline():
    """Un oraculo que le gana al baseline por menos de +5 pp pero se sale de la banda
    del azar SI valida el instrumento. Es el caso que el pre-registro original
    invalidaba de mas (medido en el smoke: +2.50 pp sobre el baseline y muy arriba
    del p95 del control)."""
    sa = evaluate_sanity(_summaries(oracle=0.055, base=0.037), _CONTROLS, 0.35, 0.30, _REPRO_OK)
    assert sa["checks"]["oracle_sees_good_turns"] is True and sa["valid"] is True


def test_an_anti_oracle_that_is_not_on_the_bad_side_invalidates_the_run():
    sa = evaluate_sanity(_summaries(anti=0.20), _CONTROLS, 0.35, 0.30, _REPRO_OK)
    assert sa["checks"]["oracle_sees_bad_turns"] is False and sa["valid"] is False


def test_an_empty_control_band_cannot_validate_the_instrument():
    """Sin banda no hay referencia: el sanity no puede pasar por defecto."""
    sa = evaluate_sanity(_summaries(), [], 0.35, 0.30, _REPRO_OK)
    assert sa["checks"]["oracle_sees_good_turns"] is False and sa["valid"] is False


def test_a_priority_that_does_not_bite_invalidates_the_run():
    sa = evaluate_sanity(_summaries(), _CONTROLS, 0.05, 0.30, _REPRO_OK)
    assert sa["checks"]["priority_bites"] is False and sa["valid"] is False


def test_ineffective_control_seeds_invalidate_the_run():
    iguales = [_sum(cagr=0.02) for _ in range(20)]
    sa = evaluate_sanity(_summaries(), iguales, 0.35, 0.30, _REPRO_OK)
    assert sa["checks"]["control_seeds_effective"] is False and sa["valid"] is False


def test_a_failed_reproduction_invalidates_the_run():
    for bad in ({"t45_ok": False, "t33_ok": True}, {"t45_ok": True, "t33_ok": False}):
        sa = evaluate_sanity(_summaries(), _CONTROLS, 0.35, 0.30, bad)
        assert sa["valid"] is False
