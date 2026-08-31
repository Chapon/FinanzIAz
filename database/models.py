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
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
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
    # ``timeout`` (segundos) define cuánto espera una conexión por el lock de
    # escritura antes de levantar "database is locked". El default de sqlite3
    # es 5s; lo subimos para tolerar scans/harvests largos concurrentes.
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(ENGINE, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    """
    Configura cada conexión SQLite nueva para minimizar 'database is locked':

    - ``journal_mode=WAL``: permite lectores concurrentes con un escritor
      activo (el modo ``DELETE`` por defecto bloquea lectura y escritura).
    - ``busy_timeout``: a nivel SQLite, espera por el lock en vez de fallar
      de inmediato (refuerza el ``timeout`` de connect_args).
    - ``synchronous=NORMAL``: seguro bajo WAL y bastante más rápido en escritura.
    """
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")  # milisegundos
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), default="USD")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)

    positions = relationship("Position", back_populates="portfolio", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="portfolio", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Portfolio(name={self.name})>"


class Position(Base):
    """Represents a stock holding within a portfolio."""

    __tablename__ = "positions"
    __table_args__ = (Index("ix_positions_portfolio_ticker", "portfolio_id", "ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolios.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_buy_price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(10), default="USD")
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    purchase_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # actual date the shares were bought

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(Integer, ForeignKey("positions.id"), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "BUY" or "SELL"
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float | None] = mapped_column(Float, default=0.0)
    date: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    position = relationship("Position", back_populates="transactions")

    @property
    def total_value(self):
        # `fees` es nullable (default 0.0): una fila con NULL —solo alcanzable por
        # un INSERT crudo, no por el ORM— hacia reventar esto con TypeError. Se
        # trata como 0.0, que es el valor de ausencia que declara la propia
        # columna. Unico camino afectado: el que hoy se cae.
        return self.quantity * self.price + (self.fees or 0.0)

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolios.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "ABOVE" | "BELOW"
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True, index=True)
    # ALRT1: estado "pausada" separado de is_active (que ya significa "disparada"
    # cuando es False). Una alerta pausada no se evalúa en check_alerts.
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive, index=True)

    def __repr__(self):
        return f"<PriceCache({self.ticker} @ {self.price})>"


class DividendCache(Base):
    """
    Stores total dividend income per ticker since a given purchase date.
    Refreshed on demand — not on every price update.
    """

    __tablename__ = "dividend_cache"
    __table_args__ = (Index("ix_dividend_cache_ticker_since", "ticker", "since_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    since_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # purchase date of position
    total_per_share: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # cumulative $/share
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)

    def __repr__(self):
        return f"<DividendCache({self.ticker} ${self.total_per_share}/share since {self.since_date.date()})>"


class HistoricalDataCache(Base):
    """
    Cache for OHLCV historical data to avoid repeated yfinance downloads.
    Keyed by (ticker, period, interval). At most one entry per combination.
    """

    __tablename__ = "historical_data_cache"
    __table_args__ = (Index("ix_hist_cache_key", "ticker", "period", "interval"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "1y", "6mo"
    interval: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "1d", "1h"
    data_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # DataFrame serialized via to_json(orient="split")
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)

    def __repr__(self):
        return f"<HistoricalDataCache({self.ticker} {self.period}/{self.interval} @ {self.fetched_at})>"


class EarningsCache(Base):
    """
    Cache for the next scheduled earnings date per ticker (T08 earnings gate).

    Populated from ``yfinance.Ticker(t).calendar``. Refreshed on a 24h TTL
    (enforced at read time via ``fetched_at``). ``earnings_date`` is nullable:
    a row with NULL means "we asked Yahoo recently and it had no calendar /
    no upcoming earnings". Caching the negative result too prevents hammering
    the API for tickers Yahoo doesn't cover.
    """

    __tablename__ = "earnings_cache"
    __table_args__ = (Index("ix_earnings_cache_ticker_fetched", "ticker", "fetched_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    earnings_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # next upcoming earnings; NULL = unknown/none
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive, index=True)

    def __repr__(self):
        when = self.earnings_date.date() if self.earnings_date else "none"
        return f"<EarningsCache({self.ticker} next={when} @ {self.fetched_at})>"


class AnalystDataCache(Base):
    """
    Cache persistente de recomendaciones de analistas + price targets.

    Sobrevive a reinicios de la app (a diferencia del cache in-memory previo).
    TTL típica: 24h (los analistas no actualizan recos intraday). Almacenamos
    el dict completo de ``get_analyst_data`` serializado como JSON — incluye
    las listas mensuales de buckets y los price targets normalizados.

    Un ticker tiene a lo sumo una fila vigente; al escribir reemplazamos la
    anterior para mantener la tabla acotada (~500 filas en estado estable
    cuando se escaneó SP500 completo).
    """

    __tablename__ = "analyst_data_cache"
    __table_args__ = (Index("ix_analyst_cache_ticker_fetched", "ticker", "fetched_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-serialized dict de get_analyst_data
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive, index=True)

    def __repr__(self):
        return f"<AnalystDataCache({self.ticker} @ {self.fetched_at})>"


class CompanyInfoCache(Base):
    """Cache persistente de metadata de compañía (nombre / sector / industria).

    ``get_company_info`` hace un scrape lento de ``yfinance.Ticker(t).info`` (con
    hard-timeout). Antes se re-pegaba a la red en cada llamada; ahora se cachea
    con TTL largo (la clasificación sectorial no cambia intraday). Habilita, entre
    otras cosas, la **exposición sectorial** del panel de concentración (V2) sin
    tocar la red desde la pestaña read-only de Métricas.

    Un ticker tiene a lo sumo una fila vigente (upsert por ticker). ``sector`` es
    nullable: una fila con NULL/"N/A" es un resultado negativo cacheado (Yahoo no
    devolvió sector) para no re-scrapear.
    """

    __tablename__ = "company_info_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive, index=True)

    def __repr__(self):
        return f"<CompanyInfoCache({self.ticker} sector={self.sector} @ {self.fetched_at})>"


class NewsEvent(Base):
    """
    Noticia cruda capturada *point-in-time* (Sprint 5 · T-CAT-0).

    Append-only: una fila por (noticia, fuente) **observada**. El valor de la
    tabla está en la serie temporal de observaciones (``fetched_at``), no en el
    último estado — nunca se sobrescribe la noticia cruda.

    Los campos de clasificación (``event_type``, ``sentiment``,
    ``classifier_confidence``, ``classified_at``, ``classified_by``) quedan
    NULL hasta que T-CAT-2 (clasificador LLM) los rellena con un UPDATE in-place. Esa es la única
    excepción al append-only y es segura: añade metadata, no altera la
    observación cruda.

    ``content_hash`` (sha1 de ticker | título-normalizado | published_at) es
    UNIQUE → da idempotencia barata: re-correr el harvester el mismo día no
    duplica filas.
    """

    __tablename__ = "news_events"
    __table_args__ = (
        Index("ix_news_ticker_published", "ticker", "published_at"),
        Index("ix_news_content_hash", "content_hash", unique=True),
        Index("ix_news_unclassified", "event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # summary o cuerpo si la fuente lo provee
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # "yfinance", "sec_8k", "pr_rss", ...
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # timestamp que declara la fuente
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utcnow_naive, index=True
    )  # cuándo LO VIMOS
    content_hash: Mapped[str] = mapped_column(String(40), nullable=False)

    # Rellenados por T-CAT-2. NULL = sin clasificar todavía.
    event_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(12), nullable=True)  # positive / neutral / negative
    classifier_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Backend que produjo el label ("heuristic" / "ollama" / "llm" / "fallback").
    # T7.4: habilita QA por backend y detectar corridas con Ollama caído a posteriori.
    classified_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # OPS1(a): polaridad numérica point-in-time (misma llamada del classify, costo
    # marginal ~cero). sentiment_score ∈ [-1,+1], relevance ∈ [0,1]. NULL = fila
    # clasificada antes de OPS1. NO entra a ninguna decisión (regla 3): es
    # acumulación de dato point-in-time para el meta-modelo (tarea 9).
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self):
        return f"<NewsEvent({self.ticker} [{self.source}] {self.title[:40]!r})>"


class AnalystEstimateSnapshot(Base):
    """
    Snapshot diario del consenso de analistas por ticker+métrica (T-CAT-0).

    Append-only: a lo sumo una fila por (ticker, metric, period_label, día).
    La serie de snapshots es lo que permite, post-earnings, leer el consenso
    *tal como estaba el día antes del evento* → base del surprise score
    (T-CAT-5). yfinance solo expone el consenso **actual**, así que la única
    vía gratis a la historia point-in-time es snapshotearlo nosotros a diario.

    ``snapshot_date`` se guarda truncado a medianoche para que el chequeo
    "¿ya tomé snapshot hoy?" sea una igualdad exacta.
    """

    __tablename__ = "analyst_estimate_snapshots"
    __table_args__ = (Index("ix_est_ticker_metric_date", "ticker", "metric", "snapshot_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(
        String(24), nullable=False
    )  # "eps", "revenue", "rec_mean", "price_target"
    period_label: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )  # "0q","+1q","0y","+1y" o "2026-09"
    consensus_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_analysts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_date: Mapped[datetime | None] = mapped_column(
        DateTime, default=utcnow_naive, index=True
    )  # día de observación (medianoche)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow_naive)

    def __repr__(self):
        d = self.snapshot_date.date() if self.snapshot_date else "?"
        return f"<AnalystEstimateSnapshot({self.ticker} {self.metric}/{self.period_label}={self.consensus_value} @ {d})>"


class FailedTicker(Base):
    """
    Registro de tickers que fallaron al consultar Yahoo Finance.

    Permite:
    - Saltar tickers conocidos como inválidos antes del bulk fetch (whitelist
      negativa) para reducir ruido en logs.
    - Mostrar al usuario qué símbolos están fallando y por qué.
    - Permitir reintento manual (limpia el registro y vuelve a probar).

    El campo ``status`` se usa así:
    - "failing"  → ticker que sigue fallando, debe omitirse.
    - "retry"    → el usuario pidió reintentar, debe volver a probarse.
    - "ignored"  → el usuario marcó este ticker como permanente para ignorar.
    """

    __tablename__ = "failed_tickers"
    # NOTE: the ticker column declares ``unique=True, index=True`` which is
    # enough — SQLAlchemy auto-generates ``ix_failed_tickers_ticker`` from it.
    # An explicit ``Index(...)`` here would collide on ``create_all`` ("index
    # already exists"), which is exactly what broke the in-memory test DB
    # when both index definitions tried to run.

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_operation: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # "price", "historical", "info", "validate"
    fail_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)
    last_failed_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="failing", nullable=False, index=True)

    def __repr__(self):
        return f"<FailedTicker({self.ticker} status={self.status} count={self.fail_count})>"


def init_db():
    """Create all tables, sync the alembic timeline, and seed default portfolio."""
    # Register paper-trading models so their tables are included in create_all.
    # Import here (not at module top) to avoid a circular import.
    try:
        import paper_trading.models  # noqa: F401
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception("paper_trading.models import failed")
    Base.metadata.create_all(ENGINE)
    _alembic_sync()
    with session_scope() as session:
        if session.query(Portfolio).count() == 0:
            default = Portfolio(name="Mi Portafolio", description="Portafolio principal", currency="USD")
            session.add(default)


def _alembic_sync(engine=None, db_path: str | None = None):
    """Schema migrations via alembic — único camino de esquema (T7.3, M1).

    Reemplaza al viejo ``_migrate()`` de parches ``ALTER TABLE`` manuales:
    ese delta quedó congelado en la revisión alembic ``0004`` (catch-up).
    A partir de acá, todo cambio de esquema = revisión alembic nueva
    (``alembic revision --autogenerate -m "..."``); este hook la aplica solo
    en el próximo arranque.

    Flujo:
    - DB nueva (sin ``alembic_version``): ``create_all`` ya construyó el
      esquema completo → ``stamp head`` para arrancar el timeline alineado.
    - DB existente: ``upgrade head``. Las revisiones catch-up (0004) son
      idempotentes, así que una DB ya-completa pasa sin DDL.

    Los kwargs existen solo para tests (apuntar a una DB temporal).
    """
    from sqlalchemy import inspect as _sa_inspect

    try:
        from alembic.config import Config

        from alembic import command
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "alembic es requerido desde T7.3 — `pip install alembic` (está en requirements.txt)"
        ) from exc

    engine = engine if engine is not None else ENGINE
    db_path = db_path if db_path is not None else DB_PATH

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Config programático (sin alembic.ini) a propósito: evita que fileConfig
    # pise la configuración de logging de la app en cada arranque.
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    if _sa_inspect(engine).has_table("alembic_version"):
        command.upgrade(cfg, "head")
    else:
        command.stamp(cfg, "head")


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
