"""
Tests de higiene de log (tarea 25 / LOG-HYGIENE).

El problema que cierran
-----------------------
Dos fuentes de ruido enterraban los errores reales del log de runtime:

(a) **WARNING "unstable model" en el 41% de los tickers.** El umbral
    ``WALKFORWARD_STD_WARN`` estaba en 0.08, que es donde cae la **mediana** del
    std entre folds — medido sobre los 134 frames 2y/1d del cache vivo: mediana
    0.0760, decil superior 0.1105, y 55/134 tickers por encima de 0.08. Un
    umbral en la mediana marca a la mitad de la población por construcción, así
    que no discriminaba nada. Además la línea INFO de ``val_acc`` salía una vez
    por ticker entrenado.

(b) **ERROR "share count failed" de yfinance.** Sale del logger de la librería
    (``yfinance/base.py``), va pegado a los eventos de throttle y yfinance ya lo
    maneja (devuelve ``None``) — pero a nivel ERROR compite con fallos reales.

Qué verifican
-------------
1. El umbral quedó en la cola de la distribución medida, no en la mediana.
2. La línea per-ticker es DEBUG; el agregado sale por scan (drain).
3. El acumulador cuenta, resetea y devuelve ``None`` cuando no hubo entrenos.
4. ``ScanResult.summary()`` incorpora el resumen (y lo omite si no hubo).
5. El filtro degrada el share-count a DEBUG **sin descartarlo**, y no toca los
   demás mensajes de yfinance.
"""

from __future__ import annotations

import logging

import pytest

from analysis.ml_signals import (
    WALKFORWARD_STD_WARN,
    _note_training,
    drain_training_summary,
)
from data import yf_noise

# Distribución medida el 2026-08-11 sobre los 134 frames 2y/1d del cache vivo
# (scratchpad diag_val_std). Sirve de ancla: si alguien vuelve a bajar el umbral
# a la mediana, el test lo frena y explica por qué.
MEASURED_MEDIAN_STD = 0.0760
MEASURED_P90_STD = 0.1105


@pytest.fixture(autouse=True)
def _drain_between_tests():
    """El acumulador es module-level: vaciarlo antes y después de cada test."""
    drain_training_summary()
    yield
    drain_training_summary()


# ── (a) Umbral de inestabilidad ───────────────────────────────────────────────


def test_threshold_sits_in_the_tail_not_at_the_median():
    """El umbral tiene que marcar outliers, no a media población.

    Con 0.08 disparaba en 55/134 = 41% de los tickers de cada scan. El valor
    nuevo tiene que estar por encima del decil superior medido.
    """
    assert WALKFORWARD_STD_WARN > MEASURED_MEDIAN_STD, (
        "un umbral en la mediana marca a la mitad de los tickers por construcción"
    )
    assert WALKFORWARD_STD_WARN >= MEASURED_P90_STD, (
        f"el umbral debería caer en la cola (p90 medido = {MEASURED_P90_STD})"
    )


# ── (a) Telemetría agregada ───────────────────────────────────────────────────


def test_drain_returns_none_when_nothing_trained():
    """El caso normal a partir del 2º scan del día, con el cache de la tarea 24."""
    assert drain_training_summary() is None


def test_drain_summarises_and_resets():
    """Un resumen con el conteo, el val_acc medio y los inestables; después limpia."""
    _note_training(0.50, 0.02)
    _note_training(0.60, 0.02)
    _note_training(0.55, WALKFORWARD_STD_WARN + 0.05)  # este cuenta como inestable

    summary = drain_training_summary()

    assert summary is not None
    assert "entrenados=3" in summary
    assert "55%" in summary  # media de 0.50, 0.60, 0.55
    assert "inestables=1" in summary

    assert drain_training_summary() is None, "el drain tiene que resetear el acumulador"


def test_unstable_count_uses_the_live_threshold():
    """Un std por debajo del umbral no cuenta como inestable."""
    _note_training(0.50, WALKFORWARD_STD_WARN - 0.001)
    _note_training(0.50, WALKFORWARD_STD_WARN + 0.001)

    summary = drain_training_summary()

    assert summary is not None
    assert "entrenados=2" in summary
    assert "inestables=1" in summary


def test_scan_summary_includes_and_omits_the_ml_line():
    """El resumen entra en la línea única del scan (estilo telemetría OPS1)."""
    from datetime import datetime

    from paper_trading.engine import ScanResult

    kwargs = dict(
        account_id=1,
        scan_at=datetime(2026, 8, 11, 16, 19),
        mode="manual",
        strategy="analyze_single",
        prices={},
    )

    with_ml = ScanResult(**kwargs, ml_training="XGB entrenados=52 val_acc medio=51% inestables=2")
    without_ml = ScanResult(**kwargs)

    assert "XGB entrenados=52" in with_ml.summary()
    assert "XGB" not in without_ml.summary()


# ── (b) Ruido de yfinance ─────────────────────────────────────────────────────


def _record(msg: str, level: int = logging.ERROR) -> logging.LogRecord:
    return logging.LogRecord("yfinance", level, __file__, 1, msg, None, None)


def test_share_count_failure_is_degraded_not_dropped():
    """El evento correlaciona con el throttle: sirve para diagnosticar, pero no
    a nivel ERROR. Se degrada a DEBUG y **se conserva**."""
    filt = yf_noise.QuoteSummary404Filter()
    rec = _record("ELV: Yahoo web request for share count failed")

    kept = filt.filter(rec)

    assert kept is True, "degradar, no descartar"
    assert rec.levelno == logging.DEBUG
    assert rec.levelname == "DEBUG"


def test_other_yfinance_errors_keep_their_level():
    """El filtro existe para destapar errores reales, no para taparlos."""
    filt = yf_noise.QuoteSummary404Filter()
    rec = _record("AAPL: algo nuevo se rompió de verdad")

    assert filt.filter(rec) is True
    assert rec.levelno == logging.ERROR
    assert rec.levelname == "ERROR"


def test_known_404s_are_still_dropped():
    """Regresión de UNIV1: los dos 404 conocidos se siguen descartando."""
    yf_noise.reset_unknown_symbols()
    filt = yf_noise.QuoteSummary404Filter()

    assert filt.filter(_record("ANSS: Quote not found for symbol: ANSS")) is False
    assert filt.filter(_record("LOW: No fundamentals data found for symbol: LOW")) is False

    assert yf_noise.is_unknown_symbol("ANSS")
    assert not yf_noise.is_unknown_symbol("LOW"), "LOW cotiza: no puede quedar marcado como muerto"
    yf_noise.reset_unknown_symbols()
