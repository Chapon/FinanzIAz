"""Tarea 286 [E-1] — un lector directo de un frame atrasado recibe el aviso.

Los consumidores vivos piden con TTL y se refrescan solos; el riesgo es el script que lee
``parquet_cache.read(..., ttl_hours=None)`` y recibe un frame que terminó hace semanas sin que
nada lo diga (la 255 vio 123 de 131 frames terminando el 2026-09-09 y no abrió tarea).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import pytest

from data import parquet_cache as pc

_HOY = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)  # viernes


@pytest.fixture
def cache(tmp_path, monkeypatch):
    pc.set_parquet_dir(tmp_path)
    monkeypatch.setattr(pc, "_hoy", lambda: _HOY)
    monkeypatch.setattr(pc, "_atraso_avisado", False)
    yield
    pc.set_parquet_dir(None)


def _frame(hasta: str, n: int = 30) -> pd.DataFrame:
    idx = pd.bdate_range(end=hasta, periods=n)
    return pd.DataFrame({"Close": range(n)}, index=idx)


def _avisos(caplog, nivel=logging.WARNING):
    return [
        r
        for r in caplog.records
        if r.name == pc.log.name and r.levelno == nivel and "atras" in r.getMessage()
    ]


def test_un_frame_que_termino_hace_semanas_avisa_al_lector_directo(cache, caplog):
    pc.write("AAA", "1y", "1d", _frame("2026-09-09"))
    with caplog.at_level(logging.DEBUG, logger=pc.log.name):
        df = pc.read("AAA", "1y", "1d", ttl_hours=None)
    assert df is not None, "el aviso no le saca el dato al lector"
    avisos = _avisos(caplog)
    assert len(avisos) == 1 and "AAA" in avisos[0].getMessage() and "2026-09-09" in avisos[0].getMessage()


def test_dentro_de_la_tolerancia_no_avisa(cache, caplog):
    """Cinco ruedas: un fin de semana largo más el día de hoy sin asentar no es un atraso."""
    pc.write("AAA", "1y", "1d", _frame("2026-09-25"))  # viernes anterior: 5 ruedas
    with caplog.at_level(logging.DEBUG, logger=pc.log.name):
        pc.read("AAA", "1y", "1d", ttl_hours=None)
    assert _avisos(caplog) == [] and _avisos(caplog, logging.DEBUG) == []
    assert pc.ruedas_de_atraso(_frame("2026-09-25"), _HOY) == 5
    assert pc.ruedas_de_atraso(_frame("2026-09-24"), _HOY) == 6


def test_el_segundo_frame_atrasado_va_a_DEBUG(cache, caplog):
    pc.write("AAA", "1y", "1d", _frame("2026-09-09"))
    pc.write("BBB", "1y", "1d", _frame("2026-09-09"))
    with caplog.at_level(logging.DEBUG, logger=pc.log.name):
        pc.read("AAA", "1y", "1d", ttl_hours=None)
        pc.read("BBB", "1y", "1d", ttl_hours=None)
    assert len(_avisos(caplog)) == 1
    assert len(_avisos(caplog, logging.DEBUG)) == 1


def test_con_TTL_no_avisa_el_consumidor_vivo_se_refresca_solo(cache, caplog):
    pc.write("AAA", "1y", "1d", _frame("2026-09-09"))
    with caplog.at_level(logging.DEBUG, logger=pc.log.name):
        pc.read("AAA", "1y", "1d", ttl_hours=24)
    assert _avisos(caplog) == []
