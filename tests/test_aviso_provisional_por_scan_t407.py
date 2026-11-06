"""Tarea 407 — el aviso de barra provisional es UNA línea por scan, no una por ticker.

La 243 lo bajó a una línea por **camino público** de fetch, y cerró *«de 132 líneas por
arranque a una»*. Pero la fase ``analyze`` del scan pide los frames **de a un ticker**, y
cada ``get_historical_data`` resumía por su cuenta: 126 WARNING en el scan del 05/11
(`docs/auditoria_tanda_2026-11-05.md` [L-1]). Ahora ``run_scan`` abre
``avisos_provisionales_en_lote()`` y los caminos públicos de adentro acumulan.
"""

from __future__ import annotations

import contextlib
import logging

import pandas as pd
import pytest

from data import yahoo_finance as yf


def _frame() -> pd.DataFrame:
    idx = pd.to_datetime(["2026-11-04", "2026-11-05"])
    return pd.DataFrame(
        {"Open": [1.0, 1.0], "High": [1.0, 1.0], "Low": [1.0, 1.0], "Close": [1.0, 1.0], "Volume": [1, 1]},
        index=idx,
    )


@pytest.fixture
def provisional(monkeypatch):
    monkeypatch.setattr(yf, "last_bar_is_provisional", lambda *_a, **_k: True)
    monkeypatch.setattr(yf, "_write_historical_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "record_success", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "_serie_congelada", lambda *_a, **_k: False)
    monkeypatch.setattr(yf, "_read_historical_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "_run_with_timeout", lambda *_a, **_k: _frame())


def _avisos(caplog) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and "asento" in r.getMessage()
    ]


def _scan_de_a_uno(n: int) -> None:
    for i in range(n):
        yf.get_historical_data(f"T{i:03d}", period="2y", interval="1d")


def test_sin_lote_100_fetch_de_a_uno_dan_100_lineas(provisional, caplog):
    """El defecto, probado primero: así salía en el scan."""
    with caplog.at_level(logging.WARNING, logger=yf.log.name):
        _scan_de_a_uno(100)
    assert len(_avisos(caplog)) == 100


def test_adentro_de_un_lote_100_fetch_de_a_uno_dan_UNA_linea_al_cerrar(provisional, caplog):
    with caplog.at_level(logging.WARNING, logger=yf.log.name), yf.avisos_provisionales_en_lote():
        _scan_de_a_uno(100)
        assert _avisos(caplog) == [], "adentro del lote no se emite nada"
    avisos = _avisos(caplog)
    assert len(avisos) == 1, avisos
    assert avisos[0].startswith("100 ticker(s)") and "T000" in avisos[0] and "y 92 más" in avisos[0]


def test_lotes_anidados_emiten_solo_al_cerrar_el_de_afuera(provisional, caplog):
    with caplog.at_level(logging.WARNING, logger=yf.log.name), yf.avisos_provisionales_en_lote():
        with yf.avisos_provisionales_en_lote():
            _scan_de_a_uno(3)
        assert _avisos(caplog) == []
        # T000-T002 ya están anotados esperando al lote de afuera (y la 112 no los repite):
        # suma T003 y T004, cinco en total.
        _scan_de_a_uno(5)
    (aviso,) = _avisos(caplog)
    assert aviso.startswith("5 ticker(s)")


def test_un_error_adentro_del_lote_no_lo_deja_abierto_y_avisa_igual(provisional, caplog):
    with (
        caplog.at_level(logging.WARNING, logger=yf.log.name),
        contextlib.suppress(RuntimeError),
        yf.avisos_provisionales_en_lote(),
    ):
        _scan_de_a_uno(2)
        raise RuntimeError("el scan se cayó")
    assert yf._provisional_lote_abierto == 0
    assert len(_avisos(caplog)) == 1
    # Y después, fuera de un lote, vuelve a resumir por llamada.
    with caplog.at_level(logging.WARNING, logger=yf.log.name):
        yf.get_historical_data("OTRO", period="2y", interval="1d")
    assert len(_avisos(caplog)) == 2


def test_run_scan_abre_UN_lote(test_db, monkeypatch):
    """El scan es el que abre el lote: una cuenta inexistente sale temprano y ya lo abrió."""
    from paper_trading import engine

    abiertos: list[int] = []

    @contextlib.contextmanager
    def espia():
        abiertos.append(1)
        yield

    monkeypatch.setattr(yf, "avisos_provisionales_en_lote", espia)
    assert engine.run_scan(999_999) is None
    assert abiertos == [1]
