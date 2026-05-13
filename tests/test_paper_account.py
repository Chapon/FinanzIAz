"""
Tests for ``paper_trading.account`` — CRUD on ``PaperAccount`` and
derived metrics (``compute_equity``, watchlist mutations).
"""

from __future__ import annotations

import pytest

from config.errors import ValidationError
from paper_trading.account import (
    add_watchlist_tickers,
    compute_equity,
    count_orders,
    create_account,
    delete_account,
    get_account,
    get_orders,
    get_pending_orders,
    get_watchlist,
    list_accounts,
    remove_watchlist_ticker,
    update_account_config,
)


def _make_account(name: str = "Test", **kwargs):
    return create_account(
        name=name,
        initial_capital=10_000.0,
        commission=0.001,
        slippage=0.0005,
        **kwargs,
    )


def test_create_and_get_account(test_db):
    a = _make_account()
    assert a.id is not None
    assert a.name == "Test"
    assert a.cash == pytest.approx(10_000.0)

    fetched = get_account(a.id)
    assert fetched is not None
    assert fetched.name == "Test"


def test_create_account_rejects_invalid_strategy(test_db):
    with pytest.raises(ValidationError):
        _make_account(strategy="not_a_real_strategy")


def test_create_account_rejects_invalid_mode(test_db):
    with pytest.raises(ValidationError):
        _make_account(mode="bogus")


def test_list_accounts_filters_active_only(test_db):
    _make_account(name="A")
    a2 = _make_account(name="B")
    update_account_config(a2.id, is_active=False)

    all_accts = list_accounts()
    assert {a.name for a in all_accts} == {"A", "B"}

    actives = list_accounts(active_only=True)
    assert {a.name for a in actives} == {"A"}


def test_delete_account_returns_true_when_exists(test_db):
    a = _make_account()
    assert delete_account(a.id) is True
    assert get_account(a.id) is None


def test_delete_missing_account_returns_false(test_db):
    assert delete_account(99_999) is False


def test_update_account_config(test_db):
    a = _make_account()
    updated = update_account_config(a.id, commission=0.005, mode="manual")
    assert updated is not None
    assert updated.commission == pytest.approx(0.005)
    assert updated.mode == "manual"


def test_update_account_rejects_invalid_mode(test_db):
    a = _make_account()
    with pytest.raises(ValidationError):
        update_account_config(a.id, mode="bogus")


def test_watchlist_add_and_remove(test_db):
    a = _make_account()
    n = add_watchlist_tickers(a.id, ["aapl", "MSFT", "AAPL"])  # dup intentional
    # AAPL appears twice in input — both get normalized to AAPL, second is skip.
    assert n == 2
    wl = get_watchlist(a.id)
    assert sorted(wl) == ["AAPL", "MSFT"]

    assert remove_watchlist_ticker(a.id, "AAPL") is True
    assert get_watchlist(a.id) == ["MSFT"]
    # Removing again is a no-op (returns False).
    assert remove_watchlist_ticker(a.id, "AAPL") is False


def test_compute_equity_handles_empty_account(test_db):
    a = _make_account()
    eq = compute_equity(a.id, prices={})
    assert eq["cash"] == pytest.approx(10_000.0)
    assert eq["positions_value"] == pytest.approx(0.0)
    assert eq["total_equity"] == pytest.approx(10_000.0)
    assert eq["per_position"] == []


def test_compute_equity_for_unknown_account(test_db):
    eq = compute_equity(99_999, prices={"AAPL": 200.0})
    assert eq["total_equity"] == pytest.approx(0.0)
    assert eq["per_position"] == []


def test_get_orders_pagination(test_db):
    """Verify the new ``offset`` parameter works."""
    from datetime import datetime

    from database.models import session_scope
    from paper_trading.models import PaperOrder

    a = _make_account()
    # Insert 5 orders directly
    with session_scope() as session:
        for i in range(5):
            session.add(
                PaperOrder(
                    account_id=a.id,
                    ticker="AAPL",
                    side="BUY",
                    target_dollars=100.0 * (i + 1),
                    status="filled",
                    created_at=datetime(2026, 1, 1 + i),
                    filled_at=datetime(2026, 1, 1 + i),
                    fill_price=150.0,
                    fill_shares=1.0,
                )
            )

    assert count_orders(a.id) == 5
    assert count_orders(a.id, status="pending") == 0

    page1 = get_orders(a.id, limit=2, offset=0)
    page2 = get_orders(a.id, limit=2, offset=2)
    page3 = get_orders(a.id, limit=2, offset=4)

    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1
    # Ordered most-recent first → no overlap between pages
    ids = {o.id for o in page1 + page2 + page3}
    assert len(ids) == 5


def test_get_pending_orders_filters_correctly(test_db):
    from database.models import session_scope
    from paper_trading.models import PaperOrder

    a = _make_account()
    with session_scope() as session:
        session.add(
            PaperOrder(account_id=a.id, ticker="AAPL", side="BUY", target_dollars=100, status="pending")
        )
        session.add(
            PaperOrder(
                account_id=a.id,
                ticker="MSFT",
                side="BUY",
                target_dollars=100,
                status="filled",
                fill_price=200,
                fill_shares=1,
            )
        )
    pending = get_pending_orders(a.id)
    assert len(pending) == 1
    assert pending[0].ticker == "AAPL"
