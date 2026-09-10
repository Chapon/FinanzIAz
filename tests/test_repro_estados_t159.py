"""Tarea 159 — un `INDETERMINADO` deja de imprimirse como `FALLA`.

``reproduction_check`` devuelve **tres** estados y la T48 les dio significados
**opuestos**: ``FALLA`` es *«misma muestra ⇒ cambió la cañería»* —una acusación— y
``INDETERMINADO`` es *«la ventana se movió ⇒ re-anclar»*, que el doc de la T68 llama
**«el diseño funcionando, no fallando»**.

**Visto en vivo el 2026-09-09.** Después de refrescar el cohorte a propósito,
`run_anom_profile_t45.py` imprimió ``repro_live  FALLA``. El estado real era
``INDETERMINADO`` —la ventana pasó de ``2016-08-08..2026-09-01`` a
``2016-09-12..2026-09-09``— y el número estaba a **0,06 pp** del ancla (9.23% vs 9.17%,
tolerancia 0.05 pp). O sea: el runner acusó a la cañería por un refresh que el
operador acababa de hacer.

**Y el alcance real es UNO, no siete — la primera medición estaba mal.** El barrido que
abrió la tarea buscó ``== REPRO_OK`` y encontró los siete runners, pero eso es el
booleano de **validez**, que es legítimo y tiene que existir. Lo que importa es qué se
**imprime**, y ahí seis de los siete ya mostraban el estado: el T39
(``sanity.get('repro_state')``), el T37 (en su §7.7), el T47 (une los estados), el T49
(``t45_state``/``t33_state``), el T54 (``base_state``) y el T51 —que hasta lo comenta:
*«confundirlos es el defecto que la 52 acaba de arreglar»*—. El T45 calculaba
``live_state``, lo guardaba en el dict y **lo tiraba al imprimir**.

Es [[validar-el-instrumento-antes-del-numero]] otra vez: el grep midió una cosa y el
enunciado afirmó otra.

**La validez NO cambia**, y es deliberado: un ``INDETERMINADO`` sigue sin ser ``OK``,
porque no se puede declarar reproducible lo que no se pudo verificar. Lo que cambia es
que el operador vea si tiene que **re-anclar** o **investigar la cañería** — dos
acciones distintas que el rótulo viejo confundía.
"""

from __future__ import annotations

import pytest

from scripts.run_anom_profile_t45 import etiqueta_sanity


def test_un_INDETERMINADO_se_imprime_como_INDETERMINADO():
    """**El defecto, en su forma exacta.** Antes esto salía `FALLA`."""
    assert etiqueta_sanity("repro_live", False, {"live_state": "INDETERMINADO"}) == "INDETERMINADO"


def test_un_FALLA_de_verdad_sigue_diciendo_FALLA():
    """La contraprueba que impide que el arreglo se coma la acusación real.

    Si la ventana **no** se movió y el número no da, eso **sí** es la cañería y tiene
    que verse como tal. Aflojar eso sería peor que el defecto original.
    """
    assert etiqueta_sanity("repro_live", False, {"live_state": "FALLA"}) == "FALLA"


def test_un_OK_se_imprime_como_su_estado():
    assert etiqueta_sanity("repro_live", True, {"live_state": "OK"}) == "OK"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(True, "OK"), (False, "FALLA"), (None, "—")],
)
def test_los_chequeos_que_NO_son_de_reproduccion_no_cambian(valor, esperado):
    """`accounting` y `oracle_takes_off` son booleanos de verdad: dos estados y punto.

    Sólo los de reproducción tienen tres. Meterle un tercer estado a un chequeo
    binario sería inventar una distinción que no existe.
    """
    assert etiqueta_sanity("accounting", valor, {"live_state": "INDETERMINADO"}) == esperado


def test_sin_estado_disponible_cae_al_booleano():
    """Fail-safe: si el dict de reproducción no trae el estado —una corrida vieja, un
    `--json` recortado— el rótulo sigue siendo el de antes en vez de romperse."""
    assert etiqueta_sanity("repro_live", False, {}) == "FALLA"
    assert etiqueta_sanity("repro_live", True, {"live_state": ""}) == "OK"


def test_la_VALIDEZ_de_la_corrida_no_la_decide_esta_funcion():
    """El invariante que separa el rótulo del gate.

    `etiqueta_sanity` sólo formatea. La validez la calcula `evaluate_sanity` con
    `live_ok = live_state == REPRO_OK`, y eso **no se tocó**: un `INDETERMINADO` sigue
    dejando la corrida sin declarar válida. Si algún día alguien quiere aflojar eso,
    que sea una decisión con su propio pre-registro, no un efecto lateral de un cambio
    de mensaje.
    """
    import inspect

    from scripts.run_anom_profile_t45 import evaluate_sanity

    fuente = inspect.getsource(evaluate_sanity)
    assert "live_ok" in fuente and "etiqueta_sanity" not in fuente
