"""Tarea 152 (DESVIOS-SIN-CLAVE) — cada desvío tiene una clave estable.

``deviations()`` devolvía ``list[str]`` de prosa y **todos** sus consumidores lo
filtraban por substring. Eso hace que agregar un desvío tenga radio de impacto
desconocido, y no es hipotético: la tarea 131 agregó *«NO se modela el **screen de
universo** E1b…»* y con eso **rompió ``test_watchlist_size_t89.py``**, cuyo filtro era
``"universo" in d`` y estaba buscando el desvío de **tamaño** del universo, que es
otro. En la misma tarea rompió también el helper que yo acababa de escribir para la
132, que filtraba por ``"barreras ATR"`` y se traía tres líneas de tres ejes
distintos.

**Los dos fallos se vieron porque eran tests.** Un consumidor que *no* falle —un
filtro que empiece a agarrar de más y siga verde— declara el desvío equivocado en un
pre-registro, que es exactamente la clase de defecto que la tarea 92 costó **7,16 pp
de CAGR**.

El segundo síntoma del mismo origen era el **conteo**: había dos tests pinneando
``len(devs)``, y un número total es lo que se pinnea cuando no hay forma de nombrar
los elementos. Ahora se pinnea el **conjunto de claves**, que dice *qué* cambió en
vez de *cuánto*.

**Comportamiento neutro, verificado byte a byte.** El banner de 8 configs —una por
rama de ``deviations()``— sale **idéntico** antes y después del refactor (27.325
bytes en las dos). ``deviations()`` sigue devolviendo ``list[str]`` y ningún runner se
tocó; lo que se agrega es ``deviations_keyed()`` para el que necesite **identificar**
un desvío en vez de reconocerlo por cómo está escrito.
"""

from __future__ import annotations

import pytest

import analysis.harness_config as hc
from analysis.harness_config import (
    LEGACY_FILL_MODE,
    LIVE_MAX_POSITIONS,
    LIVE_TRAIL_MULT,
    LIVE_WATCHLIST_SIZE,
    NO_STOP_MULT,
    ArtifactWindow,
    HarnessConfig,
    deviations,
    deviations_keyed,
)

# El catálogo. Una clave se elige **una vez** y no se toca: es el contrato con el que
# los consumidores identifican un desvío. El texto sí puede reescribirse libremente,
# que es todo el punto de separarlos.
CLAVES_CONOCIDAS = frozenset(
    {
        "slots",
        "universo_size",
        "analyze_window",
        "barrier_eval",
        "barrier_fill",
        "barrier_fill_lookahead",
        "artifact_window",
        "artifact_window_undeclared",
        "atr_master_off",
        "atr_hard_stop",
        "atr_trail",
        "vol_overlay",
        "regime_scale",
        "universe_screen",
        "earnings_blackout",
        "reentry_gates",
        "reentry_gates_no_cartera",
    }
)


def _cfg(**kw) -> HarnessConfig:
    return HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, **kw)


def _todas_las_ramas(monkeypatch) -> list[HarnessConfig]:
    """Configs que entre todas ejercitan **cada** rama de ``deviations()``.

    Es la contraprueba de la que dependen los dos tests de abajo: un catálogo
    verificado contra una sola config diría que sobran quince claves.
    """
    return [
        _cfg(),
        HarnessConfig(5, "x.txt", 127),  # slots + universo_size
        _cfg(eval_mode="touch"),
        _cfg(fill_mode=LEGACY_FILL_MODE),
        _cfg(live_gates=True),
        _cfg(per_trade=True),
        _cfg(atr_stop_mult=NO_STOP_MULT, atr_trail_mult=LIVE_TRAIL_MULT),
        # Sólo el trailing: el stop espeja lo vivo (apagado) y el trail no.
        _cfg(atr_stop_mult=NO_STOP_MULT, atr_trail_mult=3.0),
        _cfg(window=ArtifactWindow("2016-08-08", "2026-09-01", 2514)),
        _cfg(
            models_vol_overlay=True,
            models_regime_scale=True,
            models_earnings_blackout=True,
            models_universe_screen=True,
        ),
    ]


def _claves(cfgs) -> set[str]:
    return {d.clave for cfg in cfgs for d in deviations_keyed(cfg)}


# ── El contrato ──────────────────────────────────────────────────────────────


def test_deviations_es_EXACTAMENTE_el_texto_de_deviations_keyed(monkeypatch):
    """La API vieja no se movió: es la nueva, proyectada. Ningún runner se tocó."""
    for cfg in _todas_las_ramas(monkeypatch):
        assert deviations(cfg) == [d.texto for d in deviations_keyed(cfg)]


def test_ninguna_clave_emitida_queda_fuera_del_catalogo(monkeypatch):
    """**El test que obliga a un desvío nuevo a registrarse.**

    Si alguien agrega una línea a ``deviations()`` sin darle una clave conocida, esto
    falla y lo obliga a decidir cómo se va a llamar — que es la decisión que antes no
    existía y por eso los consumidores tenían que adivinar por el texto.
    """
    monkeypatch.setattr(hc, "LIVE_ATR_STOPS_ENABLED", False)
    con_switch_off = _claves(_todas_las_ramas(monkeypatch))
    monkeypatch.setattr(hc, "LIVE_ATR_STOPS_ENABLED", True)
    emitidas = con_switch_off | _claves(_todas_las_ramas(monkeypatch))

    assert not (sin := emitidas - CLAVES_CONOCIDAS), (
        f"estos desvíos emiten una clave que no está en el catálogo: {sorted(sin)}"
    )


def test_el_catalogo_no_tiene_claves_FANTASMA(monkeypatch):
    """La contraprueba: una clave que ya nadie emite es una promesa vencida.

    Sin esto el catálogo envejecería en la dirección opuesta —llenándose de claves
    muertas— y el test de arriba pasaría igual de verde.
    """
    monkeypatch.setattr(hc, "LIVE_ATR_STOPS_ENABLED", False)
    emitidas = _claves(_todas_las_ramas(monkeypatch))
    monkeypatch.setattr(hc, "LIVE_ATR_STOPS_ENABLED", True)
    emitidas |= _claves(_todas_las_ramas(monkeypatch))

    assert not (fantasmas := CLAVES_CONOCIDAS - emitidas), (
        f"estas claves ya no las emite nadie: {sorted(fantasmas)}"
    )


@pytest.mark.parametrize("i", range(10))
def test_una_corrida_no_repite_claves(i, monkeypatch):
    """Dos desvíos con la misma clave en la misma corrida hacen que filtrar por clave
    devuelva de más — el defecto que se está arreglando, con otra ropa."""
    cfg = _todas_las_ramas(monkeypatch)[i]
    claves = [d.clave for d in deviations_keyed(cfg)]
    assert len(claves) == len(set(claves)), f"claves repetidas: {claves}"


# ── El conteo pasa a ser un CONJUNTO ─────────────────────────────────────────


def test_la_config_viva_declara_este_CONJUNTO_de_desvios():
    """Reemplaza semánticamente al ``len(devs) == 10``.

    Un número dice *cuántos*; el conjunto dice *cuáles*. Cuando la tarea 131 agregó
    el screen, el test de conteo falló con `assert 9 == 10` — que no le dice a nadie
    qué pasó. Esto falla nombrando la clave que entró o salió.
    """
    assert {d.clave for d in deviations_keyed(_cfg())} == {
        "analyze_window",
        "barrier_eval",
        "barrier_fill",
        "artifact_window_undeclared",
        "atr_hard_stop",
        "vol_overlay",
        "regime_scale",
        "universe_screen",
        "earnings_blackout",
        "reentry_gates",
    }


def test_el_master_switch_apagado_REEMPLAZA_las_dos_lineas_de_barreras(monkeypatch):
    """La 132 vista por claves: no es que se agregue una línea, es que ``atr_master_off``
    **ocupa el lugar** de ``atr_hard_stop`` y ``atr_trail``."""
    monkeypatch.setattr(hc, "LIVE_ATR_STOPS_ENABLED", False)
    claves = {d.clave for d in deviations_keyed(_cfg())}

    assert "atr_master_off" in claves
    assert not ({"atr_hard_stop", "atr_trail"} & claves)


def test_las_dos_lineas_de_universo_son_claves_DISTINTAS():
    """El choque exacto que abrió esta tarea: el desvío de **tamaño** del universo y
    el del **screen** de universo comparten la palabra y no la clave."""
    claves = {d.clave for d in deviations_keyed(HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", 127))}
    assert {"universo_size", "universe_screen"} <= claves
