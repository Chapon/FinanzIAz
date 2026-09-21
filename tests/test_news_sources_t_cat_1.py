"""
Tests for T-CAT-1 news sources: SEC 8-K (EDGAR) + per-ticker RSS + source wiring.

Fully offline: the EDGAR parsers are pure functions exercised against recorded
JSON fixtures (no network), and the wiring test monkeypatches the per-source
collectors. The live HTTP paths (``fetch_cik_map`` / ``collect_sec_8k`` request
calls) are intentionally not exercised here — they run on Windows during the
real harvest; what matters for correctness is the parsing + dedup logic.
"""

from __future__ import annotations

from datetime import datetime

import data.news_sources as ns
from data.news_sources import (
    NewsItem,
    _finnhub_source_label,
    cik_for_ticker,
    collect_all,
    collect_finnhub_news,
    parse_company_tickers,
    parse_edgar_submissions,
    parse_finnhub_news,
)

# ── fixtures (recorded EDGAR shapes) ─────────────────────────────────────────

COMPANY_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
}

SUBMISSIONS_AAPL = {
    "cik": 320193,
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-26-000050",
                "0000320193-26-000049",
                "0000320193-26-000048",
            ],
            "filingDate": ["2026-05-01", "2026-04-15", "2026-04-10"],
            "form": ["8-K", "10-Q", "8-K"],
            "items": ["2.02,9.01", "", "5.02"],
            "primaryDocument": [
                "aapl-8k_20260501.htm",
                "aapl-10q.htm",
                "aapl-8k_20260410.htm",
            ],
            "primaryDocDescription": ["8-K", "10-Q", "8-K"],
        }
    },
}


# ── ticker → CIK map ─────────────────────────────────────────────────────────


def test_parse_company_tickers():
    m = parse_company_tickers(COMPANY_TICKERS)
    assert m == {"AAPL": 320193, "NVDA": 1045810}


def test_parse_company_tickers_defensive_on_junk():
    assert parse_company_tickers({"0": "not a dict", "1": {"ticker": "X"}}) == {}


def test_cik_for_ticker_uses_provided_map():
    m = {"AAPL": 320193}
    assert cik_for_ticker("aapl", m) == 320193
    assert cik_for_ticker("MSFT", m) is None


# ── parse_edgar_submissions ──────────────────────────────────────────────────


def test_parse_edgar_keeps_only_8k():
    items = parse_edgar_submissions("AAPL", SUBMISSIONS_AAPL)
    # 2 of the 3 filings are 8-K; the 10-Q is dropped
    assert len(items) == 2
    assert all(i.source == "sec_8k" for i in items)
    assert all(i.ticker == "AAPL" for i in items)


def test_parse_edgar_item_codes_become_labels():
    items = parse_edgar_submissions("AAPL", SUBMISSIONS_AAPL)
    first = items[0]
    assert "Results of Operations and Financial Condition" in first.title
    assert "Financial Statements and Exhibits" in first.title
    assert first.content is not None and "2.02, 9.01" in first.content


def test_parse_edgar_published_at_is_filing_date():
    items = parse_edgar_submissions("AAPL", SUBMISSIONS_AAPL)
    assert items[0].published_at == datetime(2026, 5, 1)


def test_parse_edgar_builds_archive_url():
    items = parse_edgar_submissions("AAPL", SUBMISSIONS_AAPL)
    assert items[0].url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000050/aapl-8k_20260501.htm"
    )


def test_parse_edgar_unknown_item_passes_through():
    payload = {
        "cik": 1,
        "filings": {
            "recent": {
                "accessionNumber": ["0000000001-26-000001"],
                "filingDate": ["2026-06-01"],
                "form": ["8-K"],
                "items": ["9.99"],  # not in the label table
                "primaryDocument": ["x.htm"],
                "primaryDocDescription": ["8-K"],
            }
        },
    }
    items = parse_edgar_submissions("XYZ", payload)
    assert items[0].title == "XYZ 8-K: 9.99"


def test_parse_edgar_respects_max_filings():
    items = parse_edgar_submissions("AAPL", SUBMISSIONS_AAPL, max_filings=1)
    assert len(items) == 1


def test_parse_edgar_empty_payload_is_safe():
    assert parse_edgar_submissions("AAPL", {}) == []
    assert parse_edgar_submissions("AAPL", {"filings": {}}) == []


# ── 8-K dedup behaviour via content_hash ─────────────────────────────────────


def test_8k_same_filing_hashes_equal():
    a = parse_edgar_submissions("AAPL", SUBMISSIONS_AAPL)
    b = parse_edgar_submissions("AAPL", SUBMISSIONS_AAPL)
    assert a[0].content_hash() == b[0].content_hash()


def test_8k_different_items_hash_differently():
    items = parse_edgar_submissions("AAPL", SUBMISSIONS_AAPL)
    # the two 8-Ks have different items (2.02,9.01 vs 5.02) → different titles
    assert items[0].content_hash() != items[1].content_hash()


# ── Finnhub company-news ─────────────────────────────────────────────────────

FINNHUB_PAYLOAD = [
    {
        "datetime": 1_700_000_000,
        "headline": "NVDA lands hyperscaler deal",
        "summary": "Multi-year GPU supply agreement.",
        "url": "https://www.reuters.com/tech/nvda-deal",
        "source": "Reuters",
        "related": "NVDA",
        "id": 1,
    },
    {
        "datetime": 1_700_003_600,
        "headline": "Analysts react to NVDA guidance",
        "summary": "",
        "url": "https://www.cnbc.com/nvda-guidance",
        "source": "CNBC",
        "id": 2,
    },
    {"summary": "no headline here", "url": "https://x.com/none", "source": "Foo"},  # skipped
]


def test_parse_finnhub_maps_fields_and_outlet():
    items = parse_finnhub_news("nvda", FINNHUB_PAYLOAD)
    assert len(items) == 2  # the headline-less item is dropped
    first = items[0]
    assert first.ticker == "NVDA"
    assert first.title == "NVDA lands hyperscaler deal"
    assert first.source == "finnhub:Reuters"  # outlet preserved
    assert first.content == "Multi-year GPU supply agreement."
    assert first.url == "https://www.reuters.com/tech/nvda-deal"
    assert first.published_at is not None
    assert items[1].source == "finnhub:CNBC"
    assert items[1].content is None  # empty summary normalized to None


def test_parse_finnhub_defensive_on_junk():
    assert parse_finnhub_news("X", None) == []
    assert parse_finnhub_news("X", {"error": "bad symbol"}) == []
    assert parse_finnhub_news("X", ["not a dict", 42]) == []


def test_finnhub_source_label_falls_back_and_caps():
    assert _finnhub_source_label(None) == "finnhub"
    assert _finnhub_source_label("  ") == "finnhub"
    assert _finnhub_source_label("Bloomberg") == "finnhub:Bloomberg"
    long = _finnhub_source_label("X" * 80)
    assert len(long) <= 50 and long.startswith("finnhub:")


def test_collect_finnhub_skips_without_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_TOKEN", raising=False)
    # no network attempted, returns [] cleanly
    assert collect_finnhub_news("NVDA") == []


def test_collect_finnhub_uses_injected_session():
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return FINNHUB_PAYLOAD

    captured = {}

    class _Sess:
        def get(self, url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            return _Resp()

    items = collect_finnhub_news("nvda", session=_Sess(), api_key="testkey", days_back=7)
    assert len(items) == 2
    assert captured["url"].endswith("/company-news")
    assert captured["params"]["symbol"] == "NVDA"
    assert captured["params"]["token"] == "testkey"
    assert "from" in captured["params"] and "to" in captured["params"]


# ── collect_all wiring across sources ────────────────────────────────────────


# La costura que parchean estos tests son las implementaciones (`_yf_news`, `_sec_8k`,
# `_finnhub_news`), no los accesores públicos: desde la tarea 207 `collect_all`
# llama a las primeras, porque son las que devuelven el veredicto además de la lista.
#
# **Y el cambio de costura NO fue cosmético.** Al mover `collect_all` a las
# implementaciones, estos tests quedaron parcheando algo que ya nadie llamaba y
# `_finnhub_news` salió a la **API real de Finnhub** —hay `FINNHUB_API_KEY` viva en la
# máquina de Chapa— devolviendo 257 artículos de verdad. Lo delató que el contenido no
# coincidiera; si el fake hubiera producido algo compatible, el test habría pasado
# **pegándole a internet**. `conftest.py` aísla la DB y el settings, pero **no la red**:
# anotado como tarea 209.


def _ok(source, items):
    return items, ns.SourceOutcome(source, "ok", len(items))


def test_collect_all_default_is_yfinance_only(monkeypatch):
    calls = []
    monkeypatch.setattr(ns, "_yf_news", lambda t: _ok("yfinance_news", [_n(t, "yf")]))
    monkeypatch.setattr(ns, "_yf_estimates", lambda t: _ok("yfinance_estimates", []))
    monkeypatch.setattr(ns, "_sec_8k", lambda t: calls.append("sec") or _ok("sec", []))

    res = collect_all("NVDA")
    assert [i.source for i in res.news] == ["yfinance-fake"]
    assert calls == []  # sec no se invoca por default
    # Y sólo las fuentes que corrieron dejan veredicto (tarea 207).
    assert [o.source for o in res.outcomes] == ["yfinance_news", "yfinance_estimates"]


def test_collect_all_includes_sec_when_selected(monkeypatch):
    """La rama ``rss`` que este test tambien ejercitaba se borro en la tarea 212."""
    monkeypatch.setattr(ns, "_yf_news", lambda t: _ok("yfinance_news", [_n(t, "yf")]))
    monkeypatch.setattr(ns, "_yf_estimates", lambda t: _ok("yfinance_estimates", []))
    monkeypatch.setattr(ns, "_sec_8k", lambda t: _ok("sec", [_n(t, "sec_8k")]))

    res = collect_all("NVDA", {"yfinance", "sec"})
    got = sorted(i.source for i in res.news)
    assert got == ["sec_8k", "yfinance-fake"]
    assert sorted(o.source for o in res.outcomes) == [
        "sec",
        "yfinance_estimates",
        "yfinance_news",
    ]


def test_collect_all_includes_finnhub_when_selected(monkeypatch):
    monkeypatch.setattr(ns, "_yf_news", lambda t: _ok("yfinance_news", [_n(t, "yf")]))
    monkeypatch.setattr(ns, "_yf_estimates", lambda t: _ok("yfinance_estimates", []))
    monkeypatch.setattr(ns, "_finnhub_news", lambda t: _ok("finnhub", [_n(t, "finnhub:Reuters")]))

    res = collect_all("NVDA", {"yfinance", "finnhub"})
    got = sorted(i.source for i in res.news)
    assert got == ["finnhub:Reuters", "yfinance-fake"]


def test_collect_all_default_does_not_call_finnhub(monkeypatch):
    calls = []
    monkeypatch.setattr(ns, "_yf_news", lambda t: _ok("yfinance_news", []))
    monkeypatch.setattr(ns, "_yf_estimates", lambda t: _ok("yfinance_estimates", []))
    monkeypatch.setattr(ns, "_finnhub_news", lambda t: calls.append("finnhub") or _ok("finnhub", []))

    collect_all("NVDA")
    assert calls == []  # finnhub not invoked by default


def _n(ticker, source):
    # distinct tag so the default-yfinance fake can't be confused with real source strings
    src = "yfinance-fake" if source == "yf" else source
    return NewsItem(ticker=ticker.upper(), title=f"{ticker} {source}", source=src)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])


# ── La rama RSS se borró (tarea 212) ─────────────────────────────────────────


def test_la_rama_rss_ya_no_existe():
    """**Decisión de Chapa 2026-09-21, con la superposición medida.**

    `feedparser` nunca estuvo instalado ni declarado en `requirements.txt`, así que
    `_rss` devolvía `skipped` **siempre** — era código que no podía ejecutarse, y la 207
    dejó ese `skipped` fuera del denominador de la alarma, así que el reporte era ciego
    a la fuente caída de raíz **por construcción**.

    Lo que decidió no fue eso sino la medición: sobre 12 tickers del universo vivo, el
    feed default de Yahoo trae 211 titulares y **182 (86%) ya estaban** en la DB,
    traídos por `yfinance` + `finnhub:Yahoo`. Y **cero** filas de `news_events` usan una
    fuente rss, así que borrar no dejó ningún dato huérfano.

    Este test existe para que el borrado no vuelva a medias: un `_rss` que reaparezca
    sin `feedparser` declarado sería el mismo defecto otra vez.
    """
    import data.news_sources as mod

    for nombre in ("_rss", "collect_rss", "yahoo_rss_url", "default_feed_urls", "_rss_source_label"):
        assert not hasattr(mod, nombre), (
            f"`{nombre}` volvió: si la rama RSS se reimplementa, `feedparser` tiene que "
            "entrar a `requirements.txt` en el mismo commit (tarea 212)"
        )


def test_collect_all_ignora_la_fuente_rss_si_alguien_la_pide():
    """El token viejo no rompe nada: se ignora, como cualquier otro desconocido.

    Importa porque el `.bat` de alguien, o un `--sources` copiado de un doc viejo, puede
    seguir diciendo `rss`. Fallar ahí sería romper el harvest por un token muerto.
    """
    res = collect_all("NVDA", {"rss"})
    assert res.news == [] and res.estimates == []
    assert res.outcomes == [], "una fuente que no existe no deja veredicto"
