"""Tarea 357: las noticias de Yahoo por ticker salen de ``yf.Search``, filtradas por ``relatedTickers``.

``Ticker.news`` contesta 404 desde el 2026-10-01 (tarea 354). ``yf.Search`` contesta, pero es
una búsqueda por **texto**: para ``AVB`` (AvalonBay) trae ArriVent BioPharma (``AVBP``) y
Avidbank (``AVBH``). Se acepta una noticia sólo si Yahoo la etiqueta con el ticker, y entra
con ``source = "yfinance:search"`` para que la serie vieja (``yfinance``) y la nueva no se
mezclen.

Las respuestas de abajo son **grabadas** el 2026-10-19 (recortadas a los campos que se leen),
incluida la de ``AVB``. Sin red: el cortafuegos de la 209 la corta igual.
"""

from __future__ import annotations

import pytest

import data.news_sources as ns
from data.news_sources import YF_SEARCH_SOURCE, _yf_news, parse_yf_search_item

# Grabada: yf.Search("AVB", news_count=10).news, 2026-10-19. Ninguna es de AvalonBay.
_AVB = [
    {
        "title": "Avidbank Holdings Inc. (AVBH) Reports Next Week: Wall Street Expects Earnings Growth",
        "publisher": "Zacks",
        "link": "https://finance.yahoo.com/markets/stocks/articles/avidbank-holdings-inc-avbh-reports-130004268.html",
        "providerPublishTime": 1792414804,
        "type": "STORY",
        "relatedTickers": ["AVBH", "COLB"],
    },
    {
        "title": "ArriVent Announces Cancer Cell Publication Highlighting Firmonertinib in EGFR "
        "PACC-Mutant Non-Small Cell Lung Cancer",
        "publisher": "GlobeNewswire",
        "link": "https://finance.yahoo.com/healthcare/articles/arrivent-announces-cancer-cell-publication-120100990.html",
        "providerPublishTime": 1792411260,
        "type": "STORY",
        "relatedTickers": ["AVBP"],
    },
    {
        "title": "ArriVent BioPharma to Present at Upcoming Investor Conference",
        "publisher": "GlobeNewswire",
        "link": "https://finance.yahoo.com/x",
        "providerPublishTime": 1792400000,
        "type": "STORY",
        "relatedTickers": ["AVBP", "STX", "6762.T"],
    },
]

# Grabada: yf.Search("BRK-B", news_count=10).news, 2026-10-19 (dos de diez), y una sin
# relatedTickers como las que trae "LOW" (la palabra, no Lowe's).
_BRK = [
    {
        "title": "Berkshire (BRK-B) Enters a New Era with Billions S",
        "publisher": "Zacks",
        "link": "https://finance.yahoo.com/a",
        "providerPublishTime": 1792414804,
        "type": "STORY",
        "relatedTickers": ["BRK-B"],
    },
    {
        "title": "Berkshire Hathaway (BRK-B)'s Cash Pile Just Shrank",
        "publisher": "Motley Fool",
        "link": "https://finance.yahoo.com/b",
        "providerPublishTime": 1792300000,
        "type": "STORY",
        "relatedTickers": ["brk-b", "GOOG"],
    },
    {
        "title": "US homebuilder sentiment tumbles to near 14-1/2-year low",
        "publisher": "Reuters",
        "link": "https://finance.yahoo.com/c",
        "providerPublishTime": 1792300000,
        "type": "STORY",
        "relatedTickers": [],
    },
]


def _con_respuesta(monkeypatch, respuesta):
    pedidos = []

    def _search(ticker):
        pedidos.append(ticker)
        return respuesta

    monkeypatch.setattr(ns, "_yf_search_news", _search)
    return pedidos


def test_AVB_no_acepta_las_noticias_de_ArriVent_ni_de_Avidbank(monkeypatch):
    _con_respuesta(monkeypatch, _AVB)
    items, o = _yf_news("AVB")
    assert items == []
    assert o.source == "yfinance_news" and o.status == "ok" and o.items == 0


def test_acepta_solo_las_que_Yahoo_etiqueta_con_el_ticker(monkeypatch):
    _con_respuesta(monkeypatch, _BRK)
    items, o = _yf_news("BRK-B")
    assert [i.title[:20] for i in items] == ["Berkshire (BRK-B) En", "Berkshire Hathaway ("]
    assert o.status == "ok" and o.items == 2


def test_la_fuente_es_otra_que_la_de_Ticker_news():
    item = parse_yf_search_item("BRK-B", _BRK[0])
    assert YF_SEARCH_SOURCE == "yfinance:search"
    assert item.source == YF_SEARCH_SOURCE != "yfinance"


def test_los_campos_salen_de_la_respuesta_plana_de_Search():
    item = parse_yf_search_item("brk-b", _BRK[0])
    assert item.ticker == "BRK-B"
    assert item.url == "https://finance.yahoo.com/a"
    # 1792414804 = 2026-10-19 13:00:04 UTC, naive como el resto de news_events
    assert item.published_at is not None and item.published_at.tzinfo is None
    assert item.published_at.isoformat() == "2026-10-19T13:00:04"


@pytest.mark.parametrize(
    "raw", [None, "x", {}, {"title": "", "relatedTickers": ["X"]}, {"relatedTickers": ["X"]}]
)
def test_entradas_sin_titulo_o_que_no_son_dict_se_descartan(raw):
    assert parse_yf_search_item("X", raw) is None


def test_sin_relatedTickers_se_descarta():
    assert parse_yf_search_item("LOW", {"title": "t", "relatedTickers": None}) is None
    assert parse_yf_search_item("LOW", {"title": "t"}) is None


def test_un_ticker_que_es_prefijo_de_otro_no_matchea():
    """``AVB`` no es ``AVBP``: la comparación es por elemento, no por substring."""
    assert parse_yf_search_item("AVB", {"title": "t", "relatedTickers": ["AVBP", "AVBH"]}) is None


def test_la_busqueda_que_revienta_es_FAILED(monkeypatch):
    def _boom(ticker):
        raise TimeoutError("curl 28")

    monkeypatch.setattr(ns, "_yf_search_news", _boom)
    items, o = _yf_news("NVDA")
    assert items == [] and o.failed and o.source == "yfinance_news"


def test_la_busqueda_usa_yf_Search_con_el_ticker(monkeypatch):
    """El camino real hasta ``yf.Search`` —el que el mock de arriba saltea—, sin red."""
    import data.yahoo_finance as yh

    llamadas = []

    class _Search:
        def __init__(self, query, **kw):
            llamadas.append((query, kw))
            self.news = _BRK

    class _YF:
        Search = _Search

    monkeypatch.setattr(yh, "yf", _YF)
    items, _ = _yf_news("BRK-B")
    assert len(items) == 2
    assert llamadas[0][0] == "BRK-B"
    assert llamadas[0][1]["news_count"] == ns.YF_SEARCH_NEWS_COUNT
