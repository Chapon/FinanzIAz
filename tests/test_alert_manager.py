"""
Tests for AlertManager — price-alert checking + batched Slack notification (NOTIF1).

AlertManager had zero coverage before NOTIF1; this closes it. Everything runs
offline: the conftest blocks network and rebinds the DB to an in-memory SQLite,
and ``get_current_price`` is monkeypatched so no quote ever hits Yahoo.

Two layers:
1. ``format_alert_message`` — the pure batched formatter (0/1/N alerts).
2. ``check_alerts`` — ABOVE/BELOW triggering, skipping tickers with no price,
   and the exactly-once batched Slack notifier contract (fail-open + flag gate).
"""

from __future__ import annotations

import pytest

from alerts.alert_manager import AlertManager
from config.settings_manager import settings
from database.models import Alert, Portfolio, session_scope
from integrations.slack import AlertNotice, format_alert_message


class _RecordingNotifier:
    """Injectable notifier that records every batched message it's handed."""

    def __init__(self, *, raises: bool = False) -> None:
        self.calls: list[str] = []
        self.raises = raises

    def __call__(self, text: str) -> bool:
        self.calls.append(text)
        if self.raises:
            raise RuntimeError("slack is down")
        return True


def _prices(mapping):
    """Build a ``get_current_price`` replacement from a ``{ticker: price}`` map."""

    def _fn(ticker):
        if ticker in mapping:
            return {"price": mapping[ticker]}
        return None

    return _fn


@pytest.fixture
def portfolio_id(test_db):
    with session_scope() as s:
        p = Portfolio(name="Test PF")
        s.add(p)
        s.flush()
        return p.id


# ── format_alert_message (pure) ──────────────────────────────────────────────


def test_format_alert_message_empty():
    assert format_alert_message([]) == ""


def test_format_alert_message_single_with_message():
    text = format_alert_message([AlertNotice("MARA", "BELOW", 14.0, 13.40, "rebote")])
    lines = text.splitlines()
    assert lines[0] == "🔔 *FinanzIAs · Alerta de precio*"
    assert lines[1] == "MARA alcanzó $13.40 — objetivo BELOW $14.00 · rebote"


def test_format_alert_message_multiple_no_message():
    text = format_alert_message(
        [
            AlertNotice("MARA", "BELOW", 14.0, 13.40),
            AlertNotice("AAPL", "ABOVE", 200.0, 250.10),
        ]
    )
    lines = text.splitlines()
    assert len(lines) == 3  # header + 2 alert lines
    assert lines[1] == "MARA alcanzó $13.40 — objetivo BELOW $14.00"
    assert lines[2] == "AAPL alcanzó $250.10 — objetivo ABOVE $200.00"
    assert " · " not in lines[1]  # no trailing separator when message is empty


# ── check_alerts (integration on in-memory DB) ───────────────────────────────


def test_check_alerts_triggers_above_below_skips_missing(portfolio_id, monkeypatch):
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0, "rebote")
    AlertManager.create_alert(portfolio_id, "AAPL", "ABOVE", 200.0)
    AlertManager.create_alert(portfolio_id, "TSLA", "ABOVE", 300.0)  # no price → skip

    monkeypatch.setattr(
        "alerts.alert_manager.get_current_price",
        _prices({"MARA": 13.0, "AAPL": 250.0}),  # TSLA absent
    )
    notifier = _RecordingNotifier()
    triggered = AlertManager(notifier=notifier).check_alerts(portfolio_id)

    assert sorted(a.ticker for a in triggered) == ["AAPL", "MARA"]

    # Exactly one batched Slack message naming both fired tickers, not the skipped one.
    assert len(notifier.calls) == 1
    assert "MARA" in notifier.calls[0]
    assert "AAPL" in notifier.calls[0]
    assert "TSLA" not in notifier.calls[0]

    # DB: fired alerts deactivated + stamped; the missing-price one stays active.
    with session_scope() as s:
        by_ticker = {a.ticker: a for a in s.query(Alert).all()}
        assert by_ticker["MARA"].is_active is False
        assert by_ticker["MARA"].triggered_at is not None
        assert by_ticker["AAPL"].is_active is False
        assert by_ticker["TSLA"].is_active is True
        assert by_ticker["TSLA"].triggered_at is None


def test_check_alerts_no_trigger_does_not_notify(portfolio_id, monkeypatch):
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 10.0)  # 13 > 10 → no trigger
    monkeypatch.setattr(
        "alerts.alert_manager.get_current_price",
        _prices({"MARA": 13.0}),
    )
    notifier = _RecordingNotifier()
    triggered = AlertManager(notifier=notifier).check_alerts(portfolio_id)

    assert triggered == []
    assert notifier.calls == []  # nothing fired → no Slack call at all


def test_check_alerts_notifier_raises_is_fail_open(portfolio_id, monkeypatch):
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)
    monkeypatch.setattr(
        "alerts.alert_manager.get_current_price",
        _prices({"MARA": 13.0}),
    )
    notifier = _RecordingNotifier(raises=True)

    # A broken Slack must not raise into check_alerts...
    triggered = AlertManager(notifier=notifier).check_alerts(portfolio_id)
    assert [a.ticker for a in triggered] == ["MARA"]
    assert len(notifier.calls) == 1  # it was attempted

    # ...and the DB marking must still have committed (the POST runs post-commit).
    with session_scope() as s:
        marked = s.query(Alert).filter(Alert.ticker == "MARA").one()
        assert marked.is_active is False
        assert marked.triggered_at is not None


def test_check_alerts_flag_off_skips_notifier(portfolio_id, monkeypatch):
    settings.set("slack_price_alerts_enabled", False)
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)
    monkeypatch.setattr(
        "alerts.alert_manager.get_current_price",
        _prices({"MARA": 13.0}),
    )
    notifier = _RecordingNotifier()
    triggered = AlertManager(notifier=notifier).check_alerts(portfolio_id)

    # Still fires + marks in DB, just no Slack post.
    assert [a.ticker for a in triggered] == ["MARA"]
    assert notifier.calls == []
