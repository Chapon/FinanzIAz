"""Tarea 351 — ``os.replace`` del cache de parquet contra un destino que otro lector tiene abierto.

En Windows, reemplazar un archivo abierto por otro handle da ``PermissionError [WinError 5]``:
es la firma de los cuatro ``Parquet cache write failed`` del log (2026-10-08 y 09). El
``write`` ahora reintenta con esperas cortas; un lector dura milisegundos.
"""

from __future__ import annotations

import logging
import sys
import threading

import pandas as pd
import pyarrow.parquet as pq
import pytest

from data import parquet_cache as pc


@pytest.fixture
def directorio(tmp_path):
    pc.set_parquet_dir(tmp_path)
    yield tmp_path
    pc.set_parquet_dir(None)


def _frame(valor: float) -> pd.DataFrame:
    idx = pd.date_range("2026-10-01", periods=3, freq="D", name="Date")
    return pd.DataFrame({"Close": [valor] * 3}, index=idx)


def _cierre(path) -> float:
    return float(pq.read_table(path).to_pandas()["Close"].iloc[-1])


@pytest.mark.skipif(sys.platform != "win32", reason="el bloqueo por handle abierto es de Windows")
def test_en_windows_un_LECTOR_ABIERTO_ya_no_pierde_el_write(directorio):
    pc.write("MDLZ", "2y", "1d", _frame(1.0))
    path = pc.path_for("MDLZ", "2y", "1d")

    lector = pq.ParquetFile(path)  # el handle de `labelled_1d` a mitad de una lectura
    threading.Timer(0.15, lector.close).start()
    pc.write("MDLZ", "2y", "1d", _frame(2.0))

    assert _cierre(path) == 2.0
    assert [p.name for p in directorio.iterdir()] == [path.name]  # sin temporales


def test_reintenta_el_PermissionError_y_reemplaza(directorio, monkeypatch, caplog):
    pc.write("MRK", "2y", "1d", _frame(1.0))
    path = pc.path_for("MRK", "2y", "1d")
    real = pc.os.replace
    fallas = iter([True, True])
    esperas: list[float] = []

    def _replace(a, b):
        if next(fallas, False):
            raise PermissionError(13, "Acceso denegado")
        return real(a, b)

    monkeypatch.setattr(pc.os, "replace", _replace)
    monkeypatch.setattr(pc.time, "sleep", esperas.append)
    caplog.set_level(logging.INFO, logger=pc.log.name)

    pc.write("MRK", "2y", "1d", _frame(2.0))

    assert _cierre(path) == 2.0
    assert esperas == [0.05, 0.1]
    assert any("tras 2 reintentos" in r.getMessage() for r in caplog.records)


def test_si_el_lector_NO_suelta_queda_el_frame_anterior_y_se_loguea(directorio, monkeypatch, caplog):
    pc.write("MRVL", "2y", "1d", _frame(1.0))
    path = pc.path_for("MRVL", "2y", "1d")
    esperas: list[float] = []

    def _siempre(a, b):
        raise PermissionError(13, "Acceso denegado")

    monkeypatch.setattr(pc.os, "replace", _siempre)
    monkeypatch.setattr(pc.time, "sleep", esperas.append)

    pc.write("MRVL", "2y", "1d", _frame(2.0))

    assert _cierre(path) == 1.0
    assert esperas == list(pc._ESPERAS_REPLACE)
    assert any("write failed for MRVL" in r.getMessage() for r in caplog.records)
    assert [p.name for p in directorio.iterdir()] == [path.name]


def test_otro_error_NO_se_reintenta(directorio, monkeypatch):
    esperas: list[float] = []

    def _otro(a, b):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pc.os, "replace", _otro)
    monkeypatch.setattr(pc.time, "sleep", esperas.append)

    pc.write("BKNG", "2y", "1d", _frame(1.0))

    assert esperas == []
    assert not pc.path_for("BKNG", "2y", "1d").exists()
