"""
Signal → target-trade generators for paper trading.

Each strategy is a function with the uniform signature::

    generate_trades(account, watchlist, positions, prices, history_provider)
        -> list[TargetTrade]

``TargetTrade`` is the intent handed to the engine; the engine decides
whether to fill it immediately (auto mode) or queue it as a pending
``PaperOrder`` (manual mode).

Two strategies are provided:

1. ``analyze_single`` — each ticker evaluated in isolation via
   ``analysis.technical.analyze``. Simple, per-position logic, sized to
   equal-weight slots of cash.

2. ``portfolio_engine`` — replicates one step of the portfolio-backtest
   loop using the account's ``allocation_mode``, ``max_positions``,
   drift threshold and monthly rebalance flag. Fully coherent with the
   historical back-tester.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from analysis.portfolio_backtest import (
    AllocationMode,
    _compute_target_weights,
    _realized_vol,
)
from analysis.portfolio_risk import (
    daily_returns,
    mean_correlation,
)
from config.logging_config import get_logger
from config.settings_manager import settings
from paper_trading.models import PaperAccount, PaperPosition

# Allocation modes whose sizing depends on per-name volatility (and, for
# Kelly, a calibrated probability) rather than a flat cash split. T06.
_VOL_SIZED_MODES = {AllocationMode.VOL_TARGET.value, AllocationMode.KELLY_FRACTIONAL.value}


def _sizing_params() -> dict[str, float]:
    """Read the user-tunable T06 sizing knobs from settings."""
    return {
        "kelly_fraction": float(settings.get("kelly_fraction")),
        "vol_target_annual": float(settings.get("vol_target_annual")),
        "max_weight": float(settings.get("max_position_weight")),
    }


def _calibrated_prob(ml_probability: float | None) -> float | None:
    """Return ml_probability only when it is a real, finite calibrated value."""
    if ml_probability is None or not np.isfinite(ml_probability):
        return None
    return float(ml_probability)


# ── Value type ────────────────────────────────────────────────────────────────


@dataclass
class TargetTrade:
    ticker: str
    side: str  # "BUY" | "SELL"
    target_shares: float | None  # for SELL: total shares to close; for BUY: None if using target_dollars
    target_dollars: float | None  # for BUY: dollar amount; for SELL: None or estimated proceeds
    reason: str
    source: str  # strategy name ("analyze_single" | "portfolio_engine")
    signal_score: float | None = None  # conviction in [0,1]; None for rebalance trades

    def __repr__(self) -> str:
        dollars = f"${self.target_dollars:,.2f}" if self.target_dollars is not None else "—"
        shares = f"{self.target_shares:.4f}" if self.target_shares is not None else "—"
        score = f" score={self.signal_score:.2f}" if self.signal_score is not None else ""
        return f"<TargetTrade({self.side} {self.ticker} {shares}sh / {dollars}{score} · {self.reason})>"


HistoryProvider = Callable[[str], pd.DataFrame | None]


# ── Correlation gate (T09) ─────────────────────────────────────────────────────


def _corr_threshold() -> float:
    """Mean-correlation ceiling for the slot-filling gate (1.0 = disabled)."""
    return float(settings.get("max_avg_correlation"))


def _returns_for(
    ticker: str,
    history_provider: HistoryProvider,
    cache: dict[str, pd.Series | None],
) -> pd.Series | None:
    """Memoised 60-day daily returns for a ticker (None if no usable history)."""
    if ticker in cache:
        return cache[ticker]
    df = history_provider(ticker)
    if df is None or df.empty or "Close" not in df.columns:
        cache[ticker] = None
        return None
    r = daily_returns(df["Close"].astype(float))
    cache[ticker] = r if not r.empty else None
    return cache[ticker]


def _select_uncorrelated(
    ordered_candidates: list[str],
    held: list[str],
    free_slots: int,
    history_provider: HistoryProvider,
    threshold: float,
) -> list[str]:
    """Pick up to ``free_slots`` candidates in priority order, skipping any whose
    mean 60-day return correlation with the active book — the already-held names
    *plus* the candidates already accepted this scan — exceeds ``threshold``.

    Comparing against the names accepted earlier in the same scan (not just the
    pre-existing positions) is what actually prevents a freshly-built book from
    being five copies of the same trade; correlating only against current
    holdings would happily admit two highly-correlated new entries at once.

    A candidate with no usable history, or for which no correlation can be
    computed, is admitted (the gate never blocks on missing data). Each skip is
    logged. ``threshold >= 1.0`` short-circuits the gate entirely.
    """
    if free_slots <= 0:
        return []
    if threshold >= 1.0:
        return ordered_candidates[:free_slots]

    cache: dict[str, pd.Series | None] = {}
    log = get_logger(__name__)
    accepted: list[str] = []
    for t in ordered_candidates:
        if len(accepted) >= free_slots:
            break
        cand_ret = _returns_for(t, history_provider, cache)
        compare_to = held + accepted
        if cand_ret is None or cand_ret.empty or not compare_to:
            accepted.append(t)
            continue
        held_rets = [
            r
            for h in compare_to
            if (r := _returns_for(h, history_provider, cache)) is not None and not r.empty
        ]
        avg = mean_correlation(cand_ret, held_rets)
        if avg is not None and avg > threshold:
            log.info("%s skipped: avg_corr=%.2f > %.2f", t, avg, threshold)
            continue
        accepted.append(t)
    return accepted


# ── Strategy 1: analyze_single ────────────────────────────────────────────────


def _default_strength(signal: str, ml_probability: float | None) -> float:
    """Conviction score in [0,1] for ranking BUY candidates."""
    if ml_probability is not None and np.isfinite(ml_probability):
        return float(max(0.0, min(1.0, ml_probability)))
    return {"BUY": 1.0, "HOLD": 0.5, "SELL": 0.0}.get(signal, 0.0)


def generate_trades_analyze_single(
    account: PaperAccount,
    watchlist: list[str],
    positions: list[PaperPosition],
    prices: dict[str, float],
    history_provider: HistoryProvider,
) -> list[TargetTrade]:
    """
    Run ``analyze()`` on every watchlist ticker and every open position.

    Rules:
      * Any open position whose overall_signal is SELL  → full-shares SELL.
      * Any candidate (not yet held) whose overall_signal is BUY
        → enters a ranked list; top (max_positions − held_after_sells)
          candidates are bought with equal slices of remaining cash.
    """
    from analysis.technical import analyze

    source = "analyze_single"
    trades: list[TargetTrade] = []

    held_tickers = {p.ticker for p in positions}
    # Positions with available history get evaluated for SELL; otherwise held.
    forced_exits: set[str] = set()

    for pos in positions:
        df = history_provider(pos.ticker)
        if df is None or df.empty:
            continue
        res = analyze(pos.ticker, df)
        if res is None:
            continue
        if res.overall_signal == "SELL":
            score = _default_strength("SELL", res.ml_probability)
            trades.append(
                TargetTrade(
                    ticker=pos.ticker,
                    side="SELL",
                    target_shares=float(pos.shares),
                    target_dollars=None,
                    reason=f"analyze SELL ({res.ml_probability or 0:.2f})",
                    source=source,
                    signal_score=score,
                )
            )
            forced_exits.add(pos.ticker)

    # Candidates for BUY — ranked by conviction. We also stash each candidate's
    # realised vol and calibrated probability so the vol-target / Kelly sizing
    # modes (T06) have what they need without re-running analyze().
    ranked: list[tuple[float, str]] = []
    cand_vol: dict[str, float] = {}
    cand_prob: dict[str, float | None] = {}
    for t in watchlist:
        if t in held_tickers and t not in forced_exits:
            continue
        df = history_provider(t)
        if df is None or df.empty:
            continue
        res = analyze(t, df)
        if res is None:
            continue
        if res.overall_signal == "BUY":
            strength = _default_strength("BUY", res.ml_probability)
            ranked.append((strength, t))
            cand_vol[t] = _realized_vol(df["Close"].astype(float)) if "Close" in df.columns else 0.0
            cand_prob[t] = _calibrated_prob(res.ml_probability)

    ranked.sort(reverse=True)
    scores = {t: s for s, t in ranked}

    # Slots available after processing forced exits
    held_after = held_tickers - forced_exits
    free_slots = max(0, account.max_positions - len(held_after))
    # Correlation gate (T09): walk the ranked list and skip candidates too
    # correlated with the active book before they consume a slot.
    picks = _select_uncorrelated(
        [t for _, t in ranked],
        list(held_after),
        free_slots,
        history_provider,
        _corr_threshold(),
    )

    if not picks:
        return trades

    # Size: equal slices of (cash + proceeds from any forced sells we estimate)
    est_proceeds = 0.0
    for pos in positions:
        if pos.ticker in forced_exits:
            px = prices.get(pos.ticker, pos.avg_cost)
            est_proceeds += pos.shares * (px or pos.avg_cost) * (1 - account.commission)
    available = account.cash + est_proceeds
    if available <= 0:
        return trades

    # ── Vol-target / Kelly sizing (T06) ───────────────────────────────────────
    # These modes size by per-name volatility (and, for Kelly, calibrated
    # probability) instead of an equal cash slice. Weights are computed against
    # total portfolio value, converted to dollars, then capped so the BUYs
    # never spend more than the available cash this scan.
    if account.allocation_mode in _VOL_SIZED_MODES:
        mode = AllocationMode(account.allocation_mode)
        pos_value = 0.0
        for p in positions:
            px = prices.get(p.ticker, p.avg_cost)
            pos_value += p.shares * (px or p.avg_cost)
        portfolio_value = float(account.cash + pos_value)

        weights = _compute_target_weights(
            picks,
            {t: scores.get(t, 0.0) for t in picks},
            {t: cand_vol.get(t, 0.0) for t in picks},
            mode,
            probs={t: cand_prob.get(t) for t in picks},
            **_sizing_params(),
        )
        dollars = {t: weights.get(t, 0.0) * portfolio_value for t in picks}
        total = sum(dollars.values())
        if total > available > 0:
            scale = available / total
            dollars = {t: v * scale for t, v in dollars.items()}

        for t in picks:
            d = dollars.get(t, 0.0)
            if d <= 0:  # Kelly may skip a pick (no calibrated prob / no edge)
                continue
            trades.append(
                TargetTrade(
                    ticker=t,
                    side="BUY",
                    target_shares=None,
                    target_dollars=float(d),
                    reason=f"analyze BUY ({account.allocation_mode})",
                    source=source,
                    signal_score=scores.get(t),
                )
            )
        return trades

    # ── Default sizing: fixed amount or equal cash slice ──────────────────────
    if account.allocation_mode == "fixed_amount":
        target_per = float(account.fixed_amount)
        total = target_per * len(picks)
        if total > available:
            target_per = available / len(picks)  # scale down
    else:
        target_per = available / len(picks)

    for t in picks:
        trades.append(
            TargetTrade(
                ticker=t,
                side="BUY",
                target_shares=None,
                target_dollars=float(target_per),
                reason="analyze BUY",
                source=source,
                signal_score=scores.get(t),
            )
        )

    return trades


# ── Strategy 2: portfolio_engine ──────────────────────────────────────────────


def _signal_for(ticker: str, df: pd.DataFrame) -> tuple[str, float, float | None]:
    """Call analyze() and return (signal, strength, calibrated_prob).

    ``calibrated_prob`` is the raw ml_probability when finite, else None — kept
    separate from ``strength`` (which collapses None to a BUY/HOLD/SELL prior)
    so Kelly sizing can skip names without a real probability.
    """
    from analysis.technical import analyze

    res = analyze(ticker, df)
    if res is None:
        return "HOLD", 0.5, None
    return (
        res.overall_signal,
        _default_strength(res.overall_signal, res.ml_probability),
        _calibrated_prob(res.ml_probability),
    )


def generate_trades_portfolio_engine(
    account: PaperAccount,
    watchlist: list[str],
    positions: list[PaperPosition],
    prices: dict[str, float],
    history_provider: HistoryProvider,
) -> list[TargetTrade]:
    """
    One step of the portfolio-backtest loop, executed against live state.

    Computes signals for every watchlist ticker, determines mandatory exits,
    fills up to ``max_positions`` slots with the top-ranked BUYs, computes
    target weights per the account's allocation mode, then emits trades only
    if at least one trigger fires:

      • signal change (any SELL on position or BUY on free slot)
      • drift > ``account.drift_threshold``
      • monthly safety net (first scan of a new month, if enabled)
    """
    source = "portfolio_engine"
    trades: list[TargetTrade] = []

    # ── Compute signals, strengths & vols for every ticker we care about ─────
    universe = sorted(set(watchlist) | {p.ticker for p in positions})
    signals: dict[str, str] = {}
    strengths: dict[str, float] = {}
    vols: dict[str, float] = {}
    probs: dict[str, float | None] = {}
    dfs: dict[str, pd.DataFrame] = {}

    for t in universe:
        df = history_provider(t)
        if df is None or df.empty or "Close" not in df.columns:
            signals[t] = "HOLD"
            strengths[t] = 0.0
            vols[t] = 0.0
            probs[t] = None
            continue
        dfs[t] = df
        sig, sv, mlp = _signal_for(t, df)
        signals[t] = sig
        strengths[t] = sv
        vols[t] = _realized_vol(df["Close"].astype(float))
        probs[t] = mlp

    # ── Forced exits (positions with SELL) ────────────────────────────────────
    held_tickers = {p.ticker: p for p in positions}
    forced_exits = [t for t, p in held_tickers.items() if signals.get(t) == "SELL"]

    # ── Fill free slots with top-ranked BUY candidates ────────────────────────
    still_held = [t for t in held_tickers if t not in forced_exits]
    free_slots = max(0, account.max_positions - len(still_held))
    candidates = sorted(
        [t for t in watchlist if signals.get(t) == "BUY" and t not in still_held and t not in forced_exits],
        key=lambda t: strengths.get(t, 0.0),
        reverse=True,
    )
    # Correlation gate (T09): skip candidates too correlated with the active
    # book (still-held positions + names already picked this scan).
    new_entries = _select_uncorrelated(
        candidates,
        still_held,
        free_slots,
        history_provider,
        _corr_threshold(),
    )
    active = still_held + new_entries

    # ── Current portfolio value (mark-to-market) ──────────────────────────────
    pos_value = 0.0
    for p in positions:
        px = prices.get(p.ticker, p.avg_cost)
        pos_value += p.shares * (px or p.avg_cost)
    portfolio_val = float(account.cash + pos_value)
    if portfolio_val <= 0:
        return trades

    # ── Target dollars per ticker ─────────────────────────────────────────────
    alloc = AllocationMode(account.allocation_mode)
    if alloc == AllocationMode.FIXED_AMOUNT:
        target_dollars = {t: float(account.fixed_amount) for t in active}
        total = sum(target_dollars.values())
        if total > portfolio_val > 0:
            scale = portfolio_val / total
            target_dollars = {t: v * scale for t, v in target_dollars.items()}
        target_weights = {t: v / portfolio_val for t, v in target_dollars.items()}
    else:
        target_weights = _compute_target_weights(
            active,
            strengths,
            vols,
            alloc,
            probs=probs,
            **_sizing_params(),
        )
        target_dollars = {t: target_weights.get(t, 0.0) * portfolio_val for t in universe}

    # Tickers to liquidate entirely
    for t in list(held_tickers):
        if t not in active:
            target_dollars[t] = 0.0
            target_weights[t] = 0.0

    # ── Triggers ──────────────────────────────────────────────────────────────
    # Signal-based: any forced exit or new entry counts.
    signal_trigger = bool(forced_exits) or bool(new_entries)

    # Drift: any active position deviates from target by > drift_threshold.
    drift_trigger = False
    for t, w_target in target_weights.items():
        p = held_tickers.get(t)
        px = prices.get(t)
        if p is None or px is None:
            continue
        actual_w = (p.shares * px) / portfolio_val
        if w_target <= 0:
            if actual_w > account.drift_threshold:
                drift_trigger = True
                break
            continue
        rel_drift = abs(actual_w - w_target) / w_target
        if rel_drift > account.drift_threshold:
            drift_trigger = True
            break

    # Monthly: first scan of a new month.
    month_trigger = False
    if account.monthly_rebalance:
        now = datetime.utcnow()
        last = account.last_monthly_rebalance
        if last is None or (last.year, last.month) != (now.year, now.month):
            month_trigger = True

    if not (signal_trigger or drift_trigger or month_trigger):
        return trades  # no action this scan

    reason_parts = []
    if signal_trigger:
        reason_parts.append("signal")
    if drift_trigger:
        reason_parts.append("drift")
    if month_trigger:
        reason_parts.append("monthly")
    reason = "+".join(reason_parts)

    # ── Emit rebalance trades ────────────────────────────────────────────────
    all_tickers = set(target_dollars.keys()) | set(held_tickers.keys())
    for t in sorted(all_tickers):
        px = prices.get(t)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        current = 0.0
        p = held_tickers.get(t)
        if p is not None:
            current = p.shares * px
        target = float(target_dollars.get(t, 0.0))
        diff = target - current
        if abs(diff) < 1e-2:  # under 1¢ — ignore
            continue
        # Rebalance trades may originate from drift/monthly, where there's no
        # active signal driving the trade — leave signal_score=None in that
        # case so analytics can distinguish "conviction trade" from "housekeeping".
        score = strengths.get(t) if signals.get(t) in ("BUY", "SELL") else None
        if diff > 0:
            trades.append(
                TargetTrade(
                    ticker=t,
                    side="BUY",
                    target_shares=None,
                    target_dollars=float(diff),
                    reason=reason,
                    source=source,
                    signal_score=score,
                )
            )
        else:
            # SELL — convert dollar deficit to shares for clarity
            sell_shares = min(p.shares if p else 0.0, (-diff) / px)
            if sell_shares <= 1e-9:
                continue
            trades.append(
                TargetTrade(
                    ticker=t,
                    side="SELL",
                    target_shares=float(sell_shares),
                    target_dollars=float(-diff),
                    reason=reason,
                    source=source,
                    signal_score=score,
                )
            )

    return trades


# ── Dispatch table ────────────────────────────────────────────────────────────

STRATEGY_FNS: dict[str, Callable] = {
    "analyze_single": generate_trades_analyze_single,
    "portfolio_engine": generate_trades_portfolio_engine,
}


def get_strategy_fn(name: str) -> Callable:
    try:
        return STRATEGY_FNS[name]
    except KeyError:
        raise ValueError(f"Estrategia desconocida: {name!r}") from None
