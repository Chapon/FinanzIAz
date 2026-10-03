"""Tarea 280 [D-1] — la misma nota por dos canales entra una sola vez.

``docs/auditoria_datos_2026-10-02.md`` [D-1]: la misma nota de Yahoo llegaba por ``yfinance`` y por
``finnhub:Yahoo`` con URLs distintas y ~1 h de diferencia. El hash es ``(ticker, título, HORA)``,
así que dos copias a ambos lados de un cambio de hora daban dos hashes: 1.988 pares, el 2,7% de
la tabla. El caso de abajo cruza ese borde (14:50 y 15:40).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from data.news_sources import NewsItem
from database.models import NewsEvent, session_scope
from scripts.harvest_catalysts import harvest


def _collector(por_ticker):
    def _collect(ticker, sources=None):
        return SimpleNamespace(news=list(por_ticker.get(ticker, [])), estimates=[])

    return _collect


def _nota(ticker, titulo, cuando, url, fuente):
    return NewsItem(ticker=ticker, title=titulo, source=fuente, published_at=cuando, url=url)


def _filas():
    with session_scope() as s:
        return s.query(NewsEvent).count()


def test_la_misma_nota_por_DOS_canales_cruzando_el_borde_de_la_hora_entra_una_vez(test_db):
    a = _nota(
        "MU",
        "Micron beats estimates",
        datetime(2026, 9, 24, 14, 50),
        "https://finance.yahoo.com/m/1",
        "yfinance",
    )
    b = _nota(
        "MU",
        "Micron Beats Estimates ",
        datetime(2026, 9, 24, 15, 40),
        "https://finnhub.io/api/news?id=9",
        "finnhub:Yahoo",
    )
    rep = harvest(["MU"], collector=_collector({"MU": [a, b]}), now=datetime(2026, 9, 24, 16))
    assert rep.news_new == 1 and rep.news_dup == 1
    assert _filas() == 1


def test_contra_una_ya_guardada_en_otra_corrida(test_db):
    a = _nota(
        "MU",
        "Micron beats estimates",
        datetime(2026, 9, 24, 14, 50),
        "https://finance.yahoo.com/m/1",
        "yfinance",
    )
    harvest(["MU"], collector=_collector({"MU": [a]}), now=datetime(2026, 9, 24, 16))
    b = _nota(
        "MU",
        "Micron beats estimates",
        datetime(2026, 9, 25, 2, 0),
        "https://finnhub.io/api/news?id=9",
        "finnhub:Yahoo",
    )
    rep = harvest(["MU"], collector=_collector({"MU": [b]}), now=datetime(2026, 9, 25, 3))
    assert rep.news_new == 0 and _filas() == 1


def test_el_mismo_titular_generico_DIAS_despues_es_otra_noticia(test_db):
    a = _nota("TSLA", "Tesla stock rises", datetime(2026, 9, 1, 15), "https://x.com/1", "yfinance")
    b = _nota("TSLA", "Tesla stock rises", datetime(2026, 9, 4, 15), "https://x.com/2", "yfinance")
    harvest(["TSLA"], collector=_collector({"TSLA": [a, b]}), now=datetime(2026, 9, 4, 16))
    assert _filas() == 2


def test_el_mismo_titulo_en_OTRO_ticker_no_es_duplicado(test_db):
    a = _nota("AAPL", "Big tech rallies", datetime(2026, 9, 1, 15), "https://x.com/1", "yfinance")
    b = _nota("MSFT", "Big tech rallies", datetime(2026, 9, 1, 15, 30), "https://x.com/2", "yfinance")
    harvest(["AAPL", "MSFT"], collector=_collector({"AAPL": [a], "MSFT": [b]}), now=datetime(2026, 9, 1, 16))
    assert _filas() == 2
