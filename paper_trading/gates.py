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
    """VESTIGIAL after Sprint 3 (2026-05-29) — see ``docs/sprint2_kill_criteria.md``.

    The wiring that called this function (``_select_uncorrelated`` in
    ``paper_trading.strategies`` and the harness's ``_build_correlation_filter``)
    was removed because attribution found the gate never rejected a candidate
    in any realistic setup — ``analyze_stacked`` with a 0.55 buy threshold
    produces 1-2 BUYs per step, never reaching the "candidates > slots"
    condition the gate was designed for.

    The function itself is preserved as pure math (no I/O, no settings): the
    next time a strategy generates many simultaneous BUYs and wants a
    correlation filter, wire this up again rather than rewrite the logic.

    Pick up to ``free_slots`` candidates skipping any whose mean correlation
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

# T09 active de-risking: partial-SELL trims emitted by the strategy layer carry
# this reason prefix. The engine treats them as risk-driven exits that bypass
# the min-holding gate, mirroring the ``atr_`` stance above.
VOL_TRIM_REASON_PREFIX = "vol_trim"


def is_vol_trim_reason(reason: str | None) -> bool:
    """True iff ``reason`` was produced by the T09 active-trim layer.

    Used by the engine to let a vol-overlay trim bypass the min-holding gate —
    de-risking an over-volatile book should not be blocked just because a
    position was opened recently (same rationale as ATR forced exits).
    """
    if not reason:
        return False
    return reason.startswith(VOL_TRIM_REASON_PREFIX)


# ── T6.4 score-hysteresis: edad mínima para SELLs de señal ───────────────────

# Validado en T6.1 (docs/exit_replay_t61_2026-06-10.md): los SELLs por señal a
# 1-3 días de edad regalan el rally que el modelo (label 5d) predice. La única
# variante pre-registrada que pasó kill criteria fue min-holding 3 días
# hábiles (+3.18 pts, DD ratio 0.92). SELLs de convicción alta de venta
# (score < bypass) ejecutan directo — cierra el follow-up "signal_score
# bypass"; exits de riesgo (atr_*, vol_trim) nunca pasan por acá.


def signal_sell_min_age_block(
    *,
    reason: str | None,
    signal_score: float | None,
    opened_at: "datetime | None",
    scan_at: datetime,
    min_age_bdays: int,
    bypass_score: float,
) -> str | None:
    """T6.4 — devuelve el motivo de bloqueo si el SELL de señal debe esperar.

    Bloquea un SELL cuando TODAS estas condiciones se cumplen:
      * ``min_age_bdays > 0`` (0 = gate apagado),
      * el reason NO es un exit de riesgo (``atr_*`` / ``vol_trim``),
      * hay ``signal_score`` (los rebalanceos/housekeeping van con None),
      * ``signal_score >= bypass_score`` (score bajo = convicción alta de
        venta → ejecuta directo),
      * la posición tiene menos de ``min_age_bdays`` días hábiles de edad
        (np.busday_count entre la fecha de apertura y la del scan).

    Devuelve None si el SELL puede ejecutar; si bloquea, devuelve el string
    de warning listo para loguear (mismo contrato que el resto de gates:
    el caller no re-deriva nada).
    """
    if min_age_bdays <= 0:
        return None
    if is_atr_forced_exit_reason(reason) or is_vol_trim_reason(reason):
        return None
    if signal_score is None:
        return None
    if signal_score < bypass_score:
        return None
    if opened_at is None:
        return None

    age_bdays = int(np.busday_count(opened_at.date(), scan_at.date()))
    if age_bdays >= min_age_bdays:
        return None
    return (
        f"SELL de señal bloqueado (T6.4 hysteresis): edad {age_bdays} días hábiles "
        f"< min {min_age_bdays} y score {signal_score:.2f} ≥ bypass {bypass_score:.2f}."
    )


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


# ── T10 ADV (average daily volume) liquidity cap ──────────────────────────────

# Default trailing window (sessions) for the ADV estimate. ~1 trading month.
DEFAULT_ADV_LOOKBACK_DAYS = 20


def recent_adv_dollars(
    history: "pd.DataFrame | None",
    lookback_days: int = DEFAULT_ADV_LOOKBACK_DAYS,
) -> float | None:
    """Average daily *dollar* volume over the last ``lookback_days`` sessions.

    ADV$ = mean(Close × Volume) across the trailing window. This is the
    realistic-fill anchor for the liquidity cap: we only assume we can absorb a
    fraction of a name's recent traded value.

    Returns ``None`` (caller fails open — no cap) when:
    * ``history`` is None or ``lookback_days <= 0``;
    * the frame lacks a ``Close`` or ``Volume`` column;
    * no finite, positive dollar-volume rows survive in the window.

    Never raises — any unexpected shape degrades to ``None``.
    """
    if history is None or lookback_days <= 0:
        return None
    try:
        if "Close" not in history.columns or "Volume" not in history.columns:
            return None
        tail = history.tail(lookback_days)
        dollar_vol = tail["Close"].astype(float) * tail["Volume"].astype(float)
        dollar_vol = dollar_vol[np.isfinite(dollar_vol)]
        if dollar_vol.empty:
            return None
        adv = float(dollar_vol.mean())
        return adv if np.isfinite(adv) and adv > 0 else None
    except Exception:
        return None


def adv_capped_notional(
    target_dollars: float,
    adv_dollars: float | None,
    cap_pct: float,
) -> tuple[float, bool]:
    """Cap a BUY notional at ``cap_pct`` of recent ADV$.

    Returns ``(capped_dollars, was_capped)``. ``cap_pct`` is a fraction in
    (0, 1] (e.g. 0.05 = 5 % of ADV). The order is left unchanged
    (``was_capped=False``) when:
    * the gate is disabled (``cap_pct <= 0``);
    * ADV is unknown or non-positive (``adv_dollars`` is None/≤0) — fail open;
    * the notional is non-finite or ≤0;
    * the order already fits under the ceiling.

    Otherwise the notional is trimmed down to ``cap_pct * adv_dollars`` and
    ``was_capped=True`` is returned so the caller can log the trim.
    """
    if cap_pct <= 0 or adv_dollars is None or adv_dollars <= 0:
        return target_dollars, False
    if not np.isfinite(target_dollars) or target_dollars <= 0:
        return target_dollars, False
    ceiling = cap_pct * adv_dollars
    if target_dollars <= ceiling:
        return target_dollars, False
    return ceiling, True


__all__ = [
    "ATR_EXIT_REASONS",
    "CorrelationSkip",
    "DEFAULT_ADV_LOOKBACK_DAYS",
    "DEFAULT_TRAIL_MIN_EXCESS_ATRS",
    "ReturnsProvider",
    "VOL_TRIM_REASON_PREFIX",
    "VolOverlayResult",
    "adv_capped_notional",
    "atr_exit_decision",
    "compute_vol_overlay",
    "is_atr_forced_exit_reason",
    "is_vol_trim_reason",
    "is_within_earnings_blackout",
    "recent_adv_dollars",
    "select_uncorrelated_picks",
    "signal_sell_min_age_block",
]
