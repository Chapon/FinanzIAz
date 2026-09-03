"""Tarea 85 — un mensaje idéntico repetido de una librería ruidosa no inunda el log.

**Medido sobre log limpio**, que es lo que la tarea pedía como primer paso y que
recién existe desde el arreglo de la 78 (la suite escribía 551 líneas por corrida
en el log de producción y contaminaba cualquier medición).

En la ventana posterior al reinicio de la app: de **100 ERROR**, **98** eran la
misma línea de `yfinance` —`$AVB: possibly delisted; no price data found
(period=5d)`— repetida **2 veces por scan durante 4h18m**. Un solo ticker era el
**99%** de los ERROR.

No es un defecto de producción: es una condición conocida, repetida. Pero entrena
a saltear los ERROR, y este proyecto **usa el log como evidencia para priorizar**.
"""

from __future__ import annotations

import logging

from config.logging_config import REPEAT_SUMMARY_EVERY, _RepeatFilter


def _rec(msg: str, *, nombre: str = "yfinance", nivel: int = logging.ERROR) -> logging.LogRecord:
    return logging.LogRecord(nombre, nivel, "f.py", 1, msg, None, None)


def test_la_primera_pasa_intacta():
    """El mensaje no se pierde: la primera vez se ve tal cual."""
    f = _RepeatFilter()
    r = _rec("$AVB: possibly delisted")
    assert f.filter(r) is True
    assert r.getMessage() == "$AVB: possibly delisted"


def test_las_repeticiones_intermedias_no_pasan():
    f = _RepeatFilter(cada=5)
    assert f.filter(_rec("igual")) is True
    assert [f.filter(_rec("igual")) for _ in range(3)] == [False, False, False]


def test_cada_N_sale_un_resumen_CON_el_conteo():
    """No se pierde información: el mensaje sigue y ahora dice cuántas veces pasó
    — el dato que antes había que sacar con `grep -c`."""
    f = _RepeatFilter(cada=5)
    for _ in range(4):
        f.filter(_rec("igual"))
    r = _rec("igual")
    assert f.filter(r) is True
    assert "repetido 5 veces" in r.getMessage()


def test_mensajes_distintos_no_se_tapan_entre_si():
    """Lo peligroso sería que una línea nueva quedara escondida detrás del conteo
    de otra."""
    f = _RepeatFilter(cada=3)
    assert f.filter(_rec("uno")) is True
    assert f.filter(_rec("dos")) is True
    assert f.filter(_rec("tres")) is True


def test_el_mismo_texto_en_otro_NIVEL_se_cuenta_aparte():
    """Un WARNING y un ERROR con el mismo texto no son el mismo evento."""
    f = _RepeatFilter(cada=3)
    assert f.filter(_rec("igual", nivel=logging.WARNING)) is True
    assert f.filter(_rec("igual", nivel=logging.ERROR)) is True


def test_el_mismo_texto_de_otra_LIBRERIA_se_cuenta_aparte():
    f = _RepeatFilter(cada=3)
    assert f.filter(_rec("igual", nombre="yfinance")) is True
    assert f.filter(_rec("igual", nombre="urllib3")) is True


def test_un_format_roto_no_puede_tapar_el_log():
    """Fail-open: si `getMessage()` revienta, la línea pasa. Un filtro de ruido no
    puede convertirse en un filtro de señal."""
    f = _RepeatFilter()
    r = logging.LogRecord("yfinance", logging.ERROR, "f.py", 1, "%d %d", (1,), None)
    assert f.filter(r) is True


def test_el_caso_real_medido():
    """98 repeticiones de la línea de AVB pasan de 98 a 4 en el log."""
    f = _RepeatFilter()  # cada = REPEAT_SUMMARY_EVERY
    msg = "$AVB: possibly delisted; no price data found  (period=5d)"
    pasaron = sum(1 for _ in range(98) if f.filter(_rec(msg)))
    assert pasaron == 1 + 98 // REPEAT_SUMMARY_EVERY == 4


def test_esta_cableado_a_las_librerias_ruidosas_y_NO_al_log_de_la_app():
    """Una línea **nuestra** repetida es una señal, no ruido: el filtro no va al
    logger raíz."""
    import config.logging_config as lc

    fuente = (lc.__file__ or "").replace(".pyc", ".py")
    with open(fuente, encoding="utf-8") as fh:
        txt = fh.read()
    assert "lg.addFilter(repetidos)" in txt
    assert "root.addFilter" not in txt
