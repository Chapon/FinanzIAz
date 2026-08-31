"""
Tests offline del harness ``scripts.run_stop_price_replay_t26b`` (Tarea 26b, STOP-PRICE)
y del ``eval_mode`` de ``analysis.scaleout_replay``.

Pre-registro: ``docs/stop_price_prereg_t26b_2026-08-14.md``.

Cubren, sin Parquet / red / DB:
1. **Regresión dura:** ``eval_mode="close"`` (default) reproduce exactamente el
   comportamiento previo ⇒ el enabler no puede mover T7/T23/T13/T21/T26.
2. La **invariante de dominancia** (§5.4): para la misma posición en la misma barra,
   todo disparo bajo ``close`` implica disparo bajo ``touch`` (``low ≤ close ≤ high``).
3. El **empate declarado** (§3): mínimo perfora el stop y máximo el TP en la misma
   barra ⇒ gana el **stop** (convención adversa).
4. La rejilla 2×5 y la regla de decisión §6, incluida **C6** (consistencia del signo
   a través del múltiplo) y los casos partidos.
5. El sanity §5 comparado contra el **control igualado**, no contra el baseline.
"""

from __future__ import annotations

import pytest

from analysis.exit_replay import AtrParams
from analysis.scaleout_replay import (
    CostModel,
    ScaleOutParams,
    _barrier_fill_price,
    _fired_barrier,
    replay_cycle,
)
from analysis.walkforward_power import STRESS_REGIMES
from scripts.run_stop_price_replay_t26b import (
    BASELINE_ARM,
    CANDIDATE_ARM,
    MODES,
    MULTS,
    arm_name,
    build_arms,
    consistency_across_mults,
    evaluate,
    evaluate_sanity,
)

_REG_NAMES = ["bull_normal"] + [r.name for r in STRESS_REGIMES]
_COMMON = dict(params=ScaleOutParams(), costs=CostModel(), cap_days=250, notional=10_000.0)


def _bars(rows):
    """rows = [(close, low, high)] → barras con fecha sintética y open=close."""
    out = []
    for i, (c, lo, hi) in enumerate(rows):
        out.append((f"2021-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", c, hi, lo, c))
    return out


def _flat(n=25, level=100.0, spread=1.0):
    return [(level, level - spread, level + spread)] * n


def _cycle(bars, atr_p, **kw):
    return replay_cycle(bars, 24, {}, atr_p=atr_p, **_COMMON, **kw)


# ── 1. Regresión: el default no cambia nada ──────────────────────────────────


def test_default_eval_mode_reproduce_el_comportamiento_previo():
    bars = _bars([*_flat(), (99.0, 94.0, 99.5), (97.0, 96.0, 98.0), (95.0, 94.0, 96.0)])
    a = AtrParams(stop_mult=2.0)
    sin_kw = _cycle(bars, a)
    con_close = _cycle(bars, a, eval_mode="close")
    assert sin_kw.exit_reasons == con_close.exit_reasons
    assert sin_kw.ret == con_close.ret
    assert [(l.date, l.price, l.reason) for l in sin_kw.legs] == [
        (l.date, l.price, l.reason) for l in con_close.legs
    ]


def test_eval_mode_invalido_falla_ruidoso():
    bars = _bars([*_flat(), (99.0, 98.0, 100.0)])
    with pytest.raises(ValueError, match="eval_mode"):
        _cycle(bars, AtrParams(), eval_mode="intraday")


# ── 2. Invariante de dominancia (§5.4) ───────────────────────────────────────


@pytest.mark.parametrize("mult", [1.0, 1.5, 2.0, 2.5, 3.0])
def test_dominancia_todo_disparo_al_close_implica_disparo_al_toque(mult):
    """``low ≤ close ≤ high`` ⇒ lo que dispara contra el close dispara contra el
    extremo. Es mecánica pura: si esto falla, el modo está mal cableado."""
    p = AtrParams(stop_mult=mult)
    casos = [
        (100.0, 95.0, 101.0),
        (100.0, 99.0, 100.5),
        (94.0, 93.0, 95.0),
        (112.0, 111.0, 113.0),
        (105.0, 96.0, 115.0),
        (98.0, 90.0, 120.0),
    ]
    for close, low, high in casos:
        bar = ("2021-06-01", close, high, low, close)
        al_close = _fired_barrier(bar, avg_cost=100.15, hwm=106.0, atr_value=2.0, p=p, eval_mode="close")
        al_toque = _fired_barrier(bar, avg_cost=100.15, hwm=106.0, atr_value=2.0, p=p, eval_mode="touch")
        if al_close is not None:
            assert al_toque is not None, (close, low, high, mult)


def test_el_toque_dispara_donde_el_close_no():
    """El caso que motiva toda la tarea: el mínimo perforó y el close se recuperó."""
    bar = ("2021-06-01", 100.0, 101.0, 95.0, 100.0)  # low 95 < stop, close 100 no
    p = AtrParams(stop_mult=2.0)
    assert _fired_barrier(bar, avg_cost=100.15, hwm=100.15, atr_value=2.0, p=p, eval_mode="close") is None
    assert (
        _fired_barrier(bar, avg_cost=100.15, hwm=100.15, atr_value=2.0, p=p, eval_mode="touch") == "atr_stop"
    )


# ── 3. El empate declarado (§3) ──────────────────────────────────────────────


def test_empate_stop_vs_tp_en_la_misma_barra_gana_el_stop():
    """Barra que perfora el stop por abajo y el TP por arriba: el OHLC no dice cuál
    fue primero, y el pre-registro congeló la convención **adversa**."""
    # avg_cost 100, ATR 2 ⇒ stop 96 (mult 2.0), TP 108 (mult 4.0)
    bar = ("2021-06-01", 100.0, 110.0, 95.0, 100.0)
    fired = _fired_barrier(
        bar,
        avg_cost=100.0,
        hwm=100.0,
        atr_value=2.0,
        p=AtrParams(stop_mult=2.0, tp_mult=4.0),
        eval_mode="touch",
    )
    assert fired == "atr_stop"


def test_el_tp_al_toque_dispara_con_el_maximo():
    bar = ("2021-06-01", 100.0, 110.0, 99.0, 100.0)  # high 110 ≥ TP 108, close no
    p = AtrParams(stop_mult=2.0, tp_mult=4.0)
    assert _fired_barrier(bar, avg_cost=100.0, hwm=100.0, atr_value=2.0, p=p, eval_mode="close") is None
    assert _fired_barrier(bar, avg_cost=100.0, hwm=100.0, atr_value=2.0, p=p, eval_mode="touch") == "atr_tp"


def test_touch_sale_mas_temprano_en_un_dip_que_cierra_arriba():
    bars = _bars(_flat() + [(100.0, 94.0, 100.5)] * 3 + [(104.0, 103.0, 105.0)] * 10)
    a = AtrParams(stop_mult=2.0)
    al_close = _cycle(bars, a, eval_mode="close")
    al_toque = _cycle(bars, a, eval_mode="touch")
    assert "atr_stop" not in al_close.exit_reasons
    assert "atr_stop" in al_toque.exit_reasons
    assert al_toque.held_days < al_close.held_days


# ── 3b. El fill de la barrera (`fill_mode`) ──────────────────────────────────
#
# El defecto que invalidó la primera corrida: decidir al close y llenar en el
# NIVEL. Como al disparar al close vale ``low ≤ close ≤ nivel``, el fill legacy
# devuelve siempre el nivel — mejor que el close y tocado ANTES de que existiera
# la información que decidió. Valía +5.01pp de CAGR sobre ``close_2.0``.


def test_resting_es_el_default_y_no_toca_las_tareas_previas():
    """Regresión dura: el default no puede mover T7/T23/T13/T21/T26."""
    bar = ("2021-06-01", 100.0, 101.0, 94.0, 95.0)  # close 95 < nivel 96
    sin_kw = _barrier_fill_price(bar, "atr_stop", 96.0, eval_mode="close", fill_mode="resting")
    assert sin_kw == 96.0  # el nivel, como siempre


def test_al_close_el_fill_decision_es_el_close_no_el_nivel():
    """El corazón de la corrección: se decidió con el close, se vende a ese close."""
    bar = ("2021-06-01", 100.0, 101.0, 94.0, 95.0)
    assert _barrier_fill_price(bar, "atr_stop", 96.0, eval_mode="close", fill_mode="resting") == 96.0
    assert _barrier_fill_price(bar, "atr_stop", 96.0, eval_mode="close", fill_mode="decision") == 95.0


def test_el_fill_al_nivel_es_siempre_mejor_que_el_close_cuando_dispara_al_close():
    """La dirección del sesgo, no sólo su existencia: el legacy nunca es peor."""
    p = AtrParams(stop_mult=2.0)
    for close, low, high in [(95.0, 90.0, 101.0), (88.0, 85.0, 99.0), (96.0, 96.0, 97.0)]:
        bar = ("2021-06-01", 100.0, high, low, close)
        fired = _fired_barrier(bar, avg_cost=100.0, hwm=100.0, atr_value=2.0, p=p, eval_mode="close")
        if fired != "atr_stop":
            continue
        legacy = _barrier_fill_price(bar, fired, 96.0, eval_mode="close", fill_mode="resting")
        honesto = _barrier_fill_price(bar, fired, 96.0, eval_mode="close", fill_mode="decision")
        assert legacy >= honesto, (close, low, high)


def test_al_toque_los_dos_fill_modes_coinciden():
    """En ``touch`` la orden en reposo SÍ es coherente: ``decision`` no cambia nada."""
    for bar in [
        ("2021-06-01", 100.0, 101.0, 94.0, 100.0),  # toque intradía
        ("2021-06-01", 93.0, 97.0, 92.0, 95.0),
    ]:  # gap-open bajo el nivel
        assert _barrier_fill_price(
            bar, "atr_stop", 96.0, eval_mode="touch", fill_mode="resting"
        ) == _barrier_fill_price(bar, "atr_stop", 96.0, eval_mode="touch", fill_mode="decision")


def test_fill_mode_invalido_falla_ruidoso():
    bars = _bars([*_flat(), (99.0, 98.0, 100.0)])
    with pytest.raises(ValueError, match="fill_mode"):
        _cycle(bars, AtrParams(), fill_mode="level")


def test_el_ciclo_completo_cobra_menos_con_el_fill_honesto():
    """De punta a punta: mismo disparo, peor precio ⇒ menor retorno.

    La barra final necesita ``open`` **por encima** del nivel: si abriera debajo,
    el fill legacy toma la rama de gap-open y los dos modos coinciden. Entrada al
    close 100.0 con costos ⇒ ``avg_cost`` 100.15, ATR 2.0 ⇒ stop en **96.15**.
    """
    bars = _bars(_flat())
    bars.append(("2021-01-26", 99.0, 99.5, 92.0, 93.0))  # open>nivel, close<nivel
    a = AtrParams(stop_mult=2.0)
    legacy = _cycle(bars, a, eval_mode="close", fill_mode="resting")
    honesto = _cycle(bars, a, eval_mode="close", fill_mode="decision")
    assert legacy.exit_reasons == honesto.exit_reasons  # mismo disparo
    assert honesto.legs[-1].price < legacy.legs[-1].price  # peor precio
    assert honesto.ret < legacy.ret  # y se cobra


# ── 4. La rejilla y la regla de decisión (§6) ────────────────────────────────


def test_build_arms_arma_la_rejilla_completa_mas_sanity():
    arms = build_arms()
    for mode in MODES:
        for m in MULTS:
            assert arms[arm_name(mode, m)]["eval_mode"] == mode
            assert arms[arm_name(mode, m)]["atr_p"].stop_mult == m
    assert BASELINE_ARM in arms and CANDIDATE_ARM in arms
    assert arms[BASELINE_ARM]["eval_mode"] == "touch"  # la regla viva
    assert arms[CANDIDATE_ARM]["eval_mode"] == "close"
    assert "stop_filter" in arms["ORACULO_STOP"]
    assert arms["ORACULO_STOP"]["eval_mode"] == "touch"  # sanity donde se decide


def test_build_arms_usa_el_fill_honesto_en_TODOS_los_brazos():
    """Incluidos los de sanity: si el instrumento se valida con un fill y el
    veredicto se dicta con otro, el sanity no valida lo que se decide."""
    arms = build_arms()
    assert {kw["fill_mode"] for kw in arms.values()} == {"decision"}
    legacy = build_arms("resting")
    assert {kw["fill_mode"] for kw in legacy.values()} == {"resting"}


def _summ(cagr, sharpe, max_dd, stop_share=0.20):
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "p5_trade": -0.07,
        "accounting_ok": True,
        "n_taken": 100,
        "n_offered": 200,
        "exposure": 0.6,
        "stop_share": stop_share,
        "exit_mix": {"atr_stop": stop_share},
        "total_return_pts": 0.0,
    }


def _reg(vals):
    return {name: {"n": 20, "mean_ret_pts": v} for name, v in zip(_REG_NAMES, vals, strict=True)}


class _Boot:
    def __init__(self, ci_low):
        self.ci_low, self.observed, self.ci_high = ci_low, 0.02, 0.05
        self.p_value, self.block, self.n_resamples = 0.01, 20, 2000


def _case(**over):
    """Caso donde TODO pasa: close ≥ touch en 4 de 5 múltiplos."""
    s = {}
    for m, (t, c) in zip(
        MULTS,
        [(0.20, 0.21), (0.16, 0.17), (0.12, 0.14), (0.09, 0.10), (0.08, 0.075)],
        strict=True,
    ):
        s[arm_name("touch", m)] = _summ(t, 0.70, 0.36)
        s[arm_name("close", m)] = _summ(c, 0.78, 0.36)
    s["ORACULO_STOP"] = _summ(0.16, 0.90, 0.28)
    s["AZAR_MISMA_TASA"] = _summ(0.13, 0.60, 0.40)
    s.update(over.get("summaries", {}))
    regimes = {
        BASELINE_ARM: _reg([0.20, -0.30, 0.90, -0.10]),
        CANDIDATE_ARM: _reg([0.24, -0.28, 0.95, -0.09]),
    }
    regimes.update(over.get("regimes", {}))
    return s, regimes


def test_ship_cuando_pasan_los_seis():
    s, r = _case()
    v = evaluate(s, r, _Boot(0.004))
    assert v["n_consistent"] == 4 and v["ship"] is True


def test_noship_si_el_dcagr_no_llega():
    s, r = _case(summaries={CANDIDATE_ARM: _summ(0.122, 0.78, 0.36)})
    v = evaluate(s, r, _Boot(0.004))
    assert v["c1_cagr"] is False and v["ship"] is False


def test_noship_si_el_maxdd_se_pasa():
    """Caso partido ex ante: confirmar al close retrasa la salida; si eso compra
    retorno con drawdown, es asumir riesgo, no mejorar la regla."""
    s, r = _case(summaries={CANDIDATE_ARM: _summ(0.14, 0.78, 0.39)})
    v = evaluate(s, r, _Boot(0.004))
    assert v["c1_cagr"] is True and v["c2_maxdd"] is False and v["ship"] is False


def test_noship_si_el_bootstrap_cruza_cero():
    s, r = _case()
    assert evaluate(s, r, _Boot(-0.001))["ship"] is False


def test_noship_si_rompe_un_regimen():
    s, r = _case(regimes={CANDIDATE_ARM: _reg([0.24, -0.28, 0.95, -0.40])})
    v = evaluate(s, r, _Boot(0.004))
    assert v["c5_regime"] is False and v["ship"] is False


def test_c6_falla_si_el_efecto_vive_en_un_solo_multiplo():
    """El análogo de la dosis-respuesta de la T26: si close sólo gana en 2.0 y pierde
    en los otros cuatro, es un punto de suerte, no una propiedad de la regla."""
    over = {arm_name("close", m): _summ(0.05, 0.40, 0.36) for m in MULTS if m != 2.0}
    s, r = _case(summaries=over)
    v = evaluate(s, r, _Boot(0.004))
    assert v["n_consistent"] == 1
    assert v["c6_consistency"] is False and v["ship"] is False


def test_consistencia_cuenta_los_cinco_pares():
    s, _ = _case()
    n, deltas = consistency_across_mults(s)
    assert set(deltas) == set(MULTS)
    assert n == 4 and deltas[3.0] < 0


# ── 5. Sanity contra el control igualado (§5) ────────────────────────────────


def test_sanity_compara_el_oraculo_contra_el_azar_no_contra_el_baseline():
    """La corrección directa del defecto que invalidó la T26."""
    s, _ = _case()
    results = {n: object() for n in s}
    san = _sanity(s, results)
    assert san["oracle_quality_ok"] is True
    # el oráculo rinde MENOS que el baseline touch_2.0 (0.16 vs 0.12 → acá gana,
    # así que se fuerza el caso inverso) y el sanity igual pasa:
    s2, _ = _case(summaries={BASELINE_ARM: _summ(0.30, 0.70, 0.36)})
    assert _sanity(s2, results)["oracle_quality_ok"] is True


def test_sanity_falla_si_el_oraculo_no_le_gana_al_azar():
    s, _ = _case(summaries={"ORACULO_STOP": _summ(0.135, 0.90, 0.28)})
    results = {n: object() for n in s}
    assert _sanity(s, results)["oracle_quality_ok"] is False


def test_sanity_falla_si_el_oraculo_no_mejora_el_drawdown():
    s, _ = _case(summaries={"ORACULO_STOP": _summ(0.16, 0.90, 0.37)})
    results = {n: object() for n in s}
    assert _sanity(s, results)["oracle_quality_ok"] is False


class _FakeRes:
    """``PortfolioResult`` mínimo para ``trade_overlap``."""

    class _T:
        def __init__(self, tk, d):
            self.ticker, self.entry_date = tk, d

    def __init__(self, pares):
        self.trades = [self._T(t, d) for t, d in pares]


def _sanity(summaries, _results, diff=0.5):
    """``evaluate_sanity`` con trades sintéticos que difieren en ``diff``."""
    base = _FakeRes([("A", "2021-01-01"), ("B", "2021-01-02")])
    cand = _FakeRes([("A", "2021-01-01"), ("C", "2021-01-03")])
    results = dict.fromkeys(summaries, base)
    results[BASELINE_ARM] = base
    results[CANDIDATE_ARM] = cand
    return evaluate_sanity(summaries, results)


def test_sanity_falla_si_la_regla_no_muerde():
    s, _ = _case()
    igual = _FakeRes([("A", "2021-01-01"), ("B", "2021-01-02")])
    results = dict.fromkeys(s, igual)
    san = evaluate_sanity(s, results)
    assert san["trade_diff_share"] == 0.0
    assert san["rule_bites"] is False and san["all_ok"] is False
