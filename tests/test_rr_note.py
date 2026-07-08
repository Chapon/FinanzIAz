"""Integración: la nota R:R/stop/TP en los BUY (V2, display-only).

El engine estampa en ``PaperOrder.notes`` los niveles de riesgo ex-ante de cada
BUY (stop/TP + R:R) para que la UI de Paper los muestre. Es display-only: no
cambia ninguna decisión ni sizing (regla 3). La matemática pura está en
``test_paper_gates.py`` (entry_risk_levels/format_entry_risk_note).
"""
from __future__ import annotations

import pandas as pd

from config.settings_manager import settings
from database.models import session_scope
from paper_trading.account import create_account
from paper_trading.models import PaperOrder, PaperWatchlistItem


def _history_varying(price: float, n: int = 30) -> pd.DataFrame:
    """OHLCV con rango intradía no nulo → ATR > 0 (High/Low ≠ Close)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    closes = [price + (i % 3) for i in range(n)]  # oscila un poco
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 2.0 for c in closes],
            "Low": [c - 2.0 for c in closes],
            "Close": closes,
            "Volume": [10_000.0] * n,
        },
        index=idx,
    )


def _history_flat(price: float, n: int = 30) -> pd.DataFrame:
    """OHLCV constante → ATR = 0 → sin nota (fail-open)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": [price] * n, "High": [price] * n, "Low": [price] * n,
         "Close": [price] * n, "Volume": [10_000.0] * n},
        index=idx,
    )


def _isolate_other_gates() -> None:
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("earnings_blackout_days", 0)
    settings.set("paper_adv_cap_pct", 0.0)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 2.0)
    settings.set("atr_tp_mult", 4.0)


def _buy_strategy(ticker: str, dollars: float):
    from paper_trading.strategies import TargetTrade

    def strat(account, watchlist, positions, prices, history_provider):
        return [TargetTrade(ticker=ticker, side="BUY", target_shares=None,
                            target_dollars=dollars, reason="analyze BUY",
                            source="analyze_single")]

    return strat


def _run(monkeypatch, account, *, ticker, price, history, buy_dollars):
    from paper_trading import engine

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy(ticker, buy_dollars))
    return engine.run_scan(
        account.id,
        prices_provider=lambda _t: {ticker: price},
        history_provider=lambda _t: history,
        earnings_provider=lambda _t: None,
    )


def test_manual_buy_gets_rr_note(test_db, monkeypatch):
    a = create_account(name="RR", initial_capital=100_000.0, mode="manual")
    _isolate_other_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    result = _run(monkeypatch, a, ticker="AAPL", price=100.0,
                  history=_history_varying(100.0), buy_dollars=10_000.0)

    assert result is not None and result.queued == 1
    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()
        assert order.notes is not None
        assert "R:R" in order.notes
        assert "stop $" in order.notes and "TP $" in order.notes


def test_auto_buy_fill_gets_rr_note(test_db, monkeypatch):
    a = create_account(name="RRauto", initial_capital=100_000.0, mode="auto")
    _isolate_other_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="MSFT"))

    result = _run(monkeypatch, a, ticker="MSFT", price=100.0,
                  history=_history_varying(100.0), buy_dollars=10_000.0)

    assert result is not None and result.filled == 1
    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.filled_orders[0]).first()
        assert order.notes is not None and "R:R" in order.notes


def test_flat_history_no_note_failopen(test_db, monkeypatch):
    a = create_account(name="RRflat", initial_capital=100_000.0, mode="manual")
    _isolate_other_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="TSLA"))

    result = _run(monkeypatch, a, ticker="TSLA", price=100.0,
                  history=_history_flat(100.0), buy_dollars=10_000.0)

    assert result is not None and result.queued == 1
    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()
        assert order.notes is None  # ATR 0 → sin nota, orden creada igual


def test_no_history_no_note_failopen(test_db, monkeypatch):
    from paper_trading import engine

    a = create_account(name="RRnohist", initial_capital=100_000.0, mode="manual")
    _isolate_other_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="NVDA"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("NVDA", 10_000.0))
    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"NVDA": 100.0},
        history_provider=lambda _t: None,
        earnings_provider=lambda _t: None,
    )

    assert result is not None and result.queued == 1
    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()
        assert order.notes is None
