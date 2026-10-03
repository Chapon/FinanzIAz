"""Tarea 292 — la sesión se decide con el calendario de la bolsa, no con el reloj.

La auditoría del 2026-10-03 contó los fills fuera de sesión por hora y día de la semana, y
así un fill de **Labor Day** (JNJ, 2026-09-07 14:05 UTC) cae «en sesión». El instrumento de
la 292 usa las ruedas de SPY como calendario; estos casos son los que distinguen las dos
versiones.
"""

from __future__ import annotations

from datetime import date, datetime

from scripts.measure_lookahead_fuera_sesion_t292 import en_sesion, sesion_siguiente

# Ruedas reales alrededor de dos fines de semana y del Labor Day de 2026.
_RUEDAS = [
    date(2026, 6, 18),
    date(2026, 6, 19),
    date(2026, 6, 22),
    date(2026, 9, 4),
    date(2026, 9, 8),
    date(2026, 9, 9),
]


def test_un_FERIADO_en_horario_de_sesion_es_fuera_de_sesion():
    labor_day = datetime(2026, 9, 7, 14, 5)  # lunes, 10:05 ET
    assert labor_day.weekday() == 0, "por reloj sería un día hábil en horario"
    assert en_sesion(labor_day, set(_RUEDAS)) is False
    assert sesion_siguiente(labor_day, _RUEDAS) == date(2026, 9, 8)


def test_un_dia_habil_en_horario_es_en_sesion():
    assert en_sesion(datetime(2026, 9, 8, 15, 0), set(_RUEDAS)) is True


def test_despues_del_cierre_abre_la_rueda_siguiente():
    viernes_noche = datetime(2026, 6, 19, 21, 8)
    assert en_sesion(viernes_noche, set(_RUEDAS)) is False
    assert sesion_siguiente(viernes_noche, _RUEDAS) == date(2026, 6, 22)


def test_un_sabado_abre_el_lunes():
    assert sesion_siguiente(datetime(2026, 6, 20, 21, 8), _RUEDAS) == date(2026, 6, 22)


def test_de_madrugada_abre_ESE_MISMO_dia():
    """Las 03:00 UTC del martes son la noche del lunes en Nueva York: la apertura que sigue es la del martes."""
    madrugada = datetime(2026, 9, 8, 3, 0)
    assert en_sesion(madrugada, set(_RUEDAS)) is False
    assert sesion_siguiente(madrugada, _RUEDAS) == date(2026, 9, 8)
