"""Tarea 344 — la barra de hoy que Yahoo devuelve sin precios no se rellena con los de ayer.

El caso es el del 2026-10-08: la última fila con Open/High/Low/Close en NaN y el volumen
presente. El ``ffill`` de ``clean_ohlcv`` le copiaba los precios de la anterior, y el frame se
cacheaba con un «cierre de hoy» que era el de ayer (LRCX: 329,51 contra 320,59 real). Los casos
están elegidos para que la versión vieja y la nueva **difieran**: con la vieja la última fila
existe y repite el Close anterior; con la nueva no existe. Y un hueco **intermedio** sigue
rellenándose igual que antes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from data import parquet_cache
from data.quality import clean_ohlcv


def _df(rows: int = 6) -> pd.DataFrame:
    idx = pd.date_range("2026-10-01", periods=rows, freq="B")
    close = pd.Series(np.arange(100.0, 100.0 + rows), index=idx)
    return pd.DataFrame(
        {"Open": close - 0.5, "High": close + 1.0, "Low": close - 1.0, "Close": close, "Volume": 1_000.0},
        index=idx,
    )


def _sin_precios_al_final(df: pd.DataFrame, n: int = 1) -> pd.DataFrame:
    df = df.copy()
    df.loc[df.index[-n:], ["Open", "High", "Low", "Close"]] = np.nan
    df.loc[df.index[-1], "Volume"] = 8_960_892.0  # el volumen sí viene
    return df


def test_la_ultima_barra_sin_precios_se_descarta_y_NO_copia_la_de_ayer():
    crudo = _sin_precios_al_final(_df())
    limpio, rep = clean_ohlcv(crudo, fill_method="ffill", max_fill_gap=2)
    assert len(limpio) == len(crudo) - 1
    assert limpio.index[-1] == crudo.index[-2], "la última barra es la de ayer, con su fecha"
    assert limpio["Close"].iloc[-1] == crudo["Close"].iloc[-2]
    assert rep.trailing_dropped == 1
    assert "descartadas=1" in rep.summary()


def test_dos_barras_del_final_sin_precio_se_descartan_las_dos():
    """Con ``max_fill_gap=2`` la versión vieja rellenaba las dos."""
    crudo = _sin_precios_al_final(_df(), n=2)
    limpio, rep = clean_ohlcv(crudo, fill_method="ffill", max_fill_gap=2)
    assert limpio.index[-1] == crudo.index[-3]
    assert rep.trailing_dropped == 2


def test_un_hueco_INTERMEDIO_se_sigue_rellenando():
    crudo = _df()
    crudo.loc[crudo.index[3], ["Open", "High", "Low", "Close"]] = np.nan
    limpio, rep = clean_ohlcv(crudo, fill_method="ffill", max_fill_gap=2)
    assert len(limpio) == len(crudo)
    assert limpio["Close"].iloc[3] == crudo["Close"].iloc[2]
    assert rep.trailing_dropped == 0


def test_con_hueco_intermedio_Y_barra_vacia_al_final_solo_se_va_la_del_final():
    """El caso que separa «descartar el final» de «descartar toda fila sin Close»."""
    crudo = _sin_precios_al_final(_df())
    crudo.loc[crudo.index[2], ["Open", "High", "Low", "Close"]] = np.nan
    limpio, rep = clean_ohlcv(crudo, fill_method="ffill", max_fill_gap=2)
    assert list(limpio.index) == list(crudo.index[:-1])
    assert limpio["Close"].iloc[2] == crudo["Close"].iloc[1]
    assert rep.trailing_dropped == 1


def test_con_fill_none_no_se_toca():
    crudo = _sin_precios_al_final(_df())
    limpio, rep = clean_ohlcv(crudo, fill_method="none")
    assert len(limpio) == len(crudo) and np.isnan(limpio["Close"].iloc[-1])
    assert rep.trailing_dropped == 0


def test_el_camino_real_de_yahoo_no_cachea_la_barra_rellenada(monkeypatch):
    """``_finalize_historical`` es el punto único de ``get_historical_data`` y del batch."""
    from data import yahoo_finance as yf

    escritos = {}
    monkeypatch.setattr(yf, "last_bar_is_provisional", lambda *_a, **_k: False)
    monkeypatch.setattr(yf, "record_success", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "_write_historical_cache", lambda t, p, i, df: escritos.setdefault(t, df))
    crudo = _sin_precios_al_final(_df())
    out = yf._finalize_historical("LRCX", crudo, "2y", "1d")
    assert out.index[-1] == crudo.index[-2]
    assert escritos["LRCX"].index[-1] == crudo.index[-2]


# ── El script que limpia lo ya cacheado ──────────────────────────────────────


@pytest.fixture
def cache(tmp_path):
    parquet_cache.set_parquet_dir(tmp_path)
    yield tmp_path
    parquet_cache.set_parquet_dir(None)


def _rellenada(df: pd.DataFrame) -> pd.DataFrame:
    """Lo que hacía el ffill viejo: la última fila con el OHLC de la anterior y su volumen."""
    df = df.copy()
    for c in ("Open", "High", "Low", "Close"):
        df.loc[df.index[-1], c] = df[c].iloc[-2]
    df.loc[df.index[-1], "Volume"] = 8_960_892.0
    return df


def test_el_script_lista_sin_escribir_y_con_aplicar_saca_SOLO_la_ultima(cache):
    from datetime import datetime, timezone

    from scripts.limpiar_barra_rellenada import limpiar

    cuando = datetime(2026, 10, 9, 0, 24, tzinfo=timezone.utc)
    parquet_cache.write("LRCX", "2y", "1d", _rellenada(_df()), fetched_at=cuando)
    sano = _df()
    parquet_cache.write("AAPL", "2y", "1d", sano, fetched_at=cuando)
    # El patrón en una fila INTERMEDIA (un día plano de un ilíquido) no es este defecto.
    plano = _df()
    plano.iloc[3, :4] = plano.iloc[2, :4].to_numpy()
    plano.loc[plano.index[3], "Volume"] = 0.0
    parquet_cache.write("AMCR", "10y", "1d", plano, fetched_at=cuando)

    assert limpiar(cache, aplicar=False) == [("LRCX__2y__1d.parquet", "2026-10-08")]
    assert len(parquet_cache._restore_frame(cache / "LRCX__2y__1d.parquet")) == 6, "sin --aplicar escribió"

    assert limpiar(cache, aplicar=True) == [("LRCX__2y__1d.parquet", "2026-10-08")]
    lrcx = parquet_cache._restore_frame(cache / "LRCX__2y__1d.parquet")
    assert len(lrcx) == 5 and str(lrcx.index[-1])[:10] == "2026-10-07"
    assert parquet_cache._read_fetched_at(cache / "LRCX__2y__1d.parquet") == cuando, "perdió el fetched_at"
    assert len(parquet_cache._restore_frame(cache / "AMCR__10y__1d.parquet")) == 6
    assert len(parquet_cache._restore_frame(cache / "AAPL__2y__1d.parquet")) == 6
    assert limpiar(cache, aplicar=True) == [], "una segunda pasada no saca otra fila"
    assert not list(cache.glob("*.tmp*"))
    assert pq.read_schema(cache / "LRCX__2y__1d.parquet").metadata is not None
