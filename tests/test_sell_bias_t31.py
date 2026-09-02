"""SELL-REMEASURE (tarea 31) — los helpers del veredicto sobre el `analyze SELL`.

El resultado cuelga de `_stats`: media, IC95% y **efecto detectable al 80%**. Esa
última es la que da vuelta la lectura de la tarea — y de las **dos** mediciones
previas que se venían citando como si se contradijeran:

* la auditoría 2026-06-09 afirmaba **+3.92%** con **n=13**, cuando su propio
  detectable era **7.42%**;
* el análisis 2026-08-12 afirmaba **−1.30%** con **n=15**, cuando el suyo era
  **6.91%**.

Las dos estaban **por debajo de su propio umbral de detección**. No se
contradicen: ninguna de las dos midió nada.
"""

from __future__ import annotations

import math

import pytest

from scripts.measure_sell_bias_t31 import _stats, forward

# ── La media y su intervalo ──────────────────────────────────────────────────


def test_media_e_intervalo_sobre_una_muestra_conocida():
    s = _stats([0.10, 0.20, 0.30])
    assert s["media"] == pytest.approx(0.20)
    assert s["sd"] == pytest.approx(0.10)  # muestral (n-1)
    assert s["ic95"][0] < 0.20 < s["ic95"][1]


def test_el_intervalo_se_angosta_con_mas_muestra():
    corta = _stats([0.05, -0.05] * 5)
    larga = _stats([0.05, -0.05] * 50)
    ancho = lambda s: s["ic95"][1] - s["ic95"][0]
    assert ancho(larga) < ancho(corta)


def test_una_muestra_de_uno_no_promete_nada():
    s = _stats([0.05])
    assert s["n"] == 1 and s["media"] is None and s["detectable_80"] is None


# ── El hit rate: cómo lo reportó el original ─────────────────────────────────


def test_el_hit_rate_cuenta_las_ventas_despues_de_las_que_SUBIO():
    """Positivo = el precio siguió subiendo = la venta fue prematura. La auditoría
    2026-06-09 lo reportó como **57%**; hoy, con n=59, da **42%**."""
    s = _stats([0.10, 0.05, -0.03, -0.08])
    assert s["hit_rate"] == pytest.approx(0.5)
    assert _stats([-0.01, -0.02, -0.03])["hit_rate"] == 0.0


def test_un_forward_exactamente_cero_no_cuenta_como_subida():
    assert _stats([0.0, 0.0, 0.10, 0.10])["hit_rate"] == pytest.approx(0.5)


# ── El poder: la cuenta que faltaba en las DOS mediciones previas ────────────


def test_el_detectable_es_la_formula_de_la_media():
    """`2.80 · SD / √n`, con 2.80 = z(0.975) + z(0.80)."""
    xs = [0.05, -0.05, 0.10, -0.10, 0.0]
    s = _stats(xs)
    n = len(xs)
    media = sum(xs) / n
    sd = math.sqrt(sum((x - media) ** 2 for x in xs) / (n - 1))
    assert s["detectable_80"] == pytest.approx(2.80 * sd / math.sqrt(n))


def test_las_dos_mediciones_previas_estaban_bajo_su_propio_umbral():
    """**El hallazgo de la tarea, como test.** Con la SD medida hoy (≈9.56%), las
    muestras de las dos afirmaciones que se venían citando no podían detectar los
    efectos que reportaron."""
    sd = 0.0956
    det = lambda n: 2.80 * sd / math.sqrt(n)

    assert det(13) == pytest.approx(0.0742, abs=0.0005)
    assert abs(0.0392) < det(13)  # la auditoría 2026-06-09: +3.92% con n=13

    assert det(15) == pytest.approx(0.0691, abs=0.0005)
    assert abs(-0.0130) < det(15)  # el análisis 2026-08-12: −1.30% con n=15

    # y hoy, con n=59, el umbral baja — pero el efecto medido sigue adentro
    assert det(59) == pytest.approx(0.0348, abs=0.0005)


def test_mas_muestra_baja_el_umbral_de_deteccion():
    xs = [0.05, -0.05, 0.10, -0.10]
    assert _stats(xs * 10)["detectable_80"] < _stats(xs)["detectable_80"]


# ── El forward ───────────────────────────────────────────────────────────────


def test_sin_barras_devuelve_None_en_vez_de_inventar():
    assert forward("NO_EXISTE_ESTE_TICKER", "2026-01-05", 100.0, 5) is None


def test_un_precio_no_positivo_no_produce_un_retorno():
    assert forward("AAPL", "2026-01-05", 0.0, 5) is None
    assert forward("AAPL", "2026-01-05", -10.0, 5) is None
