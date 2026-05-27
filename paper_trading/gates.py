"""
Pure gate functions shared between the live engine and the Sprint-1 harness.

Why this module exists
----------------------
The four gates (T01 ATR stops, T08 earnings blackout, T09 correlation,
T10 portfolio-vol overlay) used to live inline in
``paper_trading/engine.py`` and ``paper_trading/strategies.py``. That worked
fine for production, but the new harness (Sprint 1) needs to apply the same
gates inside ``analysis/portfolio_backtest.py`` — if we left the logic
duplicated it would drift the moment anyone changed one side.

Design rules
------------
* **No side effects.** No DB, no settings read, no logger. Callers provide all
  knobs (cutoffs, multipliers, vol targets) explicitly.
* **No globals.** Every dependency is a function argument or a callable
  provider, so tests and the harness can swap implementations freely.
* **Return enough to log.** Where the live engine wants to record "T09 skipped
  AAPL avg_corr=0.71 > 0.60", the gate returns the avg_corr value; the caller
  formats it. Likewise ATR returns the trigger reason string so the engine can
  stamp ``PaperOrder.reason`` without re-deriving it.

Each public function has a unit test in ``tests/test_paper_gates.py``. The
existing engine/strategies behaviour-level tests stay untouched and serve as
regression guardrails for the refactor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import numpy as np
import pandas as pd

# ── T01 ATR stop / trail / take-profit gate ────────────────────────────────────

# Reasons emitted by ``atr_exit_decision``. Anything starting with ``atr_`` is
# treated as a forced exit by downstream code (min-holding bypass, etc.).
ATR_EXIT_REASONS: tuple[str, ...] = ("atr_stop", "atr_tp", "atr_trail")

# Trail safeguard: only fire the trailing stop once the high-water mark is
# strictly above entry by at least this many ATRs. Below the threshold, the
# trail collapses onto the stop-loss and would whipsaw on the first down tick.
DEFAULT_TRAIL_MIN_EXCESS_ATRS = 1.0


def is_atr_forced_exit_reason(reason: str | None) -> bool:
    """True iff ``reason`` was produced by :func:`atr_exit_decision`.

    Use this from the engine to decide whether a SELL bypasses the min-holding
    gate. Closed-market and other hard gates still apply regardless.
    """
    if not reason:
        return False
    return any(reason.startswith(prefix) for prefix in ATR_EXIT_REASONS)


def atr_exit_decision(
    *,
    current_price: float,
    avg_cost: float,
    high_water_mark: float | None,
    atr_value: float,
    stop_mult: float,
    tp_mult: float,
    trail_enabled: bool,
    trail_min_excess_atrs: float = DEFAULT_TRAIL_MIN_EXCESS_ATRS,
) -> tuple[str | None, float | None]:
    """Decide whether an open position should be force-closed by the ATR gate.

    Returns ``(reason, trigger_level)``. ``reason`` is ``None`` when no
    threshold fired; otherwise it is one of ``atr_stop``, ``atr_trail``,
    ``atr_tp`` (prefixed with the human description used in
    ``PaperOrder.reason``).

    Evaluation order: hard stop → trail → take-profit. Only the first match
    wins, matching the live engine's behaviour.

    The trailing stop is suppressed unless the high-water mark is strictly
    above ``avg_cost`` by at least ``trail_min_excess_atrs * atr_value`` —
    without this, the trail duplicates the hard stop and noise-trips
    immediately after entry.

    All numeric inputs are assumed to be positive floats. Returns
    ``(None, None)`` when any input is non-finite, ≤0, or otherwise
    degenerate; this matches the engine's defensive skip behaviour.
    """
    if not all(np.isfinite([current_price, avg_cost, atr_value])):
        return None, None
    if current_price <= 0 or avg_cost <= 0 or atr_value <= 0:
        return None, None
    if stop_mult < 0 or tp_mult < 0:
        return None, None

    hwm = float(high_water_mark) if high_water_mark is not None else float(avg_cost)

    stop_level = avg_cost - stop_mult * atr_value
    tp_level = avg_cost + tp_mult * atr_value
    trail_level = hwm - stop_mult * atr_value if trail_enabled else None

    if stop_level > 0 and current_price <= stop_level:
        reason = (
            f"atr_stop @ {current_price:.2f} ≤ {stop_level:.2f} "
            f"(entry {avg_cost:.2f} − {stop_mult:.1f}×ATR {atr_value:.2f})"
        )
        return reason, stop_level

    if (
        trail_enabled
        and trail_level is not None
        and trail_level > 0
        and current_price <= trail_level
        and hwm > avg_cost + trail_min_excess_atrs * atr_value
    ):
        reason = (
            f"atr_trail @ {current_price:.2f} ≤ {trail_level:.2f} "
            f"(peak {hwm:.2f} − {stop_mult:.1f}×ATR {atr_value:.2f})"
        )
        return reason, trail_level

    if tp_level > 0 and current_price >= tp_level:
        reason = (
            f"atr_tp @ {current_price:.2f} ≥ {tp_level:.2f} "
            f"(entry {avg_cost:.2f} + {tp_mult:.1f}×ATR {atr_value:.2f})"
        )
        return reason, tp_level

    return None, None


# ── T08 earnings blackout gate ────────────────────────────────────────────────


def is_within_earnings_blackout(
    earnings_date: datetime | None,
    scan_at: datetime,
    blackout_days: int,
) -> bool:
    """True iff ``earnings_date`` falls within ±``blackout_days`` of ``scan_at``.

    Compared at calendar-day granularity so an earnings event scheduled for
    "tomorrow" trips a ±1 window regardless of the intraday scan time.
    Returns False when there is no known date or the gate is disabled
    (``blackout_days <= 0``).
    """
    if earnings_date is None or blackout_days <= 0:
        return False
    delta_days = (earnings_date.date() - scan_at.date()).days
    return abs(delta_days) <= blackout_days


# ── T09 correlation gate ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class CorrelationSkip:
    """One candidate rejected by :func:`select_uncorrelated_picks`."""
    ticker: str
    avg_correlation: float


ReturnsProvider = Callable[[str], "pd.Series | None"]


def select_uncorrelated_picks(
    ordered_candidates: list[str],
    held: list[str],
    free_slots: int,
    returns_provider: ReturnsProvider,
    threshold: float,
    *,
    mean_corr_fn: Callable[["pd.Series", list["pd.Series"]], float | None] | None = None,
) -> tuple[list[str], list[CorrelationSkip]]:
    """Pick up to ``free_slots`` candidates skipping any whose mean correlation
    with the active book exceeds ``threshold``.

    The "active book" is the union of currently held names and candidates
    already accepted in the same call — comparing only against pre-existing
    holdings would allow two highly-correlated new entries through together.

    A candidate with no usable history, or where the mean correlation can't be
    computed, is admitted (the gate never blocks on missing data). Each
    skipped pick is returned in ``skips`` with its measured correlation so the
    caller can log it.

    ``threshold >= 1.0`` short-circuits the gate entirely (returns the first
    ``free_slots`` candidates unmodified, no correlation work done).

    ``mean_corr_fn`` is injected so callers can supply their own implementation
    (in production, ``analysis.portfolio_risk.mean_correlation``; tests can
    pass a stub).
    """
    if free_slots <= 0:
        return [], []
    if threshold >= 1.0:
        return ordered_candidates[:free_slots], []

    if mean_corr_fn is None:
        from analysis.portfolio_risk import mean_correlation as _mc
        mean_corr_fn = _mc

    accepted: list[str] = []
    skipped: list[CorrelationSkip] = []
    for t in ordered_candidates:
        if len(accepted) >= free_slots:
            break
        cand_ret = returns_provider(t)
        compare_to = held + accepted
        if cand_ret is None or cand_ret.empty or not compare_to:
            accepted.append(t)
            continue
        held_rets = [
            r for h in compare_to
            if (r := returns_provider(h)) is not None and not r.empty
        ]
        avg = mean_corr_fn(cand_ret, held_rets) if held_rets else None
        if avg is not None and avg > threshold:
            skipped.append(CorrelationSkip(ticker=t, avg_correlation=float(avg)))
            continue
        accepted.append(t)
    return accepted, skipped


# ── T10 portfolio volatility overlay ──────────────────────────────────────────


@dataclass(frozen=True)
class VolOverlayResult:
    """Outcome of :func:`compute_vol_overlay`. ``factor < 1.0`` means the
    overlay engaged and the caller should multiply the picks' dollar map by it.
    ``sigma`` is the annualised σ of the combined (held + picks) book."""
    factor: float
    sigma: float | None
    scaled_weights: dict[str, float]


def compute_vol_overlay(
    combined_weights: dict[str, float],
    returns_df: "pd.DataFrame | None",
    vol_target_annual: float,
    *,
    apply_fn: Callable | None = None,
) -> VolOverlayResult:
    """Compute the T10 portfolio-vol overlay factor for a candidate book.

    ``combined_weights`` is the union of currently-held weights (not being
    force-sold) and the new picks. ``returns_df`` is the aligned daily-returns
    frame for those tickers. ``vol_target_annual`` is the annualised σ ceiling
    (≤ 0 disables — the function returns ``factor=1.0`` immediately).

    Returns a :class:`VolOverlayResult` with the computed factor, the
    annualised σ of the book, and the scaled weights map. The caller is
    responsible for applying the factor to its picks' dollar map; this gate
    does not mutate anything.

    ``apply_fn`` is injected so callers can swap the implementation in tests.
    In production it is ``analysis.portfolio_risk.apply_portfolio_vol_overlay``.
    """
    if vol_target_annual <= 0 or not combined_weights:
        return VolOverlayResult(factor=1.0, sigma=None, scaled_weights=dict(combined_weights))

    if apply_fn is None:
        from analysis.portfolio_risk import apply_portfolio_vol_overlay as apply_fn

    scaled, sigma, factor = apply_fn(combined_weights, returns_df, vol_target_annual)
    return VolOverlayResult(
        factor=float(factor),
        sigma=(float(sigma) if sigma is not None else None),
        scaled_weights=dict(scaled),
    )


__all__ = [
    "ATR_EXIT_REASONS",
    "CorrelationSkip",
    "DEFAULT_TRAIL_MIN_EXCESS_ATRS",
    "ReturnsProvider",
    "VolOverlayResult",
    "atr_exit_decision",
    "compute_vol_overlay",
    "is_atr_forced_exit_reason",
    "is_within_earnings_blackout",
    "select_uncorrelated_picks",
]
