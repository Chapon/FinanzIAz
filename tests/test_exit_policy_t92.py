"""Tarea 92 — la política de SALIDA viva se declara como desvío, igual que los slots.

El 2026-08-27 Chapa apagó el stop duro en vivo (`soff_t2.0`, el candidato que
eligió la tarea 37) y **nada del lado del harness se enteró**: `AtrParams()` sigue
teniendo `stop_mult=2.0` —stop duro encendido— y **16 runners lo usan pelado**.

El tamaño lo midió el propio proyecto (`docs/stop_value_t37_2026-08-27.md` §2):
el default del harness da **2,01%** de CAGR y lo vivo **9,17%**. **7,16 pp** —
más que el look-ahead del fill (5,01 pp), que se ganó la tarea 33 entera.

Y ya había contaminado una corrida: la T51 corrió el **2026-08-28**, un día
después del flip, con `atr_p=AtrParams()`.

**Por qué el arreglo no toca ningún runner.** `HarnessConfig` ya usaba el patrón
para `eval_mode`/`fill_mode`/`live_gates`: *"los defaults son los de
`replay_cycle`, así que un runner que no los pase declara lo que corre"*. Los
campos nuevos espejan `AtrParams`, así que los 16 declaran su desvío **solos**.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analysis.exit_replay import AtrParams
from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_TRAIL_MULT,
    LIVE_WATCHLIST_SIZE,
    NO_STOP_MULT,
    HarnessConfig,
    announce,
    deviations_keyed,
)

_REPO = Path(__file__).resolve().parent.parent


def _cfg(**kw) -> HarnessConfig:
    return HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, **kw)


# Por CLAVE y no por substring (tarea 152). Filtrar `"stop duro" in d` funcionaba
# hasta que apareciera otro desvío con esas palabras — que es exactamente lo que le
# pasó al helper de la 132, que filtraba por "barreras ATR" y se traía tres ejes.
_CLAVES_SALIDA = {"atr_master_off", "atr_hard_stop", "atr_trail"}


def _salida(cfg) -> list[str]:
    return [d.texto for d in deviations_keyed(cfg) if d.clave in _CLAVES_SALIDA]


# ── El desvío ────────────────────────────────────────────────────────────────


def test_el_default_del_harness_declara_el_desvio_SIN_que_el_runner_haga_nada():
    """**El punto de la tarea.** Los 16 runners que usan `AtrParams()` pelado no se
    tocaron: sus defaults espejan los del simulador, así que el desvío sale solo."""
    devs = _salida(_cfg())
    assert len(devs) == 1
    assert "ENCENDIDO a 2.0×ATR en el harness vs APAGADO" in devs[0]
    assert "7.16pp" in devs[0]  # el número, no una vaguedad


def test_un_runner_que_declara_la_politica_viva_no_tiene_desvio():
    """Si el harness corre lo mismo que la cuenta, no hay nada que declarar —
    mismo criterio que `fill_mode` bajo `touch`."""
    assert _salida(_cfg(atr_stop_mult=NO_STOP_MULT, atr_trail_mult=LIVE_TRAIL_MULT)) == []


def test_el_trailing_se_declara_por_separado():
    """Son dos ejes: se puede coincidir en el stop y diferir en el trailing."""
    devs = _salida(_cfg(atr_stop_mult=NO_STOP_MULT, atr_trail_mult=3.0))
    assert len(devs) == 1 and "trailing 3.0×ATR" in devs[0]


def test_el_trail_sin_declarar_cae_al_stop_igual_que_en_AtrParams():
    """`trail_mult=None` ⇒ manda `stop_mult`. Si esto se desincroniza de
    `AtrParams.effective_trail_mult`, el banner declara un trailing que el
    simulador no corre."""
    assert _cfg(atr_stop_mult=3.0).effective_trail_mult == AtrParams(stop_mult=3.0).effective_trail_mult


def test_los_defaults_de_HarnessConfig_ESPEJAN_a_AtrParams():
    """El invariante del que cuelga todo: si `AtrParams` cambia sus defaults y esto
    no, los 16 runners declararían una política distinta de la que corren."""
    a, c = AtrParams(), _cfg()
    assert c.atr_stop_mult == a.stop_mult
    assert c.atr_trail_mult == a.trail_mult
    assert c.effective_trail_mult == a.effective_trail_mult


def test_announce_pasa_la_politica_a_la_config(capsys):
    cfg = announce(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, atr_stop_mult=NO_STOP_MULT)
    capsys.readouterr()
    assert cfg.hard_stop_on is False


def test_el_banner_lo_dice():
    """Un desvío que no llega al banner no lo lee nadie."""
    from analysis.harness_config import config_banner

    assert "stop duro" in config_banner(_cfg())


# ── Las constantes vivas ─────────────────────────────────────────────────────


# `test_la_politica_viva_es_la_de_la_cuenta_2` vivía acá y **se reemplazó** por
# `tests/test_espejos_vivos_t130.py` (tarea 130). Pinneaba `LIVE_HARD_STOP_ENABLED`,
# `LIVE_TRAIL_MULT` y `LIVE_STOP_MULT` contra literales escritos en este archivo, o
# sea que comparaba el repo contra el repo: no podía enterarse de que Chapa moviera
# la perilla, que es exactamente lo que decía estar cuidando. El reemplazo lee
# `~/.finanzias/settings.json` y compara los 13 espejos de una.


def test_la_constante_del_t37_se_renombro_en_vez_de_re_apuntarse():
    """`run_stop_value_t37.py` definía `LIVE_STOP, LIVE_TRAIL = 2.0, 2.0` — **el
    nombre "LIVE" quedó falso el mismo día que esa tarea shipeó**.

    Pero el arreglo **no** es re-apuntarlo a la política de hoy: ese par es el
    **baseline de una comparación congelada**. Re-apuntarlo hace que
    ``BASELINE_ARM`` pase a ser ``soff_t2.0`` y el runner compare el candidato
    **contra sí mismo** — el veredicto publicado deja de reproducir. Lo intenté y
    rompió **8 tests** de esa tarea; la suite lo cazó.

    **El baseline de una comparación congelada es historia, no configuración.**
    Por eso se renombra, y la política viva de hoy vive en `harness_config`.
    """
    txt = (_REPO / "scripts" / "run_stop_value_t37.py").read_text(encoding="utf-8")
    codigo = "\n".join(ln for ln in txt.splitlines() if not ln.lstrip().startswith("#"))
    assert "LIVE_STOP" not in codigo and "LIVE_TRAIL" not in codigo
    assert "BASELINE_STOP, BASELINE_TRAIL = 2.0, 2.0" in codigo

    from scripts.run_stop_value_t37 import BASELINE_ARM

    assert BASELINE_ARM == "s2.0_t2.0", "el baseline publicado no se puede mover"


def test_el_t61_lee_las_dos_claves_que_cambiaron():
    """Era el ÚNICO runner que leía la config viva… y leía tres claves ignorando
    justo `atr_hard_stop_enabled` y `atr_trail_mult`. El camino *"leo lo que corre
    en vivo"* mintiendo en silencio es peor que no leerlo."""
    txt = (_REPO / "scripts" / "run_exit_replay_t61.py").read_text(encoding="utf-8")
    codigo = "\n".join(ln for ln in txt.splitlines() if not ln.lstrip().startswith("#"))
    assert 'settings.get("atr_hard_stop_enabled"' in codigo
    assert 'settings.get("atr_trail_mult"' in codigo


@pytest.mark.parametrize("hard_stop,esperado", [(True, 2.0), (False, NO_STOP_MULT)])
def test_el_t61_traduce_el_flag_al_multiplo(monkeypatch, hard_stop, esperado):
    """El harness no tiene flag: expresa "apagado" con un múltiplo que nunca
    dispara. La traducción tiene que ser explícita, no implícita."""
    from config.settings_manager import settings
    from scripts.run_exit_replay_t61 import _atr_params_from_settings

    monkeypatch.setattr(settings, "get", lambda k, d=None: hard_stop if k == "atr_hard_stop_enabled" else d)
    assert _atr_params_from_settings().stop_mult == esperado
