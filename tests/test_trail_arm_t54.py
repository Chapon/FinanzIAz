"""
Tests de la medición del armado del trailing — Tarea 54 (TRAIL-ARM), paso previo.

Pre-registro: ``docs/trail_arm_prereg_t54_2026-08-28.md``.

Todo sintético: sin Parquet, sin red, sin DB.

Cubre:
  trade_excess_atrs       — el excedente máximo sobre la entrada, en ATRs, que es la
                            magnitud contra la que el gate compara el umbral
  differential_population — la población que un brazo **puede mover**: el intervalo
                            (k, base], no la acumulada, que la sobrestima

Y del runner (``scripts/run_trail_arm_t54.py``):

  differential_keys / population_share — el mismo intervalo, sobre las claves
  thr_for_keys        — el umbral sólo a un subconjunto (los oráculos)
  oracle_arm_keys     — la enmienda 2: los oráculos se eligen DENTRO de lo que el
                        brazo puede tocar, e igualados en tasa por construcción
  changed_exits       — cuántas salidas cambian **de verdad**: cambiar el estado de
                        armado no es cambiar la salida
  evaluate / outcome_of — el AND del §6, C9 (el resultado, no la etiqueta) y la
                        guarda de corrida INVÁLIDA (la que la tarea 60 tuvo que
                        agregarle al runner de la 51 después de escribirlo)
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


# ── El runner (§5 y §6) ──────────────────────────────────────────────────────

from scripts.run_trail_arm_t54 import (
    BASE_K,
    changed_exits,
    differential_keys,
    differential_return,
    evaluate,
    exit_mix,
    oracle_arm_keys,
    outcome_of,
    population_share,
    thr_for_keys,
)


def _res(trades):
    return SimpleNamespace(trades=trades)


def _tr(ticker, entry, *, ret=0.0, exit_date="2026-02-01", reason="signal_full"):
    return SimpleNamespace(ticker=ticker, entry_date=entry, ret=ret,
                           exit_date=exit_date, exit_reason=reason)


_POP_OK = {"ok": True}
_POP_NO = {"ok": False}


def test_differential_keys_is_the_interval_both_ways():
    """Bajar el umbral toca ``(k, 1.0]``; subirlo toca ``(1.0, k]``. Las dos
    direcciones cuentan: subirlo **desarma** trades que hoy arman."""
    excess = {("A", "d"): 0.2, ("B", "d"): 0.9, ("C", "d"): 1.2, ("D", "d"): 4.0}
    assert differential_keys(excess, 0.5) == {("B", "d")}
    assert differential_keys(excess, 1.5) == {("C", "d")}
    assert differential_keys(excess, BASE_K) == set()
    assert population_share(excess, 0.5) == 0.25


def test_the_threshold_applies_only_to_the_chosen_keys():
    """``thr_for_keys`` es pura y sólo toca el subconjunto: es lo que hace que los
    oráculos sean comparables con el candidato."""
    f = thr_for_keys({("A", "d1")}, 0.0)
    assert f("A", "d1") == 0.0
    assert f("A", "d2") == BASE_K and f("B", "d1") == BASE_K


def test_the_oracles_split_the_affectable_population_in_disjoint_halves():
    """**Enmienda 2.** Elegir entre todos los candidatos daba un anti-oráculo
    idéntico al baseline: el excedente es el techo del retorno, así que *los que
    mejor terminan* son casi exactamente *los que el umbral no puede tocar*. Ahora
    los dos salen de la población afectable, y quedan igualados en tasa."""
    base = _res([_tr("A", "d", ret=-0.5), _tr("B", "d", ret=0.4),
                 _tr("C", "d", ret=-0.2), _tr("D", "d", ret=0.9)])
    D = {("A", "d"), ("B", "d"), ("C", "d"), ("D", "d")}
    peores = oracle_arm_keys(D, base, worst=True)
    mejores = oracle_arm_keys(D, base, worst=False)
    assert peores == {("A", "d"), ("C", "d")}
    assert mejores == {("B", "d"), ("D", "d")}
    assert len(peores) == len(mejores)          # igualados en tasa
    assert not (peores & mejores)               # y disjuntos


def test_the_oracles_stay_inside_the_population_they_are_given():
    """No pueden tocar posiciones que el brazo no cambia: si lo hicieran, medirían
    otra cosa que el mecanismo bajo prueba."""
    base = _res([_tr("A", "d", ret=-0.5), _tr("Z", "d", ret=-9.9)])
    assert oracle_arm_keys({("A", "d")}, base, worst=True) <= {("A", "d")}


def test_changed_exits_counts_the_salidas_not_the_armings():
    """El descriptivo que el smoke obligó a agregar: un trailing **armado** que
    nunca dispara deja la salida igual, así que la población del §5.3 es una cota
    superior de lo que un brazo mueve."""
    base = _res([_tr("A", "d", exit_date="2026-03-01", reason="signal_full"),
                 _tr("B", "d", exit_date="2026-03-05", reason="signal_full")])
    cand = _res([_tr("A", "d", exit_date="2026-02-10", reason="atr_trail"),
                 _tr("B", "d", exit_date="2026-03-05", reason="signal_full")])
    ce = changed_exits(base, cand, {("A", "d"), ("B", "d")})
    assert ce["n_common"] == 2 and ce["n_changed"] == 1
    assert ce["share"] == 0.5 and ce["n_changed_in_diff_pop"] == 1


def test_the_differential_return_is_paired_by_key():
    """C9 compara **los mismos trades** en los dos brazos: sin parear, la cascada
    de slots metería trades distintos en cada punta."""
    base = _res([_tr("A", "d", ret=-0.10), _tr("B", "d", ret=0.20)])
    cand = _res([_tr("A", "d", ret=-0.02), _tr("Z", "d", ret=5.0)])
    dr = differential_return(base, cand, {("A", "d"), ("B", "d")})
    assert dr["n_common"] == 1                       # B no está en el candidato
    assert dr["base_pts"] == -10.0 and dr["cand_pts"] == -2.0
    assert dr["delta_pts"] == 8.0


def test_exit_mix_groups_by_reason_not_by_level():
    """La razón viva trae el nivel adentro (``atr_trail @ 12.3 ≤ …``); el
    descriptivo agrupa por el motivo."""
    res = _res([_tr("A", "d", reason="atr_trail @ 12.30 ≤ 12.50 (peak …)"),
                _tr("B", "d", reason="atr_trail @ 9.10 ≤ 9.20 (peak …)"),
                _tr("C", "d", reason="signal_full")])
    assert exit_mix(res) == {"atr_trail": 2, "signal_full": 1}


def _v(**over):
    base = {"cagr": 0.05, "max_dd": 0.30}
    cand = {"cagr": 0.07, "max_dd": 0.30}
    boot = SimpleNamespace(ci_low=0.001, ci_high=0.02, observed=0.01, p_value=0.01)
    kw = {"base": base, "cand": cand, "boot": boot,
          "c6": {"passes": True}, "c8": {"passes": True},
          "sens": {"c1": True, "c4": True},
          "diff_ret": {"n_common": 10, "delta_pts": 1.0}}
    kw.update(over)
    return evaluate(**kw)


def test_the_and_of_the_criteria_ships_only_when_all_hold():
    assert _v()["ship"] is True
    assert _v(boot=None)["ship"] is False
    assert _v(c6={"passes": False})["ship"] is False
    assert _v(sens=None)["ship"] is False


def test_c9_fails_when_the_arm_only_moves_the_label():
    """El criterio propio de esta tarea: si el retorno de los trades que el brazo
    toca no mejora, cambió **quién firma la salida**, no el resultado."""
    v = _v(diff_ret={"n_common": 10, "delta_pts": -0.5})
    assert v["c9_moves_the_result"] is False and v["ship"] is False
    assert "MOTIVO de salida, no el resultado" in outcome_of(v, _POP_OK, sanity_valid=True)


def test_a_failed_sanity_invalidates_the_run_over_every_criterion():
    """La guarda que la tarea 60 tuvo que agregarle al runner de la 51 después de
    escribirlo: acá está desde el principio."""
    out = outcome_of(_v(), _POP_OK, sanity_valid=False)
    assert "CORRIDA INVÁLIDA" in out and "SHIP" not in out


def test_no_population_is_not_a_no_ship():
    out = outcome_of(_v(), _POP_NO, sanity_valid=True)
    assert "SIN POBLACIÓN" in out and "no refutado" in out
    assert "NO-SHIP" not in out


def test_failing_c1_says_the_live_threshold_is_not_misplaced():
    """El desenlace más probable según la predicción del §0.3, resuelto ex ante: si
    mover el umbral no paga, el 1.0 vivo **no está mal puesto**, y eso es
    información útil sobre una salida que está en producción."""
    v = _v(cand={"cagr": 0.05, "max_dd": 0.30})
    out = outcome_of(v, _POP_OK, sanity_valid=True)
    assert "NO-SHIP" in out and "NO está mal puesto" in out


def test_outcome_of_requires_declaring_the_sanity():
    import pytest

    with pytest.raises(TypeError):
        outcome_of(_v(), _POP_OK)
