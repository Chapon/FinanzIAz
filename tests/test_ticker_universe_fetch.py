"""Tests del fetch live del universo S&P 500 y del filtro de ruido de yfinance (UNIV1).

Cubre las tres patas de la tarea 18 del backlog:
  (a) el fetch de Wikipedia manda un User-Agent de browser (sin él: HTTP 403)
  (b) el fallback hardcoded no tiene símbolos muertos conocidos
  (c) los 404 de quoteSummary no ensucian el log, y solo el que dice
      "Quote not found" se toma como delisting permanente
"""

from __future__ import annotations

import logging

import pytest

from data import ticker_universe, yf_noise
from data.ticker_universe import normalize_symbols

# Tabla mínima con la misma forma que la de Wikipedia (columna "Symbol" primera).
_FIXTURE_HTML = """
<html><body>
<table class="wikitable sortable">
  <tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>
  <tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td></tr>
  <tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td></tr>
  <tr><td>MSFT</td><td>Microsoft</td><td>Information Technology</td></tr>
</table>
</body></html>
"""


# ── (a) User-Agent ───────────────────────────────────────────────────────────

def test_fetch_sends_browser_user_agent(monkeypatch):
    """Sin UA de browser Wikipedia devuelve 403 — el header no es opcional."""
    seen = {}

    class _Resp:
        text = _FIXTURE_HTML

        def raise_for_status(self):
            return None

    def _fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("requests.get", _fake_get)

    html = ticker_universe._fetch_sp500_html()

    assert html == _FIXTURE_HTML
    ua = seen["headers"].get("User-Agent", "")
    assert "Mozilla/5.0" in ua, f"UA sin forma de browser: {ua!r}"
    assert "python" not in ua.lower(), "un UA de script es justo lo que Wikipedia rebota"
    assert seen["timeout"] == ticker_universe.WIKIPEDIA_TIMEOUT_SECONDS


def test_fetch_falls_back_when_http_fails(monkeypatch):
    """Un error de red no se propaga: devuelve None y el caller usa el fallback."""
    def _boom(*a, **kw):
        raise RuntimeError("HTTP Error 403: Forbidden")

    monkeypatch.setattr("requests.get", _boom)
    assert ticker_universe._fetch_sp500_from_wikipedia() is None


def test_fetch_rejects_truncated_table(monkeypatch):
    """Si el parse devuelve menos de MIN_EXPECTED_SYMBOLS, preferimos el fallback."""
    pytest.importorskip("lxml", reason="pandas.read_html necesita un parser de HTML")

    class _Resp:
        text = _FIXTURE_HTML

        def raise_for_status(self):
            return None

    monkeypatch.setattr("requests.get", lambda *a, **kw: _Resp())
    # La fixture tiene 3 símbolos, muy por debajo del mínimo.
    assert ticker_universe._fetch_sp500_from_wikipedia() is None


def test_fetch_parses_fixture_html(monkeypatch):
    """Parse end-to-end del HTML con el guard de tamaño bajado."""
    pytest.importorskip("lxml", reason="pandas.read_html necesita un parser de HTML")

    class _Resp:
        text = _FIXTURE_HTML

        def raise_for_status(self):
            return None

    monkeypatch.setattr("requests.get", lambda *a, **kw: _Resp())
    monkeypatch.setattr(ticker_universe, "MIN_EXPECTED_SYMBOLS", 2)

    symbols = ticker_universe._fetch_sp500_from_wikipedia()
    assert symbols == ["AAPL", "BRK-B", "MSFT"]


def test_missing_html_parser_is_not_fatal(monkeypatch):
    """Sin lxml el fetch se degrada al fallback con un warning, no con un traceback."""
    class _Resp:
        text = _FIXTURE_HTML

        def raise_for_status(self):
            return None

    monkeypatch.setattr("requests.get", lambda *a, **kw: _Resp())

    def _no_parser(*a, **kw):
        raise ImportError("Missing optional dependency 'lxml'")

    monkeypatch.setattr("pandas.read_html", _no_parser)
    monkeypatch.setattr(ticker_universe, "_warned_missing_parser", False)

    assert ticker_universe._fetch_sp500_from_wikipedia() is None


# ── normalize_symbols (puro, sin parser de HTML) ─────────────────────────────

def test_normalize_symbols_converts_dots_to_dashes():
    assert normalize_symbols(["BRK.B", "BF.B"]) == ["BRK-B", "BF-B"]


def test_normalize_symbols_drops_junk_rows():
    """Notas al pie y celdas raras no deben entrar al universo."""
    out = normalize_symbols(["AAPL", "", "  ", "DEMASIADOLARGO", "ñoño", "MSFT"])
    assert out == ["AAPL", "MSFT"]


def test_normalize_symbols_strips_whitespace():
    assert normalize_symbols(["  AAPL  ", "\tMSFT\n"]) == ["AAPL", "MSFT"]


# ── (b) Fallback depurado ────────────────────────────────────────────────────

# Confirmados sin barras contra Yahoo el 2026-07-20 (adquisiciones y renames).
DEAD_SYMBOLS = (
    "ANSS", "CTLT", "CMA", "CTRA", "DAY", "DFS", "FI",
    "HOLX", "HES", "IPG", "JNPR", "MMC", "PARA", "WBA",
)


@pytest.mark.parametrize("symbol", DEAD_SYMBOLS)
def test_fallback_has_no_dead_symbols(symbol):
    """Regresión del log 2026-07-15: estos producían 404 en cada scan."""
    assert symbol not in ticker_universe.get_sp500_fallback()


@pytest.mark.parametrize("symbol", ["MRSH", "BNY", "PSKY", "EXE", "PLTR", "COIN"])
def test_fallback_has_current_symbols(symbol):
    """Los renames y las altas recientes del índice sí tienen que estar."""
    assert symbol in ticker_universe.get_sp500_fallback()


def test_alive_tickers_that_404_are_kept():
    """FOX y LOW devuelven 404 de fundamentals pero COTIZAN — no son delistings.

    Es el caso que rompe la heurística ingenua "404 ⇒ deslistado": tratarlos como
    muertos habría sacado a Lowe's del universo.
    """
    fallback = ticker_universe.get_sp500_fallback()
    assert "FOX" in fallback
    assert "LOW" in fallback


# ── (c) Filtro de ruido de yfinance ──────────────────────────────────────────

def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("yfinance", logging.ERROR, __file__, 1, msg, None, None)


@pytest.fixture(autouse=True)
def _clean_unknown_symbols():
    yf_noise.reset_unknown_symbols()
    yield
    yf_noise.reset_unknown_symbols()


def test_quote_not_found_is_silenced_and_recorded():
    """'Quote not found' = símbolo inexistente: se descarta del log y se anota."""
    filt = yf_noise.QuoteSummary404Filter()
    msg = ('HTTP Error 404: {"quoteSummary":{"result":null,"error":'
           '{"code":"Not Found","description":"Quote not found for symbol: ANSS"}}}')

    assert filt.filter(_record(msg)) is False
    assert yf_noise.is_unknown_symbol("ANSS")


def test_no_fundamentals_is_silenced_but_not_recorded():
    """'No fundamentals data' = el símbolo existe, falta ese módulo (FOX/LOW)."""
    filt = yf_noise.QuoteSummary404Filter()
    msg = ('HTTP Error 404: {"quoteSummary":{"result":null,"error":'
           '{"code":"Not Found","description":"No fundamentals data found for symbol: LOW"}}}')

    assert filt.filter(_record(msg)) is False
    assert not yf_noise.is_unknown_symbol("LOW"), "LOW cotiza: no puede quedar marcado como muerto"


def test_other_yfinance_errors_still_pass_through():
    """El filtro silencia dos patrones conocidos, no los errores nuevos."""
    filt = yf_noise.QuoteSummary404Filter()

    assert filt.filter(_record("HTTP Error 500: Internal Server Error")) is True
    assert filt.filter(_record("HTTP Error 401: Invalid Crumb")) is True
    assert filt.filter(_record("algo inesperado explotó")) is True


def test_install_is_idempotent():
    """Instalar dos veces no debe apilar filtros duplicados."""
    logger = logging.getLogger("yfinance-test-univ1")
    before = len(logger.filters)
    yf_noise.install("yfinance-test-univ1")
    yf_noise.install("yfinance-test-univ1")
    assert len(logger.filters) - before <= 1


def test_404_is_not_classified_as_transient():
    """Un 404 es permanente: no debe entrar al camino de retry/backoff de throttle."""
    from data.yahoo_finance import _is_transient

    exc = Exception(
        'HTTP Error 404: {"quoteSummary":{"result":null,"error":'
        '{"code":"Not Found","description":"Quote not found for symbol: ANSS"}}}'
    )
    assert _is_transient(exc) is False
