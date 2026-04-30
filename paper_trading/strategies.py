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

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import numpy as np
import pandas as pd

from paper_trading.models import PaperAccount, PaperPosition
from analysis.portfolio_backtest import (
    AllocationMode, _compute_target_weights, _realized_vol,
)


# ── Value type ────────────────────────────────────────────────────────────────

@dataclass
class TargetTrade:
    ticker:         str
    side:           str          # "BUY" | "SELL"
    target_shares:  Optional[float]   # for SELL: total shares to close; for BUY: None if using target_dollars
    target_dollars: Optional[float]   # for BUY: dollar amount; for SELL: None or estimated proceeds
    reason:         str
    source:         str          # strategy name ("analyze_single" | "portfolio_engine")

    def __repr__(self) -> str:
        dollars = f"${self.target_dollars:,.2f}" if self.target_dollars is not None else "—"
        shares  = f"{self.target_shares:.4f}"    if self.target_shares  is not None else "—"
        return f"<TargetTrade({self.side} {self.ticker} {shares}sh / {dollars} · {self.reason})>"


HistoryProvider = Callable[[str], Optional[pd.DataFrame]]


# ── Strategy 1: analyze_single ────────────────────────────────────────────────

def _default_strength(signal: str, ml_probability: Optional[float]) -> float:
    """Conviction score in [0,1] for ranking BUY candidates."""
    if ml_probability is not None and np.isfinite(ml_probability):
        return float(max(0.0, min(1.0, ml_probability)))
    return {"BUY": 1.0, "HOLD": 0.5, "SELL": 0.0}.get(signal, 0.0)


def generate_trades_analyze_single(
    account:          PaperAccount,
    watchlist:        list[str],
    positions:        list[PaperPosition],
    prices:           dict[str, float],
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
            trades.append(TargetTrade(
                ticker         = pos.ticker,
                side           = "SELL",
                target_shares  = float(pos.shares),
                target_dollars = None,
                reason         = f"analyze SELL ({res.ml_probability or 0:.2f})",
                source         = source,
            ))
            forced_exits.add(pos.ticker)

    # Candidates for BUY — ranked by conviction
    ranked: list[tuple[float, str]] = []
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

    ranked.sort(reverse=True)

    # Slots available after processing forced exits
    held_after  = (held_tickers - forced_exits)
    free_slots  = max(0, account.max_positions - len(held_after))
    picks       = [t for _, t in ranked[:free_slots]]

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

    if account.allocation_mode == "fixed_amount":
        target_per = float(account.fixed_amount)
        total      = target_per * len(picks)
        if total > available:
            target_per = available / len(picks)   # scale down
    else:
        target_per = available / len(picks)

    for t in picks:
        trades.append(TargetTrade(
            ticker         = t,
            side           = "BUY",
            target_shares  = None,
            target_dollars = float(target_per),
            reason         = "analyze BUY",
            source         = source,
        ))

    return trades


# ── Strategy 2: portfolio_engine ──────────────────────────────────────────────

def _signal_for(ticker: str, df: pd.DataFrame) -> tuple[str, float]:
    """Call analyze() and return (signal, strength)."""
    from analysis.technical import analyze
    res = analyze(ticker, df)
    if res is None:
        return "HOLD", 0.5
    return res.overall_signal, _default_strength(res.overall_signal, res.ml_probability)


def generate_trades_portfolio_engine(
    account:          PaperAccount,
    watchlist:        list[str],
    positions:        list[PaperPosition],
    prices:           dict[str, float],
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
    signals:   dict[str, str]   = {}
    strengths: dict[str, float] = {}
    vols:      dict[str, float] = {}
    dfs:       dict[str, pd.DataFrame] = {}

    for t in universe:
        df = history_provider(t)
        if df is None or df.empty or "Close" not in df.columns:
            signals[t]   = "HOLD"
            strengths[t] = 0.0
            vols[t]      = 0.0
            continue
        dfs[t] = df
        sig, sv = _signal_for(t, df)
        signals[t]   = sig
        strengths[t] = sv
        vols[t]      = _realized_vol(df["Close"].astype(float))

    # ── Forced exits (positions with SELL) ────────────────────────────────────
    held_tickers = {p.ticker: p for p in positions}
    forced_exits = [t for t, p in held_tickers.items() if signals.get(t) == "SELL"]

    # ── Fill free slots with top-ranked BUY candidates ────────────────────────
    still_held = [t for t in held_tickers if t not in forced_exits]
    free_slots = max(0, account.max_positions - len(still_held))
    candidates = sorted(
        [t for t in watchlist
         if signals.get(t) == "BUY"
         and t not in still_held
         and t not in forced_exits],
        key=lambda t: strengths.get(t, 0.0),
        reverse=True,
    )
    new_entries = candidates[:free_slots]
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
        target_weights = _compute_target_weights(active, strengths, vols, alloc)
        target_dollars = {t: target_weights.get(t, 0.0) * portfolio_val for t in universe}

    # Tickers to liquidate entirely
    for t in list(held_tickers):
        if t not in active:
            target_dollars[t]  = 0.0
            target_weights[t]  = 0.0

    # ── Triggers ──────────────────────────────────────────────────────────────
    # Signal-based: any forced exit or new entry counts.
    signal_trigger = bool(forced_exits) or bool(new_entries)

    # Drift: any active position deviates from target by > drift_threshold.
    drift_trigger = False
    for t, w_target in target_weights.items():
        p  = held_tickers.get(t)
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
        return trades   # no action this scan

    reason_parts = []
    if signal_trigger: reason_parts.append("signal")
    if drift_trigger:  reason_parts.append("drift")
    if month_trigger:  reason_parts.append("monthly")
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
        target  = float(target_dollars.get(t, 0.0))
        diff    = target - current
        if abs(diff) < 1e-2:        # under 1¢ — ignore
            continue
        if diff > 0:
            trades.append(TargetTrade(
                ticker         = t,
                side           = "BUY",
                target_shares  = None,
                target_dollars = float(diff),
                reason         = reason,
                source         = source,
            ))
        else:
            # SELL — convert dollar deficit to shares for clarity
            sell_shares = min(p.shares if p else 0.0, (-diff) / px)
            if sell_shares <= 1e-9:
                continue
            trades.append(TargetTrade(
                ticker         = t,
                side           = "SELL",
                target_shares  = float(sell_shares),
                target_dollars = float(-diff),
                reason         = reason,
                source         = source,
            ))

    return trades


# ── Dispatch table ────────────────────────────────────────────────────────────

STRATEGY_FNS: dict[str, Callable] = {
    "analyze_single":   generate_trades_analyze_single,
    "portfolio_engine": generate_trades_portfolio_engine,
}


def get_strategy_fn(name: str) -> Callable:
    try:
        return STRATEGY_FNS[name]
    except KeyError:
        raise ValueError(f"Estrategia desconocida: {name!r}") from None
