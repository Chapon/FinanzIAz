"""
Paper-trading engine — orchestrates scans, executions and approvals.

Public entry points
-------------------
``run_scan(account_id, *, prices_provider=None, history_provider=None)``
    Full scan cycle:
        1. fetch live prices for watchlist ∪ current positions,
        2. fetch OHLCV history for each ticker,
        3. call the account's strategy → list of ``TargetTrade``,
        4. in AUTO mode, fill every trade immediately (create a filled
           ``PaperOrder``, update cash & positions),
        5. in MANUAL mode, create ``pending`` orders for approval,
        6. snapshot equity, stamp ``last_scan_at`` / ``last_monthly_rebalance``.

``approve_order(order_id)`` / ``reject_order(order_id)``
    Pending-order lifecycle for MANUAL mode.

The engine is deterministic given the two *_provider callables, which is
what makes unit tests possible without real yfinance calls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from config.settings_manager import settings
from database.models import session_scope
from paper_trading.account import record_equity_snapshot
from paper_trading.models import (
    PaperAccount,
    PaperOrder,
    PaperPosition,
    PaperWatchlistItem,
)
from paper_trading.strategies import (
    HistoryProvider,
    TargetTrade,
    get_strategy_fn,
)

PricesProvider = Callable[[list[str]], dict[str, float]]


# ── Default live providers (thin wrappers over yfinance cache) ────────────────


def _default_prices_provider(tickers: list[str]) -> dict[str, float]:
    from data.yahoo_finance import get_bulk_prices

    out: dict[str, float] = {}
    for ticker, info in get_bulk_prices(tickers).items():
        if info is None:
            continue
        px = info.get("price")
        if px is not None and np.isfinite(px) and px > 0:
            out[ticker] = float(px)
    return out


_VALID_YF_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}


def _default_history_provider(ticker: str) -> pd.DataFrame | None:
    """Fetch OHLCV history. Period is configurable via ``paper_history_period``
    (default ``"2y"``) — see ``config/settings_manager.py``."""
    from data.yahoo_finance import get_historical_data

    raw = settings.get("paper_history_period", "2y")
    period = str(raw) if str(raw) in _VALID_YF_PERIODS else "2y"
    return get_historical_data(ticker, period=period)


def _is_market_open_safe() -> bool:
    """Wrapper around data.yahoo_finance.is_market_open() that never raises."""
    try:
        from data.yahoo_finance import is_market_open

        open_, _ = is_market_open()
        return bool(open_)
    except Exception:
        return False


def _last_closed_cycle_pnl_pct(
    session,
    account_id: int,
    ticker: str,
    within_days: int,
) -> float | None:
    """Return the realized P/L % of the most recent closed cycle for ``ticker``,
    or ``None`` if there is no SELL fill for the ticker within ``within_days``.

    A "cycle" is the set of BUY fills between two consecutive SELLs (or, for
    the first cycle, all BUYs preceding the first SELL). We weight BUY prices
    by ``fill_shares`` and compare against the last SELL's ``fill_price``.

    Used by Gate 5 (anti-whipsaw) to decide whether a fresh BUY should be
    blocked because the same ticker was just sold at a loss.
    """
    if within_days <= 0:
        return None

    cutoff = datetime.utcnow() - timedelta(days=within_days)

    last_sell = (
        session.query(PaperOrder)
        .filter(PaperOrder.account_id == account_id)
        .filter(PaperOrder.ticker == ticker)
        .filter(PaperOrder.side == "SELL")
        .filter(PaperOrder.status == "filled")
        .filter(PaperOrder.filled_at >= cutoff)
        .order_by(PaperOrder.filled_at.desc())
        .first()
    )
    if last_sell is None or not last_sell.fill_price:
        return None

    prev_sell = (
        session.query(PaperOrder)
        .filter(PaperOrder.account_id == account_id)
        .filter(PaperOrder.ticker == ticker)
        .filter(PaperOrder.side == "SELL")
        .filter(PaperOrder.status == "filled")
        .filter(PaperOrder.filled_at < last_sell.filled_at)
        .order_by(PaperOrder.filled_at.desc())
        .first()
    )

    buys_q = (
        session.query(PaperOrder)
        .filter(PaperOrder.account_id == account_id)
        .filter(PaperOrder.ticker == ticker)
        .filter(PaperOrder.side == "BUY")
        .filter(PaperOrder.status == "filled")
        .filter(PaperOrder.filled_at <= last_sell.filled_at)
    )
    if prev_sell is not None:
        buys_q = buys_q.filter(PaperOrder.filled_at > prev_sell.filled_at)
    buys = buys_q.all()
    if not buys:
        return None

    total_shares = sum(float(b.fill_shares or 0.0) for b in buys)
    total_cost = sum(float(b.fill_shares or 0.0) * float(b.fill_price or 0.0) for b in buys)
    if total_shares <= 0 or total_cost <= 0:
        return None
    avg_buy = total_cost / total_shares
    if avg_buy <= 0:
        return None
    return (float(last_sell.fill_price) - avg_buy) / avg_buy * 100.0


# ── ATR-stop gate (T01) ───────────────────────────────────────────────────────


# Reasons used by the ATR-stop gate. Anything starting with ``atr_`` is treated
# as a forced exit by downstream gates (Gate 2 bypass, etc.) — kept in a tuple
# so the check stays a cheap startswith().
ATR_EXIT_REASONS: tuple[str, ...] = ("atr_stop", "atr_tp", "atr_trail")


def _is_atr_forced_exit(reason: str | None) -> bool:
    """True iff ``reason`` was produced by ``_compute_atr_forced_exits``.

    Forced exits bypass the min-holding gate so a fresh position that collapses
    can still be cut. They do NOT bypass market-hours (Gate 1) — closed market
    means no fills regardless of urgency.
    """
    if not reason:
        return False
    return any(reason.startswith(prefix) for prefix in ATR_EXIT_REASONS)


def _compute_atr_forced_exits(
    positions: list,
    prices: dict[str, float],
    history_provider,
) -> list:
    """
    Evaluate each open position against the ATR stop/TP/trailing levels.

    Returns a list of ``TargetTrade`` SELLs for the tickers whose live price
    crossed at least one threshold. Order of evaluation: ``atr_stop`` (worst
    case) → ``atr_trail`` (give-back from peak) → ``atr_tp`` (profit lock).
    The first trigger that fires wins; the other two are not re-evaluated for
    that ticker.

    Also returns (via side-effect on the caller) NOTHING — the caller is
    responsible for updating ``high_water_mark`` separately, after this
    function has read the *pre-update* high. This keeps the trailing stop
    semantics correct: if today's price is a new high but is still inside
    the trailing band off yesterday's high, we don't whipsaw on the same
    bar that set the new high.
    """
    from paper_trading.strategies import TargetTrade
    from analysis.atr import compute_atr

    if not bool(settings.get("atr_stops_enabled", False)):
        return []

    period = max(2, int(settings.get("atr_period", 14)))
    stop_mult = max(0.0, float(settings.get("atr_stop_mult", 2.0)))
    tp_mult = max(0.0, float(settings.get("atr_tp_mult", 4.0)))
    trail_enabled = bool(settings.get("atr_trail_enabled", True))

    out: list = []
    for pos in positions:
        px = prices.get(pos.ticker)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        if pos.shares is None or pos.shares <= 1e-9:
            continue
        if pos.avg_cost is None or pos.avg_cost <= 0:
            continue

        df = history_provider(pos.ticker)
        atr = compute_atr(df, period=period)
        if atr is None or not np.isfinite(atr) or atr <= 0:
            continue

        avg_cost = float(pos.avg_cost)
        # Trailing baseline: pre-update HWM. If never seeded, use avg_cost so
        # the trailing stop has SOME baseline even before the first scan
        # tick. This is conservative — equivalent to "from entry" until the
        # next scan upgrades HWM to a real high.
        hwm = pos.high_water_mark if pos.high_water_mark is not None else avg_cost
        hwm = float(hwm)

        stop_level = avg_cost - stop_mult * atr
        tp_level = avg_cost + tp_mult * atr
        trail_level = hwm - stop_mult * atr if trail_enabled else None

        reason: str | None = None
        trigger_level: float | None = None
        if stop_level > 0 and px <= stop_level:
            reason = (
                f"atr_stop @ {px:.2f} ≤ {stop_level:.2f} "
                f"(entry {avg_cost:.2f} − {stop_mult:.1f}×ATR {atr:.2f})"
            )
            trigger_level = stop_level
        elif (
            trail_enabled
            and trail_level is not None
            and trail_level > 0
            and px <= trail_level
            # Trail is only meaningful once we've seen a high above entry —
            # otherwise it duplicates the stop-loss. The check is "HWM
            # strictly above entry by at least 1 ATR" to avoid noise.
            and hwm > avg_cost + atr
        ):
            reason = (
                f"atr_trail @ {px:.2f} ≤ {trail_level:.2f} "
                f"(peak {hwm:.2f} − {stop_mult:.1f}×ATR {atr:.2f})"
            )
            trigger_level = trail_level
        elif tp_level > 0 and px >= tp_level:
            reason = (
                f"atr_tp @ {px:.2f} ≥ {tp_level:.2f} "
                f"(entry {avg_cost:.2f} + {tp_mult:.1f}×ATR {atr:.2f})"
            )
            trigger_level = tp_level

        if reason is None:
            continue

        out.append(
            TargetTrade(
                ticker=pos.ticker,
                side="SELL",
                target_shares=float(pos.shares),  # full close
                target_dollars=None,
                reason=reason,
                source="atr_stop_gate",
                signal_score=1.0,  # max conviction — see roadmap T01
            )
        )
        # Trigger_level not used downstream but kept for log clarity.
        _ = trigger_level

    return out


def _update_high_water_marks(positions: list, prices: dict[str, float]) -> None:
    """
    Seed / advance ``high_water_mark`` for each position based on the live
    price. NULL HWM is seeded with the current price (or avg_cost, whichever
    is higher — protects against the seed being below entry on a down tick).
    Existing HWM is advanced only if the new price is strictly higher.

    Called *after* ``_compute_atr_forced_exits`` so the trailing stop uses
    the pre-update HWM.
    """
    for pos in positions:
        px = prices.get(pos.ticker)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        if pos.high_water_mark is None:
            seed = max(float(px), float(pos.avg_cost or 0.0))
            pos.high_water_mark = float(seed)
        elif float(px) > float(pos.high_water_mark):
            pos.high_water_mark = float(px)


# ── Scan result type ──────────────────────────────────────────────────────────


@dataclass
class ScanResult:
    account_id: int
    scan_at: datetime
    mode: str  # "auto" | "manual"
    strategy: str
    prices: dict[str, float]
    generated: int = 0  # total trades proposed by strategy
    filled: int = 0  # executed immediately
    queued: int = 0  # pending approval
    skipped: int = 0  # rejected by engine (no price, insufficient cash, …)
    equity_before: float = 0.0
    equity_after: float = 0.0
    warnings: list[str] = field(default_factory=list)
    filled_orders: list[int] = field(default_factory=list)
    pending_orders: list[int] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Scan {self.scan_at:%Y-%m-%d %H:%M} · {self.strategy} · {self.mode}  "
            f"· generated={self.generated} filled={self.filled} "
            f"queued={self.queued} skipped={self.skipped}  "
            f"· equity ${self.equity_before:,.2f} → ${self.equity_after:,.2f}"
        )


# ── Main entry point ──────────────────────────────────────────────────────────


def run_scan(
    account_id: int,
    *,
    prices_provider: PricesProvider | None = None,
    history_provider: HistoryProvider | None = None,
) -> ScanResult | None:
    """Scan the market once, execute trades (or queue them), snapshot equity."""
    prices_provider = prices_provider or _default_prices_provider
    history_provider = history_provider or _default_history_provider

    with session_scope() as session:
        acct: PaperAccount = session.query(PaperAccount).filter(PaperAccount.id == account_id).first()
        if acct is None or not acct.is_active:
            return None

        watchlist = [
            w.ticker
            for w in (
                session.query(PaperWatchlistItem).filter(PaperWatchlistItem.account_id == account_id).all()
            )
        ]
        positions: list[PaperPosition] = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == account_id)
            .filter(PaperPosition.shares > 0)
            .all()
        )

        tickers = sorted(set(watchlist) | {p.ticker for p in positions})
        prices = prices_provider(tickers) if tickers else {}

        # Equity before any trades
        equity_before = acct.cash + sum(p.shares * prices.get(p.ticker, p.avg_cost) for p in positions)

        # ── ATR-stop gate (T01) ──────────────────────────────────────────
        # Runs BEFORE the strategy so a stopped-out position can free up
        # its slot in the same scan. The returned trades use reason starting
        # with ``atr_`` so downstream gates can recognize them as forced
        # exits and bypass min-holding.
        atr_exits: list[TargetTrade] = _compute_atr_forced_exits(
            positions, prices, history_provider
        )
        atr_exit_tickers = {t.ticker for t in atr_exits}

        # Advance HWM *after* reading it for the trailing check, so the
        # trailing stop uses the pre-update high. New positions get their
        # HWM seeded here.
        _update_high_water_marks(positions, prices)

        # Run the strategy (reads detached attributes, so safe)
        strategy_fn = get_strategy_fn(acct.strategy)
        strategy_trades: list[TargetTrade] = strategy_fn(
            acct, watchlist, positions, prices, history_provider
        )

        # Dedup: if ATR forces a SELL for a ticker, drop any strategy-emitted
        # SELL for the same ticker — the ATR trigger wins (more specific +
        # has signal_score=1.0 for downstream consumers).
        strategy_trades = [
            t
            for t in strategy_trades
            if not (t.side == "SELL" and t.ticker in atr_exit_tickers)
        ]
        trades: list[TargetTrade] = atr_exits + strategy_trades

        result = ScanResult(
            account_id=account_id,
            scan_at=datetime.utcnow(),
            mode=acct.mode,
            strategy=acct.strategy,
            prices=prices,
            generated=len(trades),
            equity_before=float(equity_before),
        )

        # Process trades in a deterministic order: SELLs first (free up cash), then BUYs.
        trades.sort(key=lambda t: 0 if t.side == "SELL" else 1)

        # In manual mode, remember which (ticker, side) pairs already have a
        # pending order so we don't duplicate the same intent on every scan.
        existing_pending: set[tuple[str, str]] = set()
        if acct.mode == "manual":
            existing_pending = {
                (o.ticker, o.side)
                for o in (
                    session.query(PaperOrder)
                    .filter(PaperOrder.account_id == acct.id)
                    .filter(PaperOrder.status == "pending")
                    .all()
                )
            }

        # ── Lite-pro guardrails ──────────────────────────────────────────────
        # Read configurable thresholds (with safe defaults) and pre-compute
        # state used by the per-trade gates inside the loop below.
        enforce_hours = bool(settings.get("paper_enforce_market_hours", True))
        min_holding_min = max(0, int(settings.get("paper_min_holding_minutes", 60)))
        anti_flap_min = max(0, int(settings.get("paper_anti_flap_minutes", 30)))
        min_trade_usd = max(0.0, float(settings.get("paper_min_trade_dollars", 50.0)))
        whipsaw_days = max(0, int(settings.get("paper_whipsaw_lookback_days", 7)))
        whipsaw_min_loss = max(0.0, float(settings.get("paper_whipsaw_min_loss_pct", 0.0)))

        market_blocked = enforce_hours and not _is_market_open_safe()
        if market_blocked and trades:
            result.warnings.append(
                "Mercado cerrado y paper_enforce_market_hours=True — "
                f"se generaron {len(trades)} señales pero no se ejecutarán."
            )

        # Index positions by ticker for the min-holding check.
        pos_by_ticker: dict[str, PaperPosition] = {p.ticker: p for p in positions}

        # Tickers with a recent filled SELL → blocked from BUY (anti-flap).
        recent_sell_tickers: set[str] = set()
        if anti_flap_min > 0:
            cutoff = result.scan_at - timedelta(minutes=anti_flap_min)
            rows = (
                session.query(PaperOrder.ticker)
                .filter(PaperOrder.account_id == acct.id)
                .filter(PaperOrder.side == "SELL")
                .filter(PaperOrder.status == "filled")
                .filter(PaperOrder.filled_at >= cutoff)
                .all()
            )
            recent_sell_tickers = {r[0] for r in rows}

        any_monthly = False
        for trade in trades:
            if "monthly" in (trade.reason or ""):
                any_monthly = True

            # Gate 1 — market hours. Hardest no-op.
            if market_blocked:
                result.skipped += 1
                continue

            # Gate 2 — min holding period (block premature SELLs).
            # ATR-forced exits (stop-loss, take-profit, trailing) bypass this
            # gate — a freshly-opened position that collapses should still be
            # cut. The forced-exit reason starts with ``atr_``.
            if (
                trade.side == "SELL"
                and min_holding_min > 0
                and not _is_atr_forced_exit(trade.reason)
            ):
                p = pos_by_ticker.get(trade.ticker)
                if p is not None and p.opened_at is not None:
                    age_min = (result.scan_at - p.opened_at).total_seconds() / 60.0
                    if age_min < min_holding_min:
                        result.skipped += 1
                        result.warnings.append(
                            f"{trade.ticker} SELL bloqueado: posición abierta hace "
                            f"{age_min:.1f} min < min_holding={min_holding_min} min."
                        )
                        continue

            # Gate 3 — anti-flap (block BUYs right after a SELL of the same ticker).
            if trade.side == "BUY" and trade.ticker in recent_sell_tickers:
                result.skipped += 1
                result.warnings.append(
                    f"{trade.ticker} BUY bloqueado: anti-flap activo (SELL en últimos {anti_flap_min} min)."
                )
                continue

            # Gate 4 — minimum trade size (skip dust BUYs whose round-trip cost
            # would dominate any expected edge).
            if trade.side == "BUY" and min_trade_usd > 0:
                td = float(trade.target_dollars or 0.0)
                if 0 < td < min_trade_usd:
                    result.skipped += 1
                    result.warnings.append(
                        f"{trade.ticker} BUY bloqueado: tamaño ${td:.2f} < mínimo ${min_trade_usd:.2f}."
                    )
                    continue

            # Gate 5 — anti-whipsaw (block re-BUY if last closed cycle was a loss
            # within the lookback window). Tightens Gate 3, which is time-only.
            if trade.side == "BUY" and whipsaw_days > 0:
                pnl_pct = _last_closed_cycle_pnl_pct(
                    session, acct.id, trade.ticker, whipsaw_days
                )
                if pnl_pct is not None and pnl_pct < -whipsaw_min_loss:
                    result.skipped += 1
                    result.warnings.append(
                        f"{trade.ticker} BUY bloqueado: anti-whipsaw — último ciclo "
                        f"cerró con {pnl_pct:+.2f}% (umbral -{whipsaw_min_loss:.2f}%) "
                        f"dentro de {whipsaw_days}d."
                    )
                    continue

            if acct.mode == "manual":
                key = (trade.ticker, trade.side)
                if key in existing_pending:
                    result.skipped += 1
                    result.warnings.append(
                        f"{trade.ticker} {trade.side}: ya existe una orden pendiente, "
                        "no se encoló una duplicada."
                    )
                    continue
                order = _create_pending_order(
                    session,
                    acct,
                    trade,
                    current_price=prices.get(trade.ticker),
                )
                existing_pending.add(key)
                result.queued += 1
                result.pending_orders.append(order.id)
                continue

            # AUTO — fill now
            px = prices.get(trade.ticker)
            if px is None or not np.isfinite(px) or px <= 0:
                result.skipped += 1
                result.warnings.append(f"{trade.ticker}: sin precio, trade omitido.")
                continue
            order = _fill_trade(session, acct, trade, price=px)
            if order is None:
                result.skipped += 1
                result.warnings.append(f"{trade.ticker}: fill rechazado (cash o shares insuficientes).")
            else:
                result.filled += 1
                result.filled_orders.append(order.id)

        # Stamp account + monthly rebalance flag
        acct.last_scan_at = result.scan_at
        if any_monthly and acct.mode == "auto":
            acct.last_monthly_rebalance = result.scan_at

        # Recompute equity after fills
        positions_after = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == account_id)
            .filter(PaperPosition.shares > 0)
            .all()
        )
        equity_after = acct.cash + sum(p.shares * prices.get(p.ticker, p.avg_cost) for p in positions_after)
        result.equity_after = float(equity_after)
        # session_scope commits automatically on successful exit

    # Snapshot outside the transaction — opens its own session
    record_equity_snapshot(account_id, prices)
    return result


# ── Manual-mode approvals ─────────────────────────────────────────────────────


def approve_order(
    order_id: int,
    *,
    prices_provider: PricesProvider | None = None,
) -> PaperOrder | None:
    """Fill a pending order at the current market price."""
    prices_provider = prices_provider or _default_prices_provider

    with session_scope() as session:
        order: PaperOrder | None = session.query(PaperOrder).filter(PaperOrder.id == order_id).first()
        if order is None or order.status != "pending":
            return None

        acct = session.query(PaperAccount).filter(PaperAccount.id == order.account_id).first()
        if acct is None:
            return None

        prices = prices_provider([order.ticker])
        px = prices.get(order.ticker)
        if px is None or not np.isfinite(px) or px <= 0:
            order.status = "expired"
            order.notes = (order.notes or "") + "\n[approve] sin precio, expirada."
            order.decided_at = datetime.utcnow()
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

        # Convert the pending order into a TargetTrade and fill.
        trade = TargetTrade(
            ticker=order.ticker,
            side=order.side,
            target_shares=order.target_shares,
            target_dollars=order.target_dollars,
            reason=f"approved: {order.reason or ''}".strip(),
            source=order.source or "manual",
        )

        order.status = "approved"
        order.decided_at = datetime.utcnow()

        filled = _fill_trade(session, acct, trade, price=px, reuse_order=order)

        # Si _fill_trade no pudo ejecutar (cash/shares insuficientes), no dejar
        # la orden colgada en "approved" para siempre — marcarla como expirada
        # con motivo. _fill_trade exitoso reescribe order.status a "filled" via
        # _stamp_order_filled(reuse_order=order); si sigue "approved" es que falló.
        if filled is None and order.status == "approved":
            order.status = "expired"
            order.notes = (
                (order.notes or "") + "\n[approve] fill rechazado: cash o shares insuficientes."
            ).strip()

        session.flush()

        if filled is not None:
            session.refresh(filled)
            session.expunge(filled)
            return filled
        session.refresh(order)
        session.expunge(order)
        return order


def reject_order(order_id: int, note: str = "") -> PaperOrder | None:
    with session_scope() as session:
        order = session.query(PaperOrder).filter(PaperOrder.id == order_id).first()
        if order is None or order.status != "pending":
            return None
        order.status = "rejected"
        order.decided_at = datetime.utcnow()
        if note:
            order.notes = (order.notes or "") + f"\n[reject] {note}"
        session.flush()
        session.refresh(order)
        session.expunge(order)
        return order


# ── Internal: create pending / fill trade ─────────────────────────────────────


def _create_pending_order(
    session,
    acct: PaperAccount,
    trade: TargetTrade,
    *,
    current_price: float | None = None,
) -> PaperOrder:
    """
    Persist a TargetTrade as a pending PaperOrder.

    Si la suggestion es BUY y target_shares no fue seteado por la estrategia,
    lo computamos a partir de target_dollars + current_price + slippage para
    que el usuario vea un número de shares entero en la orden pendiente.
    Para SELL ya se setea target_shares; lo redondeamos hacia abajo a entero.
    """
    target_shares = trade.target_shares

    if (
        trade.side == "BUY"
        and target_shares is None
        and trade.target_dollars is not None
        and current_price is not None
        and np.isfinite(current_price)
        and current_price > 0
    ):
        budget = min(float(trade.target_dollars), acct.cash)
        fill_price = current_price * (1 + acct.slippage)
        raw_shares = (budget * (1 - acct.commission)) / fill_price
        int_shares = int(raw_shares)
        if int_shares >= 1:
            target_shares = float(int_shares)

    elif trade.side == "SELL" and target_shares is not None and target_shares > 0:
        target_shares = float(int(float(target_shares)))  # floor a entero
        if target_shares < 1.0:
            target_shares = trade.target_shares  # dejar lo original

    order = PaperOrder(
        account_id=acct.id,
        ticker=trade.ticker,
        side=trade.side,
        target_shares=target_shares,
        target_dollars=trade.target_dollars,
        reason=trade.reason,
        source=trade.source,
        signal_score=trade.signal_score,
        status="pending",
    )
    session.add(order)
    session.flush()
    return order


def _fill_trade(
    session,
    acct: PaperAccount,
    trade: TargetTrade,
    *,
    price: float,
    reuse_order: PaperOrder | None = None,
) -> PaperOrder | None:
    """
    Execute a trade against the live account state. Returns the filled
    PaperOrder (new or reused) or None if the trade couldn't happen
    (zero shares, zero cash, etc.).

    Cost models
    -----------
    Slippage: applied via ``PercentSlippage(acct.slippage)`` so that any
    future per-account override (e.g. ``TickSlippage``) plugs in here
    without changing this function.
    Commission: driven by the global ``ibkr_commission_plan`` setting via
    ``get_active_commission_model()``. ``"tiered"``/``"fixed"`` use the
    realistic IBKR Pro model (per-share + min + 1% cap + regulatory/exchange
    pass-through); ``"legacy"`` falls back to the per-account flat % field
    so older tests and pre-migration accounts keep their previous behaviour.
    """
    from config.settings_manager import settings as _settings
    from paper_trading.costs import (
        commission_from_legacy,
        get_active_commission_model,
        slippage_from_legacy,
    )

    side = trade.side
    plan = str(_settings.get("ibkr_commission_plan", "tiered")).lower()
    if plan == "legacy":
        commission_m = commission_from_legacy(acct.commission)
        commission_pct = float(acct.commission)
    else:
        commission_m = get_active_commission_model()
        # Per-share models don't have a meaningful "%" — keep budgeting code
        # working by approximating with the legacy field. The real cost is
        # recomputed from commission_m.cost(...) after the fill anyway.
        commission_pct = float(acct.commission)
    slippage_m = slippage_from_legacy(acct.slippage)

    if side == "BUY":
        budget = trade.target_dollars if trade.target_dollars is not None else 0.0
        budget = min(float(budget), acct.cash)
        if budget <= 1e-6:
            return None
        fill_price = slippage_m.adjust_price(side="BUY", price=price)

        # Shares ahora son ENTEROS — el usuario va a ejecutar manualmente en
        # un broker que no permite fracciones. Floor del cómputo crudo y
        # recalculamos el cash gastado a partir de las shares finales.
        raw_shares = (budget * (1 - commission_pct)) / fill_price
        shares_got = float(int(raw_shares))  # floor a entero
        if shares_got < 1.0:
            return None

        # Real notional + commission a partir de las shares enteras.
        actual_notional = shares_got * fill_price
        commission_paid = commission_m.cost(side="BUY", shares=shares_got, price=fill_price)
        actual_cost = actual_notional + commission_paid
        # Edge case: si el actual_cost supera el budget por redondeo, recortar.
        if actual_cost > acct.cash + 1e-6:
            return None

        # Update / create position
        pos = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == acct.id)
            .filter(PaperPosition.ticker == trade.ticker)
            .first()
        )
        if pos is None:
            pos = PaperPosition(
                account_id=acct.id,
                ticker=trade.ticker,
                shares=shares_got,
                avg_cost=fill_price,
                opened_at=datetime.utcnow(),
                entry_reason=trade.reason,
                high_water_mark=float(fill_price),
            )
            session.add(pos)
        else:
            new_total_cost = pos.shares * pos.avg_cost + shares_got * fill_price
            pos.shares += shares_got
            pos.avg_cost = new_total_cost / pos.shares
            pos.updated_at = datetime.utcnow()
            # Advance HWM on add-ons too, so a later trailing-stop check
            # doesn't ignore a higher post-add fill price.
            if pos.high_water_mark is None or float(fill_price) > float(pos.high_water_mark):
                pos.high_water_mark = float(fill_price)
        acct.cash -= actual_cost

        slippage_cost = shares_got * (fill_price - price)
        return _stamp_order_filled(
            session,
            acct,
            trade,
            reuse_order,
            fill_price=fill_price,
            fill_shares=shares_got,
            commission_paid=commission_paid,
            slippage_cost=slippage_cost,
        )

    elif side == "SELL":
        pos = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == acct.id)
            .filter(PaperPosition.ticker == trade.ticker)
            .first()
        )
        if pos is None or pos.shares <= 1e-9:
            return None
        want_shares = trade.target_shares
        if want_shares is None or want_shares <= 0:
            want_shares = pos.shares
        want_shares = float(want_shares)

        # Floor a entero. Excepción: si la intención es liquidar todas las
        # shares enteras de la posición, vendemos también el residual
        # fraccional (posiciones legacy de antes del cambio a enteros) para
        # cerrar la posición limpia.
        int_want = int(want_shares)
        int_held = int(pos.shares)
        if int_want < 1:
            return None
        if int_want >= int_held:
            sell_shares = float(pos.shares)  # cierre total + residual
        else:
            sell_shares = float(int_want)  # trim parcial entero

        sell_shares = min(sell_shares, float(pos.shares))
        if sell_shares <= 1e-9:
            return None

        fill_price = slippage_m.adjust_price(side="SELL", price=price)
        gross = sell_shares * fill_price
        commission_paid = commission_m.cost(side="SELL", shares=sell_shares, price=fill_price)
        proceeds = gross - commission_paid
        pos.shares -= sell_shares
        pos.updated_at = datetime.utcnow()
        acct.cash += proceeds

        # If fully closed, drop the row.
        if pos.shares <= 1e-9:
            session.delete(pos)

        slippage_cost = sell_shares * (price - fill_price)
        return _stamp_order_filled(
            session,
            acct,
            trade,
            reuse_order,
            fill_price=fill_price,
            fill_shares=sell_shares,
            commission_paid=commission_paid,
            slippage_cost=slippage_cost,
        )

    return None


def _stamp_order_filled(
    session,
    acct: PaperAccount,
    trade: TargetTrade,
    reuse_order: PaperOrder | None,
    *,
    fill_price: float,
    fill_shares: float,
    commission_paid: float,
    slippage_cost: float,
) -> PaperOrder:
    """Create or update a PaperOrder as 'filled' and return it."""
    now = datetime.utcnow()
    if reuse_order is None:
        order = PaperOrder(
            account_id=acct.id,
            ticker=trade.ticker,
            side=trade.side,
            target_shares=trade.target_shares,
            target_dollars=trade.target_dollars,
            reason=trade.reason,
            source=trade.source,
            signal_score=trade.signal_score,
            status="filled",
            created_at=now,
            filled_at=now,
            fill_price=float(fill_price),
            fill_shares=float(fill_shares),
            commission_paid=float(commission_paid),
            slippage_cost=float(slippage_cost),
        )
        session.add(order)
        session.flush()
    else:
        # Idempotency guard: don't double-fill an already-filled order.
        # Without this, a retry of approve_order on a stale view of the DB
        # could double-spend cash. The caller already filters by
        # status == 'pending', but we belt-and-braces here too.
        if reuse_order.status == "filled":
            return reuse_order
        reuse_order.status = "filled"
        reuse_order.filled_at = now
        reuse_order.fill_price = float(fill_price)
        reuse_order.fill_shares = float(fill_shares)
        reuse_order.commission_paid = float(commission_paid)
        reuse_order.slippage_cost = float(slippage_cost)
        order = reuse_order
    return order


# ── Recovery helpers ──────────────────────────────────────────────────────────


def reconcile_account(account_id: int, *, expire_pending_after_hours: int = 24) -> int:
    """
    Sweep stale pending orders for an account.

    Pending orders that were generated before the most recent app crash
    can pile up indefinitely if the user never visits the Paper Trading
    tab again. This helper marks anything older than
    ``expire_pending_after_hours`` as ``expired`` so the engine starts
    each session with a clean slate.

    Returns the number of orders expired.
    """
    from database.models import session_scope

    cutoff = datetime.utcnow() - timedelta(hours=max(0, int(expire_pending_after_hours)))
    expired = 0
    try:
        with session_scope() as session:
            stale = (
                session.query(PaperOrder)
                .filter(PaperOrder.account_id == account_id)
                .filter(PaperOrder.status == "pending")
                .filter(PaperOrder.created_at <= cutoff)
                .all()
            )
            for o in stale:
                o.status = "expired"
                o.decided_at = datetime.utcnow()
                o.notes = ((o.notes or "") + "\n[reconcile] expired automatically.").strip()
                expired += 1
        if expired:
            from config.logging_config import get_logger

            get_logger(__name__).info(
                "reconcile_account(%d): expired %d stale pending orders.",
                account_id,
                expired,
            )
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception("reconcile_account(%d) failed", account_id)
    return expired
