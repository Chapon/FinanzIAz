"""Tarea 340 — por qué re-entrena XGB: el ticker en el WARNING y el motivo en el resumen por scan.

La 25 midió *«0 en los scans siguientes»*; en octubre el log mostraba ~100 re-entrenamientos por
hora de mercado y el WARNING de modelo inestable no decía el ticker. El cache es una sola clave
hasheada, así que un fallo no decía qué se había movido. Ahora el resumen del scan cuenta, por
motivo, las piezas de la clave que cambiaron.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("xgboost")
pytest.importorskip("sklearn.calibration")

from analysis import ml_signals
from analysis.ml_signals import (
    _motivo_reentreno,
    clear_ml_cache,
    drain_training_summary,
    train_xgboost_signal,
)


def _frame(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    wiggle = np.abs(rng.normal(0, 0.002, n))
    idx = pd.date_range(end=pd.Timestamp("2026-08-11"), periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": np.r_[close[0], close[:-1]],
            "High": close * (1 + wiggle),
            "Low": close * (1 - wiggle),
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
        },
        index=idx,
    )


def _revisado(df: pd.DataFrame) -> pd.DataFrame:
    """Un cierre viejo corregido (un ajuste retroactivo): cambian los cierres, no las filas."""
    out = df.copy()
    out.iloc[10, out.columns.get_loc("Close")] *= 1.01
    return out


@pytest.fixture(autouse=True)
def _limpio():
    clear_ml_cache()
    drain_training_summary()
    yield
    clear_ml_cache()
    drain_training_summary()


P = {"cierres": "a", "columnas": "x|y", "filas": "300", "ultima_fila": "2026-08-04"}


def test_el_motivo_nombra_la_pieza_que_cambio():
    assert _motivo_reentreno("AAA", P) == "nuevo"
    assert _motivo_reentreno("AAA", dict(P)) == "desalojado", "nada cambió: lo sacó el LRU"
    assert _motivo_reentreno("AAA", {**P, "cierres": "b"}) == "cierres"
    assert _motivo_reentreno("AAA", {**P, "cierres": "b", "filas": "301"}) == "filas"
    assert _motivo_reentreno("AAA", {**P, "columnas": "x"}) == "cierres+columnas+filas"
    assert _motivo_reentreno("BBB", P) == "nuevo", "cada ticker lleva su propia historia"
    assert _motivo_reentreno(None, P) == "sin_ticker"


def test_el_resumen_del_scan_cuenta_los_motivos_y_un_acierto_no_suma():
    df = _frame()
    assert train_xgboost_signal(df, "AAA") is not None
    assert train_xgboost_signal(df, "AAA") is not None  # acierto de cache: no entrena
    train_xgboost_signal(_revisado(df), "AAA")
    resumen = drain_training_summary()
    assert resumen.startswith("XGB entrenados=2 ")
    assert resumen.endswith("motivos: cierres=1 nuevo=1") or resumen.endswith("motivos: nuevo=1 cierres=1")
    assert drain_training_summary() is None, "el drain resetea también los motivos"


def test_el_warning_de_modelo_inestable_dice_el_ticker(monkeypatch, caplog):
    monkeypatch.setattr(ml_signals, "WALKFORWARD_STD_WARN", -1.0)  # todo modelo cuenta como inestable
    with caplog.at_level(logging.WARNING, logger=ml_signals.log.name):
        train_xgboost_signal(_frame(), "LRCX")
    avisos = [r.getMessage() for r in caplog.records if "unstable model" in r.getMessage()]
    assert avisos and avisos[0].startswith("XGBoost LRCX: unstable model")


def test_el_scan_le_pasa_el_ticker(monkeypatch):
    """``technical.analyze`` es el camino del scan: sin el ticker, todo sería ``sin_ticker``."""
    from analysis import technical

    vistos = []
    # ``analyze`` lo importa adentro de la función: se parchea en ``ml_signals``.
    monkeypatch.setattr(ml_signals, "train_xgboost_signal", lambda df, ticker=None: vistos.append(ticker))
    monkeypatch.setattr(technical, "_toggle", lambda key, default=True: key == "xgb_signal_enabled")
    technical.analyze("MSFT", _frame(), enable_xgboost=True)
    assert vistos == ["MSFT"]
