"""Tarea 42 (VOLPEN) — la penalidad de volatilidad deja de ser un literal escondido.

El argumento de diseno para sacarla no depende de ninguna medicion: penalizar
volatilidad es una decision de **sizing**, y el sistema ya la toma **dos veces** por
otro lado (overlay de sigma de cartera + escalado por regimen, los dos ON). Meterla
ademas en la **seleccion** mezcla riesgo con retorno esperado en la misma cifra.

**Pero el numero que justificaba sacarla se cayo:** de +1,61 pp (T21) y +1,57 pp
(fill honesto, T33) a **+0,29 pp** re-medido el 2026-09-07 con `touch` + `live_gates`
— adentro del ruido de un harness cuya banda del azar abarca ~7,7 pp. Asi que se
shipea el **mecanismo** y **no** la politica (patron T53), y estos tests fijan las dos
mitades: que la perilla exista y que el default no mueva nada.
"""

from __future__ import annotations

import pytest

from analysis.harness_config import LIVE_VOL_PENALTY_COEF
from analysis.ml_signals import VOL_PENALTY_COEF_DEFAULT, _vol_penalty_coef
from config.settings_manager import DEFAULTS, SCHEMA, settings


def test_el_default_NO_cambia_el_comportamiento():
    """La mitad que importa: shipear la perilla no puede mover la seleccion viva."""
    assert DEFAULTS["paper_vol_penalty_coef"] == 0.08
    assert VOL_PENALTY_COEF_DEFAULT == 0.08
    assert _vol_penalty_coef() == 0.08


def test_el_flag_manda_sobre_el_literal(monkeypatch):
    """Si el flag no llegara al calculo, la perilla seria decorativa."""
    monkeypatch.setitem(settings._data, "paper_vol_penalty_coef", 0.0)
    assert _vol_penalty_coef() == 0.0
    monkeypatch.setitem(settings._data, "paper_vol_penalty_coef", 0.05)
    assert _vol_penalty_coef() == pytest.approx(0.05)


def test_un_valor_ABSURDO_cae_al_default_y_no_rompe_el_scan(monkeypatch):
    """Fail-safe: la seleccion corre en cada scan, asi que un valor fuera de rango no
    puede propagarse ni tirar. El SCHEMA ya valida en `set`, pero el store puede venir
    de un JSON editado a mano."""
    for malo in (-1.0, 5.0, float("nan")):
        monkeypatch.setitem(settings._data, "paper_vol_penalty_coef", malo)
        assert _vol_penalty_coef() == VOL_PENALTY_COEF_DEFAULT, malo


def test_la_penalidad_ENTRA_de_verdad_en_la_probabilidad(monkeypatch):
    """Contraprueba de punta a punta: con coef 0 el score tiene que ser MAYOR que con
    el coef vivo, sobre el mismo input. Sin esto, cablear el flag y no usarlo pasaria
    en verde."""
    from analysis.ml_signals import MarketContext, compute_signal_probability
    from analysis.technical import TechnicalSignal

    # Mezcla que NO satura: con una sola BUY fuerte `raw_prob` da 1.0 y el
    # `np.clip(..., 0.05, 0.95)` se come parte de la penalidad, escondiendo el
    # coeficiente. Con BUY + SELL el score queda en el medio y el efecto se ve entero.
    señales = [
        TechnicalSignal(indicator="rsi", signal="BUY", strength="strong", value=25.0, description="t"),
        TechnicalSignal(indicator="macd", signal="SELL", strength="weak", value=-0.1, description="t"),
    ]
    ctx = MarketContext(
        regime="trending",
        regime_confidence=0.9,
        volatility_level="high",
        annual_volatility=0.4,
        risk_score=1.0,
    )

    monkeypatch.setitem(settings._data, "paper_vol_penalty_coef", 0.0)
    sin_pen = compute_signal_probability(señales, ctx)
    monkeypatch.setitem(settings._data, "paper_vol_penalty_coef", 0.08)
    con_pen = compute_signal_probability(señales, ctx)

    assert sin_pen > con_pen, "la penalidad no esta entrando en la seleccion"
    assert sin_pen - con_pen == pytest.approx(0.08, abs=1e-9), (
        f"la penalidad tiene que valer exactamente coef x risk_score (1.0): {sin_pen} vs {con_pen}"
    )


def test_el_harness_de_la_T21_NO_duplica_el_coeficiente():
    """El defecto lateral que la 42 cierra: `run_ranking_t21` tenia
    `VOL_PENALTY_COEF = 0.08  # ml_signals.py:1147`, un literal duplicado con una
    referencia de linea que ya habia caducado dos veces (hoy es otra). El brazo B2
    reconstruye el score SIN la penalidad, asi que si los dos numeros se separan mide
    otra cosa que la que dice medir.
    """
    from pathlib import Path

    from scripts.run_ranking_t21 import VOL_PENALTY_COEF

    assert VOL_PENALTY_COEF == LIVE_VOL_PENALTY_COEF
    src = (Path(__file__).resolve().parent.parent / "scripts" / "run_ranking_t21.py").read_text(
        encoding="utf-8"
    )
    assert "VOL_PENALTY_COEF = 0.08" not in src, "volvio el literal duplicado"


def test_el_espejo_del_harness_sigue_al_valor_vivo():
    """Igual que `LIVE_REGIME_SCALE_FACTOR`: si alguien mueve el flag vivo y no
    actualiza el espejo, esto falla en vez de desincronizarse en silencio."""
    assert DEFAULTS["paper_vol_penalty_coef"] == LIVE_VOL_PENALTY_COEF
    assert SCHEMA["paper_vol_penalty_coef"].doc
