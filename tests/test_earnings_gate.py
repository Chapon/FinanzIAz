"""
Tests for Gate 6 (earnings blackout) in paper_trading.engine — roadmap T08.

The gate blocks BUY *and* SELL when the ticker has scheduled earnings within
±``earnings_blackout_days`` of the scan, with two carve-outs:
- ATR-forced stop-loss / take-profit / trailing SELLs (T01) bypass it.
- Unknown / failed earnings lookups fail-open (no block, warning logged).

Three layers are covered:
1. ``_earnings_blackout_hit`` — the pure ±window predicate.
2. ``_parse_next_earnings`` — parsing both yfinance calendar shapes.
3. ``run_scan`` — full integration via an injected ``earnings_provider``.
"""

from __future__ import annotations

import datetime as dt
import logging
from datetime import datetime, timedelta

import pandas as pd

from config.settings_manager import settings
from data.yahoo_finance import _parse_next_earnings
from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.engine import _earnings_blackout_hit
from paper_trading.models import PaperWatchlistItem
from paper_trading.strategies import TargetTrade

# ── Pure predicate: _earnings_blackout_hit ────────────────────────────────────


def test_blackout_hit_tomorrow_within_window():
    scan = datetime(2026, 5, 22, 14, 0, 0)
    assert _earnings_blackout_hit(scan + timedelta(days=1), scan, blackout_days=2) is True


def test_blackout_hit_far_outside_window():
    scan = datetime(2026, 5, 22, 14, 0, 0)
    assert _earnings_blackout_hit(scan + timedelta(days=5), scan, blackout_days=2) is False


def test_blackout_hit_recent_past_still_blocks():
    """Post-earnings gaps matter too — ±window is symmetric."""
    scan = datetime(2026, 5, 22, 14, 0, 0)
    assert _earnings_blackout_hit(scan - timedelta(days=1), scan, blackout_days=2) is True


def test_blackout_hit_disabled_with_zero_days():
    scan = datetime(2026, 5, 22, 14, 0, 0)
    assert _earnings_blackout_hit(scan + timedelta(days=0), scan, blackout_days=0) is False


def test_blackout_hit_none_date_never_blocks():
    scan = datetime(2026, 5, 22, 14, 0, 0)
    assert _earnings_blackout_hit(None, scan, blackout_days=2) is False


def test_blackout_hit_boundary_is_inclusive():
    scan = datetime(2026, 5, 22, 14, 0, 0)
    # Exactly +2 days with a window of 2 → inclusive hit.
    assert _earnings_blackout_hit(scan + timedelta(days=2), scan, blackout_days=2) is True
    # +3 days → just outside.
    assert _earnings_blackout_hit(scan + timedelta(days=3), scan, blackout_days=2) is False


# ── Parser: _parse_next_earnings (both yfinance calendar shapes) ──────────────


def test_parse_dict_calendar_recent_yfinance():
    now = datetime(2026, 5, 22)
    cal = {"Earnings Date": [dt.date(2026, 5, 25)], "Earnings High": [1.23]}
    got = _parse_next_earnings(cal, now=now)
    assert got is not None
    assert got.date() == dt.date(2026, 5, 25)


def test_parse_dict_picks_earliest_future():
    now = datetime(2026, 5, 22)
    cal = {"Earnings Date": [dt.date(2026, 6, 10), dt.date(2026, 5, 25)]}
    got = _parse_next_earnings(cal, now=now)
    assert got.date() == dt.date(2026, 5, 25)


def test_parse_dataframe_calendar_legacy_yfinance():
    now = datetime(2026, 5, 22)
    cal = pd.DataFrame(
        {0: [pd.Timestamp("2026-05-25"), 1.0], 1: [pd.Timestamp("2026-05-26"), 2.0]},
        index=["Earnings Date", "Earnings Average"],
    )
    got = _parse_next_earnings(cal, now=now)
    assert got is not None
    assert got.date() == dt.date(2026, 5, 25)


def test_parse_all_past_returns_most_recent():
    now = datetime(2026, 5, 22)
    cal = {"Earnings Date": [dt.date(2026, 5, 1), dt.date(2026, 5, 10)]}
    got = _parse_next_earnings(cal, now=now)
    assert got.date() == dt.date(2026, 5, 10)


def test_parse_empty_or_none_returns_none():
    assert _parse_next_earnings(None) is None
    assert _parse_next_earnings({}) is None
    assert _parse_next_earnings({"Earnings Date": []}) is None


# ── Integration helpers ────────────────────────────────────────────────────────


def _buy_strategy(ticker: str, dollars: float = 1_000.0):
    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker=ticker,
                side="BUY",
                target_shares=None,
                target_dollars=dollars,
                reason="analyze BUY",
                source="analyze_single",
            )
        ]

    return strat


def _relax_other_gates():
    """Turn off the gates that would otherwise mask Gate 6 in these tests."""
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("paper_min_holding_minutes", 0)


# ── Integration: run_scan + earnings gate ──────────────────────────────────────


def test_gate_blocks_buy_with_imminent_earnings(test_db, monkeypatch):
    """Earnings tomorrow → BUY blocked, blackout warning emitted."""
    from paper_trading import engine

    a = create_account(name="E", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("earnings_blackout_days", 2)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("AAPL"))

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: None,
        earnings_provider=lambda _t: utcnow_naive() + timedelta(days=1),
    )

    assert result is not None
    assert result.queued == 0
    assert result.filled == 0
    assert result.skipped >= 1
    assert any("blackout" in w for w in result.warnings)


def test_gate_allows_buy_with_distant_earnings(test_db, monkeypatch):
    """Earnings 10 days out, window=2 → BUY proceeds."""
    from paper_trading import engine

    a = create_account(name="E", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("earnings_blackout_days", 2)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="MSFT"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("MSFT"))

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"MSFT": 100.0},
        history_provider=lambda _t: None,
        earnings_provider=lambda _t: utcnow_naive() + timedelta(days=10),
    )

    assert result is not None
    assert result.queued == 1
    assert not any("blackout" in w for w in result.warnings)


def test_gate_fail_open_when_provider_raises(test_db, monkeypatch, caplog):
    """A provider that raises must NOT block — fail-open + warning logged."""
    from paper_trading import engine

    a = create_account(name="E", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("earnings_blackout_days", 2)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="NVDA"))

    def boom(_ticker):
        raise RuntimeError("yfinance calendar exploded")

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("NVDA"))

    with caplog.at_level(logging.WARNING):
        result = engine.run_scan(
            a.id,
            prices_provider=lambda _t: {"NVDA": 100.0},
            history_provider=lambda _t: None,
            earnings_provider=boom,
        )

    assert result is not None
    assert result.queued == 1  # not blocked
    assert not any("blackout" in w for w in result.warnings)
    assert any("earnings gate" in rec.message for rec in caplog.records)


def test_gate_disabled_with_zero_days(test_db, monkeypatch):
    """earnings_blackout_days=0 disables the gate even with imminent earnings."""
    from paper_trading import engine

    a = create_account(name="E", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("earnings_blackout_days", 0)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AMD"))

    # Provider should not even be consulted; make it explode if it is.
    def boom(_ticker):
        raise AssertionError("provider should not be called when gate is disabled")

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("AMD"))

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AMD": 100.0},
        history_provider=lambda _t: None,
        earnings_provider=boom,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("blackout" in w for w in result.warnings)


def test_atr_forced_sell_bypasses_earnings_gate(test_db, monkeypatch):
    """An ATR-reason SELL must fire even inside the earnings blackout window."""
    from paper_trading import engine

    a = create_account(name="E", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("earnings_blackout_days", 2)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="TSLA"))

    def atr_sell_strategy(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker="TSLA",
                side="SELL",
                target_shares=10.0,
                target_dollars=None,
                reason="atr_stop @ 90.00 ≤ 92.00 (entry 100.00 − 2.0×ATR 4.00)",
                source="atr_stop_gate",
                signal_score=1.0,
            )
        ]

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: atr_sell_strategy)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"TSLA": 90.0},
        history_provider=lambda _t: None,
        earnings_provider=lambda _t: utcnow_naive() + timedelta(days=1),
    )

    assert result is not None
    # ATR SELL bypasses the blackout → it gets queued, no blackout warning.
    assert result.queued == 1
    assert not any("blackout" in w for w in result.warnings)


def test_gate_blocks_strategy_sell_during_blackout(test_db, monkeypatch):
    """A *non-ATR* SELL is blocked during the earnings window."""
    from paper_trading import engine

    a = create_account(name="E", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("earnings_blackout_days", 2)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="GOOG"))

    def sell_strategy(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker="GOOG",
                side="SELL",
                target_shares=5.0,
                target_dollars=None,
                reason="analyze SELL (0.40)",
                source="analyze_single",
            )
        ]

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: sell_strategy)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"GOOG": 100.0},
        history_provider=lambda _t: None,
        earnings_provider=lambda _t: utcnow_naive() + timedelta(days=1),
    )

    assert result is not None
    assert result.queued == 0
    assert result.skipped >= 1
    assert any("blackout" in w for w in result.warnings)
