"""Tareas 94, 95 y 96 — tres perillas vivas que el harness no modela, declaradas.

Las tres estaban **encendidas en la cuenta 2** y ningún runner las modela. Hasta
la auditoría `desvios` del 2026-09-02, que se las declarara dependía de que el
autor del pre-registro se acordara de escribirlo a mano:

* el **escalado por régimen** aparecía en **14** pre-registros,
* el **blackout de earnings** en **7**,
* el **overlay de volatilidad** en **ninguno**.

Y el pre-registro más nuevo (T51) **dejó de enumerarlos y delegó en
`deviations()`** — o sea que desde ahí, **lo que la función no dice no lo dice
nadie**. Ése es el hilo que une a los tres.
"""

from __future__ import annotations

import pytest

from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    config_banner,
    deviations,
)


def _cfg(**kw) -> HarnessConfig:
    return HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, **kw)


_CASOS = [
    ("models_vol_overlay", "overlay de volatilidad", "todos los días"),
    ("models_regime_scale", "escalado por régimen", "0 de 62"),
    ("models_earnings_blackout", "blackout de earnings", "15.8%"),
]


@pytest.mark.parametrize("campo,texto,numero", _CASOS, ids=[c[0] for c in _CASOS])
def test_se_declara_cuando_el_runner_no_lo_modela(campo, texto, numero):
    """Ningún runner los modela hoy, así que el default declara lo que corre."""
    devs = [d for d in deviations(_cfg()) if texto in d]
    assert len(devs) == 1
    assert numero in devs[0], "el desvío tiene que llevar su número medido, no una vaguedad"


@pytest.mark.parametrize("campo,texto,_n", _CASOS, ids=[c[0] for c in _CASOS])
def test_deja_de_declararse_si_el_runner_dice_que_lo_modela(campo, texto, _n):
    """Mismo criterio que `live_gates`: modelarlo saca el desvío, no lo silencia."""
    assert [d for d in deviations(_cfg(**{campo: True})) if texto in d] == []


def test_los_tres_llegan_al_banner():
    """Un desvío que no llega al banner no lo lee nadie."""
    banner = config_banner(_cfg())
    for _campo, texto, _n in _CASOS:
        assert texto in banner


# `test_las_constantes_son_las_de_la_cuenta_viva` vivía acá y **se reemplazó** por
# `tests/test_espejos_vivos_t130.py` (tarea 130).
#
# Su comentario decía *«este test hizo su trabajo: pinneaba el 0.5 y falló al cambiar
# el valor vivo»*, y era **falso**: `git show --stat 2a4404a` muestra que
# `analysis/harness_config.py` y el assert cambiaron en el **mismo commit**. Disparó
# sobre la edición del repo, nunca sobre la del `settings.json` — no podía, porque
# comparaba contra un literal escrito en este mismo archivo.


def test_apagar_la_perilla_viva_saca_el_desvio(monkeypatch):
    """Contraprueba: el desvío cuelga de que la perilla esté **encendida en vivo**,
    no de una lista fija. Si mañana se apaga el overlay, deja de haber desvío."""
    import analysis.harness_config as hc

    monkeypatch.setattr(hc, "LIVE_VOL_OVERLAY_ENABLED", False)
    assert [d for d in deviations(_cfg()) if "overlay de volatilidad" in d] == []


def test_el_de_earnings_dice_que_NO_es_modelable():
    """El caveat que cambia la remediación: no hay fechas de earnings PIT a 10
    años, así que el cierre honesto es declararlo, no modelarlo. Si eso no está
    escrito, alguien va a abrir una tarea para modelar algo imposible."""
    dev = next(d for d in deviations(_cfg()) if "blackout de earnings" in d)
    assert "NO es modelable hoy" in dev and "point-in-time" in dev
