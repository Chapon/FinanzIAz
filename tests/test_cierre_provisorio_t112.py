"""Tarea 112 — la última barra del cache era un precio PROVISORIO, y nadie lo veía.

El refresh del cohorte corrió el 2026-09-01 a las 20:03-20:07 UTC, con el cierre de
NYSE a las 20:00, y guardó como cierre del día el precio **al momento del fetch**.
Medido sobre 45 tickers: **42 de 45 (93%)** tenían mal el cierre, mediana 0,32%, máx
2,07%. Y quedó así **tres días**.

**Qué mueve, medido — y el enunciado de la tarea decía mal la mitad:**

* el **ATR no se mueve** (0,00%): el True Range de la última barra usa su High/Low y
  el cierre **anterior**, así que su propio Close no entra hasta la barra siguiente;
* la **señal sí**: cambia en **9 de 127 (7,1%)** de la watchlist viva, y dos dan
  vuelta el signo entero (BKR `BUY→SELL`, MPC `SELL→BUY`).

Ningún guard podía verlo: la barra **existe** y está en la **fecha correcta**, así que
`stale_artifacts` (puntas), `artifact_window` (puntas) y `cross_period_gaps` (fechas)
la dan por buena. Es el punto ciego de la 110 pero en el **valor**.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import pytest

from data import yahoo_finance as yf


def _frame(fechas: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1},
        index=pd.to_datetime(fechas),
    )


@pytest.fixture
def hoy_et():
    tz = yf.market_timezone()
    assert tz is not None, "el test necesita la zona; si falla, es la tarea 104"
    return datetime.now(tz)


# ── El predicado ────────────────────────────────────────────────────────────


def test_la_barra_de_hoy_EN_el_horario_del_scan_es_provisoria(hoy_et):
    """**El caso real.** El scan diario corre a las **16:05 ET**, cinco minutos
    después del cierre — exactamente la ventana donde se midió el 93% de error."""
    df = _frame([hoy_et.strftime("%Y-%m-%d")])
    assert yf.last_bar_is_provisional(df, hoy_et.replace(hour=16, minute=5)) is True


def test_pasado_el_margen_ya_no_lo_es(hoy_et):
    """El control positivo: si diera `True` siempre, el test de arriba no probaría
    nada y el aviso sería ruido permanente."""
    df = _frame([hoy_et.strftime("%Y-%m-%d")])
    assert yf.last_bar_is_provisional(df, hoy_et.replace(hour=17, minute=0)) is False


def test_durante_la_sesion_tambien(hoy_et):
    """Una barra de hoy a mitad de rueda es lo más provisorio que hay."""
    df = _frame([hoy_et.strftime("%Y-%m-%d")])
    assert yf.last_bar_is_provisional(df, hoy_et.replace(hour=11, minute=30)) is True


def test_una_barra_de_AYER_no_es_provisoria(hoy_et):
    """Lo que distingue al predicado de *«la última barra es reciente»*: una sesión
    que ya cerró está asentada, no importa la hora que sea ahora."""
    df = _frame(["2020-01-02", "2020-01-03"])
    assert yf.last_bar_is_provisional(df, hoy_et.replace(hour=11, minute=0)) is False


def test_un_frame_vacio_o_None_no_acusa():
    assert yf.last_bar_is_provisional(None) is False
    assert yf.last_bar_is_provisional(pd.DataFrame()) is False


def test_sin_zona_horaria_NO_acusa(monkeypatch, hoy_et):
    """Sin hora confiable no se puede afirmar que una barra sea provisoria. Acusar
    igual sería ruido — y un guard que hace ruido se termina apagando. El aviso de
    que la zona no resuelve ya lo da `market_timezone` (tarea 104)."""
    monkeypatch.setattr(yf, "market_timezone", lambda: None)
    df = _frame([hoy_et.strftime("%Y-%m-%d")])
    assert yf.last_bar_is_provisional(df, hoy_et.replace(hour=16, minute=5)) is False


# ── El cableado al punto único de escritura ─────────────────────────────────


def test_el_aviso_sale_al_cachear_y_dice_la_consecuencia(monkeypatch, caplog, hoy_et):
    """`_finalize_historical` es el punto **único** de escritura, compartido por
    `get_historical_data` y `get_historical_data_batch`: cablearlo ahí lo cubre todo
    sin depender de que alguien se acuerde en cada camino."""
    monkeypatch.setattr(yf, "last_bar_is_provisional", lambda *_a, **_k: True)
    monkeypatch.setattr(yf, "_write_historical_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "record_success", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "_PROVISIONAL_AVISADO", set())

    with caplog.at_level(logging.WARNING):
        yf._finalize_historical("ZZTOP", _frame(["2026-08-03", "2026-08-04"]), "2y", "1d")

    msgs = [r.getMessage() for r in caplog.records]
    assert any("no asento" in m for m in msgs), msgs
    assert any("7%" in m for m in msgs), "el aviso tiene que decir qué se mueve"


def test_el_aviso_sale_UNA_vez_por_ticker(monkeypatch, caplog):
    """Corre por cada ticker del universo en cada refresh: un WARNING por llamada
    serían 128 líneas por tanda."""
    monkeypatch.setattr(yf, "last_bar_is_provisional", lambda *_a, **_k: True)
    monkeypatch.setattr(yf, "_write_historical_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "record_success", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "_PROVISIONAL_AVISADO", set())

    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            yf._finalize_historical("ZZTOP", _frame(["2026-08-03", "2026-08-04"]), "2y", "1d")

    assert sum("no asento" in r.getMessage() for r in caplog.records) == 1


def test_con_la_barra_asentada_no_avisa_nada(monkeypatch, caplog):
    """El control del cableado: sin esto, un aviso que sale siempre pasaría los dos
    de arriba y no distinguiría nada."""
    monkeypatch.setattr(yf, "last_bar_is_provisional", lambda *_a, **_k: False)
    monkeypatch.setattr(yf, "_write_historical_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "record_success", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "_PROVISIONAL_AVISADO", set())

    with caplog.at_level(logging.WARNING):
        yf._finalize_historical("ZZTOP", _frame(["2026-08-03", "2026-08-04"]), "2y", "1d")

    assert not any("no asento" in r.getMessage() for r in caplog.records)


def test_DECLARA_pero_NO_descarta_la_barra(monkeypatch):
    """**La decisión de la tarea, fijada.** El guard avisa y el frame se cachea
    igual: descartar la última barra mueve el **ATR 1,92% mediana** —más que el
    defecto, que lo mueve 0,00%— así que sería cambiar una decisión para arreglar
    otra, sin haber medido la mejor. Queda para cuando se mida el margen real de
    asentamiento; hoy sólo se sabe que 3-7 minutos no alcanzan."""
    escrito = {}
    monkeypatch.setattr(yf, "last_bar_is_provisional", lambda *_a, **_k: True)
    monkeypatch.setattr(yf, "_write_historical_cache", lambda t, p, i, d: escrito.update(n=len(d)))
    monkeypatch.setattr(yf, "record_success", lambda *_a, **_k: None)
    monkeypatch.setattr(yf, "_PROVISIONAL_AVISADO", set())

    df = _frame(["2026-08-03", "2026-08-04", "2026-08-05"])
    out = yf._finalize_historical("ZZTOP", df, "2y", "1d")

    assert escrito["n"] == 3, "no se descarta ninguna barra al cachear"
    assert out is not None and len(out) == 3, "y el caller recibe el frame entero"
