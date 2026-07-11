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

from types import SimpleNamespace

import pytest

from alerts.alert_manager import (
    AlertManager,
    alert_row_actions,
    alert_status,
)
from config.settings_manager import settings
from database.models import Alert, Portfolio, session_scope, utcnow_naive
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


# ── ALRT1: gestión (editar / pausar) + helpers puros ─────────────────────────


def _stub(is_active: bool, is_paused: bool):
    """Objeto mínimo para los helpers puros (sin DB ni ORM)."""
    return SimpleNamespace(is_active=is_active, is_paused=is_paused)


def test_update_alert_persists_and_rearms_even_a_triggered_one(portfolio_id):
    a = AlertManager.create_alert(portfolio_id, "mara", "BELOW", 14.0, "viejo")
    # Simular que ya se disparó.
    with session_scope() as s:
        row = s.query(Alert).filter(Alert.id == a.id).one()
        row.is_active = False
        row.triggered_at = utcnow_naive()

    updated = AlertManager.update_alert(
        a.id, ticker="aapl", alert_type="ABOVE", target_value=200.0, message="nuevo"
    )
    # Los 4 campos + normalización de ticker + re-armado.
    assert updated.ticker == "AAPL"
    assert updated.alert_type == "ABOVE"
    assert updated.target_value == 200.0
    assert updated.message == "nuevo"
    assert updated.is_active is True
    assert updated.triggered_at is None

    with session_scope() as s:
        row = s.query(Alert).filter(Alert.id == a.id).one()
        assert row.ticker == "AAPL"
        assert row.is_active is True
        assert row.triggered_at is None


def test_update_alert_missing_returns_none(portfolio_id):
    assert (
        AlertManager.update_alert(
            999999, ticker="AAPL", alert_type="ABOVE", target_value=1.0, message=""
        )
        is None
    )


def test_set_paused_toggles_and_is_idempotent(portfolio_id):
    a = AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)
    assert a.is_paused is False

    assert AlertManager.set_paused(a.id, True).is_paused is True
    assert AlertManager.set_paused(a.id, True).is_paused is True  # idempotente
    assert AlertManager.set_paused(a.id, False).is_paused is False
    with session_scope() as s:
        assert s.query(Alert).filter(Alert.id == a.id).one().is_paused is False


def test_check_alerts_does_not_evaluate_paused(portfolio_id, monkeypatch):
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)  # activa → dispara
    paused = AlertManager.create_alert(portfolio_id, "AAPL", "ABOVE", 200.0)
    AlertManager.set_paused(paused.id, True)

    priced: dict[str, int] = {}

    def _price(ticker):
        priced[ticker] = priced.get(ticker, 0) + 1
        return {"price": {"MARA": 13.0, "AAPL": 250.0}[ticker]}

    monkeypatch.setattr("alerts.alert_manager.get_current_price", _price)

    triggered = AlertManager(notifier=_RecordingNotifier()).check_alerts(portfolio_id)

    assert [a.ticker for a in triggered] == ["MARA"]  # solo la activa
    assert "AAPL" not in priced  # la pausada ni siquiera consulta precio
    with session_scope() as s:
        aapl = s.query(Alert).filter(Alert.ticker == "AAPL").one()
        assert aapl.is_active is True  # intacta
        assert aapl.triggered_at is None


def test_alert_status_maps_three_states():
    assert alert_status(_stub(is_active=True, is_paused=False)) == "activa"
    assert alert_status(_stub(is_active=True, is_paused=True)) == "pausada"
    assert alert_status(_stub(is_active=False, is_paused=False)) == "disparada"
    # Borde: disparada gana aunque quedara is_paused=True.
    assert alert_status(_stub(is_active=False, is_paused=True)) == "disparada"


def test_alert_row_actions_per_state():
    activa = alert_row_actions(_stub(True, False))
    assert activa["editar"] is True and activa["eliminar"] is True
    assert activa["pausar_visible"] is True
    assert activa["pausar_label"] == "Pausar"

    pausada = alert_row_actions(_stub(True, True))
    assert pausada["pausar_visible"] is True
    assert pausada["pausar_label"] == "Reanudar"

    disparada = alert_row_actions(_stub(False, False))
    assert disparada["pausar_visible"] is False  # nada que pausar
    assert disparada["editar"] is True and disparada["eliminar"] is True
