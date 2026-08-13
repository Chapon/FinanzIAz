"""
Tests offline del harness ``scripts.run_stop_cal_replay_t26`` (Tarea 26, STOP-CAL)
y del hook ``stop_filter`` de ``analysis.scaleout_replay``.

Pre-registro: ``docs/stop_cal_prereg_t26_2026-08-13.md`` (con la enmienda §0).

Cubren las piezas PURAS (sin Parquet, sin red, sin DB):
1. El hook ``stop_filter``: default ``None`` ⇒ **cero cambio** (regresión de T7/T23/T13),
   y cuando actúa suprime **sólo** el ``atr_stop`` sin apagar el trailing ni el TP —
   que es lo que el pre-registro §2 congeló (en el engine los dos niveles comparten
   múltiplo, así que apagar el stop "a lo bruto" apagaría también el trail).
2. Los brazos: un stop más estricto dispara donde uno más laxo no; ``S_off`` no emite
   ninguna salida de la barrera de abajo.
3. Los oráculos: miran ``close[i+20]`` y caen al baseline al final de la serie.
4. La regla de decisión §6 (el AND de los 6 criterios, el candidato = mejor Sharpe) y
   **C6 reformulado**: el baseline no cuenta como vecino.
5. Los sanity del §5, incluida la monotonía mecánica del ``%atr_stop``.
"""

from __future__ import annotations

from analysis.exit_replay import AtrParams
from analysis.scaleout_replay import CostModel, ScaleOutParams, replay_cycle
from analysis.walkforward_power import STRESS_REGIMES
from scripts.run_stop_cal_replay_t26 import (
    BASELINE_ARM,
    DECISION_ARMS,
    NO_STOP,
    ORACLE_HORIZON,
    _anti_oracle_stop_filter,
    _oracle_stop_filter,
    c6_dose_response,
    evaluate,
    pick_candidate,
    random_stop_filter,
    stop_share_monotone,
)

_REG_NAMES = ["bull_normal"] + [r.name for r in STRESS_REGIMES]


# ── Helpers de barras sintéticas ─────────────────────────────────────────────


def _bars(closes: list[float], spread: float = 1.0):
    """Barras con rango constante ``2*spread`` ⇒ ATR ≈ 2 en régimen tranquilo."""
    out = []
    for i, c in enumerate(closes):
        d = f"2021-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
        out.append((d, c, c + spread, c - spread, c))
    return out


def _flat_then(after: list[float], flat: int = 25, level: float = 100.0):
    """``flat`` barras planas (para que el ATR14 exista) + la trayectoria del test."""
    return _bars([level] * flat + after)


_COMMON = dict(params=ScaleOutParams(), costs=CostModel(), cap_days=250, notional=10_000.0)


def _cycle(bars, atr_p, **kw):
    return replay_cycle(bars, 24, {}, atr_p=atr_p, **_COMMON, **kw)


# ── 1. El hook stop_filter ───────────────────────────────────────────────────


def test_stop_filter_default_none_no_cambia_nada():
    """Regresión: sin ``stop_filter`` y con ``stop_filter=None`` el ciclo es idéntico.

    Es la garantía de que el enabler no puede mover los veredictos de T7/T23/T13/T21.
    """
    bars = _flat_then([99.0, 97.0, 95.0, 93.0, 91.0, 90.0])
    a = AtrParams(stop_mult=2.0)
    sin_hook = _cycle(bars, a)
    con_none = _cycle(bars, a, stop_filter=None)
    assert sin_hook.exit_reasons == con_none.exit_reasons
    assert sin_hook.ret == con_none.ret
    assert sin_hook.legs[0].price == con_none.legs[0].price


def test_stop_filter_suprime_el_atr_stop():
    bars = _flat_then([99.0, 97.0, 95.0, 93.0, 91.0, 90.0])
    a = AtrParams(stop_mult=2.0)
    assert "atr_stop" in _cycle(bars, a).exit_reasons
    libre = _cycle(bars, a, stop_filter=lambda _b, _i: False)
    assert "atr_stop" not in libre.exit_reasons


def test_stop_filter_no_apaga_el_trailing():
    """La pata delicada: el trail comparte múltiplo con el stop (gates.py:101-103).

    Si la supresión se implementara apagando ``stop_mult`` a secas, apagaría también
    el trailing. Acá el precio sube (arma el trail) y después se derrumba: sin filtro
    sale por ``atr_stop``; con filtro tiene que salir por ``atr_trail``, no seguir viva.
    """
    subida = [101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
    bars = _flat_then(subida + [90.0, 89.0, 88.0])
    a = AtrParams(stop_mult=2.0, tp_mult=NO_STOP)   # TP fuera del camino
    base = _cycle(bars, a)
    assert "atr_stop" in base.exit_reasons
    filtrado = _cycle(bars, a, stop_filter=lambda _b, _i: False)
    assert "atr_trail" in filtrado.exit_reasons
    assert "atr_stop" not in filtrado.exit_reasons


def test_stop_filter_no_apaga_el_take_profit():
    bars = _flat_then([102.0, 104.0, 106.0, 108.0, 110.0, 112.0])
    a = AtrParams(stop_mult=2.0)
    filtrado = _cycle(bars, a, stop_filter=lambda _b, _i: False)
    assert "atr_tp" in filtrado.exit_reasons


def test_stop_filter_es_por_barra():
    """El filtro se consulta con el índice de la barra, no una sola vez por ciclo."""
    bars = _flat_then([99.0, 97.0, 95.0, 93.0, 91.0, 90.0])
    vistos: list[int] = []

    def _spy(_b, i):
        vistos.append(i)
        return False

    _cycle(bars, AtrParams(stop_mult=2.0), stop_filter=_spy)
    assert vistos, "el filtro nunca se consultó"
    assert vistos == sorted(vistos) and len(set(vistos)) == len(vistos)


# ── 2. Los brazos ────────────────────────────────────────────────────────────


def test_stop_mas_estricto_dispara_donde_el_laxo_no():
    """Dip corto y recuperación: el stop 1.0 corta, el 3.0 aguanta."""
    bars = _flat_then([98.0, 97.0, 99.0] + [101.0] * 10)
    estricto = _cycle(bars, AtrParams(stop_mult=1.0))
    laxo = _cycle(bars, AtrParams(stop_mult=3.0))
    assert "atr_stop" in estricto.exit_reasons
    assert "atr_stop" not in laxo.exit_reasons
    assert laxo.ret > estricto.ret          # el que aguantó capturó la recuperación


def test_s_off_no_emite_ninguna_barrera_de_abajo():
    """``S_off`` apaga stop **y** trailing — es el acoplamiento vivo, declarado en §3.2."""
    bars = _flat_then([106.0, 95.0, 80.0, 70.0] + [60.0] * 5)
    res = _cycle(bars, AtrParams(stop_mult=NO_STOP, tp_mult=NO_STOP))
    assert "atr_stop" not in res.exit_reasons
    assert "atr_trail" not in res.exit_reasons


def test_brazo_de_diagnostico_mueve_solo_el_stop():
    """``D1_stop_only_3.0``: stop en 3.0 con el trailing pineado en 2.0."""
    subida = [101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
    bars = _flat_then(subida + [95.0, 94.0])
    d1 = _cycle(bars, AtrParams(stop_mult=3.0, trail_mult=2.0, tp_mult=NO_STOP))
    acoplado = _cycle(bars, AtrParams(stop_mult=3.0, tp_mult=NO_STOP))
    # con el trail pineado en 2.0 el nivel queda más arriba ⇒ sale antes o igual
    assert d1.held_days <= acoplado.held_days


# ── 3. Los oráculos ──────────────────────────────────────────────────────────


def test_oraculo_permite_el_stop_solo_si_la_caida_sigue():
    bajando = _bars([100.0 - i for i in range(40)])
    subiendo = _bars([100.0 + i for i in range(40)])
    assert _oracle_stop_filter(bajando, 5) is True     # close[25] < close[5]
    assert _oracle_stop_filter(subiendo, 5) is False   # rebota ⇒ el stop no dispara


def test_anti_oraculo_es_el_espejo():
    bajando = _bars([100.0 - i for i in range(40)])
    subiendo = _bars([100.0 + i for i in range(40)])
    assert _anti_oracle_stop_filter(bajando, 5) is False
    assert _anti_oracle_stop_filter(subiendo, 5) is True


def test_oraculos_caen_al_baseline_sin_horizonte():
    """Sin barra ``i+20`` los dos permiten el stop: no se inventa ventaja al final."""
    corta = _bars([100.0] * (ORACLE_HORIZON + 2))
    i = len(corta) - 1
    assert _oracle_stop_filter(corta, i) is True
    assert _anti_oracle_stop_filter(corta, i) is True


def test_control_aleatorio_es_determinista_y_respeta_la_tasa():
    """El control post-hoc no puede depender del ``hash()`` salteado por proceso."""
    bars = _bars([100.0 + (i % 7) for i in range(400)])
    f1 = random_stop_filter(0.463, seed=42)
    f2 = random_stop_filter(0.463, seed=42)
    dec1 = [f1(bars, i) for i in range(len(bars))]
    assert dec1 == [f2(bars, i) for i in range(len(bars))]
    tasa = sum(dec1) / len(dec1)
    assert 0.38 < tasa < 0.55           # ~0.463 con tolerancia de muestra
    otra = random_stop_filter(0.463, seed=43)
    assert dec1 != [otra(bars, i) for i in range(len(bars))]


def test_oraculo_le_gana_al_baseline_en_un_dip_que_rebota():
    bars = _flat_then([97.0, 94.0] + [104.0] * 25)
    a = AtrParams(stop_mult=2.0)
    base = _cycle(bars, a)
    orac = _cycle(bars, a, stop_filter=_oracle_stop_filter)
    assert "atr_stop" in base.exit_reasons
    assert orac.ret > base.ret


# ── 4. Regla de decisión (§6) ────────────────────────────────────────────────


def _summ(cagr, sharpe, max_dd, stop_share=0.20):
    return {"cagr": cagr, "sharpe": sharpe, "max_dd": max_dd, "p5_trade": -0.07,
            "accounting_ok": True, "n_taken": 100, "n_offered": 200, "exposure": 0.6,
            "stop_share": stop_share, "exit_mix": {"atr_stop": stop_share},
            "total_return_pts": 0.0}


def _reg(vals):
    return {name: {"n": 20, "mean_ret_pts": v} for name, v in zip(_REG_NAMES, vals)}


class _Boot:
    def __init__(self, ci_low):
        self.ci_low = ci_low
        self.observed = 0.03
        self.ci_high = 0.06
        self.p_value = 0.01
        self.block = 20
        self.n_resamples = 2000


def _case(**over):
    """Un caso donde TODO pasa; ``over`` pisa brazos puntuales."""
    summaries = {
        "S_1.0": _summ(0.060, 0.40, 0.42, 0.55),
        "S_1.5": _summ(0.090, 0.60, 0.40, 0.38),
        "S_2.0": _summ(0.100, 0.70, 0.39, 0.25),   # baseline
        "S_2.5": _summ(0.112, 0.76, 0.39, 0.18),   # acompaña al candidato (C6)
        "S_3.0": _summ(0.130, 0.85, 0.40, 0.12),   # candidato
        "S_3.5": _summ(0.120, 0.80, 0.41, 0.07),
        "S_off": _summ(0.105, 0.72, 0.44, 0.00),
    }
    summaries.update(over.get("summaries", {}))
    regimes = {n: _reg([0.20, -0.30, 0.90, -0.10]) for n in summaries}
    regimes["S_3.0"] = _reg([0.28, -0.28, 0.95, -0.08])
    regimes.update(over.get("regimes", {}))
    return summaries, regimes


def test_candidato_es_el_mejor_sharpe_entre_los_seis():
    summaries, _ = _case()
    assert pick_candidate(summaries) == "S_3.0"
    assert BASELINE_ARM not in tuple(n for n in DECISION_ARMS if n != BASELINE_ARM)


def test_ship_cuando_pasan_los_seis():
    summaries, regimes = _case()
    v = evaluate(summaries, regimes, _Boot(0.008), "S_3.0")
    assert v["ship"] is True
    assert all(v[k] for k in ("c1_cagr", "c2_maxdd", "c3_boot", "c4_sharpe",
                              "c5_regime", "c6_dose"))


def test_noship_si_el_dcagr_no_llega():
    summaries, regimes = _case(summaries={"S_3.0": _summ(0.103, 0.85, 0.40, 0.12)})
    v = evaluate(summaries, regimes, _Boot(0.008), "S_3.0")
    assert v["c1_cagr"] is False and v["ship"] is False


def test_noship_si_el_maxdd_empeora_mas_de_2pp():
    """El caso partido resuelto ex ante: más CAGR comprado con drawdown NO shipea."""
    summaries, regimes = _case(summaries={"S_3.0": _summ(0.130, 0.85, 0.42, 0.12)})
    v = evaluate(summaries, regimes, _Boot(0.008), "S_3.0")
    assert v["c1_cagr"] is True          # el retorno mejora...
    assert v["c2_maxdd"] is False        # ...pero el riesgo se pasa del umbral
    assert v["ship"] is False


def test_noship_si_el_bootstrap_cruza_cero():
    summaries, regimes = _case()
    v = evaluate(summaries, regimes, _Boot(-0.002), "S_3.0")
    assert v["c3_boot"] is False and v["ship"] is False


def test_noship_si_rompe_un_regimen():
    summaries, regimes = _case(regimes={"S_3.0": _reg([0.28, -0.28, 0.95, -0.40])})
    v = evaluate(summaries, regimes, _Boot(0.008), "S_3.0")
    assert v["c5_regime"] is False and v["ship"] is False


def test_noship_si_el_sharpe_cae_demasiado():
    summaries, regimes = _case(summaries={"S_3.0": _summ(0.130, 0.60, 0.40, 0.12)})
    v = evaluate(summaries, regimes, _Boot(0.008), "S_3.0")
    assert v["c4_sharpe"] is False and v["ship"] is False


# ── C6 reformulado (enmienda §0) ─────────────────────────────────────────────


def test_c6_el_baseline_no_cuenta_como_vecino():
    """El defecto que la enmienda §0 corrige: si el baseline contara, C6 sería vacuo."""
    summaries, _ = _case(summaries={
        "S_2.5": _summ(0.090, 0.60, 0.39, 0.18),   # peor que el baseline
        "S_3.0": _summ(0.130, 0.85, 0.40, 0.12),   # pico aislado
        "S_3.5": _summ(0.095, 0.55, 0.41, 0.07),
        "S_off": _summ(0.098, 0.50, 0.44, 0.00),
    })
    assert c6_dose_response(summaries, "S_3.0") is False


def test_c6_pasa_cuando_un_vecino_del_mismo_lado_acompana():
    summaries, _ = _case()
    assert c6_dose_response(summaries, "S_3.0") is True


def test_c6_es_aplicable_al_lado_estricto():
    """Con la enmienda, un candidato estricto también puede pasar C6 (antes no podía)."""
    summaries, _ = _case(summaries={
        "S_1.0": _summ(0.140, 0.90, 0.36, 0.55),   # candidato estricto
        "S_1.5": _summ(0.105, 0.75, 0.38, 0.38),   # acompaña (Δ ≥ 0)
    })
    assert c6_dose_response(summaries, "S_1.0") is True
    summaries["S_1.5"] = _summ(0.080, 0.50, 0.38, 0.38)   # deja de acompañar
    assert c6_dose_response(summaries, "S_1.0") is False


# ── 5. Sanity del instrumento (§5) ───────────────────────────────────────────


def test_monotonia_mecanica_del_stop_share():
    summaries, _ = _case()
    assert stop_share_monotone(summaries) is True


def test_monotonia_mecanica_falla_si_el_orden_se_rompe():
    summaries, _ = _case(summaries={"S_2.5": _summ(0.112, 0.76, 0.39, 0.30)})
    assert stop_share_monotone(summaries) is False


def test_monotonia_mecanica_exige_cero_en_s_off():
    summaries, _ = _case(summaries={"S_off": _summ(0.105, 0.72, 0.44, 0.02)})
    assert stop_share_monotone(summaries) is False
