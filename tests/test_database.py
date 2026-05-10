"""
Sanity tests for the SQLAlchemy layer:
- session_scope commits/rolls-back as advertised
- Foreign-key cascades work (delete portfolio → positions vanish)
- Indexes that we declared actually exist on the in-memory DB
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect

from database.models import (
    Alert, Portfolio, Position, Transaction,
    session_scope,
)


def test_session_scope_commits_on_clean_exit(test_db):
    with session_scope() as s:
        s.add(Portfolio(name="X", currency="USD"))
    # Commit happened — the row must be visible in a *new* session.
    with session_scope() as s:
        assert s.query(Portfolio).filter_by(name="X").count() == 1


def test_session_scope_rolls_back_on_error(test_db):
    """If the body raises, no row should be persisted."""
    with pytest.raises(RuntimeError):
        with session_scope() as s:
            s.add(Portfolio(name="Y", currency="USD"))
            raise RuntimeError("boom")
    with session_scope() as s:
        assert s.query(Portfolio).filter_by(name="Y").count() == 0


def test_position_cascade_delete(test_db):
    """Deleting a portfolio must cascade to its positions and alerts."""
    with session_scope() as s:
        p = Portfolio(name="Cascade", currency="USD")
        s.add(p)
        s.flush()
        s.add(Position(portfolio_id=p.id, ticker="AAPL", quantity=10, avg_buy_price=150))
        s.add(Alert(portfolio_id=p.id, ticker="AAPL", alert_type="ABOVE", target_value=200))
        pid = p.id

    with session_scope() as s:
        p = s.get(Portfolio, pid)   # SA 2.x form, replaces legacy Query.get
        s.delete(p)

    with session_scope() as s:
        assert s.query(Position).filter_by(portfolio_id=pid).count() == 0
        assert s.query(Alert).filter_by(portfolio_id=pid).count() == 0


def test_transactions_belong_to_position(test_db):
    """Cascade also applies one level deeper: portfolio → position → transactions."""
    with session_scope() as s:
        p = Portfolio(name="Tx", currency="USD")
        s.add(p)
        s.flush()
        pos = Position(portfolio_id=p.id, ticker="MSFT", quantity=5, avg_buy_price=300)
        s.add(pos)
        s.flush()
        s.add(Transaction(position_id=pos.id, transaction_type="BUY", quantity=5, price=300))
        pid = p.id
        pos_id = pos.id

    with session_scope() as s:
        s.delete(s.get(Portfolio, pid))

    with session_scope() as s:
        assert s.query(Transaction).filter_by(position_id=pos_id).count() == 0


def test_declared_indexes_exist_on_db(test_db):
    """Make sure the indexes we declared in models.py made it into the DDL."""
    insp = inspect(test_db)
    pos_idx = {ix["name"] for ix in insp.get_indexes("positions")}
    tx_idx  = {ix["name"] for ix in insp.get_indexes("transactions")}
    alerts_idx = {ix["name"] for ix in insp.get_indexes("alerts")}
    assert "ix_positions_portfolio_ticker" in pos_idx
    assert "ix_transactions_position_date" in tx_idx
    assert "ix_alerts_active_portfolio" in alerts_idx
    assert "ix_alerts_ticker_active"   in alerts_idx
