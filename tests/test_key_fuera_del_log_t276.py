"""Tarea 276 — las API keys no llegan al log.

El defecto (``docs/auditoria_seguridad_2026-10-02.md`` [S-2]): Finnhub y Tiingo recibían la key
como ``?token=`` en la URL, y cuando un pedido fallaba ``requests`` armaba el mensaje con la URL
completa: la key de Finnhub estaba 240 veces en ``finanzias.log`` y 208 en ``.log.1``. Dos capas:
la key va por **header** (no hay URL que la contenga) y el formatter del log **enmascara** lo que
igual llegue. Y [S-1]: ``scripts/setup_slack.py`` versionaba el prefijo real del token de Slack.

La key de los tests es sintética.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest

from config.logging_config import FormatterQueEnmascara, enmascarar

KEY = "SINTETICA1234abcd"
_REPO = Path(__file__).resolve().parent.parent


# ── La segunda capa: el formatter ────────────────────────────────────────────


@pytest.mark.parametrize(
    "texto",
    [
        f"/api/v1/company-news?symbol=ABBV&from=2026-09-15&to=2026-09-22&token={KEY} (Caused by",
        f"headers={{'X-Finnhub-Token': '{KEY}'}}",
        f"https://api.tiingo.com/iex/?tickers=AAPL&apikey={KEY}",
        f"api_key={KEY}",
    ],
)
def test_enmascara_la_key_en_cada_forma(texto):
    out = enmascarar(texto)
    assert KEY not in out and "***" in out


def test_un_token_de_slack_se_enmascara():
    assert "abcdefghijkl" not in enmascarar("xoxb-1234567890-abcdefghijkl")


@pytest.mark.parametrize(
    "texto", ["Scan token=ok n=3", "tokens=5", "el tokenizer de qwen", "equity $51,214.97"]
)
def test_no_enmascara_lo_que_no_es_una_credencial(texto):
    assert enmascarar(texto) == texto


def test_el_formatter_enmascara_el_TRACEBACK_y_no_solo_el_mensaje():
    """La key estaba en el `MaxRetryError` del traceback, que se arma dentro de `format()`."""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(FormatterQueEnmascara("%(levelname)s %(message)s"))
    lg = logging.getLogger("test_t276")
    lg.addHandler(h)
    lg.propagate = False
    try:
        try:
            raise ConnectionError(f"Max retries exceeded with url: /api/v1/quote?symbol=AAPL&token={KEY}")
        except ConnectionError:
            lg.exception("collect_finnhub_news failed for %s", "AAPL")
    finally:
        lg.removeHandler(h)
    out = buf.getvalue()
    assert "Traceback" in out and "Max retries" in out
    assert KEY not in out


def test_setup_logging_usa_el_formatter_que_enmascara():
    src = (_REPO / "config" / "logging_config.py").read_text(encoding="utf-8")
    cuerpo = src[src.index("def setup_logging(") :]
    assert "FormatterQueEnmascara(" in cuerpo
    assert "logging.Formatter(DEFAULT_FORMAT" not in cuerpo


# ── La primera capa: la key por header ───────────────────────────────────────


class _Resp:
    def raise_for_status(self):
        return None

    def json(self):
        return []


class _Captura:
    def __init__(self):
        self.llamadas = []

    def get(self, url, **kw):
        self.llamadas.append((url, kw))
        return _Resp()


def _sin_key_en_la_url(url, kw):
    assert KEY not in url
    assert "token" not in (kw.get("params") or {}), "la key sigue yendo en la URL"
    assert KEY in " ".join(str(v) for v in (kw.get("headers") or {}).values()), "la key no va por header"


def test_finnhub_news_manda_la_key_por_header():
    from data.news_sources import collect_finnhub_news

    cap = _Captura()
    collect_finnhub_news("AAPL", session=cap, api_key=KEY)
    assert cap.llamadas
    _sin_key_en_la_url(*cap.llamadas[0])


@pytest.mark.parametrize("funcion", ["second_opinion", "tiingo_quote"])
def test_las_cotizaciones_mandan_la_key_por_header(monkeypatch, funcion):
    import requests

    import data.providers as prov

    cap = _Captura()
    monkeypatch.setattr(requests, "get", cap.get)
    getattr(prov, funcion)("AAPL", api_key=KEY)
    assert cap.llamadas
    _sin_key_en_la_url(*cap.llamadas[0])


def test_tiingo_diario_manda_la_key_por_header(monkeypatch):
    import requests

    from data.providers import TiingoProvider

    cap = _Captura()
    monkeypatch.setattr(requests, "get", cap.get)
    TiingoProvider(api_key=KEY).daily("AAPL", "1y")
    assert cap.llamadas
    _sin_key_en_la_url(*cap.llamadas[0])


# ── [S-1] ────────────────────────────────────────────────────────────────────


def test_el_ejemplo_de_setup_slack_es_un_prefijo_FICTICIO():
    """El ejemplo era el prefijo real del token (el id del workspace) en un repo público.

    Este test no escribe el valor real a propósito: si lo hiciera, lo volvería a versionar.
    """
    src = (_REPO / "scripts" / "setup_slack.py").read_text(encoding="utf-8")
    assert "xoxb-0000000000000-" in src
