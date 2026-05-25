"""
Tests for the recovery / idempotency safeguards added in the
``paper_trading.engine`` refactor:

- ``reconcile_account()`` expires stale pending orders
- ``_stamp_order_filled`` doesn't double-fill an already-filled order
"""

from __future__ import annotations

from datetime import datetime, timedelta

from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.engine import reconcile_account
from paper_trading.models import PaperOrder


def _make_account():
    return create_account(name="Recover", initial_capital=10_000.0)


def test_reconcile_expires_old_pending_orders(test_db):
    a = _make_account()
    cutoff_ago = utcnow_naive() - timedelta(hours=48)
    fresh_ago = utcnow_naive() - timedelta(hours=1)

    with session_scope() as session:
        session.add(
            PaperOrder(
                account_id=a.id,
                ticker="AAPL",
                side="BUY",
                target_dollars=100,
                status="pending",
                created_at=cutoff_ago,
            )
        )
        session.add(
            PaperOrder(
                account_id=a.id,
                ticker="MSFT",
                side="BUY",
                target_dollars=100,
                status="pending",
                created_at=fresh_ago,
            )
        )

    n = reconcile_account(a.id, expire_pending_after_hours=24)
    assert n == 1  # only the 48h-old one is expired

    with session_scope() as session:
        rows = session.query(PaperOrder).filter(PaperOrder.account_id == a.id).all()
        statuses = {r.ticker: r.status for r in rows}
    assert statuses["AAPL"] == "expired"
    assert statuses["MSFT"] == "pending"


def test_reconcile_does_nothing_when_no_stale_orders(test_db):
    a = _make_account()
    n = reconcile_account(a.id)
    assert n == 0


def test_reconcile_invalid_account_does_not_raise(test_db):
    """Bogus account id must not crash the scheduler startup loop."""
    n = reconcile_account(99_999)
    assert n == 0


def test_stamp_order_filled_is_idempotent(test_db):
    """
    Calling _stamp_order_filled twice on the same order shouldn't double-
    apply the fill metadata. The guard was added explicitly in the engine
    refactor to prevent double-spending cash on retries.
    """
    from paper_trading.engine import _stamp_order_filled
    from paper_trading.models import PaperAccount
    from paper_trading.strategies import TargetTrade

    a = _make_account()
    with session_scope() as session:
        acct_db = session.query(PaperAccount).filter(PaperAccount.id == a.id).first()
        order = PaperOrder(
            account_id=a.id,
            ticker="AAPL",
            side="BUY",
            target_dollars=100,
            status="pending",
        )
        session.add(order)
        session.flush()

        trade = TargetTrade(
            ticker="AAPL",
            side="BUY",
            target_dollars=100,
            target_shares=1,
            reason="test",
            source="test",
        )

        # First fill — succeeds, updates the order in place.
        _stamp_order_filled(
            session,
            acct_db,
            trade,
            order,
            fill_price=150.0,
            fill_shares=1.0,
            commission_paid=0.15,
            slippage_cost=0.05,
        )
        first_filled_at = order.filled_at
        assert order.status == "filled"
        assert order.fill_price == 150.0

        # Second call must be a no-op — the guard returns early when
        # ``status == 'filled'``.
        _stamp_order_filled(
            session,
            acct_db,
            trade,
            order,
            fill_price=999.0,
            fill_shares=99.0,
            commission_paid=99.0,
            slippage_cost=99.0,
        )
        assert order.fill_price == 150.0
        assert order.fill_shares == 1.0
        assert order.filled_at == first_filled_at
