"""
Account-layer helpers for paper trading.

Provides CRUD operations over ``PaperAccount`` and friends, plus a few
derived metrics (equity, unrealized P&L, positions snapshot). All functions
open their own session via ``session_scope`` and return detached objects so
callers don't have to worry about SQLAlchemy session lifecycle.
"""

from __future__ import annotations

from config.errors import ValidationError
from database.models import session_scope, utcnow_naive
from paper_trading.models import (
    ALLOC_MODES,
    MODES,
    STRATEGIES,
    PaperAccount,
    PaperEquitySnapshot,
    PaperOrder,
    PaperPosition,
    PaperWatchlistItem,
)

# ── Account CRUD ──────────────────────────────────────────────────────────────


def create_account(
    *,
    name: str,
    strategy: str = "analyze_single",
    mode: str = "auto",
    allocation_mode: str = "equal_weight",
    max_positions: int = 5,
    fixed_amount: float = 5_000.0,
    initial_capital: float = 50_000.0,
    commission: float = 0.001,
    slippage: float = 0.0005,
    drift_threshold: float = 0.25,
    monthly_rebalance: bool = True,
    slack_notify: bool = True,
    description: str = "",
) -> PaperAccount:
    """Create and persist a paper-trading account."""
    if strategy not in STRATEGIES:
        raise ValidationError(f"strategy inválida: {strategy}")
    if mode not in MODES:
        raise ValidationError(f"mode inválido: {mode}")
    if allocation_mode not in ALLOC_MODES:
        raise ValidationError(f"allocation_mode inválido: {allocation_mode}")

    with session_scope() as session:
        acct = PaperAccount(
            name=name,
            description=description,
            strategy=strategy,
            mode=mode,
            allocation_mode=allocation_mode,
            max_positions=int(max_positions),
            fixed_amount=float(fixed_amount),
            initial_capital=float(initial_capital),
            cash=float(initial_capital),
            commission=float(commission),
            slippage=float(slippage),
            drift_threshold=float(drift_threshold),
            monthly_rebalance=bool(monthly_rebalance),
            slack_notify=bool(slack_notify),
        )
        session.add(acct)
        session.flush()
        session.refresh(acct)
        session.expunge(acct)
        return acct


def list_accounts(active_only: bool = False) -> list[PaperAccount]:
    with session_scope() as session:
        q = session.query(PaperAccount)
        if active_only:
            q = q.filter(PaperAccount.is_active.is_(True))
        out = q.order_by(PaperAccount.created_at.desc()).all()
        session.expunge_all()
        return out


def get_account(account_id: int) -> PaperAccount | None:
    with session_scope() as session:
        acct = session.query(PaperAccount).filter(PaperAccount.id == account_id).first()
        if acct is not None:
            session.expunge(acct)
        return acct


def delete_account(account_id: int) -> bool:
    with session_scope() as session:
        acct = session.query(PaperAccount).filter(PaperAccount.id == account_id).first()
        if acct is None:
            return False
        session.delete(acct)
        return True


def update_account_config(account_id: int, **fields) -> PaperAccount | None:
    """Patch mutable account fields (strategy, mode, allocation, thresholds…)."""
    allowed = {
        "strategy",
        "mode",
        "allocation_mode",
        "max_positions",
        "fixed_amount",
        "commission",
        "slippage",
        "drift_threshold",
        "monthly_rebalance",
        "slack_notify",
        "description",
        "is_active",
    }
    if "strategy" in fields and fields["strategy"] not in STRATEGIES:
        raise ValidationError(f"strategy inválida: {fields['strategy']}")
    if "mode" in fields and fields["mode"] not in MODES:
        raise ValidationError(f"mode inválido: {fields['mode']}")
    if "allocation_mode" in fields and fields["allocation_mode"] not in ALLOC_MODES:
        raise ValidationError(f"allocation_mode inválido: {fields['allocation_mode']}")

    with session_scope() as session:
        acct = session.query(PaperAccount).filter(PaperAccount.id == account_id).first()
        if acct is None:
            return None
        for k, v in fields.items():
            if k in allowed:
                setattr(acct, k, v)
        session.flush()
        session.refresh(acct)
        session.expunge(acct)
        return acct


# ── Watchlist CRUD ────────────────────────────────────────────────────────────


def add_watchlist_tickers(account_id: int, tickers: list[str]) -> int:
    """Insert new tickers; duplicates (account_id, ticker) are silently skipped."""
    added = 0
    with session_scope() as session:
        existing = {
            r.ticker
            for r in session.query(PaperWatchlistItem)
            .filter(PaperWatchlistItem.account_id == account_id)
            .all()
        }
        for t in tickers:
            tu = t.strip().upper()
            if not tu or tu in existing:
                continue
            session.add(PaperWatchlistItem(account_id=account_id, ticker=tu))
            existing.add(tu)
            added += 1
    return added


def remove_watchlist_ticker(account_id: int, ticker: str) -> bool:
    with session_scope() as session:
        item = (
            session.query(PaperWatchlistItem)
            .filter(PaperWatchlistItem.account_id == account_id)
            .filter(PaperWatchlistItem.ticker == ticker.upper())
            .first()
        )
        if item is None:
            return False
        session.delete(item)
        return True


def get_watchlist(account_id: int) -> list[str]:
    with session_scope() as session:
        rows = (
            session.query(PaperWatchlistItem)
            .filter(PaperWatchlistItem.account_id == account_id)
            .order_by(PaperWatchlistItem.added_at.asc())
            .all()
        )
        return [r.ticker for r in rows]


# ── Positions & P&L ───────────────────────────────────────────────────────────


def get_positions(account_id: int) -> list[PaperPosition]:
    with session_scope() as session:
        rows = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == account_id)
            .filter(PaperPosition.shares > 0)
            .order_by(PaperPosition.opened_at.asc())
            .all()
        )
        session.expunge_all()
        return rows


def get_position_entry_prices(account_id: int) -> dict[str, float]:
    """
    For each currently open position, return the fill_price of the earliest
    filled BUY order that happened on/after the position's ``opened_at``.

    This represents the original entry price (incl. slippage) of the position
    at the moment it was first opened — distinct from ``avg_cost`` which is
    the running VWAP that gets updated as the position is averaged into.

    Returns ``{ticker: entry_price}``. Tickers without a recoverable order
    (e.g. legacy positions from before the orders table existed) are omitted.
    """
    with session_scope() as session:
        positions = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == account_id)
            .filter(PaperPosition.shares > 0)
            .all()
        )
        out: dict[str, float] = {}
        for p in positions:
            q = (
                session.query(PaperOrder)
                .filter(PaperOrder.account_id == account_id)
                .filter(PaperOrder.ticker == p.ticker)
                .filter(PaperOrder.side == "BUY")
                .filter(PaperOrder.status == "filled")
            )
            if p.opened_at is not None:
                q = q.filter(PaperOrder.filled_at >= p.opened_at)
            order = q.order_by(PaperOrder.filled_at.asc()).first()
            if order is not None and order.fill_price is not None:
                out[p.ticker] = float(order.fill_price)
        return out


def compute_equity(account_id: int, prices: dict[str, float]) -> dict:
    """
    Mark-to-market equity given a {ticker: price} dict.
    Returns {'cash', 'positions_value', 'total_equity', 'per_position'}.
    """
    with session_scope() as session:
        acct = session.query(PaperAccount).filter(PaperAccount.id == account_id).first()
        if acct is None:
            return {"cash": 0.0, "positions_value": 0.0, "total_equity": 0.0, "per_position": []}
        positions = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == account_id)
            .filter(PaperPosition.shares > 0)
            .all()
        )
        per_pos = []
        pos_val = 0.0
        for p in positions:
            px = prices.get(p.ticker)
            mv = (p.shares * px) if (px is not None and px > 0) else p.shares * p.avg_cost
            pnl = mv - p.shares * p.avg_cost
            pnl_pct = (pnl / (p.shares * p.avg_cost)) if p.avg_cost > 0 else 0.0
            per_pos.append(
                {
                    "ticker": p.ticker,
                    "shares": p.shares,
                    "avg_cost": p.avg_cost,
                    "price": float(px) if px is not None else None,
                    "mv": float(mv),
                    "pnl": float(pnl),
                    "pnl_pct": float(pnl_pct),
                }
            )
            pos_val += mv
        return {
            "cash": float(acct.cash),
            "positions_value": float(pos_val),
            "total_equity": float(acct.cash + pos_val),
            "per_position": per_pos,
        }


def record_equity_snapshot(
    account_id: int,
    prices: dict[str, float],
    *,
    portfolio_sigma: float | None = None,
) -> PaperEquitySnapshot:
    """Persist a point on the equity curve using current prices.

    ``portfolio_sigma`` is the estimated annualised book volatility at snapshot
    time (T10); ``None`` when the overlay is off or there isn't enough history.
    """
    eq = compute_equity(account_id, prices)
    with session_scope() as session:
        snap = PaperEquitySnapshot(
            account_id=account_id,
            snapshot_at=utcnow_naive(),
            cash=eq["cash"],
            positions_value=eq["positions_value"],
            total_equity=eq["total_equity"],
            portfolio_sigma=portfolio_sigma,
        )
        session.add(snap)
        session.flush()
        session.refresh(snap)
        session.expunge(snap)
        return snap


def get_equity_curve(account_id: int, limit: int = 5_000) -> list[PaperEquitySnapshot]:
    with session_scope() as session:
        rows = (
            session.query(PaperEquitySnapshot)
            .filter(PaperEquitySnapshot.account_id == account_id)
            .order_by(PaperEquitySnapshot.snapshot_at.asc())
            .limit(limit)
            .all()
        )
        session.expunge_all()
        return rows


# ── Order queries (history / pending) ─────────────────────────────────────────


def get_orders(
    account_id: int,
    status: str | None = None,
    limit: int = 200,
    *,
    offset: int = 0,
) -> list[PaperOrder]:
    """
    Return at most ``limit`` orders for the account, ordered most-recent
    first. Use ``offset`` for paginated views (e.g. table page N: pass
    ``offset=N*limit``).
    """
    with session_scope() as session:
        q = session.query(PaperOrder).filter(PaperOrder.account_id == account_id)
        if status:
            q = q.filter(PaperOrder.status == status)
        rows = (
            q.order_by(PaperOrder.created_at.desc())
            .offset(max(0, int(offset)))
            .limit(max(1, int(limit)))
            .all()
        )
        session.expunge_all()
        return rows


def count_orders(account_id: int, status: str | None = None) -> int:
    """Total order count for the account (for paginator UI)."""
    with session_scope() as session:
        q = session.query(PaperOrder).filter(PaperOrder.account_id == account_id)
        if status:
            q = q.filter(PaperOrder.status == status)
        return int(q.count())


def get_pending_orders(account_id: int) -> list[PaperOrder]:
    return get_orders(account_id, status="pending")


# ── La cuenta VIVA para los jobs de fondo — Tarea 70 (CUENTA-VIVA-APP) ───────
#
# Por qué existe
# --------------
# Hasta el 2026-09-01, **todos** los jobs de fondo con alcance de cuenta tenían
# el literal ``1`` como default —dashboard, rebuild de ``surprise_profiles``,
# harvest de catalysts y sus cuatro herederos— y **ninguno miraba ``is_active``**.
# La cuenta 1 está pausada desde el 2026-07-01, así que durante dos meses:
#
# * el dashboard se re-estampó **todos los días** con fecha fresca mostrando una
#   cartera congelada (verificado: ``generated_at`` de hoy, ``last trade``
#   2026-07-01, las 5 posiciones zombie), y la cuenta viva no aparecía nunca;
# * el harvest recolectó noticias para los **52** tickers de la cuenta 1 en vez
#   de los **128** de la 2 — **79** nombres del universo vivo sin *una sola*
#   noticia en 45 días, y esa cobertura **no se recupera**: la fuente consulta
#   ``days_back=7`` (``data/news_sources.py:477``) y las noticias de yfinance son
#   sólo recientes.
#
# Del lado **harness** esto ya estaba resuelto desde la tarea 27
# (``analysis/harness_config.LIVE_ACCOUNT_ID``, con banner y tests). Del lado app
# no existía el equivalente, y **poner ``2`` en los siete lugares habría sido el
# mismo defecto con otro número**: el próximo cambio de cuenta lo reabre igual.
# Por eso esto **resuelve contra la DB**, no contra un literal.
#
# Las tres decisiones de diseño
# -----------------------------
# 1. **Un flag explícito se respeta, pero se GRITA si apunta a una pausada.** Si
#    el operador lo seteó, mandó él — pero el silencio es lo que dejó correr esto
#    dos meses, así que no puede quedarse callado.
# 2. **Sin flag, el default deja de ser un literal y pasa a ser "la activa".** Es
#    el corazón del arreglo: hoy ninguno de los flags está seteado, así que todos
#    tomaban el ``1`` hardcodeado.
# 3. **Devuelve ``None`` cuando no hay cuenta viva, y el caller SALTEA.** Un job
#    de fondo que no sabe sobre qué cuenta corre no debe elegir una: no correr es
#    la respuesta correcta. Y ante cualquier error de DB devuelve ``None`` en vez
#    de romper el scan (fail-safe, mismo criterio que los guards de la 59 y la 64).


def live_account_id(setting_key: str | None = None) -> int | None:
    """El id de la cuenta **viva** para un job de fondo, o ``None`` si no hay.

    ``setting_key`` es el flag que puede pisar la resolución automática (p. ej.
    ``"dashboard_refresh_account_id"``). Si está seteado se respeta **aunque
    apunte a una cuenta pausada**, pero en ese caso se loguea un WARNING: la
    decisión es del operador, el silencio no.

    Sin flag —que es el caso de **todos** los jobs hoy— se resuelve contra
    ``is_active``: una sola activa ⇒ ésa; varias ⇒ la de menor id, con aviso
    (ambigüedad, no error); ninguna ⇒ ``None``, y el job no corre.
    """
    from config.logging_config import get_logger

    log = get_logger(__name__)
    try:
        if setting_key:
            from config.settings_manager import settings

            crudo = settings.get(setting_key, None)
            if crudo:
                pedida = int(crudo)
                acct = get_account(pedida)
                if acct is None:
                    log.warning(
                        "%s=%s pero esa cuenta no existe — se resuelve la cuenta activa",
                        setting_key,
                        pedida,
                    )
                elif not acct.is_active:
                    log.warning(
                        "%s=%s apunta a una cuenta PAUSADA (%s, is_active=0). Se respeta "
                        "porque está seteado a mano, pero el job va a correr sobre una "
                        "cuenta que no opera (tarea 70).",
                        setting_key,
                        pedida,
                        acct.name,
                    )
                    return pedida
                else:
                    return pedida

        activas = list_accounts(active_only=True)
        if not activas:
            log.warning("no hay ninguna cuenta con is_active=1: el job de fondo no corre (tarea 70)")
            return None
        if len(activas) > 1:
            elegida = min(activas, key=lambda a: int(a.id))
            log.warning(
                "hay %d cuentas activas (%s): el job de fondo corre sobre la de menor id "
                "(%s). Seteá el flag correspondiente si querés otra (tarea 70).",
                len(activas),
                ", ".join(f"{a.id}:{a.name}" for a in activas),
                elegida.id,
            )
            return int(elegida.id)
        return int(activas[0].id)
    except Exception:
        log.exception("live_account_id falló — el job de fondo no corre (fail-safe, tarea 70)")
        return None
