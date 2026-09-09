"""Tareas 131 y 132 — las dos perillas vivas que no tenían espejo.

Son el **punto ciego declarado** del guard de la 130: ése cierra *«el espejo dejó de
seguir al vivo»* y no puede ver *«hay algo vivo sin espejo»*. Éstas eran las dos que
estaban en esa situación, y por eso se cierran juntas y detrás de él — así nacen con
guard en vez de nacer invisibles.

**131 — SCREEN-DESVIO.** `paper_universe_screen_enabled` está en `True` desde el
2026-09-07 y `strategies.py:290` dropea **candidatos de BUY**. Buscar
`screen|E1b|fundamental` en `harness_config.py`, `portfolio_sim.py` y
`scaleout_replay.py` daba **vacío**. Antes lo declaraban a mano tres pre-registros y
los tres envejecieron mal —uno con una razón que caducó justo el 2026-09-07, dos
describiéndolo como problema de *sourcing*, que es el riesgo equivocado— y **los dos
pre-registros del mismo día del flip delegan en el banner**, que no lo decía. Es el
modo de falla que advierte `harness_config.py`: *«lo que acá no se diga, no lo dice
nadie»*.

**132 — STOPSW-ESPEJO.** `atr_stops_enabled` es el master switch que `engine.py:491`
chequea **antes que todo lo demás**, y era el único de la política de salida sin
espejo. Con él apagado, las tres constantes de la T92 no significan nada: la cuenta
no tendría barreras ATR **en absoluto**, y `deviations()` seguiría declarando *«stop
duro APAGADO / trailing 2.0×ATR»* — el desvío **al revés**, que es el modo de falla
exacto que la T92 existe para prevenir.

Las dos son **declaración, no modelado**: ningún runner se toca y el default `False`
hace que un runner que no diga nada declare exactamente lo que corre — mismo criterio
que `live_gates` y que las tareas 94/95/96.
"""

from __future__ import annotations

import pytest

import analysis.harness_config as hc
from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    config_banner,
    deviations_keyed,
)


def _cfg(**kw) -> HarnessConfig:
    return HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, **kw)


def _screen(cfg) -> list[str]:
    return [d.texto for d in deviations_keyed(cfg) if d.clave == "universe_screen"]


# Por CLAVE (tarea 152). La primera version de esto filtraba `"barreras ATR" in d` y
# me trajo TRES lineas: ese texto tambien aparece en el desvio de la **T32** (el
# *precio de evaluacion* de la barrera) y en el de la **T33** (el *fill*), que son
# otros ejes y siguen valiendo. El filtro estaba mal, pero la pregunta que abrio es
# buena y quedo como tarea 151.
_CLAVES_POLITICA_ATR = {"atr_master_off", "atr_hard_stop", "atr_trail"}


def _atr(cfg) -> list[str]:
    return [d.texto for d in deviations_keyed(cfg) if d.clave in _CLAVES_POLITICA_ATR]


# ── 131 · el screen de universo ──────────────────────────────────────────────


def test_el_screen_se_declara_SIN_que_ningun_runner_haga_nada():
    """El punto de la tarea: el default `False` hace que los 21 runners lo declaren
    solos, igual que la política de salida de la 92 y los tres gates de la 94/96."""
    devs = _screen(_cfg())
    assert len(devs) == 1
    assert "2026-09-07" in devs[0]
    assert "DINÁMICO" in devs[0]  # y no un desvío de tamaño de universo


def test_el_desvio_dice_que_el_de_TAMANO_de_universo_no_lo_cubre():
    """Es la confusión que la tarea pedía evitar: `n_tickers` compara **tamaños**
    (127 vs 128), y el screen es un drop por scan. Si el texto no lo dice, el
    próximo pre-registro va a asumir que ya está declarado."""
    (d,) = _screen(_cfg())
    assert "desvío de tamaño del universo no lo cubre" in d


def test_un_runner_que_declara_modelarlo_no_tiene_desvio():
    """Contraprueba: el desvío cuelga de que el runner NO lo modele."""
    assert _screen(_cfg(models_universe_screen=True)) == []


def test_apagar_la_perilla_viva_saca_el_desvio(monkeypatch):
    """Y de que la perilla esté **encendida en vivo**, no de una lista fija. Es la
    misma contraprueba que la 94/96 le hace a sus tres."""
    monkeypatch.setattr(hc, "LIVE_UNIVERSE_SCREEN_ENABLED", False)
    assert _screen(_cfg()) == []


def test_el_screen_llega_al_banner():
    """Un desvío que no llega al banner no lo lee nadie."""
    assert "screen de universo" in config_banner(_cfg())


def test_el_desvio_declara_que_la_brecha_MEDIDA_es_cero():
    """La 129 midió que hoy el screen no excluye a nadie de los 128. Eso va **en el
    texto**, con su fecha: un desvío que no dice cuánto vale se lee como si valiera
    cualquier cosa. Y va con la salvedad de que el cero depende de EDGAR, no del
    código — mañana puede no serlo sin que nadie toque nada."""
    (d,) = _screen(_cfg())
    assert "T129" in d and "no excluye a nadie" in d
    assert "depende de los datos de EDGAR" in d


# ── 132 · el master switch de las barreras ATR ───────────────────────────────


def test_hoy_el_switch_esta_ON_y_se_declaran_los_multiplos():
    """El estado de hoy: el switch está encendido, así que los espejos de la 92
    significan lo que dicen y el desvío es el de siempre."""
    assert hc.LIVE_ATR_STOPS_ENABLED is True
    devs = _atr(_cfg())
    assert any("stop duro" in d for d in devs)
    assert not any("NO tiene barreras ATR" in d for d in devs)


def test_con_el_switch_APAGADO_se_declara_la_AUSENCIA_y_no_un_multiplo(monkeypatch):
    """**El corazón de la 132.** Sin esto, apagar el master switch dejaría al banner
    diciendo *«stop duro APAGADO / trailing 2.0×ATR en la cuenta 2»* sobre una cuenta
    que no corre **ninguna** de las dos — el desvío declarado al revés."""
    monkeypatch.setattr(hc, "LIVE_ATR_STOPS_ENABLED", False)
    devs = _atr(_cfg())

    assert len(devs) == 1
    assert "NO tiene barreras ATR" in devs[0]
    assert "master switch" in devs[0]
    assert not any("vs APAGADO en la cuenta" in d for d in devs)


def test_con_el_switch_apagado_el_desvio_NO_depende_de_que_el_harness_coincida(monkeypatch):
    """Incluso un runner que espeje la política viva de la T92 está declarando algo
    que en vivo no existe: sin barreras ATR no hay múltiplo que coincida."""
    monkeypatch.setattr(hc, "LIVE_ATR_STOPS_ENABLED", False)
    devs = _atr(_cfg(atr_stop_mult=hc.NO_STOP_MULT, atr_trail_mult=hc.LIVE_TRAIL_MULT))
    assert len(devs) == 1 and "NO tiene barreras ATR" in devs[0]


def test_el_switch_apagado_llega_al_banner(monkeypatch):
    monkeypatch.setattr(hc, "LIVE_ATR_STOPS_ENABLED", False)
    assert "NO tiene barreras ATR" in config_banner(_cfg())


@pytest.mark.parametrize("espejo", ["LIVE_ATR_STOPS_ENABLED", "LIVE_UNIVERSE_SCREEN_ENABLED"])
def test_los_dos_espejos_nuevos_existen_y_son_bool(espejo):
    """Contraprueba de que no pasen por estar ausentes: el guard de la 130 los
    compara contra el settings vivo, y compararía un `None` sin quejarse."""
    assert isinstance(getattr(hc, espejo), bool)
