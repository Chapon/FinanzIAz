"""
Database models for FinanzIAs investment tracker.
Uses SQLAlchemy ORM with SQLite backend.
"""
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, Float, String,
    DateTime, Boolean, ForeignKey, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "finanzias.db")
ENGINE = create_engine(f"sqlite:///{DB_PATH}", echo=False)


class Base(DeclarativeBase):
    pass


class Portfolio(Base):
    """Represents a named investment portfolio."""
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    currency = Column(String(10), default="USD")
    created_at = Column(DateTime, default=datetime.utcnow)

    positions = relationship("Position", back_populates="portfolio", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="portfolio", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Portfolio(name={self.name})>"


class Position(Base):
    """Represents a stock holding within a portfolio."""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    company_name = Column(String(200), nullable=True)
    quantity = Column(Float, nullable=False)
    avg_buy_price = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    sector = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    purchase_date = Column(DateTime, nullable=True)   # actual date the shares were bought

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

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False)
    transaction_type = Column(String(10), nullable=False)  # "BUY" or "SELL"
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fees = Column(Float, default=0.0)
    date = Column(DateTime, default=datetime.utcnow)
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    alert_type = Column(String(20), nullable=False)  # "ABOVE", "BELOW", "CHANGE_PCT"
    target_value = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True)
    triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    message = Column(Text, nullable=True)

    portfolio = relationship("Portfolio", back_populates="alerts")

    def __repr__(self):
        return f"<Alert({self.ticker} {self.alert_type} {self.target_value})>"


class PriceCache(Base):
    """Cache for recently fetched prices to reduce API calls."""
    __tablename__ = "price_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False)
    price = Column(Float, nullable=False)
    change_pct = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    market_cap = Column(Float, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<PriceCache({self.ticker} @ {self.price})>"


class DividendCache(Base):
    """
    Stores total dividend income per ticker since a given purchase date.
    Refreshed on demand — not on every price update.
    """
    __tablename__ = "dividend_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False)
    since_date = Column(DateTime, nullable=False)   # purchase date of position
    total_per_share = Column(Float, nullable=False, default=0.0)  # cumulative $/share
    fetched_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DividendCache({self.ticker} ${self.total_per_share}/share since {self.since_date.date()})>"


def init_db():
    """Create all tables, run lightweight migrations, and seed default portfolio."""
    # Register paper-trading models so their tables are included in create_all.
    # Import here (not at module top) to avoid a circular import.
    try:
        import paper_trading.models  # noqa: F401
    except Exception as e:
        print(f"[init_db] paper_trading.models import failed: {e}")
    Base.metadata.create_all(ENGINE)
    _migrate()
    Session = sessionmaker(bind=ENGINE)
    session = Session()
    try:
        if session.query(Portfolio).count() == 0:
            default = Portfolio(
                name="Mi Portafolio",
                description="Portafolio principal",
                currency="USD"
            )
            session.add(default)
            session.commit()
    finally:
        session.close()


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


def get_session():
    """Return a new SQLAlchemy session."""
    Session = sessionmaker(bind=ENGINE)
    return Session()
