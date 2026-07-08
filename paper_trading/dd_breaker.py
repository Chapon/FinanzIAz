"""
Account-level drawdown circuit breaker (R1 — pure detector).

No live desk lets the strategy keep buying into a deepening account drawdown:
the standard guardrail is to degrade (smaller size → exits-only → halt). This
module holds the **pure decision** — given the account's equity snapshots and
its current equity, is the account in a drawdown deep enough to arm the breaker?

Like the ATR stops, this guardrail does NOT depend on the signal having alpha:
it reacts to the account's own equity regime, complementing the static
``kill_only`` mode with a dynamic response. When armed, the consuming gate in
``run_scan`` suppresses **BUYs only** — SELLs / ATR-exits / signal exits always
keep running (the breaker never blocks a way out, same rule as the E1b screen).

Design (pre-registered 2026-07-08, see ``docs/dd_breaker_r1_2026-07-08.md``):

- The peak is measured over a **rolling window** (``window_days``), not the
  all-time high: a stale peak from months ago would keep the breaker armed over
  a drawdown the account already digested. The window ties it to the recent
  regime ("drawdown from the peak of the last N days").
- The current equity is a **peak candidate**: a fresh high today ⇒ drawdown 0,
  even though the current scan's snapshot isn't persisted yet when the gate runs.
- This module is pure (no DB, no network, no settings): the gate reads the
  snapshots and the master switch; the detector only does the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from database.models import utcnow_naive


@dataclass(frozen=True)
class DrawdownState:
    """The account's drawdown vs the rolling-window peak, and whether it arms.

    ``triggered`` reflects only the drawdown condition (``drawdown_pct >=
    threshold_pct``); it does NOT include the master switch — the gate combines
    this with ``paper_dd_breaker_enabled``.

    ``drawdown_pct`` is a non-negative fraction (0.095 = 9.5 %). ``peak_at`` is
    the snapshot time of the window peak, or ``None`` when the current equity is
    itself the peak (i.e. ``drawdown_pct == 0``).
    """

    triggered: bool
    current_equity: float
    peak_equity: float
    peak_at: datetime | None
    drawdown_pct: float
    threshold_pct: float
    window_days: int
    n_snapshots_in_window: int


def compute_drawdown_state(
    current_equity: float,
    snapshots: list[tuple[datetime, float]],
    *,
    threshold_pct: float,
    window_days: int,
    now: datetime | None = None,
) -> DrawdownState:
    """Pure drawdown decision over the rolling window.

    ``snapshots`` are ``(snapshot_at, total_equity)`` pairs (order irrelevant);
    typically the account's ``paper_equity_snapshots``. Only those with
    ``snapshot_at >= now - window_days`` count toward the peak, together with
    ``current_equity``. Rows with a ``None`` equity are ignored.

    Fails safe: a non-positive peak (no usable history, corrupt equity) yields
    ``drawdown_pct = 0`` and ``triggered = False`` — a data gap never arms the
    breaker on its own.
    """
    now = now or utcnow_naive()
    cutoff = now - timedelta(days=max(0, window_days))

    in_window = [
        (at, float(eq))
        for (at, eq) in snapshots
        if at is not None and eq is not None and at >= cutoff
    ]

    # Peak = highest equity in the window; current equity is also a candidate so
    # a brand-new high reads as drawdown 0 (the current scan is not snapshotted
    # yet when the gate runs).
    peak_equity = float(current_equity)
    peak_at: datetime | None = None
    for at, eq in in_window:
        if eq > peak_equity:
            peak_equity = eq
            peak_at = at

    if peak_equity <= 0:
        drawdown_pct = 0.0
    else:
        drawdown_pct = max(0.0, (peak_equity - current_equity) / peak_equity)

    triggered = peak_equity > 0 and drawdown_pct >= threshold_pct

    return DrawdownState(
        triggered=triggered,
        current_equity=float(current_equity),
        peak_equity=peak_equity,
        peak_at=peak_at,
        drawdown_pct=drawdown_pct,
        threshold_pct=float(threshold_pct),
        window_days=int(window_days),
        n_snapshots_in_window=len(in_window),
    )


def format_breaker_warning(state: DrawdownState) -> str:
    """Human-readable ES message for the scan warning / UI banner.

    Only meaningful when ``state.triggered``; the caller decides whether to show
    it. Kept here so the gate and the UI phrase it identically.
    """
    peak_txt = (
        f" (peak {state.peak_at:%Y-%m-%d})" if state.peak_at is not None else ""
    )
    return (
        f"Circuit breaker de drawdown ARMADO: caída {state.drawdown_pct * 100:.1f}% "
        f"desde el peak de {state.window_days}d{peak_txt} "
        f"(umbral {state.threshold_pct * 100:.1f}%). BUYs suprimidos; "
        f"stops y salidas siguen. Rearme manual."
    )
