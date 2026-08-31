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
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base, utcnow_naive

# ── Valid enum-like values (validated in the code layer, not via CHECK) ───────

STRATEGIES = {"analyze_single", "portfolio_engine"}
MODES = {"auto", "manual"}
ALLOC_MODES = {
    "equal_weight",
    "signal_weighted",
    "inverse_vol",
    "fixed_amount",
    "vol_target",
    "kelly_fractional",
}
ORDER_SIDES = {"BUY", "SELL"}
ORDER_STATUS = {"pending", "approved", "rejected", "filled", "expired", "cancelled"}


class PaperAccount(Base):
    """One simulated trading account, with its own config and cash ledger."""

    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Strategy & execution
    strategy: Mapped[str] = mapped_column(String(30), nullable=False, default="analyze_single")
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="auto")
    allocation_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="equal_weight")
    max_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    fixed_amount: Mapped[float] = mapped_column(Float, nullable=False, default=5_000.0)

    # Capital & costs
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=50_000.0)
    cash: Mapped[float] = mapped_column(Float, nullable=False, default=50_000.0)
    commission: Mapped[float] = mapped_column(Float, nullable=False, default=0.001)  # 0.10 %
    slippage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0005)  # 0.05 %

    # Rebalance policy
    drift_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    monthly_rebalance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_monthly_rebalance: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Notifications (T12). Per-account opt-out for Slack: when False, run_scan
    # skips the Slack summary for this account even if the global master switch
    # (slack_notifications_enabled) is on. Nullable for legacy rows; the engine
    # treats NULL as True (notify) so existing accounts keep notifying.
    slack_notify: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True)

    # Relationships
    watchlist = relationship("PaperWatchlistItem", back_populates="account", cascade="all, delete-orphan")
    positions = relationship("PaperPosition", back_populates="account", cascade="all, delete-orphan")
    orders = relationship("PaperOrder", back_populates="account", cascade="all, delete-orphan")
    snapshots = relationship("PaperEquitySnapshot", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return (
            f"<PaperAccount(name={self.name!r}, strategy={self.strategy}, "
            f"mode={self.mode}, cash=${self.cash:,.2f})>"
        )


class PaperWatchlistItem(Base):
    """A ticker the account's strategy may BUY into."""

    __tablename__ = "paper_watchlist"
    __table_args__ = (
        UniqueConstraint("account_id", "ticker", name="uq_paper_watchlist_acct_ticker"),
        Index("ix_paper_watchlist_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("paper_accounts.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    added_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)

    account = relationship("PaperAccount", back_populates="watchlist")

    def __repr__(self) -> str:
        return f"<PaperWatchlistItem({self.ticker})>"


class PaperPosition(Base):
    """Current open position in a paper account (VWAP avg_cost)."""

    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("account_id", "ticker", name="uq_paper_position_acct_ticker"),
        # Hot path: get_positions filters account_id + shares > 0.
        Index("ix_paper_positions_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("paper_accounts.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # VWAP incl. fees/slippage
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    entry_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Highest live price seen since the position was opened (or partially
    # added to). Powers the ATR trailing-stop gate. NULL on legacy rows and
    # on freshly-created positions until the first scan updates it.
    high_water_mark: Mapped[float | None] = mapped_column(Float, nullable=True)

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
    __table_args__ = (
        # Engine queries: account_id + status (pending / filled within window).
        Index("ix_paper_orders_account_status", "account_id", "status"),
        Index("ix_paper_orders_account_filled", "account_id", "filled_at"),
        Index("ix_paper_orders_ticker_filled", "ticker", "filled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("paper_accounts.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # "BUY" | "SELL"

    # Intent
    target_shares: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # approx; SELL may use all shares
    target_dollars: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # "signal", "drift", "monthly", ...
    source: Mapped[str | None] = mapped_column(String(30), nullable=True)  # strategy name that generated it
    # Conviction score in [0,1] produced by the strategy. Nullable for legacy
    # rows and for synthetic orders (e.g. drift/monthly rebalances) that don't
    # have a model probability behind them. Used by analytics + future gates.
    signal_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Status flow
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # approved / rejected
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # actually executed

    # Fill details (null if not filled)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fill_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission_paid: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    account = relationship("PaperAccount", back_populates="orders")

    @property
    def fill_value(self) -> float:
        if self.fill_shares is None or self.fill_price is None:
            return 0.0
        return self.fill_shares * self.fill_price

    def __repr__(self) -> str:
        return f"<PaperOrder({self.side} {self.ticker} status={self.status} shares={self.target_shares})>"


class PaperEquitySnapshot(Base):
    """One equity-curve point per scan (or manual snapshot)."""

    __tablename__ = "paper_equity_snapshots"
    __table_args__ = (Index("ix_paper_equity_account_at", "account_id", "snapshot_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("paper_accounts.id"), nullable=False)
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    positions_value: Mapped[float] = mapped_column(Float, nullable=False)
    total_equity: Mapped[float] = mapped_column(Float, nullable=False)
    # Estimated annualised book volatility at snapshot time (T10). Nullable:
    # NULL when the overlay is disabled or there isn't enough history to
    # estimate σ. Powers monitoring of how close the book runs to its vol target.
    portfolio_sigma: Mapped[float | None] = mapped_column(Float, nullable=True)

    account = relationship("PaperAccount", back_populates="snapshots")

    def __repr__(self) -> str:
        return (
            f"<PaperEquitySnapshot(acct={self.account_id} "
            f"at={self.snapshot_at:%Y-%m-%d %H:%M} "
            f"${self.total_equity:,.2f})>"
        )
