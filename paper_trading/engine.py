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

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd

from config.settings_manager import settings
from database.models import get_session
from paper_trading.models import (
    PaperAccount, PaperPosition, PaperOrder, PaperWatchlistItem,
)
from paper_trading.account import record_equity_snapshot
from paper_trading.strategies import (
    TargetTrade, get_strategy_fn, HistoryProvider,
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


def _default_history_provider(ticker: str) -> Optional[pd.DataFrame]:
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


# ── Scan result type ──────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    account_id:      int
    scan_at:         datetime
    mode:            str            # "auto" | "manual"
    strategy:        str
    prices:          dict[str, float]
    generated:       int = 0        # total trades proposed by strategy
    filled:          int = 0        # executed immediately
    queued:          int = 0        # pending approval
    skipped:         int = 0        # rejected by engine (no price, insufficient cash, …)
    equity_before:   float = 0.0
    equity_after:    float = 0.0
    warnings:        list[str] = field(default_factory=list)
    filled_orders:   list[int] = field(default_factory=list)
    pending_orders:  list[int] = field(default_factory=list)

    def summary(self) -> str:
        return (f"Scan {self.scan_at:%Y-%m-%d %H:%M} · {self.strategy} · {self.mode}  "
                f"· generated={self.generated} filled={self.filled} "
                f"queued={self.queued} skipped={self.skipped}  "
                f"· equity ${self.equity_before:,.2f} → ${self.equity_after:,.2f}")


# ── Main entry point ──────────────────────────────────────────────────────────

def run_scan(
    account_id:       int,
    *,
    prices_provider:  Optional[PricesProvider]  = None,
    history_provider: Optional[HistoryProvider] = None,
) -> Optional[ScanResult]:
    """Scan the market once, execute trades (or queue them), snapshot equity."""
    prices_provider  = prices_provider  or _default_prices_provider
    history_provider = history_provider or _default_history_provider

    session = get_session()
    try:
        acct: PaperAccount = (session.query(PaperAccount)
                              .filter(PaperAccount.id == account_id).first())
        if acct is None or not acct.is_active:
            return None

        watchlist = [w.ticker for w in (session.query(PaperWatchlistItem)
                                        .filter(PaperWatchlistItem.account_id == account_id).all())]
        positions: list[PaperPosition] = (session.query(PaperPosition)
                                          .filter(PaperPosition.account_id == account_id)
                                          .filter(PaperPosition.shares > 0).all())

        tickers = sorted(set(watchlist) | {p.ticker for p in positions})
        prices  = prices_provider(tickers) if tickers else {}

        # Equity before any trades
        equity_before = acct.cash + sum(
            p.shares * prices.get(p.ticker, p.avg_cost) for p in positions
        )

        # Run the strategy (reads detached attributes, so safe)
        strategy_fn = get_strategy_fn(acct.strategy)
        trades: list[TargetTrade] = strategy_fn(
            acct, watchlist, positions, prices, history_provider
        )

        result = ScanResult(
            account_id    = account_id,
            scan_at       = datetime.utcnow(),
            mode          = acct.mode,
            strategy      = acct.strategy,
            prices        = prices,
            generated     = len(trades),
            equity_before = float(equity_before),
        )

        # Process trades in a deterministic order: SELLs first (free up cash), then BUYs.
        trades.sort(key=lambda t: 0 if t.side == "SELL" else 1)

        # In manual mode, remember which (ticker, side) pairs already have a
        # pending order so we don't duplicate the same intent on every scan.
        existing_pending: set[tuple[str, str]] = set()
        if acct.mode == "manual":
            existing_pending = {
                (o.ticker, o.side)
                for o in (session.query(PaperOrder)
                          .filter(PaperOrder.account_id == acct.id)
                          .filter(PaperOrder.status == "pending").all())
            }

        # ── Lite-pro guardrails ──────────────────────────────────────────────
        # Read configurable thresholds (with safe defaults) and pre-compute
        # state used by the per-trade gates inside the loop below.
        enforce_hours      = bool(settings.get("paper_enforce_market_hours", True))
        min_holding_min    = max(0, int(settings.get("paper_min_holding_minutes", 60)))
        anti_flap_min      = max(0, int(settings.get("paper_anti_flap_minutes",   30)))
        min_trade_usd      = max(0.0, float(settings.get("paper_min_trade_dollars", 50.0)))

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
            rows = (session.query(PaperOrder.ticker)
                    .filter(PaperOrder.account_id == acct.id)
                    .filter(PaperOrder.side       == "SELL")
                    .filter(PaperOrder.status     == "filled")
                    .filter(PaperOrder.filled_at  >= cutoff).all())
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
            if trade.side == "SELL" and min_holding_min > 0:
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
                    f"{trade.ticker} BUY bloqueado: anti-flap activo "
                    f"(SELL en últimos {anti_flap_min} min)."
                )
                continue

            # Gate 4 — minimum trade size (skip dust BUYs whose round-trip cost
            # would dominate any expected edge).
            if trade.side == "BUY" and min_trade_usd > 0:
                td = float(trade.target_dollars or 0.0)
                if 0 < td < min_trade_usd:
                    result.skipped += 1
                    result.warnings.append(
                        f"{trade.ticker} BUY bloqueado: tamaño ${td:.2f} < "
                        f"mínimo ${min_trade_usd:.2f}."
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
                    session, acct, trade,
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
        positions_after = (session.query(PaperPosition)
                           .filter(PaperPosition.account_id == account_id)
                           .filter(PaperPosition.shares > 0).all())
        equity_after = acct.cash + sum(
            p.shares * prices.get(p.ticker, p.avg_cost) for p in positions_after
        )
        result.equity_after = float(equity_after)

        session.commit()
    finally:
        session.close()

    # Snapshot outside the transaction — opens its own session
    record_equity_snapshot(account_id, prices)
    return result


# ── Manual-mode approvals ─────────────────────────────────────────────────────

def approve_order(
    order_id: int,
    *,
    prices_provider: Optional[PricesProvider] = None,
) -> Optional[PaperOrder]:
    """Fill a pending order at the current market price."""
    prices_provider = prices_provider or _default_prices_provider

    session = get_session()
    try:
        order: Optional[PaperOrder] = session.query(PaperOrder).filter(
            PaperOrder.id == order_id
        ).first()
        if order is None or order.status != "pending":
            return None

        acct = session.query(PaperAccount).filter(
            PaperAccount.id == order.account_id
        ).first()
        if acct is None:
            return None

        prices = prices_provider([order.ticker])
        px = prices.get(order.ticker)
        if px is None or not np.isfinite(px) or px <= 0:
            order.status = "expired"
            order.notes  = (order.notes or "") + "\n[approve] sin precio, expirada."
            order.decided_at = datetime.utcnow()
            session.commit()
            session.refresh(order); session.expunge(order)
            return order

        # Convert the pending order into a TargetTrade and fill.
        trade = TargetTrade(
            ticker         = order.ticker,
            side           = order.side,
            target_shares  = order.target_shares,
            target_dollars = order.target_dollars,
            reason         = f"approved: {order.reason or ''}".strip(),
            source         = order.source or "manual",
        )

        order.status     = "approved"
        order.decided_at = datetime.utcnow()

        filled = _fill_trade(session, acct, trade, price=px, reuse_order=order)
        session.commit()

        if filled is not None:
            session.refresh(filled)
            session.expunge(filled)
            return filled
        return order
    finally:
        session.close()


def reject_order(order_id: int, note: str = "") -> Optional[PaperOrder]:
    session = get_session()
    try:
        order = session.query(PaperOrder).filter(PaperOrder.id == order_id).first()
        if order is None or order.status != "pending":
            return None
        order.status     = "rejected"
        order.decided_at = datetime.utcnow()
        if note:
            order.notes = (order.notes or "") + f"\n[reject] {note}"
        session.commit()
        session.refresh(order); session.expunge(order)
        return order
    finally:
        session.close()


# ── Internal: create pending / fill trade ─────────────────────────────────────

def _create_pending_order(
    session,
    acct: PaperAccount,
    trade: TargetTrade,
    *,
    current_price: Optional[float] = None,
) -> PaperOrder:
    """
    Persist a TargetTrade as a pending PaperOrder.

    Si la suggestion es BUY y target_shares no fue seteado por la estrategia,
    lo computamos a partir de target_dollars + current_price + slippage para
    que el usuario vea un número de shares entero en la orden pendiente.
    Para SELL ya se setea target_shares; lo redondeamos hacia abajo a entero.
    """
    target_shares = trade.target_shares

    if (trade.side == "BUY" and target_shares is None
            and trade.target_dollars is not None
            and current_price is not None
            and np.isfinite(current_price) and current_price > 0):
        budget     = min(float(trade.target_dollars), acct.cash)
        fill_price = current_price * (1 + acct.slippage)
        raw_shares = (budget * (1 - acct.commission)) / fill_price
        int_shares = int(raw_shares)
        if int_shares >= 1:
            target_shares = float(int_shares)

    elif trade.side == "SELL" and target_shares is not None and target_shares > 0:
        target_shares = float(int(float(target_shares)))   # floor a entero
        if target_shares < 1.0:
            target_shares = trade.target_shares           # dejar lo original

    order = PaperOrder(
        account_id     = acct.id,
        ticker         = trade.ticker,
        side           = trade.side,
        target_shares  = target_shares,
        target_dollars = trade.target_dollars,
        reason         = trade.reason,
        source         = trade.source,
        status         = "pending",
    )
    session.add(order)
    session.flush()
    return order


def _fill_trade(
    session,
    acct:   PaperAccount,
    trade:  TargetTrade,
    *,
    price:  float,
    reuse_order: Optional[PaperOrder] = None,
) -> Optional[PaperOrder]:
    """
    Execute a trade against the live account state. Returns the filled
    PaperOrder (new or reused) or None if the trade couldn't happen
    (zero shares, zero cash, etc.).
    """
    side         = trade.side
    commission   = acct.commission
    slippage     = acct.slippage

    if side == "BUY":
        budget = trade.target_dollars if trade.target_dollars is not None else 0.0
        budget = min(float(budget), acct.cash)
        if budget <= 1e-6:
            return None
        fill_price  = price * (1 + slippage)

        # Shares ahora son ENTEROS — el usuario va a ejecutar manualmente en
        # un broker que no permite fracciones. Floor del cómputo crudo y
        # recalculamos el cash gastado a partir de las shares finales.
        raw_shares = (budget * (1 - commission)) / fill_price
        shares_got = float(int(raw_shares))   # floor a entero
        if shares_got < 1.0:
            return None

        # Real notional + commission a partir de las shares enteras.
        actual_notional = shares_got * fill_price
        commission_paid = actual_notional * commission
        actual_cost     = actual_notional + commission_paid
        # Edge case: si el actual_cost supera el budget por redondeo, recortar.
        if actual_cost > acct.cash + 1e-6:
            return None

        # Update / create position
        pos = (session.query(PaperPosition)
               .filter(PaperPosition.account_id == acct.id)
               .filter(PaperPosition.ticker     == trade.ticker)
               .first())
        if pos is None:
            pos = PaperPosition(
                account_id  = acct.id,
                ticker      = trade.ticker,
                shares      = shares_got,
                avg_cost    = fill_price,
                opened_at   = datetime.utcnow(),
                entry_reason = trade.reason,
            )
            session.add(pos)
        else:
            new_total_cost = pos.shares * pos.avg_cost + shares_got * fill_price
            pos.shares    += shares_got
            pos.avg_cost   = new_total_cost / pos.shares
            pos.updated_at = datetime.utcnow()
        acct.cash -= actual_cost

        slippage_cost = shares_got * (fill_price - price)
        return _stamp_order_filled(
            session, acct, trade, reuse_order,
            fill_price=fill_price, fill_shares=shares_got,
            commission_paid=commission_paid, slippage_cost=slippage_cost,
        )

    elif side == "SELL":
        pos = (session.query(PaperPosition)
               .filter(PaperPosition.account_id == acct.id)
               .filter(PaperPosition.ticker     == trade.ticker)
               .first())
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
            sell_shares = float(pos.shares)   # cierre total + residual
        else:
            sell_shares = float(int_want)     # trim parcial entero

        sell_shares = min(sell_shares, float(pos.shares))
        if sell_shares <= 1e-9:
            return None

        fill_price = price * (1 - slippage)
        proceeds   = sell_shares * fill_price * (1 - commission)
        pos.shares -= sell_shares
        pos.updated_at = datetime.utcnow()
        acct.cash += proceeds

        # If fully closed, drop the row.
        if pos.shares <= 1e-9:
            session.delete(pos)

        commission_paid = sell_shares * fill_price * commission
        slippage_cost   = sell_shares * (price - fill_price)
        return _stamp_order_filled(
            session, acct, trade, reuse_order,
            fill_price=fill_price, fill_shares=sell_shares,
            commission_paid=commission_paid, slippage_cost=slippage_cost,
        )

    return None


def _stamp_order_filled(
    session,
    acct: PaperAccount,
    trade: TargetTrade,
    reuse_order: Optional[PaperOrder],
    *,
    fill_price:      float,
    fill_shares:     float,
    commission_paid: float,
    slippage_cost:   float,
) -> PaperOrder:
    """Create or update a PaperOrder as 'filled' and return it."""
    now = datetime.utcnow()
    if reuse_order is None:
        order = PaperOrder(
            account_id     = acct.id,
            ticker         = trade.ticker,
            side           = trade.side,
            target_shares  = trade.target_shares,
            target_dollars = trade.target_dollars,
            reason         = trade.reason,
            source         = trade.source,
            status         = "filled",
            created_at     = now,
            filled_at      = now,
            fill_price     = float(fill_price),
            fill_shares    = float(fill_shares),
            commission_paid= float(commission_paid),
            slippage_cost  = float(slippage_cost),
        )
        session.add(order)
        session.flush()
    else:
        reuse_order.status          = "filled"
        reuse_order.filled_at       = now
        reuse_order.fill_price      = float(fill_price)
        reuse_order.fill_shares     = float(fill_shares)
        reuse_order.commission_paid = float(commission_paid)
        reuse_order.slippage_cost   = float(slippage_cost)
        order = reuse_order
    return order
