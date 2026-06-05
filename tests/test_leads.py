"""Tests para ``analysis.leads`` (scoring + filtering) y el universo SP500."""

from __future__ import annotations

from analysis.leads import (
    BUCKET_WEIGHTS,
    LeadRow,
    compute_lead_score,
    filter_leads,
)
from data.ticker_universe import get_sp500_fallback, get_sp500_tickers


# ── compute_lead_score ────────────────────────────────────────────────────────

def _make_analyst(buckets: dict, price=None, mean_target=None) -> dict:
    """Helper: arma la estructura que devuelve get_analyst_data."""
    total = sum(buckets.values())
    return {
        "recommendations": [
            # -3m... 0m, todo igual para simplificar; el scoring usa solo el último
            {"period": "-3m", **buckets, "total": total},
            {"period": "-2m", **buckets, "total": total},
            {"period": "-1m", **buckets, "total": total},
            {"period": "0m", **buckets, "total": total},
        ],
        "price_targets": (
            {"current": price, "mean": mean_target, "median": None,
             "low": None, "high": None}
            if (price is not None or mean_target is not None) else None
        ),
    }


def test_compute_score_strong_buy_dominant():
    """Mayoría strong buy → score cerca de +2."""
    analyst = _make_analyst({"strongBuy": 20, "buy": 5, "hold": 0, "sell": 0, "strongSell": 0})
    row = compute_lead_score(analyst, "AAPL")
    assert row is not None
    assert row.ticker == "AAPL"
    expected = (2 * 20 + 1 * 5) / 25  # 1.8
    assert abs(row.score - expected) < 1e-6
    assert row.verdict == "Compra fuerte"
    assert row.total_analysts == 25
    assert abs(row.pct_strong_buy - 80.0) < 1e-6


def test_compute_score_balanced_hold():
    """Mayoría hold → score 0 → verdict Mantener."""
    analyst = _make_analyst({"strongBuy": 1, "buy": 1, "hold": 10, "sell": 1, "strongSell": 1})
    row = compute_lead_score(analyst, "X")
    assert row is not None
    # (2 + 1 + 0 - 1 - 2) / 14 = 0
    assert row.score == 0.0
    assert row.verdict == "Mantener"


def test_compute_score_strong_sell():
    analyst = _make_analyst({"strongBuy": 0, "buy": 0, "hold": 1, "sell": 5, "strongSell": 10})
    row = compute_lead_score(analyst, "JUNK")
    assert row.score < -1.5
    assert row.verdict == "Venta fuerte"


def test_compute_score_no_data_returns_none():
    assert compute_lead_score({"recommendations": [], "price_targets": None}, "ZZZ") is None
    assert compute_lead_score(None, "ZZZ") is None
    # Total 0 → None (no aporta info)
    assert compute_lead_score({"recommendations": [{"period": "0m", "strongBuy": 0,
                                                    "buy": 0, "hold": 0, "sell": 0,
                                                    "strongSell": 0, "total": 0}],
                               "price_targets": None}, "X") is None


def test_upside_calculation():
    analyst = _make_analyst(
        {"strongBuy": 10, "buy": 5, "hold": 2, "sell": 0, "strongSell": 0},
        price=100.0,
        mean_target=125.0,
    )
    row = compute_lead_score(analyst, "MSFT")
    assert row.price == 100.0
    assert row.mean_target == 125.0
    assert abs(row.upside_pct - 25.0) < 1e-6


def test_upside_none_when_no_targets():
    analyst = _make_analyst({"strongBuy": 10, "buy": 5, "hold": 2, "sell": 0, "strongSell": 0})
    row = compute_lead_score(analyst, "X")
    assert row.upside_pct is None
    assert row.price is None
    assert row.mean_target is None


def test_bucket_weights_constants_sane():
    """Si alguien cambia los pesos, debería ser intencional — este test rompe."""
    assert BUCKET_WEIGHTS == {"strongBuy": 2, "buy": 1, "hold": 0, "sell": -1, "strongSell": -2}


# ── filter_leads ──────────────────────────────────────────────────────────────

def _row(ticker: str, score: float, analysts: int) -> LeadRow:
    return LeadRow(
        ticker=ticker, score=score, total_analysts=analysts,
        pct_strong_buy=0, pct_buy=0, pct_hold=0, pct_sell=0, pct_strong_sell=0,
        verdict="X", price=None, mean_target=None, upside_pct=None,
    )


def test_filter_leads_score_threshold():
    rows = [_row("A", 1.5, 10), _row("B", 0.5, 10), _row("C", 1.2, 10)]
    out = filter_leads(rows, min_score=1.0, min_analysts=1)
    tickers = [r.ticker for r in out]
    assert "B" not in tickers
    assert tickers == ["A", "C"]  # ordenado desc por score


def test_filter_leads_analyst_threshold():
    rows = [_row("A", 2.0, 3), _row("B", 1.5, 10)]
    out = filter_leads(rows, min_score=1.0, min_analysts=5)
    assert [r.ticker for r in out] == ["B"]


def test_filter_leads_ordering():
    """Ties por score se rompen con # analistas."""
    rows = [_row("A", 1.5, 5), _row("B", 1.5, 20), _row("C", 1.8, 6)]
    out = filter_leads(rows, min_score=1.0, min_analysts=1)
    assert [r.ticker for r in out] == ["C", "B", "A"]


def test_filter_leads_empty_input():
    assert filter_leads([]) == []


# ── ticker_universe ───────────────────────────────────────────────────────────

def test_sp500_fallback_has_expected_size():
    """El fallback hardcoded debe tener al menos 400 tickers (margen vs 503 reales)."""
    tickers = get_sp500_fallback()
    assert len(tickers) >= 400
    # Sanity: tickers comunes
    assert "AAPL" in tickers
    assert "MSFT" in tickers
    assert "GOOGL" in tickers
    assert "BRK-B" in tickers  # debe usar guion (formato yfinance)


def test_sp500_fallback_no_duplicates():
    tickers = get_sp500_fallback()
    assert len(tickers) == len(set(tickers))


def test_sp500_fallback_clean_format():
    """Sin espacios, sin puntos, todo mayúsculas, ascii."""
    for t in get_sp500_fallback():
        assert t == t.strip()
        assert " " not in t
        assert "." not in t
        assert t == t.upper()
        assert t.isascii()
        assert 1 <= len(t) <= 6


def test_get_sp500_tickers_works_without_network(monkeypatch):
    """Si Wikipedia falla, get_sp500_tickers debe devolver el fallback sin tirar."""
    # Limpiar cache para forzar el fetch
    from data import ticker_universe
    ticker_universe._cache.clear()

    monkeypatch.setattr(
        "data.ticker_universe._fetch_sp500_from_wikipedia",
        lambda: None,
    )
    tickers = get_sp500_tickers()
    assert len(tickers) >= 400
    assert "AAPL" in tickers


def test_get_sp500_tickers_caches(monkeypatch):
    """Segunda llamada no debe re-disparar fetch."""
    from data import ticker_universe
    ticker_universe._cache.clear()

    call_count = {"n": 0}

    def _fake_fetch():
        call_count["n"] += 1
        return ["FAKE1", "FAKE2"] + list(get_sp500_fallback())

    monkeypatch.setattr("data.ticker_universe._fetch_sp500_from_wikipedia", _fake_fetch)

    get_sp500_tickers()
    get_sp500_tickers()
    get_sp500_tickers()
    assert call_count["n"] == 1
