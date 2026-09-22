"""Tarea 219 — tests offline del runner y del hook, ANTES de correr (§8.1 del pre-registro).

El pre-registro (`docs/signal_exit_delay_prereg_t219_2026-09-22.md`) exige tests del runner
antes de la corrida, y por un motivo concreto: los brazos sanity **deciden si la corrida es
válida**, así que un sanity mal implementado no da un número malo, da un veredicto que
parece bueno.

**Lo que se fija acá:**

* que ``senal_filter=None`` **no cambie nada** — el baseline de esta tarea tiene que ser
  idéntico a lo que midieron la T7, la T13 y la T170, o los Δ no son comparables;
* que el hook suprima de verdad cuando dice que suprime;
* que el oráculo **permita** cuando no hay barra futura, en vez de inventar una ventaja;
* que el sorteo del control vaya por **(semilla, ticker, fecha)** y no por índice de barra
  — la lección de la tarea **164**, que dejó inválidas dos corridas con veredicto
  publicado;
* que la regla de decisión exija **las cuatro** condiciones, y en particular que la
  heredada de la T7 (el signo en stress) **rechace** un brazo que se dé vuelta.
"""

from __future__ import annotations

import pytest

from analysis.portfolio_sim import simulate_portfolio
from analysis.scaleout_replay import AtrParams, CostModel, ScaleOutParams, replay_cycle
from scripts.run_signal_exit_delay_t219 import (
    AZAR,
    BASELINE,
    DESAFIANTES,
    ORACULO,
    REFERENCIA,
    T170_BASELINE_CAGR,
    T170_BASELINE_SHARPE,
    T170_BASELINE_TAKEN,
    _oraculo_salida,
    _so_params,
    azar_misma_tasa,
    evaluar,
    evaluar_sanity,
    tenencia_media,
)

# ── fixtures sintéticas ──────────────────────────────────────────────────────


def _bars(closes: list[float], start_day: int = 1) -> list[tuple]:
    """`[(iso10, open, high, low, close)]` con rango intradía ±2%."""
    out = []
    for k, c in enumerate(closes):
        dia = f"2024-01-{start_day + k:02d}"
        out.append((dia, c, c * 1.02, c * 0.98, c))
    return out


_SUBE = _bars([100.0 + k for k in range(40)])


def _sig_sell_en(bars, idxs: set[int]) -> dict:
    return {b[0]: ("SELL" if k in idxs else "HOLD") for k, b in enumerate(bars)}


_ATR = AtrParams(stop_mult=0.0, trail_mult=2.0, tp_mult=4.0)
_SO = ScaleOutParams(sell_fraction=1.0, min_age_bdays=0, bypass_score=0.25)


def _ciclo(**kw):
    base = {
        "params": _SO,
        "atr_p": _ATR,
        "cap_days": 30,
        "costs": CostModel(),
        "notional": 10_000.0,
        "ticker": "AAA",
    }
    base.update(kw)
    return replay_cycle(_SUBE, 0, _sig_sell_en(_SUBE, {5}), **base)


# ── El hook: que None no cambie NADA ─────────────────────────────────────────


def test_senal_filter_None_es_identico_a_no_pasarlo():
    """**La propiedad que hace comparables los Δ.** Si el default moviera aunque sea un
    centavo, el baseline de esta tarea dejaría de ser el de la T7/T13/T170."""
    sin = _ciclo()
    con_none = _ciclo(senal_filter=None)

    assert sin is not None and con_none is not None
    assert [(lg.date, lg.price, lg.shares, lg.reason) for lg in sin.legs] == [
        (lg.date, lg.price, lg.shares, lg.reason) for lg in con_none.legs
    ]


def test_el_filtro_que_dice_NO_suprime_la_salida_por_senal():
    con_salida = _ciclo()
    suprimida = _ciclo(senal_filter=lambda bars, i, ticker="": False)

    assert any("signal" in (lg.reason or "") for lg in con_salida.legs), "el baseline SÍ vende"
    assert not any("signal" in (lg.reason or "") for lg in suprimida.legs), "y el filtro lo impide"


def test_el_filtro_que_dice_SI_deja_todo_igual():
    """La contraprueba: un filtro que permite siempre es el baseline."""
    base = _ciclo()
    permisivo = _ciclo(senal_filter=lambda bars, i, ticker="": True)

    assert [lg.reason for lg in base.legs] == [lg.reason for lg in permisivo.legs]


def test_el_filtro_va_DESPUES_de_la_histeresis():
    """Con Gate 2b bloqueando la venta, el filtro no puede *habilitarla*.

    Importa porque si actuara antes, el sanity mediría un universo de salidas que el
    motor vivo nunca ofreció — y el oráculo se vería mejor de lo que es.
    """
    so = ScaleOutParams(sell_fraction=1.0, min_age_bdays=20, bypass_score=0.0)
    r = _ciclo(params=so, senal_filter=lambda bars, i, ticker="": True)

    assert not any("signal" in (lg.reason or "") for lg in r.legs), (
        "la edad mínima manda: el filtro permite pero el gate no dejó llegar"
    )


# ── El oráculo ───────────────────────────────────────────────────────────────


def test_el_oraculo_deja_vender_si_vender_era_CORRECTO():
    """`close[i+20] < close[i]` ⇒ vender estuvo bien ⇒ se permite."""
    bajando = _bars([200.0 - k for k in range(40)])
    assert _oraculo_salida(bajando, 0) is True


def test_el_oraculo_suprime_si_el_precio_SUBIO():
    assert _oraculo_salida(_SUBE, 0) is False


def test_sin_barra_FUTURA_el_oraculo_PERMITE():
    """**No inventa ventaja.** Al final de la serie cae al baseline, que es la misma
    decisión que tomó el oráculo de la T26. Si suprimiera, se estaría regalando al brazo
    un tramo de retención gratis justo donde no hay dato para justificarlo."""
    assert _oraculo_salida(_SUBE, len(_SUBE) - 1) is True
    assert _oraculo_salida(_SUBE, len(_SUBE) - 5) is True


# ── El control igualado en tasa (lección de la tarea 164) ────────────────────


def test_el_azar_EXIGE_el_ticker():
    """Sin ticker el sorteo es una moneda por fecha, igual para toda la cartera."""
    f = azar_misma_tasa(0.5)
    with pytest.raises(ValueError, match="necesita el ticker"):
        f(_SUBE, 0, "")


def test_el_sorteo_depende_del_TICKER_y_no_solo_de_la_fecha():
    f = azar_misma_tasa(0.5)
    decisiones = {t: f(_SUBE, 3, t) for t in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")}
    assert len(set(decisiones.values())) == 2, f"todas iguales ⇒ es una moneda por fecha: {decisiones}"


def test_el_sorteo_NO_depende_del_INDICE_de_barra():
    """**La lección de la tarea 164, fijada.** Con la clave por índice, recortar la cabeza
    del frame re-sorteaba el 51% de las decisiones para las MISMAS fechas — y eso invalidó
    dos corridas con veredicto publicado. Acá: mismo ticker, misma fecha, índice distinto
    porque el frame arranca más tarde ⇒ **misma** decisión."""
    f = azar_misma_tasa(0.5)
    recortado = _SUBE[7:]  # la fecha de _SUBE[10] ahora vive en el índice 3

    assert _SUBE[10][0] == recortado[3][0], "la fixture tiene que apuntar a la misma fecha"
    assert f(_SUBE, 10, "AAA") == f(recortado, 3, "AAA")


def test_el_azar_respeta_la_tasa_pedida():
    """Con tasa 0 no deja pasar ninguna; con 1, todas. En el medio, aproximadamente."""
    assert all(not azar_misma_tasa(0.0)(_SUBE, k, "AAA") for k in range(len(_SUBE)))
    assert all(azar_misma_tasa(1.0)(_SUBE, k, "AAA") for k in range(len(_SUBE)))
    f = azar_misma_tasa(0.5)
    tickers = [f"T{k:03d}" for k in range(400)]
    tasa = sum(f(_SUBE, 3, t) for t in tickers) / len(tickers)
    assert 0.40 < tasa < 0.60, tasa


# ── Los brazos del gate mueven UNA perilla ───────────────────────────────────


def test_el_baseline_es_la_perilla_VIVA():
    p = _so_params(BASELINE)
    assert p.min_age_bdays == 3, "la cuenta 2 corre con paper_signal_sell_min_age_bdays=3"
    assert p.sell_fraction == 1.0, "y la señal cierra entero"


@pytest.mark.parametrize("brazo,edad", [("age5", 5), ("age10", 10), ("age20", 20)])
def test_los_desafiantes_solo_mueven_la_edad(brazo, edad):
    p = _so_params(brazo)
    assert p.min_age_bdays == edad
    assert p.sell_fraction == 1.0, "no se toca la fracción: eso es el eje de la T7"
    assert p.bypass_score == 0.25, "ni el bypass: mover dos perillas hace indecidible cuál movió"


def test_la_referencia_es_C_A4_y_no_un_desafiante():
    """`C_A4_repl` existe para saber cuánto hay disponible en esta población, no para
    competir: su veredicto ya lo dio la T7."""
    assert _so_params(REFERENCIA).sell_fraction == 0.0
    assert REFERENCIA not in DESAFIANTES


# ── La regla de decisión: hacen falta LAS CUATRO ─────────────────────────────


def _res(cagr, sharpe, dd, held=8.0, taken=500):
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": dd,
        "held_days": held,
        "signal_exit_share": 0.5,
        "n_taken": taken,
        "accounting_ok": True,
    }


def _base_t170(**kw):
    """El baseline sintético **reproduciendo la T170**, que es lo que el sanity exige.

    Va acá y no inline porque si no cada test que arma un `res` tiene que acordarse de los
    tres números, y el que se olvide sale INVÁLIDO por el motivo equivocado.
    """
    base = _res(T170_BASELINE_CAGR, T170_BASELINE_SHARPE, 0.284, held=7.9, taken=T170_BASELINE_TAKEN)
    base.update(kw)
    return base


def test_un_brazo_con_magnitud_pero_signo_NEGATIVO_en_stress_NO_pasa():
    """**El criterio heredado de la T7, y es el que mató a C_A4.** Sin esta mitad se
    estaría midiendo con una regla más laxa que la que ya rechazó al brazo vecino."""
    res = {BASELINE: _res(0.15, 1.0, 0.20), "age5": _res(0.17, 1.2, 0.19)}
    regs = {"age5": {"bull_normal": [0.02] * 50, "stress_bear_2022": [-0.01] * 30}}

    v = evaluar(res, regs, {})["age5"]
    assert v["magnitud_ok"] and v["maxdd_ok"], "la magnitud y el DD sí dan"
    assert not v["stress_signo_ok"], "pero se da vuelta en bear-2022"
    assert v["PASS"] is False


def test_el_mismo_brazo_SIN_el_signo_negativo_SI_pasa():
    """La otra dirección: si el criterio rechazara siempre, no informaría."""
    res = {BASELINE: _res(0.15, 1.0, 0.20), "age5": _res(0.17, 1.2, 0.19)}
    regs = {"age5": {"bull_normal": [0.02] * 50, "stress_bear_2022": [0.005] * 30}}

    v = evaluar(res, regs, {})["age5"]
    assert v["stress_signo_ok"] and v["PASS"] is True


def test_sin_magnitud_no_pasa_aunque_el_stress_este_limpio():
    res = {BASELINE: _res(0.15, 1.0, 0.20), "age5": _res(0.152, 1.02, 0.19)}
    regs = {"age5": {"bull_normal": [0.001] * 50, "stress_bear_2022": [0.001] * 30}}

    assert evaluar(res, regs, {})["age5"]["PASS"] is False


def test_subir_el_maxDD_no_pasa():
    res = {BASELINE: _res(0.15, 1.0, 0.20), "age5": _res(0.20, 1.4, 0.25)}
    regs = {"age5": {"bull_normal": [0.05] * 50}}

    v = evaluar(res, regs, {})["age5"]
    assert v["magnitud_ok"] and not v["maxdd_ok"] and v["PASS"] is False


def test_la_tenencia_va_SIEMPRE_al_lado_del_delta():
    """No es cosmético: es la variable que explicó el veredicto de la T7."""
    res = {BASELINE: _res(0.15, 1.0, 0.20, held=7.5), "age5": _res(0.17, 1.2, 0.19, held=13.0)}
    v = evaluar(res, {"age5": {"bull_normal": [0.02] * 50}}, {})["age5"]

    assert v["held_days"] == 13.0
    assert v["held_days_vs_base"] == pytest.approx(5.5)


# ── El sanity decide si hay veredicto ────────────────────────────────────────


def test_si_el_oraculo_no_se_separa_del_azar_la_corrida_es_INVALIDA():
    """Si un brazo que elige mirando el futuro no gana, el harness no ve **calidad** de
    salida y ningún Δ de los brazos del gate significa algo."""
    res = {
        BASELINE: _base_t170(),
        "age5": _res(0.16, 1.1, 0.19),
        "age10": _res(0.16, 1.1, 0.19),
        "age20": _res(0.16, 1.1, 0.19),
        REFERENCIA: _res(0.17, 1.1, 0.19),
        ORACULO: _res(0.16, 1.1, 0.19),
        AZAR: _res(0.159, 1.1, 0.19),
    }
    s = evaluar_sanity(res)
    assert not s["oraculo_ok"] and s["VALIDA"] is False


def test_con_el_oraculo_separado_la_corrida_es_VALIDA():
    res = {
        BASELINE: _base_t170(),
        "age5": _res(0.16, 1.1, 0.19),
        "age10": _res(0.16, 1.1, 0.19),
        "age20": _res(0.16, 1.1, 0.19),
        REFERENCIA: _res(0.17, 1.1, 0.19),
        ORACULO: _res(0.25, 1.6, 0.15),
        AZAR: _res(0.155, 1.05, 0.19),
    }
    s = evaluar_sanity(res)
    assert s["oraculo_ok"] and s["VALIDA"] is True


def test_una_contabilidad_rota_invalida_la_corrida():
    res = {
        BASELINE: _base_t170(),
        ORACULO: _res(0.25, 1.6, 0.15),
        AZAR: _res(0.155, 1.05, 0.19),
    }
    res[BASELINE]["accounting_ok"] = False
    assert evaluar_sanity(res)["VALIDA"] is False


def test_la_monotonia_es_un_sanity_BLANDO():
    """Declarado en el pre-registro: si la curva sale en U **no invalida**, pero obliga a
    explicar por qué antes de leer el veredicto — es lo que le pasó a la T23 con el TP."""
    res = {
        BASELINE: _base_t170(),
        "age5": _res(0.19, 1.1, 0.19),
        "age10": _res(0.16, 1.1, 0.19),
        "age20": _res(0.17, 1.1, 0.19),
        REFERENCIA: _res(0.18, 1.1, 0.19),
        ORACULO: _res(0.25, 1.6, 0.15),
        AZAR: _res(0.155, 1.05, 0.19),
    }
    s = evaluar_sanity(res)
    assert not s["monotona"], "la curva sale desordenada"
    assert s["VALIDA"] is True, "pero eso NO invalida la corrida"


# ── El sanity que cazó el bug de esta tarea ─────────────────────────────────


def test_el_baseline_tiene_que_reproducir_el_numero_PUBLICADO_de_la_T170():
    """`age3` **es** el `soff_t2.0` de la T170: misma config viva, misma población, misma
    ventana, `ScaleOutParams()` por default. Así que tiene que dar su número publicado."""
    s = evaluar_sanity(
        {BASELINE: _base_t170(), ORACULO: _res(0.25, 1.6, 0.15), AZAR: _res(0.155, 1.05, 0.19)}
    )
    assert s["repro_t170"]["OK"] and s["VALIDA"] is True


@pytest.mark.parametrize(
    "campo,valor",
    [("cagr", -0.179), ("sharpe", -1.76), ("n_taken", 8838)],
    ids=["cagr", "sharpe", "trades"],
)
def test_un_baseline_que_NO_reproduce_INVALIDA_la_corrida(campo, valor):
    """**La dirección que importa, y con los números del caso REAL que la motivó.**

    La primera corrida de esta tarea puso `stop_mult=0.0` creyendo que era el stop apagado
    —es `NO_STOP=1e9`— y con eso el stop quedó **en el precio de entrada**: salió con
    **8.838** trades, tenencia 1,6 días y CAGR **−17,9%** con Sharpe **−1,76** en los siete
    brazos. Y lo peligroso: **los Δ entre brazos seguían pareciendo razonables y la curva
    seguía siendo monótona**, así que el veredicto habría salido sin que nada lo marcara.
    Los tres valores de este parametrize son los que salieron de verdad.
    """
    base = _base_t170(**{campo: valor})
    s = evaluar_sanity({BASELINE: base, ORACULO: _res(0.25, 1.6, 0.15), AZAR: _res(0.155, 1.05, 0.19)})

    assert not s["repro_t170"]["OK"], f"{campo}={valor} no reproduce la T170"
    assert s["VALIDA"] is False, "y eso tiene que invalidar la corrida"


def test_la_referencia_de_reproduccion_es_EXTERNA_a_la_corrida():
    """Por qué la T170 y no un número de esta misma corrida.

    Si la referencia saliera de la población que se chequea, sería **ciega al defecto que
    afecta a todos los brazos** — que es exactamente lo que pasó acá (los siete daban
    −17%) y el defecto que las tareas 101 y 110 dejaron documentado. Los números están
    clavados del doc publicado, no derivados de esta corrida."""
    assert T170_BASELINE_CAGR == 0.0878
    assert T170_BASELINE_SHARPE == 0.55
    assert T170_BASELINE_TAKEN == 2531


# ── Integración mínima: el hook llega hasta simulate_portfolio ───────────────


def test_el_hook_llega_a_simulate_portfolio():
    bars_by = {"AAA": _SUBE}
    sigs_by = {"AAA": _sig_sell_en(_SUBE, {5})}
    common = {
        "max_positions": 10,
        "initial_capital": 50_000.0,
        "cap_days": 30,
        "atr_p": _ATR,
        "costs": CostModel(),
        "so_params": _SO,
    }
    con = simulate_portfolio([("AAA", 0)], bars_by, sigs_by, **common)
    sin = simulate_portfolio([("AAA", 0)], bars_by, sigs_by, senal_filter=lambda b, i, t="": False, **common)

    assert con.trades and sin.trades
    assert "signal" in (con.trades[0].exit_reason or "")
    assert "signal" not in (sin.trades[0].exit_reason or "")
    assert tenencia_media(sin) > tenencia_media(con), "suprimir la salida retiene más"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
