"""
Tests for ``data.quality`` — OHLCV validation + cleaning.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.quality import check_ohlcv, clean_ohlcv


def _df(rows: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = pd.Series(np.linspace(100, 110, rows), index=idx)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1_000_000.0,
        },
        index=idx,
    )


def test_check_ohlcv_clean_frame_has_no_issues():
    rep = check_ohlcv(_df())
    assert rep.is_usable
    assert not rep.has_issues()
    assert rep.rows == 30


def test_check_ohlcv_detects_zero_prices():
    df = _df()
    df.loc[df.index[5], "Close"] = 0
    df.loc[df.index[10], "Close"] = -1
    rep = check_ohlcv(df)
    assert rep.has_issues()
    assert rep.zero_or_negative.get("Close") == 2


def test_check_ohlcv_detects_calendar_gaps():
    df = _df(rows=30)
    # Drop a 5-day chunk to create a business-day gap
    df = pd.concat([df.iloc[:10], df.iloc[16:]])
    rep = check_ohlcv(df)
    assert len(rep.calendar_gaps) >= 1


def test_check_ohlcv_rejects_all_nan_close():
    df = _df()
    df["Close"] = np.nan
    rep = check_ohlcv(df)
    assert not rep.is_usable


def test_clean_ohlcv_replaces_zeros_and_ffills():
    df = _df()
    df.loc[df.index[5], "Close"] = 0  # zero → NaN → ffilled
    cleaned, _rep = clean_ohlcv(df, fill_method="ffill", max_fill_gap=2)
    assert cleaned is not None
    # No more zeros after cleaning
    assert (cleaned["Close"] > 0).all()


def test_clean_ohlcv_drops_duplicate_index():
    df = _df()
    dup = df.iloc[[5]]
    df_with_dup = pd.concat([df, dup])
    cleaned, rep = clean_ohlcv(df_with_dup)
    assert rep.duplicate_index == 1
    # Cleaned has unique index
    assert not cleaned.index.duplicated().any()


def test_clean_ohlcv_returns_none_for_unusable_input():
    """Empty / None inputs round-trip through with usable=False, no exception."""
    cleaned, rep = clean_ohlcv(None)
    assert cleaned is None
    assert not rep.is_usable

    _cleaned2, rep2 = clean_ohlcv(pd.DataFrame())
    assert not rep2.is_usable


# ── Un frame de UNA barra no puede reventar la QA — Tarea 114 ────────────────


def _frame(n: int, close: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [close] * n,
            "High": [close] * n,
            "Low": [close] * n,
            "Close": [close] * n,
            "Volume": [1000] * n,
        },
        index=pd.date_range("2026-01-01", periods=n, freq="B"),
    )


def test_una_sola_barra_devuelve_reporte_y_no_revienta():
    """Tarea 114 — `df["Close"].squeeze()` devuelve un **escalar** con una fila, y
    `.dropna()` explotaba con AttributeError.

    Es alcanzable por la puerta de adelante: el docstring de `get_historical_data`
    lista `period="1d"` como valido, y `clean_ohlcv` se llama desde
    `_finalize_historical` **fuera de todo try**, asi que la excepcion se propagaba
    al caller en vez de fallar suave como el resto de la QA.
    """
    rep = check_ohlcv(_frame(1))  # antes: AttributeError
    assert rep.rows == 1
    assert rep.is_usable, "una barra con Close valido es poca, pero no es inusable"


def test_lo_dice_en_vez_de_reportar_CERO_saltos():
    """Un `suspicious_jumps = 0` sobre una sola barra se lee como *"revisado y
    limpio"* y en realidad es *"no habia nada que revisar"*. La diferencia importa
    porque este reporte es lo que decide si un frame entra."""
    rep = check_ohlcv(_frame(1))
    assert any("Single-bar" in n for n in rep.notes)
    assert rep.suspicious_jumps == 0


def test_con_DOS_barras_vuelve_a_evaluar_los_saltos():
    """Contraprueba: la rama nueva no puede tragarse el caso normal. Sin esto,
    saltear siempre la evaluacion pasaria en verde."""
    df = _frame(2)
    df.iloc[1, df.columns.get_loc("Close")] = 300.0  # +200%
    rep = check_ohlcv(df)
    assert rep.suspicious_jumps == 1
    assert not any("Single-bar" in n for n in rep.notes)


def test_close_duplicado_sigue_aplanandose():
    """`squeeze()` estaba ahi para aplanar un frame con la columna `Close` repetida.
    El reemplazo tiene que conservar eso, o el arreglo cambia un bug por otro."""
    df = _frame(3)
    df = pd.concat([df, df["Close"]], axis=1)
    assert list(df.columns).count("Close") == 2
    rep = check_ohlcv(df)
    assert rep.rows == 3 and rep.is_usable
