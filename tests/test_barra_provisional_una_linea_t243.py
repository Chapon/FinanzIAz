"""Tarea 243 — el aviso de barra provisional es UNA línea por lote, no una por ticker.

El aviso de la tarea 112 salía una vez por ticker y por proceso: con el warm-up del arranque en
horario de mercado eran **132 WARNING por arranque**, 1.506 de los 2.215 del log vivo al
2026-09-30 (68%). Y el único WARNING del harvest —una corrida con 0/4 fuentes limpias— quedó
enterrado ahí (auditoría del 2026-09-30, [G-3]). Decisión de Chapa: bajar el ruido, sin Slack.

El dato no se pierde: el resumen dice **cuántos** y nombra una muestra; el detalle por ticker
va a DEBUG. Y `_PROVISIONAL_AVISADO` sigue siendo una vez por ticker y por proceso.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from data import yahoo_finance as yf


def _frame() -> pd.DataFrame:
    idx = pd.to_datetime(["2026-09-29", "2026-09-30"])
    return pd.DataFrame(
        {"Open": [1.0, 1.0], "High": [1.0, 1.0], "Low": [1.0, 1.0], "Close": [1.0, 1.0], "Volume": [1, 1]},
        index=idx,
    )


@pytest.fixture
def provisional(monkeypatch):
    monkeypatch.setattr(yf, "last_bar_is_provisional", lambda *_a, **_k: True)
    monkeypatch.setattr(yf, "_write_historical_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "record_success", lambda *_a, **_k: None)


def _avisos(caplog, nivel=logging.WARNING) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == nivel and "asento" in r.getMessage()]


def test_un_lote_de_132_da_UNA_linea_que_dice_cuantos(provisional, caplog):
    tickers = [f"T{i:03d}" for i in range(132)]
    with caplog.at_level(logging.DEBUG, logger=yf.log.name):
        for t in tickers:
            yf._finalize_historical(t, _frame(), "2y", "1d")
        yf._avisar_provisionales()

    avisos = _avisos(caplog)
    assert len(avisos) == 1, avisos
    assert avisos[0].startswith("132 ticker(s)") and "T000" in avisos[0] and "y 124 más" in avisos[0]
    assert "7%" in avisos[0], "el resumen conserva la consecuencia que decía el aviso de la 112"
    assert len(_avisos(caplog, logging.DEBUG)) == 132, "el detalle por ticker no se pierde: va a DEBUG"


def test_el_segundo_lote_del_mismo_proceso_no_repite_los_mismos_tickers(provisional, caplog):
    with caplog.at_level(logging.WARNING, logger=yf.log.name):
        for _ in range(2):
            for t in ("AAPL", "MSFT"):
                yf._finalize_historical(t, _frame(), "2y", "1d")
            yf._avisar_provisionales()
    assert len(_avisos(caplog)) == 1


def test_el_batch_publico_resume_al_terminar(provisional, monkeypatch, caplog):
    """El resumen lo emite el camino público, no hay que acordarse de llamarlo."""
    batch = pd.concat({t: _frame() for t in ("AAPL", "MSFT", "NVDA")}, axis=1)
    monkeypatch.setattr(yf, "_read_historical_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "_run_with_timeout", lambda *_a, **_k: batch)
    monkeypatch.setattr(yf, "_slice_ticker", lambda b, t: _frame())
    with caplog.at_level(logging.WARNING, logger=yf.log.name):
        yf.get_historical_data_batch(["AAPL", "MSFT", "NVDA"], period="2y", interval="1d")
    avisos = _avisos(caplog)
    assert len(avisos) == 1 and avisos[0].startswith("3 ticker(s)"), avisos


def test_el_fetch_individual_tambien_resume(provisional, monkeypatch, caplog):
    monkeypatch.setattr(yf, "_read_historical_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "_run_with_timeout", lambda *_a, **_k: _frame())
    with caplog.at_level(logging.WARNING, logger=yf.log.name):
        yf.get_historical_data("AAPL", period="2y", interval="1d")
    avisos = _avisos(caplog)
    assert len(avisos) == 1 and avisos[0].startswith("1 ticker(s)") and "AAPL" in avisos[0]
