"""Tarea 478 — el contador de consultas del filtro de stops, y que el primer sorteo es el de la T170.

La medición (`scripts/medir_oraculo_t478.py`) compara el oráculo contra 21 sorteos del control, y
la primera fila tiene que ser **el** sorteo con el que la T170 y la 477 decidieron su sanity: si
no, la comparación contra lo publicado se lee contra otro número.
"""

from __future__ import annotations

import math

import scripts.medir_oraculo_t478 as m


def test_el_contador_cuenta_consultas_y_las_que_dejan_disparar():
    respuestas = iter([True, False, False, True])
    c = m.Contador(lambda bars, i, ticker="": next(respuestas))
    assert [c([], k, "AAA") for k in range(4)] == [True, False, False, True]
    assert (c.llamadas, c.conserva, c.tasa) == (4, 2, 0.5)


def test_sin_consultas_la_tasa_no_se_inventa():
    assert math.isnan(m.Contador(lambda bars, i, ticker="": True).tasa)


def test_el_contador_le_pasa_el_ticker_al_filtro():
    """El control aleatorio exige el ticker (tarea 164): sin él, el sorteo sería común a toda la
    cartera. El envoltorio no se lo puede comer."""
    visto = []
    c = m.Contador(lambda bars, i, ticker="": visto.append(ticker) or True)
    c([], 0, "MSFT")
    assert visto == ["MSFT"]


def test_el_primer_sorteo_es_el_de_la_T170_y_no_se_repite():
    s = m.semillas_del_control(20)
    assert s[0] == 20260813 == m.RANDOM_KEEP_SEED
    assert len(s) == 21 and len(set(s)) == 21
