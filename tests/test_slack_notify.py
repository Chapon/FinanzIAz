"""
Tests for Slack notifications on new BUY/SELL orders — engine roadmap T12.

The engine composes a per-scan summary of the orders it created and hands the
text to an injectable ``slack_notifier`` callable (same pattern as
``earnings_provider`` in T08), so these tests never touch the network.

Three layers are covered:
1. ``select_notifiable`` — the pending/filled/both filter (pure).
2. ``format_order_line`` / ``format_scan_summary`` — message building (pure).
3. ``run_scan`` — full integration via an injected recording notifier, gated
   by the ``slack_notifications_enabled`` / ``slack_notify_on`` settings, and
   fail-open when the notifier raises.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytest

from config.settings_manager import settings
from database.models import session_scope
from integrations.slack import (
    OrderNotice,
    format_order_line,
    format_scan_summary,
    select_notifiable,
)
from paper_trading.account import create_account
from paper_trading.models import PaperWatchlistItem
from paper_trading.strategies import TargetTrade


# ── Test doubles & helpers ──────────────────────────────────────────────────────


class _RecordingNotifier:
    """Injectable notifier that records every message it's handed."""

    def __init__(self, *, raises: bool = False) -> None:
        self.calls: list[str] = []
        self.raises = raises

    def __call__(self, text: str) -> bool:
        self.calls.append(text)
        if self.raises:
            raise RuntimeError("slack is down")
        return True


@pytest.fixture(autouse=True)
def _reset_slack_settings():
    """Keep Slack settings isolated per test (the manager is a global singleton)."""
    settings.set("slack_notifications_enabled", False)
    settings.set("slack_notify_on", "both")
    yield
    settings.set("slack_notifications_enabled", False)
    settings.set("slack_notify_on", "both")


def _relax_other_gates() -> None:
    """Turn off gates that would otherwise stop a trade from being created."""
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("paper_min_holding_minutes", 0)
    settings.set("earnings_blackout_days", 0)


def _buy_strategy(ticker: str, dollars: float = 1_000.0, score: float | None = 0.82):
    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker=ticker,
                side="BUY",
                target_shares=None,
                target_dollars=dollars,
                reason="analyze BUY",
                source="analyze_single",
                signal_score=score,
            )
        ]

    return strat


def _notice(**kw) -> OrderNotice:
    base = dict(
        account_name="Sim Principal",
        ticker="AAPL",
        side="BUY",
        status="pending",
        shares=12.0,
        price=190.5,
        dollars=2286.0,
        reason="analyze BUY",
        signal_score=0.82,
    )
    base.update(kw)
    return OrderNotice(**base)


# ── select_notifiable (pure filter) ─────────────────────────────────────────────


def test_select_notifiable_pending_only():
    notices = [_notice(status="pending"), _notice(status="filled", ticker="MSFT")]
    out = select_notifiable(notices, "pending")
    assert [n.ticker for n in out] == ["AAPL"]


def test_select_notifiable_filled_only():
    notices = [_notice(status="pending"), _notice(status="filled", ticker="MSFT")]
    out = select_notifiable(notices, "filled")
    assert [n.ticker for n in out] == ["MSFT"]


def test_select_notifiable_both():
    notices = [_notice(status="pending"), _notice(status="filled", ticker="MSFT")]
    out = select_notifiable(notices, "both")
    assert len(out) == 2


def test_select_notifiable_unknown_mode_defaults_to_both():
    notices = [_notice(status="pending"), _notice(status="filled")]
    assert len(select_notifiable(notices, "garbage")) == 2


# ── format_order_line / format_scan_summary (pure) ──────────────────────────────


def test_format_order_line_has_all_fields():
    line = format_order_line(_notice())
    assert "BUY AAPL" in line
    assert "12 sh" in line  # whole-share rendering
    assert "$190.50" in line
    assert "$2,286.00" in line
    assert "score 0.82" in line
    assert "analyze BUY" in line
    assert "[pending]" in line


def test_format_order_line_optional_fields_omitted():
    line = format_order_line(
        OrderNotice(
            account_name="A",
            ticker="GLD",
            side="SELL",
            status="filled",
            shares=None,
            price=None,
            dollars=None,
            reason=None,
            signal_score=None,
        )
    )
    assert "SELL GLD" in line
    assert "[filled]" in line
    assert "score" not in line  # no score → omitted


def test_format_scan_summary_empty_is_blank():
    assert format_scan_summary("Sim Principal", []) == ""


def test_format_scan_summary_lists_orders_and_account():
    msg = format_scan_summary(
        "Sim Principal",
        [_notice(ticker="AAPL"), _notice(ticker="MSFT", side="SELL", status="filled")],
        scan_at=datetime(2026, 5, 22, 16, 5),
        equity_after=51_234.0,
    )
    assert "Sim Principal" in msg
    assert "AAPL" in msg and "MSFT" in msg
    assert "2026-05-22 16:05" in msg
    assert "$51,234.00" in msg
    # One header + two order lines.
    assert msg.count("\n") == 2


# ── Integration: run_scan + injected notifier ───────────────────────────────────


def test_scan_sends_summary_when_enabled(test_db, monkeypatch):
    """Master switch on + a new pending order → exactly one summary message."""
    from paper_trading import engine

    a = create_account(name="Sim Principal", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("slack_notifications_enabled", True)
    settings.set("slack_notify_on", "both")

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("AAPL"))
    notifier = _RecordingNotifier()

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: None,
        slack_notifier=notifier,
    )

    assert result is not None
    assert result.queued == 1
    assert len(notifier.calls) == 1
    assert "AAPL" in notifier.calls[0]
    assert "Sim Principal" in notifier.calls[0]


def test_scan_does_not_send_when_disabled(test_db, monkeypatch):
    """Master switch off → notifier never called, even with a new order."""
    from paper_trading import engine

    a = create_account(name="Off", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("slack_notifications_enabled", False)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("AAPL"))
    notifier = _RecordingNotifier()

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: None,
        slack_notifier=notifier,
    )

    assert result is not None
    assert result.queued == 1
    assert notifier.calls == []


def test_scan_notify_on_filled_skips_pending_orders(test_db, monkeypatch):
    """notify_on='filled' + a manual (pending) order → no message."""
    from paper_trading import engine

    a = create_account(name="FilledOnly", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("slack_notifications_enabled", True)
    settings.set("slack_notify_on", "filled")

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("AAPL"))
    notifier = _RecordingNotifier()

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: None,
        slack_notifier=notifier,
    )

    assert result is not None
    assert result.queued == 1
    assert notifier.calls == []  # pending order doesn't match 'filled'


def test_scan_auto_fill_notifies_with_filled_status(test_db, monkeypatch):
    """An auto account that fills a BUY → one message tagged [filled]."""
    from paper_trading import engine

    a = create_account(name="Auto", initial_capital=10_000.0, mode="auto")
    _relax_other_gates()
    settings.set("slack_notifications_enabled", True)
    settings.set("slack_notify_on", "filled")

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("AAPL"))
    notifier = _RecordingNotifier()

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: None,
        slack_notifier=notifier,
    )

    assert result is not None
    assert result.filled == 1
    assert len(notifier.calls) == 1
    assert "[filled]" in notifier.calls[0]
    assert "AAPL" in notifier.calls[0]


def test_scan_fail_open_when_notifier_raises(test_db, monkeypatch, caplog):
    """A notifier that raises must NOT break the scan — fail-open + logged."""
    from paper_trading import engine

    a = create_account(name="Boom", initial_capital=10_000.0, mode="manual")
    _relax_other_gates()
    settings.set("slack_notifications_enabled", True)
    settings.set("slack_notify_on", "both")

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("AAPL"))
    notifier = _RecordingNotifier(raises=True)

    with caplog.at_level(logging.ERROR):
        result = engine.run_scan(
            a.id,
            prices_provider=lambda _t: {"AAPL": 100.0},
            history_provider=lambda _t: None,
            slack_notifier=notifier,
        )

    assert result is not None
    assert result.queued == 1  # scan completed normally
    assert len(notifier.calls) == 1  # it was called and blew up
    assert any("Slack notify" in rec.message for rec in caplog.records)


# ── Per-account opt-out (slack_notify flag, T12) ────────────────────────────────


def test_account_optout_suppresses_notification(test_db, monkeypatch):
    """Account with slack_notify=False → no message even when the global switch is on."""
    from paper_trading import engine

    a = create_account(
        name="Silenciada",
        initial_capital=10_000.0,
        mode="manual",
        slack_notify=False,
    )
    _relax_other_gates()
    settings.set("slack_notifications_enabled", True)
    settings.set("slack_notify_on", "both")

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("AAPL"))
    notifier = _RecordingNotifier()

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: None,
        slack_notifier=notifier,
    )

    assert result is not None
    assert result.queued == 1  # order still created
    assert notifier.calls == []  # but no Slack message for this account


def test_account_optin_still_notifies(test_db, monkeypatch):
    """Account with slack_notify=True (default) notifies normally."""
    from paper_trading import engine

    a = create_account(
        name="Ruidosa",
        initial_capital=10_000.0,
        mode="manual",
        slack_notify=True,
    )
    _relax_other_gates()
    settings.set("slack_notifications_enabled", True)
    settings.set("slack_notify_on", "both")

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("AAPL"))
    notifier = _RecordingNotifier()

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: None,
        slack_notifier=notifier,
    )

    assert result is not None
    assert len(notifier.calls) == 1
    assert "Ruidosa" in notifier.calls[0]
