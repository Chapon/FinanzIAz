"""Tarea 367: GOOGL acepta las noticias etiquetadas ``GOOG``, y LOW, NOW y DE se buscan por nombre.

El filtro de la 357 acepta una noticia sólo si Yahoo la etiqueta con el ticker. Medido el
2026-10-22 sobre los 127 tickers vivos: Yahoo etiqueta las de Alphabet como ``GOOG`` (9 de 9,
también buscando «Alphabet»), y la búsqueda toma ``LOW``, ``NOW`` y ``DE`` como palabras
(1, 1 y 0 etiquetadas de 10). Buscando por nombre, 10 de 10. El filtro **no** se afloja:
lo que entra es lo que Yahoo etiqueta con el ticker o con un alias declarado.
"""

from __future__ import annotations

import pytest

import data.news_sources as ns
from data.news_sources import _yf_news, parse_yf_search_item

# Grabada: yf.Search("GOOGL", news_count=10).news, 2026-10-22 (tres de nueve, recortadas).
# Las nueve venían con GOOG y ninguna con GOOGL.
_GOOGL = [
    {
        "title": "Meta, AI Stocks Tumble As AI Spending Fears Reignite",
        "publisher": "Investor's Business Daily",
        "link": "https://finance.yahoo.com/m/c3b6ab41-5e55-3fb0-9139-d427005fd0e6/meta%2C-ai-stocks-tumble-as-ai.html",
        "providerPublishTime": 1792693760,
        "type": "STORY",
        "relatedTickers": ["META", "AMZN", "GOOG", "MSFT"],
    },
    {
        "title": "IBM Is America’s Worst Big Tech Company",
        "publisher": "24/7 Wall St.",
        "link": "https://finance.yahoo.com/technology/articles/ibm-america-worst-big-tech-181538518.html",
        "providerPublishTime": 1792692938,
        "type": "STORY",
        "relatedTickers": ["IBM", "MSFT", "GOOG", "META", "NVDA"],
    },
    {
        "title": "Investors are punishing Big Tech's biggest spenders. Meta is the latest casualty.",
        "publisher": "Yahoo Finance",
        "link": "https://finance.yahoo.com/markets/article/investors-are-punishing-big-techs-biggest-spenders-meta-is-the-latest-casualty-174236447.html",
        "providerPublishTime": 1792690956,
        "type": "STORY",
        "relatedTickers": ["META", "AAPL", "LLY", "WMT", "GOOG", "SPCX"],
    },
]
# Sintética: una de la misma búsqueda sin GOOG, que tiene que seguir afuera.
_SIN_GOOG = {"title": "Microsoft sube", "link": "https://x", "relatedTickers": ["MSFT", "META"]}


def _con_yf(monkeypatch, news):
    import data.yahoo_finance as yh

    consultas = []

    class _Search:
        def __init__(self, query, **kw):
            consultas.append(query)
            self.news = news

    monkeypatch.setattr(yh, "yf", type("_YF", (), {"Search": _Search}))
    return consultas


def test_googl_acepta_las_etiquetadas_goog_y_las_guarda_como_googl(monkeypatch):
    consultas = _con_yf(monkeypatch, [*_GOOGL, _SIN_GOOG])
    items, o = _yf_news("GOOGL")
    assert consultas == ["GOOGL"]
    assert [i.title[:20] for i in items] == [r["title"][:20] for r in _GOOGL]
    assert {i.ticker for i in items} == {"GOOGL"}
    assert o.status == "ok" and o.items == 3


def test_el_alias_es_de_googl_y_no_de_cualquiera():
    """Que ``GOOG`` sea alias de ``GOOGL`` no hace que una noticia de GOOG entre a MSFT."""
    assert parse_yf_search_item("MSFT", {"title": "t", "relatedTickers": ["GOOG"]}) is None
    assert parse_yf_search_item("GOOGL", _SIN_GOOG) is None


@pytest.mark.parametrize(("ticker", "consulta"), [("LOW", "Lowe's"), ("NOW", "ServiceNow"), ("DE", "Deere")])
def test_los_tickers_que_son_palabras_se_buscan_por_nombre(monkeypatch, ticker, consulta):
    consultas = _con_yf(
        monkeypatch,
        [
            {"title": "propia", "link": "a", "relatedTickers": [ticker]},
            {"title": "ajena", "link": "b", "relatedTickers": ["HD"]},
        ],
    )
    items, _ = _yf_news(ticker)
    assert consultas == [consulta]
    assert [i.title for i in items] == ["propia"]  # el filtro por etiqueta sigue igual
    assert items[0].ticker == ticker


def test_el_resto_se_sigue_buscando_por_ticker(monkeypatch):
    consultas = _con_yf(monkeypatch, [])
    _yf_news("AVB")
    assert consultas == ["AVB"]


def test_los_mapas_estan_en_mayusculas():
    """La consulta y el alias se buscan con el ticker en mayúsculas."""
    assert all(k == k.upper() for k in [*ns.YF_SEARCH_ALIAS, *ns.YF_SEARCH_CONSULTA])
    assert all(a == a.upper() for v in ns.YF_SEARCH_ALIAS.values() for a in v)
