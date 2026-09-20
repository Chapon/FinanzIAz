"""Tarea 213 — los memos por ticker de ``data.yahoo_finance`` no cruzan de un test a otro.

**El defecto, medido.** Los cuatro memos (``_out_of_band_streak``, ``_split_factor_cache``,
``_second_opinion_cache``, ``_opinion_log``) son ``dict`` module-level y ninguno se borraba
solo. `test_price_sanity.py` rechaza el precio de KLAC en tres tests distintos, así que el
tercero —``test_get_current_price_rejects_out_of_band``— arrancaba con la racha en **3**,
que es exactamente ``_ESCALATE_AFTER``, y entonces ``unreliable_reference`` **salía a
buscar splits a Yahoo**. Corrido solo el test no tocaba la red; corriendo el archivo
entero, sí: su contacto con internet dependía del **orden de ejecución**.

**Por qué hace falta este archivo y no alcanzaba con el fixture.** Al mutar el fixture
—sacarle el ``clear()``— la suite seguía **verde**: el defecto volvía (la bitácora del
cortafuegos lo marcaba) y ninguna aserción lo veía, porque el camino falla abierto. O sea
que el arreglo no tenía cobertura y el próximo que tocara el conftest lo podía deshacer
sin enterarse. Estos tests son lo que pone eso en rojo.

**Van en pares y en este orden**, igual que los de la bitácora en la 209: hace falta un
test que **ensucie** para que el siguiente pueda afirmar que arrancó limpio. Pytest corre
los tests de un archivo en orden de definición; si alguien los separa, el segundo deja de
probar lo suyo, y por eso el nombre los numera.
"""

from __future__ import annotations

import pytest

import data.yahoo_finance as yfm
from tests.conftest import _MEMOS_POR_TICKER

# El fixture limpia por **nombre**, así que la lista es parte del contrato: si alguien
# agrega un memo por ticker a `yahoo_finance` y no lo suma, queda fuera del aislamiento
# sin que nada avise. Esto no lo puede detectar solo (no hay forma de saber qué dict
# nuevo es "por ticker"), pero al menos fija que los cuatro declarados existen de verdad.
_ESPERADOS = (
    "_out_of_band_streak",
    "_split_factor_cache",
    "_second_opinion_cache",
    "_opinion_log",
)


def test_la_lista_del_fixture_nombra_memos_que_existen():
    """Un `clear()` sobre un nombre mal escrito es un no-op silencioso.

    El fixture usa ``getattr(mod, nombre, {})``, que **no falla** si el atributo no
    existe: limpia un dict descartable y sigue. O sea que un typo, o un memo renombrado
    en `yahoo_finance`, deja de aislarse **sin ningún síntoma**. Esto lo fija.
    """
    assert set(_MEMOS_POR_TICKER) == set(_ESPERADOS)
    for nombre in _ESPERADOS:
        assert isinstance(getattr(yfm, nombre), dict), (
            f"{nombre} dejó de ser un dict module-level: el fixture de aislamiento "
            "(tests/conftest.py) hay que actualizarlo junto con el cambio."
        )


def test_memos_1_este_test_los_ensucia():
    """Primera mitad del par: deja los cuatro memos con algo adentro."""
    yfm._out_of_band_streak["ZZZZ"] = (3, "2026-01-01 00:00:00", "")
    yfm._split_factor_cache["ZZZZ"] = (0.0, 10.0)
    yfm._second_opinion_cache["ZZZZ"] = (0.0, 123.0)
    yfm._opinion_log["ZZZZ"] = {"veredicto": "sucio"}

    for nombre in _ESPERADOS:
        assert getattr(yfm, nombre), f"{nombre} tenía que quedar sucio"


def test_memos_2_arrancan_vacios_pese_a_lo_que_dejo_el_anterior():
    """Segunda mitad: el autouse los vacía al empezar **cada** test.

    Ésta es la que se pone roja si alguien le saca el ``clear()`` al fixture — el caso
    que, sin este archivo, la suite entera dejaba pasar en verde.
    """
    for nombre in _ESPERADOS:
        assert getattr(yfm, nombre) == {}, (
            f"{nombre} llegó con estado del test anterior. Eso hace que el resultado de "
            "un test dependa del ORDEN de ejecución — y en el caso de "
            "`_out_of_band_streak` decide además si se sale o no a la red (tarea 213)."
        )


def test_la_racha_heredada_es_la_que_habilitaba_el_fetch_de_splits():
    """Por qué el aislamiento no es higiene: el umbral que destraba la red es ese `n`.

    No se ejercita el fetch (el cortafuegos de la 209 lo cortaría igual); se fija la
    **condición**, que es lo que la herencia de estado empujaba sola hasta cruzarla.
    """
    assert yfm._ESCALATE_AFTER == 3
    assert yfm._out_of_band_streak == {}, "arranca limpio, o sea n=0 y no n=_ESCALATE_AFTER"

    n = 0
    for _ in range(yfm._ESCALATE_AFTER):
        n, _since = yfm._note_out_of_band("ZZZZ")
    assert n == yfm._ESCALATE_AFTER, (
        "hacen falta _ESCALATE_AFTER rechazos DENTRO de un test para habilitar el "
        "lookup de splits; heredarlos de tests anteriores era el defecto"
    )


@pytest.mark.parametrize("nombre", _ESPERADOS)
def test_cada_memo_se_aisla_por_separado(nombre):
    """Que el conjunto esté limpio no dice que cada uno lo esté: se afirma uno por uno.

    Lo pide la mutación *«se aísla la racha pero NO el cache de splits»*, que con una
    aserción sobre el conjunto entero podría pasar desapercibida según el orden.
    """
    assert getattr(yfm, nombre) == {}
    getattr(yfm, nombre)["ZZZZ"] = (1, "x", "")
