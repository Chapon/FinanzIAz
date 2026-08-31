"""
Slack notifications for new paper-trading orders (engine roadmap T12).

Design
------
The engine (``paper_trading.engine.run_scan``) composes a *per-scan summary*
of the new orders it generated and hands the text to an **injectable
notifier callable**, mirroring the ``prices_provider`` / ``earnings_provider``
pattern already used in the engine. That makes unit tests run without ever
touching the network — they inject a mock notifier that just records the text.

Delivery uses the **Slack Web API** (``chat.postMessage``) with a **bot token**
read from the ``SLACK_BOT_TOKEN`` environment variable. The token is *never*
hard-coded, committed, or stored in ``settings.json`` — only the non-secret
channel id lives in settings (or the ``SLACK_CHANNEL`` env var). The master
switch is the ``slack_notifications_enabled`` setting and ``slack_notify_on``
∈ {pending, filled, both} selects which orders are worth a message.

Everything here is **fail-open**: a missing token, a network error, or a
non-OK Slack response logs a warning and returns ``False`` — it must never
raise into the scan's critical path (a broken Slack must not stop trading).

Public surface
--------------
``OrderNotice``          — session-detached snapshot of one new order.
``select_notifiable``    — filter notices by the ``slack_notify_on`` mode.
``format_order_line``    — one human line for a single order (pure).
``format_scan_summary``  — the full per-scan message (pure).
``post_to_slack``        — the network boundary (fail-open).
``default_notifier``     — reads settings + env, posts to Slack.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

# A notifier takes the composed message text and delivers it somewhere,
# returning True on success. The engine injects a mock in tests.
SlackNotifier = Callable[[str], bool]

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
SLACK_TOKEN_ENV = "SLACK_BOT_TOKEN"
SLACK_CHANNEL_ENV = "SLACK_CHANNEL"
_HTTP_TIMEOUT_SECONDS = 5.0

# Allowed values for the ``slack_notify_on`` setting.
NOTIFY_PENDING = "pending"
NOTIFY_FILLED = "filled"
NOTIFY_BOTH = "both"
NOTIFY_ON_CHOICES = (NOTIFY_PENDING, NOTIFY_FILLED, NOTIFY_BOTH)


def _log():
    """Lazy logger import — avoids pulling logging_config at module import."""
    from config.logging_config import get_logger

    return get_logger(__name__)


# ── Data shape ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrderNotice:
    """
    A lightweight, session-detached snapshot of one new order, captured by the
    engine while the ORM object is still attached. Plain values only, so the
    message can be built safely *after* the DB transaction closes.
    """

    account_name: str
    ticker: str
    side: str  # "BUY" | "SELL"
    status: str  # "pending" | "filled"
    shares: float | None = None
    price: float | None = None
    dollars: float | None = None
    reason: str | None = None
    signal_score: float | None = None


# ── Filtering ──────────────────────────────────────────────────────────────────


def select_notifiable(
    notices: Iterable[OrderNotice],
    notify_on: str,
) -> list[OrderNotice]:
    """
    Keep only the notices that match the ``slack_notify_on`` mode.

    - ``"pending"`` → only queued orders (manual mode).
    - ``"filled"``  → only executed orders (auto mode / approved).
    - ``"both"``    → everything (default).

    An unknown mode is treated as ``"both"`` (fail-open: notify rather than
    silently swallow).
    """
    notices = list(notices)
    if notify_on == NOTIFY_PENDING:
        return [n for n in notices if n.status == "pending"]
    if notify_on == NOTIFY_FILLED:
        return [n for n in notices if n.status == "filled"]
    return notices


# ── Formatting (pure, fully unit-testable) ───────────────────────────────────────


def _fmt_shares(shares: float | None) -> str:
    if shares is None:
        return "?"
    # Whole-share counts are the common case; show integers cleanly.
    if abs(shares - round(shares)) < 1e-9:
        return f"{round(shares)}"
    return f"{shares:.4f}"


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "?"
    return f"${value:,.2f}"


def format_order_line(notice: OrderNotice) -> str:
    """
    One line describing a single order, e.g.::

        BUY AAPL — 12 sh @ $190.50 (~$2,286.00) · score 0.82 · analyze BUY [pending]

    Shares/price/dollars/score are all optional and rendered only when known.
    """
    parts: list[str] = [f"{notice.side} {notice.ticker}"]

    detail = f"{_fmt_shares(notice.shares)} sh"
    if notice.price is not None:
        detail += f" @ {_fmt_money(notice.price)}"
    if notice.dollars is not None:
        detail += f" (~{_fmt_money(notice.dollars)})"
    parts.append(detail)

    tail: list[str] = []
    if notice.signal_score is not None:
        tail.append(f"score {notice.signal_score:.2f}")
    if notice.reason:
        tail.append(str(notice.reason))

    line = " — ".join(parts)
    if tail:
        line += " · " + " · ".join(tail)
    line += f" [{notice.status}]"
    return line


def format_scan_summary(
    account_name: str,
    notices: Sequence[OrderNotice],
    *,
    scan_at: datetime | None = None,
    equity_after: float | None = None,
) -> str:
    """
    The full per-scan message: a header line naming the account (and optionally
    the scan time / equity) followed by one line per order. Returns ``""`` when
    there are no notices, so the engine can use truthiness to decide whether to
    send anything at all.
    """
    notices = list(notices)
    if not notices:
        return ""

    n = len(notices)
    when = f" · {scan_at:%Y-%m-%d %H:%M}" if scan_at is not None else ""
    plural = "orden" if n == 1 else "órdenes"
    header = f"*FinanzIAs · {account_name}*{when} — {n} nueva{'' if n == 1 else 's'} {plural}"
    if equity_after is not None:
        header += f" · equity {_fmt_money(equity_after)}"

    lines = [header]
    lines.extend(f"• {format_order_line(notice)}" for notice in notices)
    return "\n".join(lines)


# ── Data-outage alert (NET1, pieza 3c) ───────────────────────────────────────


def format_outage_message(kind: str, *, minutes: float, level: int) -> str:
    """Mensaje de outage de datos de Yahoo (NET1). Puro / testeable.

    ``kind`` ∈ {"open", "recovered"}. Un kind desconocido devuelve ``""`` (mismo
    contrato que ``format_scan_summary``: el caller usa la truthiness para decidir
    si manda algo).
    """
    if kind == "open":
        return (
            f"⚠️ *FinanzIAs · Yahoo sin responder* hace ~{minutes:.0f} min "
            f"(nivel {level}) — precios congelados, stops no actualizados. "
            "El breaker reintenta con backoff."
        )
    if kind == "recovered":
        return f"✅ *FinanzIAs · Yahoo se recuperó* tras ~{minutes:.0f} min — precios al día."
    return ""


# ── Price alerts (NOTIF1) ────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlertNotice:
    """
    Session-detached snapshot of one price alert that fired in a single
    ``AlertManager.check_alerts`` pass. Plain values only, captured while the
    ORM object is still attached, so the batched Slack message can be built
    *after* the DB transaction closes.
    """

    ticker: str
    alert_type: str  # "ABOVE" | "BELOW"
    target_value: float
    current_price: float
    message: str = ""


def format_alert_message(triggered: Sequence[AlertNotice]) -> str:
    """
    The batched price-alert message: a header followed by one line per fired
    alert, e.g.::

        🔔 *FinanzIAs · Alerta de precio*
        MARA alcanzó $13.40 — objetivo BELOW $14.00 · rebote

    Returns ``""`` for an empty list (same contract as ``format_scan_summary``:
    the caller uses truthiness to decide whether to send anything).
    """
    triggered = list(triggered)
    if not triggered:
        return ""

    lines = ["🔔 *FinanzIAs · Alerta de precio*"]
    for a in triggered:
        line = (
            f"{a.ticker} alcanzó {_fmt_money(a.current_price)} — "
            f"objetivo {a.alert_type} {_fmt_money(a.target_value)}"
        )
        if a.message:
            line += f" · {a.message}"
        lines.append(line)
    return "\n".join(lines)


# ── Network boundary (fail-open) ─────────────────────────────────────────────────


def _resolve_token(token: str | None) -> str | None:
    return token or os.environ.get(SLACK_TOKEN_ENV) or None


def _resolve_channel(channel: str | None) -> str | None:
    if channel:
        return channel
    env_channel = os.environ.get(SLACK_CHANNEL_ENV)
    if env_channel:
        return env_channel
    try:
        from config.settings_manager import settings

        configured = settings.get("slack_channel", "")
    except Exception:
        configured = ""
    return configured or None


def post_to_slack(
    text: str,
    *,
    channel: str | None = None,
    token: str | None = None,
) -> bool:
    """
    POST ``text`` to Slack via ``chat.postMessage``. Returns True on success.

    Fail-open in every branch: a missing token/channel, an HTTP error, or a
    non-OK Slack payload logs a warning and returns False — it never raises.
    The bot token comes from the ``SLACK_BOT_TOKEN`` env var unless passed
    explicitly; it is never read from settings.json.
    """
    if not text:
        return False

    resolved_token = _resolve_token(token)
    resolved_channel = _resolve_channel(channel)
    if not resolved_token or not resolved_channel:
        _log().warning(
            "Slack notify: missing %s or channel — skipping send (fail-open).",
            SLACK_TOKEN_ENV,
        )
        return False

    try:
        import requests

        resp = requests.post(
            SLACK_POST_MESSAGE_URL,
            headers={
                "Authorization": f"Bearer {resolved_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"channel": resolved_channel, "text": text},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        payload = resp.json()
        if not payload.get("ok", False):
            _log().warning(
                "Slack notify: API returned not-ok (error=%s).",
                payload.get("error", "unknown"),
            )
            return False
        return True
    except Exception:
        _log().exception("Slack notify: send failed (fail-open, scan unaffected).")
        return False


def default_notifier(text: str) -> bool:
    """
    Default ``SlackNotifier`` used by the engine when none is injected. Reads
    the channel from settings / env and the token from env, then posts. Pure
    pass-through to :func:`post_to_slack`, kept separate so the engine can hold
    a stable callable reference and tests can swap it out.
    """
    return post_to_slack(text)
