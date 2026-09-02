"""BUYSCORE-REVERIFY (tarea 73) — los helpers estadísticos que sostienen el veredicto.

El resultado de la tarea cuelga de tres cuentas: la correlación, su IC95% por
Fisher y el **efecto detectable al 80%**. Esa tercera es la que el original de
2026-06-17 no reportó, y es la que cambia la lectura: con **n=21** sólo se detecta
|r| ≥ **0.58**, o sea que aquella muestra **no podía distinguir "no predice" de "no
se midió"**.

Se testean acá porque son **puras** — sin DB, sin cache, sin red — y porque un
error en `detectable_r` daría vuelta el veredicto sin que nada más lo note.
"""

from __future__ import annotations

import math

import pytest

from scripts.measure_buyscore_fwd5_t73 import _ic95, _pearson, detectable_r

# ── La correlación ───────────────────────────────────────────────────────────


def test_correlacion_perfecta_y_perfecta_inversa():
    assert _pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert _pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)


def test_una_relacion_en_V_da_correlacion_CERO():
    """Y esto es una advertencia sobre la métrica, no sólo un caso borde: la V es
    **perfectamente determinística** —`y` queda fijado por `x`— y su correlación de
    Pearson es **exactamente 0**. Pearson mide lo **lineal**. O sea que un `r ≈ 0`
    no dice *"el score no tiene información"*: dice *"no tiene información lineal"*.
    Va escrito acá porque el veredicto de la tarea 73 se apoya en un `r`."""
    assert _pearson([1, 2, 3, 4], [1, 4, 4, 1]) == pytest.approx(0.0, abs=1e-12)


def test_un_predictor_constante_no_tiene_correlacion_definida():
    """Es el caso del fallback: si todos los `signal_score` fueran 1.0, no hay nada
    que correlacionar y devolver 0.0 se leería como *"no predice"* — que es una
    afirmación, no una ausencia de datos."""
    assert _pearson([1.0, 1.0, 1.0, 1.0], [3, 1, 4, 1]) is None


def test_muestra_demasiado_chica_devuelve_None():
    assert _pearson([1, 2], [3, 4]) is None


# ── El intervalo ─────────────────────────────────────────────────────────────


def test_el_ic_contiene_al_estimador():
    lo, hi = _ic95(0.30, 50)
    assert lo < 0.30 < hi


def test_el_ic_se_angosta_con_mas_muestra():
    a_lo, a_hi = _ic95(0.20, 30)
    b_lo, b_hi = _ic95(0.20, 300)
    assert (b_hi - b_lo) < (a_hi - a_lo)


def test_con_r_cero_el_ic_es_simetrico():
    lo, hi = _ic95(0.0, 85)
    assert lo == pytest.approx(-hi, abs=1e-12)


# ── El poder: la cuenta que cambia la lectura ────────────────────────────────


def test_el_detectable_del_original_es_enorme():
    """**El hallazgo de la tarea.** Con la muestra del original (n=21) sólo se
    detecta |r| ≥ 0.58 — una correlación que no existe en finanzas a 5 días. Ese
    número es el que convierte *"no predice"* en *"no se midió con poder"*."""
    assert detectable_r(21) == pytest.approx(0.578, abs=0.005)


def test_el_detectable_de_hoy_sigue_sin_descartar_lo_que_importa():
    """Con n=85 el detectable baja a ~0.30 — mejor, pero **no alcanza**: una
    correlación real de 0.15 sería económicamente relevante y esta muestra **no la
    puede descartar**. Por eso el veredicto no es *"el score no predice"*."""
    d = detectable_r(85)
    assert d == pytest.approx(0.300, abs=0.005)
    assert d > 0.15  # lo que NO se puede descartar


def test_el_detectable_baja_con_la_muestra_y_tiende_a_cero():
    assert detectable_r(30) > detectable_r(100) > detectable_r(1000)
    assert detectable_r(100_000) < 0.01


def test_con_muestra_degenerada_no_promete_poder():
    assert detectable_r(3) == 1.0
    assert detectable_r(0) == 1.0


def test_la_formula_es_la_de_fisher():
    """Pin de la fórmula: `tanh((z_alfa + z_beta)/sqrt(n-3))` con 1.96 + 0.84."""
    n = 85
    assert detectable_r(n) == pytest.approx(math.tanh(2.80 / math.sqrt(n - 3)), abs=1e-12)
