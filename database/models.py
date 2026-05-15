"""
Database models for FinanzIAs investment tracker.
Uses SQLAlchemy ORM with SQLite backend.

Session usage
-------------
Prefer the ``session_scope()`` context manager for new code:

    from database.models import session_scope
    with session_scope() as session:
        ...
        # commit happens automatically on success;
        # rollback + re-raise on exception; close always.

The legacy ``get_session()`` helper still exists for incremental migration —
remember to wrap its usage in try/finally and call ``session.close()``.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    relationship,
    scoped_session,
    sessionmaker,
)
from sqlalchemy.orm import (
    Session as SASession,
)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "finanzias.db")
# ``check_same_thread=False`` permits a single connection to be reused across
# threads — safe for SQLite as long as we serialise writes (which SQLAlchemy's
# default transactional flow does). Required by the paper-trading scheduler
# that runs scans on QThreads.
ENGINE = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)

# Single sessionmaker bound to the engine. Re-using one factory is more
# efficient than re-building it on every ``get_session()`` call.
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, expire_on_commit=False)

# Thread-local session registry. Useful in long-running background jobs
# (paper-trading scheduler, alert checker) that want a single session per
# thread instead of opening one per call. Always remember to call
# ``ScopedSession.remove()`` when the thread exits or after a logical unit
# of work, otherwise the connection stays bound.
ScopedSession = scoped_session(SessionLocal)


class Base(DeclarativeBase):
    pass


def utcnow_naive() -> datetime:
    """
    Naive UTC timestamp for column defaults.

    All ``DateTime`` columns in this schema are timezone-naive (we never
    declared ``DateTime(timezone=True)``), so historical rows are stored
    as naive UTC. ``datetime.utcnow`` was the obvious source but is
    deprecated as of Python 3.12 with a removal scheduled for the future.

    This helper returns the same value (year/month/day/h/m/s, no tzinfo)
    by going through ``datetime.now(timezone.utc)`` and stripping the
    tzinfo, so on-disk values stay binary-compatible with what
    ``datetime.utcnow`` was producing before.

    Usage::

        created_at = Column(DateTime, default=utcnow_naive)
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Portfolio(Base):
    """Represents a named investment portfolio."""

    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    currency = Column(String(10), default="USD")
    created_at = Column(DateTime, default=utcnow_naive)

    positions = relationship("Position", back_populates="portfolio", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="portfolio", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Portfolio(name={self.name})>"


class Position(Base):
    """Represents a stock holding within a portfolio."""

    __tablename__ = "positions"
    __table_args__ = (Index("ix_positions_portfolio_ticker", "portfolio_id", "ticker"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    company_name = Column(String(200), nullable=True)
    quantity = Column(Float, nullable=False)
    avg_buy_price = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    sector = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    purchase_date = Column(DateTime, nullable=True)  # actual date the shares were bought

    portfolio = relationship("Portfolio", back_populates="positions")
    transactions = relationship("Transaction", back_populates="position", cascade="all, delete-orphan")

    @property
    def total_invested(self):
        return self.quantity * self.avg_buy_price

    def __repr__(self):
        return f"<Position(ticker={self.ticker}, qty={self.quantity})>"


class Transaction(Base):
    """Records of individual buy/sell transactions."""

    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_position_date", "position_id", "date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False, index=True)
    transaction_type = Column(String(10), nullable=False)  # "BUY" or "SELL"
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fees = Column(Float, default=0.0)
    date = Column(DateTime, default=utcnow_naive, index=True)
    notes = Column(Text, nullable=True)

    position = relationship("Position", back_populates="transactions")

    @property
    def total_value(self):
        return self.quantity * self.price + self.fees

    def __repr__(self):
        return f"<Transaction({self.transaction_type} {self.quantity} @ {self.price})>"


class Alert(Base):
    """Price alert for a specific ticker."""

    __tablename__ = "alerts"
    __table_args__ = (
        # Hot path: AlertManager.check_alerts filters on is_active + portfolio_id.
        Index("ix_alerts_active_portfolio", "is_active", "portfolio_id"),
        Index("ix_alerts_ticker_active", "ticker", "is_active"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    alert_type = Column(String(20), nullable=False)  # "ABOVE", "BELOW", "CHANGE_PCT"
    target_value = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
    message = Column(Text, nullable=True)

    portfolio = relationship("Portfolio", back_populates="alerts")

    def __repr__(self):
        return f"<Alert({self.ticker} {self.alert_type} {self.target_value})>"


class PriceCache(Base):
    """Cache for recently fetched prices to reduce API calls."""

    __tablename__ = "price_cache"
    __table_args__ = (
        # Hot path: lookup latest entry per ticker within TTL window.
        Index("ix_price_cache_ticker_fetched", "ticker", "fetched_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False, index=True)
    price = Column(Float, nullable=False)
    change_pct = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    market_cap = Column(Float, nullable=True)
    fetched_at = Column(DateTime, default=utcnow_naive, index=True)

    def __repr__(self):
        return f"<PriceCache({self.ticker} @ {self.price})>"


class DividendCache(Base):
    """
    Stores total dividend income per ticker since a given purchase date.
    Refreshed on demand — not on every price update.
    """

    __tablename__ = "dividend_cache"
    __table_args__ = (Index("ix_dividend_cache_ticker_since", "ticker", "since_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False, index=True)
    since_date = Column(DateTime, nullable=False)  # purchase date of position
    total_per_share = Column(Float, nullable=False, default=0.0)  # cumulative $/share
    fetched_at = Column(DateTime, default=utcnow_naive)

    def __repr__(self):
        return f"<DividendCache({self.ticker} ${self.total_per_share}/share since {self.since_date.date()})>"


class HistoricalDataCache(Base):
    """
    Cache for OHLCV historical data to avoid repeated yfinance downloads.
    Keyed by (ticker, period, interval). At most one entry per combination.
    """

    __tablename__ = "historical_data_cache"
    __table_args__ = (Index("ix_hist_cache_key", "ticker", "period", "interval"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False)
    period = Column(String(10), nullable=False)  # e.g. "1y", "6mo"
    interval = Column(String(10), nullable=False)  # e.g. "1d", "1h"
    data_json = Column(Text, nullable=False)  # DataFrame serialized via to_json(orient="split")
    fetched_at = Column(DateTime, default=utcnow_naive)

    def __repr__(self):
        return f"<HistoricalDataCache({self.ticker} {self.period}/{self.interval} @ {self.fetched_at})>"


def init_db():
    """Create all tables, run lightweight migrations, and seed default portfolio."""
    # Register paper-trading models so their tables are included in create_all.
    # Import here (not at module top) to avoid a circular import.
    try:
        import paper_trading.models  # noqa: F401
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception("paper_trading.models import failed")
    Base.metadata.create_all(ENGINE)
    _migrate()
    with session_scope() as session:
        if session.query(Portfolio).count() == 0:
            default = Portfolio(name="Mi Portafolio", description="Portafolio principal", currency="USD")
            session.add(default)


def _migrate():
    """Add new columns to existing tables without losing data."""
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # positions.purchase_date
    cur.execute("PRAGMA table_info(positions)")
    cols = [row[1] for row in cur.fetchall()]
    if "purchase_date" not in cols:
        cur.execute("ALTER TABLE positions ADD COLUMN purchase_date DATETIME")
        conn.commit()
    conn.close()


def get_session() -> SASession:
    """
    Return a new SQLAlchemy session. **Legacy** API — prefer ``session_scope()``.
    Caller is responsible for ``session.close()`` (use try/finally).
    """
    return SessionLocal()


@contextmanager
def session_scope() -> "Iterator[SASession]":
    """
    Context manager around a SQLAlchemy session.

    Behaviour
    ---------
    - Yields a fresh ``Session`` bound to the global engine.
    - Commits at the end of the block on normal exit.
    - Rolls back and re-raises on exception.
    - Always closes the session.

    Usage
    -----
        with session_scope() as session:
            session.add(obj)
            # implicit commit on exit
    """
    session: SASession = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
