"""Aviso Slack del outage de datos de Yahoo (NET1, pieza 3c).

Cuando el breaker de throttle escala a nivel ≥2 (outage sostenido) se manda UN
mensaje por incidente + uno al recuperarse, reusando la infra T12. Gated por
``slack_data_outage_enabled`` (default True), fail-open total. Reloj mockeado.
"""

from __future__ import annotations

from data import yahoo_finance as yfm
from integrations.slack import format_outage_message


class _Clock:
    def __init__(self, t0: float = 1000.0) -> None:
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _patch_clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(yfm.time, "monotonic", clock)
    yfm.reset_throttle()
    return clock


# ── Formatter puro ────────────────────────────────────────────────────────────


def test_format_outage_message_open_and_recovered():
    o = format_outage_message("open", minutes=6.0, level=2)
    assert "Yahoo" in o and "6" in o and "nivel 2" in o
    r = format_outage_message("recovered", minutes=97.0, level=0)
    assert "recuper" in r and "97" in r


def test_format_outage_message_unknown_kind_is_empty():
    assert format_outage_message("weird", minutes=1.0, level=1) == ""


# ── Hook points: un aviso por incidente al cruzar nivel 2 + uno al recuperarse ─


def test_outage_notified_once_at_level2_and_on_recovery(monkeypatch):
    clock = _patch_clock(monkeypatch)
    calls: list[tuple] = []
    monkeypatch.setattr(yfm, "_maybe_notify_outage", lambda kind, **kw: calls.append((kind, kw)))

    yfm._note_throttle()  # nivel 1 → sin aviso todavía
    assert calls == []

    clock.advance(91)
    yfm._note_throttle()  # nivel 2 → aviso "open" (una vez)
    assert len(calls) == 1 and calls[0][0] == "open"

    clock.advance(271)
    yfm._note_throttle()  # nivel 3 → NO re-avisa (uno por incidente)
    assert len(calls) == 1

    yfm._note_fetch_success()  # recuperación → aviso "recovered"
    assert len(calls) == 2 and calls[1][0] == "recovered"


def test_no_recovery_notify_if_never_reached_level2(monkeypatch):
    _patch_clock(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(yfm, "_maybe_notify_outage", lambda kind, **kw: calls.append(kind))

    yfm._note_throttle()  # nivel 1
    yfm._note_fetch_success()  # recuperó en nivel 1 → nunca se avisó apertura
    assert calls == []


# ── Flag gating + inyección de notifier + fail-open ───────────────────────────


def test_maybe_notify_outage_respects_flag_and_notifier(monkeypatch):
    from config.settings_manager import settings

    sent: list[str] = []
    monkeypatch.setattr(yfm, "_outage_notifier", lambda text: sent.append(text) or True)

    settings.set("slack_data_outage_enabled", True)
    yfm._maybe_notify_outage("open", minutes=6.0, level=2)
    assert len(sent) == 1 and "Yahoo" in sent[0]

    settings.set("slack_data_outage_enabled", False)
    yfm._maybe_notify_outage("open", minutes=6.0, level=2)
    assert len(sent) == 1  # flag OFF → no manda


def test_maybe_notify_outage_is_fail_open(monkeypatch):
    from config.settings_manager import settings

    def _boom(_text):
        raise RuntimeError("slack caído")

    settings.set("slack_data_outage_enabled", True)
    monkeypatch.setattr(yfm, "_outage_notifier", _boom)
    # No debe propagar la excepción (fail-open).
    yfm._maybe_notify_outage("recovered", minutes=10.0, level=0)
