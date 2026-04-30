"""
Database models for paper-trading accounts.

Reuses the existing ``Base`` from ``database.models`` so that
``database.init_db()`` creates these tables automatically via
``Base.metadata.create_all``. Nothing needs to be registered manually —
as long as this module is imported before ``init_db()`` runs.

Table summary
-------------
``paper_accounts``          One row per simulated account. Each account has
                            its own strategy, execution mode, allocation
                            settings and cash balance.
``paper_watchlist``         Tickers the account's strategy may consider for
                            entry (the trading universe).
``paper_positions``         Open positions in an account (VWAP ``avg_cost``).
``paper_orders``            Every order ever generated — pending (manual
                            mode), filled (auto mode or approved-manual),
                            or rejected/expired. Serves as the full audit
                            trail.
``paper_equity_snapshots``  Time-series of cash + market value, populated
                            on every scan. Powers the equity curve chart.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, DateTime, Boolean, ForeignKey, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database.models import Base


# ── Valid enum-like values (validated in the code layer, not via CHECK) ───────

STRATEGIES   = {"analyze_single", "portfolio_engine"}
MODES        = {"auto", "manual"}
ALLOC_MODES  = {"equal_weight", "signal_weighted", "inverse_vol", "fixed_amount"}
ORDER_SIDES  = {"BUY", "SELL"}
ORDER_STATUS = {"pending", "approved", "rejected", "filled", "expired", "cancelled"}


class PaperAccount(Base):
    """One simulated trading account, with its own config and cash ledger."""
    __tablename__ = "paper_accounts"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    name            = Column(String(100), nullable=False, unique=True)
    description     = Column(Text, nullable=True)

    # Strategy & execution
    strategy        = Column(String(30), nullable=False, default="analyze_single")
    mode            = Column(String(10), nullable=False, default="auto")
    allocation_mode = Column(String(30), nullable=False, default="equal_weight")
    max_positions   = Column(Integer, nullable=False, default=5)
    fixed_amount    = Column(Float,   nullable=False, default=5_000.0)

    # Capital & costs
    initial_capital = Column(Float, nullable=False, default=50_000.0)
    cash            = Column(Float, nullable=False, default=50_000.0)
    commission      = Column(Float, nullable=False, default=0.001)   # 0.10 %
    slippage        = Column(Float, nullable=False, default=0.0005)  # 0.05 %

    # Rebalance policy
    drift_threshold        = Column(Float,   nullable=False, default=0.25)
    monthly_rebalance      = Column(Boolean, nullable=False, default=True)
    last_monthly_rebalance = Column(DateTime, nullable=True)

    # Lifecycle
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    last_scan_at  = Column(DateTime, nullable=True)

    # Relationships
    watchlist = relationship("PaperWatchlistItem",   back_populates="account",
                             cascade="all, delete-orphan")
    positions = relationship("PaperPosition",        back_populates="account",
                             cascade="all, delete-orphan")
    orders    = relationship("PaperOrder",           back_populates="account",
                             cascade="all, delete-orphan")
    snapshots = relationship("PaperEquitySnapshot",  back_populates="account",
                             cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return (f"<PaperAccount(name={self.name!r}, strategy={self.strategy}, "
                f"mode={self.mode}, cash=${self.cash:,.2f})>")


class PaperWatchlistItem(Base):
    """A ticker the account's strategy may BUY into."""
    __tablename__ = "paper_watchlist"
    __table_args__ = (
        UniqueConstraint("account_id", "ticker", name="uq_paper_watchlist_acct_ticker"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False)
    ticker     = Column(String(20), nullable=False)
    added_at   = Column(DateTime, default=datetime.utcnow)

    account = relationship("PaperAccount", back_populates="watchlist")

    def __repr__(self) -> str:
        return f"<PaperWatchlistItem({self.ticker})>"


class PaperPosition(Base):
    """Current open position in a paper account (VWAP avg_cost)."""
    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("account_id", "ticker", name="uq_paper_position_acct_ticker"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    account_id    = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False)
    ticker        = Column(String(20), nullable=False)
    shares        = Column(Float, nullable=False, default=0.0)
    avg_cost      = Column(Float, nullable=False, default=0.0)   # VWAP incl. fees/slippage
    opened_at     = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    entry_reason  = Column(String(100), nullable=True)

    account = relationship("PaperAccount", back_populates="positions")

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost

    def __repr__(self) -> str:
        return f"<PaperPosition({self.ticker} x{self.shares:.4f} @ ${self.avg_cost:.2f})>"


class PaperOrder(Base):
    """
    A single order in the account's lifecycle.

    Auto mode: created with ``status='filled'`` immediately and the cash/
    position ledger is updated atomically.

    Manual mode: created with ``status='pending'`` and waits for
    ``approve_order`` / ``reject_order``.
    """
    __tablename__ = "paper_orders"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    account_id      = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False)
    ticker          = Column(String(20), nullable=False)
    side            = Column(String(4),  nullable=False)   # "BUY" | "SELL"

    # Intent
    target_shares   = Column(Float, nullable=True)   # approx; SELL may use all shares
    target_dollars  = Column(Float, nullable=True)
    reason          = Column(String(200), nullable=True)   # "signal", "drift", "monthly", ...
    source          = Column(String(30), nullable=True)    # strategy name that generated it

    # Status flow
    status          = Column(String(20), nullable=False, default="pending")
    created_at      = Column(DateTime, default=datetime.utcnow)
    decided_at      = Column(DateTime, nullable=True)     # approved / rejected
    filled_at       = Column(DateTime, nullable=True)     # actually executed

    # Fill details (null if not filled)
    fill_price      = Column(Float, nullable=True)
    fill_shares     = Column(Float, nullable=True)
    commission_paid = Column(Float, nullable=True)
    slippage_cost   = Column(Float, nullable=True)

    notes           = Column(Text, nullable=True)

    account = relationship("PaperAccount", back_populates="orders")

    @property
    def fill_value(self) -> float:
        if self.fill_shares is None or self.fill_price is None:
            return 0.0
        return self.fill_shares * self.fill_price

    def __repr__(self) -> str:
        return (f"<PaperOrder({self.side} {self.ticker} "
                f"status={self.status} shares={self.target_shares})>")


class PaperEquitySnapshot(Base):
    """One equity-curve point per scan (or manual snapshot)."""
    __tablename__ = "paper_equity_snapshots"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    account_id      = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False)
    snapshot_at     = Column(DateTime, default=datetime.utcnow)
    cash            = Column(Float, nullable=False)
    positions_value = Column(Float, nullable=False)
    total_equity    = Column(Float, nullable=False)

    account = relationship("PaperAccount", back_populates="snapshots")

    def __repr__(self) -> str:
        return (f"<PaperEquitySnapshot(acct={self.account_id} "
                f"at={self.snapshot_at:%Y-%m-%d %H:%M} "
                f"${self.total_equity:,.2f})>")
