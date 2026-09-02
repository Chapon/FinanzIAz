"""Tarea 88 — el t12 dice "tickers", no "cobertura".

El hallazgo original (auditoría `muestra`, B-3) era que
`run_insider_cluster_replay_t12.py` medía cobertura del store PIT **por ticker**
mientras el loader deja a los tickers sin artefacto en **ATR-only en silencio** —
el enunciado literal de la tarea 75, en el hermano que la 75 no tocó.

**La premisa se movió al cerrar la 86, y por eso el arreglo es otro.** La 86
cableó `announce_signal_store` a los 21 runners: un artefacto que existe pero no
cubre todas las fechas **aborta la corrida antes de este banner**. Así que
*"ese porcentaje es la única visibilidad"* dejó de ser cierto.

Lo que queda es el **eje del número y su etiqueta**, y son dos cosas distintas:

* el **eje por ticker es el correcto** para lo único que este número puede ver —
  un ticker **sin** artefacto, que acá no se excluye sino que degrada a ATR-only;
* la **etiqueta "cobertura" no lo era**: invitaba a leerlo como cobertura de las
  decisiones del brazo, que es el defecto que cerró la 75.

Y el patrón de pares del t21 **no se porta**: allá la población son las entradas
BUY porque `b2()` se llama sobre candidatos; acá la señal se consulta **durante la
tenencia**, que no se conoce antes de simular.
"""

from __future__ import annotations

from pathlib import Path

_RUNNER = Path(__file__).resolve().parent.parent / "scripts" / "run_insider_cluster_replay_t12.py"


def _fuente() -> str:
    return _RUNNER.read_text(encoding="utf-8")


def _codigo() -> list[str]:
    """Sólo líneas de código: un comentario puede citar la etiqueta vieja, y debe."""
    return [ln for ln in _fuente().splitlines() if not ln.lstrip().startswith("#")]


def test_el_banner_no_llama_cobertura_a_una_fraccion_por_ticker():
    """El defecto era la etiqueta. Si vuelve `% cobertura` sobre `n_sig/len(bars_by)`,
    vuelve a invitar a leer un conteo de tickers como cobertura de decisiones."""
    codigo = "\n".join(_codigo())
    assert "% cobertura" not in codigo, "el banner volvió a llamar «cobertura» a un conteo por ticker"


def test_el_banner_dice_el_denominador_y_que_pasa_con_el_resto():
    """Un número sin denominador no se puede interpretar, y el resto no es cero:
    los tickers sin artefacto **corren igual**, en ATR-only."""
    codigo = "\n".join(_codigo())
    assert "de {len(bars_by)} tickers CON artefacto" in codigo
    assert "ATR-only" in codigo


def test_el_chequeo_por_FECHAS_sigue_estando():
    """La otra mitad del cuadro. Si alguien saca `announce_signal_store` de acá, el
    banner por ticker vuelve a ser la única visibilidad — que es el estado que la
    auditoría reportó."""
    codigo = "\n".join(_codigo())
    assert "announce_signal_store(" in codigo
    assert "SignalStoreGapError" in codigo


def test_queda_escrito_por_que_no_se_porta_el_patron_del_t21():
    """Sin esto, el próximo que lea el hallazgo B-3 va a portar el patrón de pares
    y va a medir sobre una población que no es la que el brazo consulta."""
    fuente = _fuente()
    assert "durante la tenencia" in fuente
    assert "no transfiere" in fuente or "no se porta" in fuente
