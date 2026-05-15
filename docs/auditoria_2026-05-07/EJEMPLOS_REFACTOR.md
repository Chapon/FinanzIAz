# Ejemplos de Código para Quick Wins

Este documento contiene fragmentos de código listos para copiar/adaptar.

---

## 1. Context Manager para Sesiones SQLAlchemy

**Crear archivo**: `config/database.py`

```python
"""Database session management with context manager."""
from contextlib import contextmanager
from sqlalchemy.orm import Session
from database.models import get_session


@contextmanager
def session_scope() -> Session:
    """
    Provide a transactional scope for database sessions.
    
    Usage:
        with session_scope() as session:
            user = session.query(User).first()
            session.add(new_record)
            # auto-commits on success, auto-rollbacks on exception
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Optional: for long-running operations
@contextmanager
def session_scope_no_commit() -> Session:
    """Session without auto-commit (for read-only or manual commit)."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()
```

**Refactorizar ejemplo** (antes):

```python
# data/yahoo_finance.py:31–76
session = get_session()
try:
    cached = (
        session.query(PriceCache)
        .filter(PriceCache.ticker == ticker.upper())
        .filter(PriceCache.fetched_at >= cutoff)
        .order_by(PriceCache.fetched_at.desc())
        .first()
    )
    if cached:
        return {...}
    # ... fetch + insert
finally:
    session.close()
```

**Después**:

```python
from config.database import session_scope

with session_scope() as session:
    cached = (
        session.query(PriceCache)
        .filter(PriceCache.ticker == ticker.upper())
        .filter(PriceCache.fetched_at >= cutoff)
        .order_by(PriceCache.fetched_at.desc())
        .first()
    )
    if cached:
        return {...}
    # ... add/flush (auto-commits on exit)
```

---

## 2. Type Hints Sistemáticos

**Antes** (`analysis/technical.py:324–330`):

```python
def analyze(
    ticker: str,
    df: pd.DataFrame,
    enable_sma_cross: bool = True,
    enable_volume: bool = True,
    enable_xgboost: bool = True,
) -> Optional[AnalysisResult]:
```

✓ Ya tiene hints, pero el resto de la función no. Agregar hints internas:

```python
def analyze(
    ticker: str,
    df: pd.DataFrame,
    enable_sma_cross: bool = True,
    enable_volume: bool = True,
    enable_xgboost: bool = True,
) -> Optional[AnalysisResult]:
    """Full technical + ML analysis on OHLCV data.
    
    Parameters
    ----------
    ticker : str
        Stock symbol (uppercase).
    df : pd.DataFrame
        OHLCV data with DatetimeIndex and Close column.
    enable_sma_cross : bool
        Include Golden/Death Cross signal (requires 200 days).
    enable_volume : bool
        Include volume accumulation/distribution signal.
    enable_xgboost : bool
        Train XGBoost classifier (disable for fast batch scans).
    
    Returns
    -------
    AnalysisResult or None
        Complete analysis with signals, or None if insufficient data (<50 rows).
    """
    if df is None or len(df) < 50:
        return None

    signals: list[TechnicalSignal] = []
    
    # Cached indicator computation
    indic: dict[str, Any] = get_cached_indicators(ticker, df)
    rsi_series: pd.Series = indic['rsi']
    macd_line, signal_line, histogram = indic['macd']
    upper, middle, lower = indic['bollinger']
    sma50: Optional[pd.Series] = indic['sma50']
    sma200: Optional[pd.Series] = indic['sma200']
    
    # RSI signal
    if not rsi_series.dropna().empty:
        signals.append(_rsi_signal(rsi_series))
    
    # ... rest of function
```

**Script para bulk-añadir hints** (experimental):

```bash
# Usar pyright en strict mode para detectar dónde faltan
pyright --outputjson analysis/technical.py | \
  grep "reportMissingTypeStubs\|reportUnknownParameterType" | head -20
```

---

## 3. Índices SQLAlchemy

**En** `database/models.py`:

```python
from sqlalchemy import Index

class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        Index("ix_pos_portfolio_id", "portfolio_id"),
        Index("ix_pos_portfolio_ticker", "portfolio_id", "ticker"),
        Index("ix_pos_updated_at", "updated_at"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    # ... rest of columns
```

**En** `paper_trading/models.py`:

```python
class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        Index("ix_order_account_status", "account_id", "status"),
        Index("ix_order_filled_at", "filled_at"),
        Index("ix_order_ticker_side", "ticker", "side"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("paper_accounts.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    side = Column(String(4), nullable=False)
    # ... rest
```

**Nota**: SQLite auto-crea índice para PK y FK, pero estos compound-indexes son manual.

---

## 4. Validación GARCH Convergencia

**En** `analysis/garch_signals.py:114–150`:

```python
def fit_garch_forecast(
    df: pd.DataFrame,
    horizon: int = GARCH_FORECAST_H,
) -> Optional[GarchForecast]:
    """Fit GARCH(1,1) with convergence validation."""
    if not _ARCH_OK:
        return None

    returns = _log_returns(df)
    if len(returns) < GARCH_MIN_ROWS:
        return None

    try:
        model = arch_model(
            returns,
            mean="Zero",
            vol="Garch",
            p=1, q=1,
            dist="normal",
            rescale=False,
        )
        res = model.fit(disp="off", show_warning=False)
        
        # ✓ NEW: Validar convergencia
        if res.convergence_flag != 0:
            import logging
            logging.warning(
                f"[GARCH] Model failed to converge (flag={res.convergence_flag}). "
                f"Using EWMA fallback."
            )
            return None
        
        # ✓ NEW: Check likelihood is finite
        if np.isnan(res.loglikelihood) or np.isinf(res.loglikelihood):
            logging.warning("[GARCH] Likelihood is nan/inf. Using EWMA fallback.")
            return None
        
        # Resto del código igual
        cond_vol_daily = float(res.conditional_volatility.iloc[-1])
        # ...
        
    except Exception as e:
        import logging
        logging.error(f"[GARCH] Fit exception: {e}. Using EWMA fallback.")
        return None
```

---

## 5. Timeout en yfinance

**En** `data/yahoo_finance.py:132–202`:

```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import logging

logger = logging.getLogger(__name__)

def get_historical_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d"
) -> Optional[pd.DataFrame]:
    """Download OHLCV with timeout and exponential backoff."""
    ticker_upper = ticker.upper()

    # Cache check (existing code)
    if _cache_enabled():
        session = get_session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=HISTORICAL_CACHE_TTL_HOURS)
            cached = (
                session.query(HistoricalDataCache)
                .filter(HistoricalDataCache.ticker == ticker_upper)
                .filter(HistoricalDataCache.period == period)
                .filter(HistoricalDataCache.interval == interval)
                .filter(HistoricalDataCache.fetched_at >= cutoff)
                .order_by(HistoricalDataCache.fetched_at.desc())
                .first()
            )
            if cached:
                df = pd.read_json(StringIO(cached.data_json), orient="split")
                df.index = pd.to_datetime(df.index)
                return df
        except Exception as e:
            logger.warning(f"[YF] Historical cache read failed for {ticker}: {e}")
        finally:
            session.close()

    # ✓ NEW: Live download con timeout
    try:
        def download_task():
            return yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True
            )
        
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(download_task)
            df = future.result(timeout=30.0)  # 30-second timeout
            
    except FuturesTimeoutError:
        logger.error(
            f"[YF] Historical download timeout for {ticker} "
            f"({period}/{interval}). Returning None."
        )
        return None
    except Exception as e:
        logger.warning(f"[YF] Historical data failed for {ticker}: {e}")
        return None

    if df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    df.index = pd.to_datetime(df.index)

    # ✓ NEW: Validar data quality
    if df.isnull().any().any():
        logger.warning(f"[YF] {ticker} has NaN values in {df.columns.tolist()}")
    
    # Cache write (existing code)
    if _cache_enabled():
        session = get_session()
        try:
            session.query(HistoricalDataCache).filter(
                HistoricalDataCache.ticker == ticker_upper,
                HistoricalDataCache.period == period,
                HistoricalDataCache.interval == interval,
            ).delete()
            session.add(HistoricalDataCache(
                ticker=ticker_upper,
                period=period,
                interval=interval,
                data_json=df.to_json(orient="split", date_format="iso"),
            ))
            session.commit()
        except Exception as e:
            logger.error(f"[YF] Historical cache write failed for {ticker}: {e}")
            session.rollback()
        finally:
            session.close()

    return df
```

---

## 6. Base QWorker Class

**Crear archivo**: `ui/workers.py`

```python
"""Base class for all background workers."""
from PyQt6.QtCore import QThread, pyqtSignal
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class BaseQWorker(QThread):
    """Abstract base for background workers with standard signals."""
    
    work_completed = pyqtSignal(object)  # Generic result type
    work_failed = pyqtSignal(str)        # Error message
    work_started = pyqtSignal()          # Optional: started notification
    
    def __init__(self, timeout_sec: int = 30, parent=None):
        """
        Initialize worker.
        
        Parameters
        ----------
        timeout_sec : int
            Timeout for task execution (not enforced by base, but available).
        parent : QObject, optional
            Parent widget.
        """
        super().__init__(parent)
        self.timeout_sec = timeout_sec
    
    def run(self):
        """Entry point for QThread. Calls do_work() with error handling."""
        try:
            self.work_started.emit()
            result = self.do_work()
            self.work_completed.emit(result)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"[{self.__class__.__name__}] {error_msg}", exc_info=True)
            self.work_failed.emit(error_msg)
    
    def do_work(self) -> Any:
        """Override in subclasses to implement actual work."""
        raise NotImplementedError("Subclasses must implement do_work()")


# ── Example: Refactor _PricesWorker from paper_tab.py

class PricesWorker(BaseQWorker):
    """Fetch current prices in background."""
    
    def __init__(self, tickers: list[str], parent=None):
        super().__init__(timeout_sec=30, parent=parent)
        self._tickers = [t for t in tickers if t]
    
    def do_work(self) -> dict[str, float]:
        """Fetch prices. Returns {ticker: price}."""
        if not self._tickers:
            return {}
        
        from data.yahoo_finance import get_bulk_prices
        
        try:
            raw = get_bulk_prices(self._tickers)
            prices: dict[str, float] = {}
            for ticker, info in (raw or {}).items():
                if isinstance(info, dict):
                    px = info.get("price")
                else:
                    px = info
                if px is None:
                    continue
                try:
                    prices[ticker] = float(px)
                except (TypeError, ValueError):
                    continue
            return prices
        except Exception as e:
            logger.error(f"[PricesWorker] {e}", exc_info=True)
            raise  # ← will be caught by run() and emit work_failed


# ── Usage in UI

# Antes
class SomeTab(QWidget):
    def fetch_prices(self, tickers: list[str]):
        worker = _PricesWorker(tickers)
        worker.prices_ready.connect(self.on_prices_ready)
        worker.start()

# Después
class SomeTab(QWidget):
    def fetch_prices(self, tickers: list[str]):
        worker = PricesWorker(tickers)
        worker.work_completed.connect(self.on_prices_ready)
        worker.work_failed.connect(self.on_prices_failed)
        worker.start()
    
    def on_prices_ready(self, prices: dict[str, float]):
        # prices = {ticker: price}
        for ticker, px in prices.items():
            # update UI
            pass
    
    def on_prices_failed(self, error: str):
        QMessageBox.warning(self, "Error", f"Price fetch failed: {error}")
```

---

## 7. Settings Validation Schema

**En** `config/settings_manager.py:86–94`:

```python
from typing import Union, Tuple, Callable

# Schema: (type_check, *validation_args)
_SCHEMA: dict[str, Tuple[Union[type, Callable], ...]] = {
    # Boolean settings
    "cache":                     (bool,),
    "notif":                     (bool,),
    "default_home":              (bool,),
    "confirm_sell":              (bool,),
    
    # Integer with range
    "paper_scan_interval_minutes": (int, 1, 1440),      # 1 min – 1 day
    "paper_min_holding_minutes":   (int, 0, 10080),     # 0 – 1 week
    "paper_anti_flap_minutes":     (int, 0, 1440),      # 0 – 1 day
    
    # Float with range
    "paper_min_trade_dollars": (float, 0.0, 100000.0),
    
    # String with enum
    "paper_history_period": (str, ("1y", "2y", "5y", "10y", "ytd", "max")),
    "paper_daily_scan_time_et": (str, _is_valid_hhmm),  # Custom validator
    
    # String (no validation)
    "pdf_dark": (bool,),
}


def _is_valid_hhmm(value: str) -> bool:
    """Validator for HH:MM format."""
    try:
        parts = value.strip().split(":")
        if len(parts) != 2:
            return False
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h < 24 and 0 <= m < 60
    except (ValueError, AttributeError):
        return False


def _validate(self, key: str, value) -> bool:
    """Validate value against schema."""
    if key not in _SCHEMA:
        return True  # no validation = accept
    
    schema = _SCHEMA[key]
    type_check = schema[0]
    
    # Type check
    if isinstance(type_check, type):
        if not isinstance(value, type_check):
            return False
    elif callable(type_check):
        if not type_check(value):
            return False
    
    # Range check (for int/float)
    if len(schema) >= 3 and isinstance(type_check, type):
        if type_check in (int, float):
            min_val, max_val = schema[1], schema[2]
            if not (min_val <= value <= max_val):
                return False
    
    # Enum check (for str)
    if len(schema) >= 2 and type_check is str:
        if value not in schema[1:]:
            return False
    
    return True


def set(self, key: str, value) -> None:
    """Set with validation."""
    if not self._validate(key, value):
        raise ValueError(
            f"Invalid value for {key}: {value!r}. "
            f"Schema: {_SCHEMA.get(key, 'no validation')}"
        )
    self._data[key] = value
    self.save()
```

**Uso**:

```python
from config.settings_manager import settings

# ✓ Valid
settings.set("paper_scan_interval_minutes", 15)

# ✗ Invalid (will raise ValueError)
try:
    settings.set("paper_scan_interval_minutes", 99999)
except ValueError as e:
    print(f"Config error: {e}")
```

---

## 8. Logging Setup

**En** `main.py`:

```python
import sys
import os
import logging
from pathlib import Path

def setup_logging():
    """Configure application logging."""
    # Create logs directory
    log_dir = Path.home() / ".finanzias" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / "app.log"
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),  # also print to console
        ],
    )
    
    # Set some loggers to WARNING to reduce noise
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)


def main():
    logger = setup_logging()
    logger.info("FinanzIAs starting...")
    
    # Initialize DB
    from database.models import init_db
    init_db()
    
    # Import Qt after path setup
    from PyQt6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    
    app = QApplication(sys.argv)
    app.setApplicationName("FinanzIAs")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("FinanzIAs")
    
    window = MainWindow()
    window.show()
    
    logger.info("UI ready, entering event loop")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

---

## 9. Refactor paper_tab.py: Account Panel

**Crear archivo**: `ui/paper_trading/account_panel.py`

```python
"""Account management panel for paper trading tab."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QMessageBox, QScrollArea, QFrame,
)
from PyQt6.QtCore import pyqtSignal
from paper_trading.account import (
    list_accounts, get_account, create_account, delete_account,
    update_account_config, get_positions,
)
from ui.widgets import MetricCard, SectionHeader


class AccountManagerPanel(QWidget):
    """Panel for creating, selecting, and configuring accounts."""
    
    account_changed = pyqtSignal(int)  # account_id
    account_deleted = pyqtSignal(int)  # account_id
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_account_id: Optional[int] = None
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = SectionHeader("Cuentas Paper")
        layout.addWidget(header)
        
        # Selector
        selector_layout = QHBoxLayout()
        self.account_combo = QComboBox()
        self.account_combo.currentIndexChanged.connect(self._on_account_selected)
        selector_layout.addWidget(self.account_combo)
        
        btn_new = QPushButton("Nueva")
        btn_new.clicked.connect(self._on_create_account)
        selector_layout.addWidget(btn_new)
        
        btn_delete = QPushButton("Eliminar")
        btn_delete.clicked.connect(self._on_delete_account)
        selector_layout.addWidget(btn_delete)
        
        layout.addLayout(selector_layout)
        
        # Metrics
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        metrics_frame = QFrame()
        metrics_layout = QVBoxLayout(metrics_frame)
        
        self.metric_equity = MetricCard("Equity", "—")
        self.metric_cash = MetricCard("Cash", "—")
        self.metric_positions = MetricCard("Posiciones", "—")
        
        metrics_layout.addWidget(self.metric_equity)
        metrics_layout.addWidget(self.metric_cash)
        metrics_layout.addWidget(self.metric_positions)
        metrics_layout.addStretch()
        
        scroll.setWidget(metrics_frame)
        layout.addWidget(scroll)
    
    def refresh(self):
        """Load and display all accounts."""
        accounts = list_accounts()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        
        for acct in accounts:
            self.account_combo.addItem(acct.name, userData=acct.id)
        
        if accounts and self.current_account_id is None:
            self.account_combo.setCurrentIndex(0)
        elif self.current_account_id is not None:
            for i in range(self.account_combo.count()):
                if self.account_combo.itemData(i) == self.current_account_id:
                    self.account_combo.setCurrentIndex(i)
                    break
        
        self.account_combo.blockSignals(False)
        self._update_metrics()
    
    def _on_account_selected(self, idx: int):
        if idx < 0:
            return
        account_id = self.account_combo.itemData(idx)
        self.current_account_id = account_id
        self._update_metrics()
        self.account_changed.emit(account_id)
    
    def _update_metrics(self):
        if self.current_account_id is None:
            return
        
        acct = get_account(self.current_account_id)
        if acct is None:
            return
        
        equity = acct.cash + sum(
            p.shares * p.avg_cost for p in get_positions(self.current_account_id)
        )
        
        self.metric_equity.set_value(f"${equity:,.2f}")
        self.metric_cash.set_value(f"${acct.cash:,.2f}")
        self.metric_positions.set_value(f"{len(get_positions(self.current_account_id))}")
    
    def _on_create_account(self):
        from ui.paper_trading.dialogs import PaperAccountDialog
        dialog = PaperAccountDialog(parent=self)
        if dialog.exec():
            self.refresh()
    
    def _on_delete_account(self):
        if self.current_account_id is None:
            return
        reply = QMessageBox.warning(
            self,
            "Confirmar",
            "¿Eliminar cuenta y todos sus datos?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_account(self.current_account_id)
            self.account_deleted.emit(self.current_account_id)
            self.refresh()
```

**Integración en PaperTradingTab**:

```python
class PaperTradingTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Split UI into independent panels
        self.account_panel = AccountManagerPanel()
        self.positions_panel = PositionsPanel()
        self.orders_panel = OrdersPanel()
        self.equity_panel = EquityChartPanel()
        
        # Connect signals
        self.account_panel.account_changed.connect(self._on_account_changed)
        self.account_panel.account_deleted.connect(self._on_account_deleted)
        
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Account selector at top
        layout.addWidget(self.account_panel, 0)
        
        # Rest of panels below
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.positions_panel)
        splitter.addWidget(self.orders_panel)
        layout.addWidget(splitter, 1)
        
        # Equity chart at bottom
        layout.addWidget(self.equity_panel, 0)
    
    def _on_account_changed(self, account_id: int):
        """Refresh all panels when account changes."""
        self.positions_panel.load_account(account_id)
        self.orders_panel.load_account(account_id)
        self.equity_panel.load_account(account_id)
    
    def _on_account_deleted(self, account_id: int):
        # Clear panels
        self.positions_panel.clear()
        self.orders_panel.clear()
        self.equity_panel.clear()
```

---

## 10. Test Example: Backtest

**Crear archivo**: `tests/test_backtest.py`

```python
"""Tests for analysis/backtest.py"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from analysis.backtest import backtest


@pytest.fixture
def sample_ohlcv():
    """Generate 100 days of mock OHLCV data."""
    dates = pd.date_range("2024-01-01", periods=100, freq="B")  # Business days
    close = 100 + np.cumsum(np.random.randn(100))  # Random walk
    
    return pd.DataFrame({
        "Open": close + np.random.uniform(-0.5, 0.5, 100),
        "High": close + np.random.uniform(0.5, 1.5, 100),
        "Low": close + np.random.uniform(-1.5, -0.5, 100),
        "Close": close,
        "Volume": np.random.randint(1_000_000, 10_000_000, 100),
    }, index=dates)


def test_backtest_no_trades():
    """Strategy that never signals should produce no trades."""
    df = sample_ohlcv()
    
    def never_trade(df_upto_t):
        return "HOLD"
    
    result = backtest(
        "TEST",
        df,
        never_trade,
        commission=0.001,
        slippage=0.0005,
        initial_capital=10000.0,
    )
    
    assert result.n_trades == 0
    assert result.total_return_pct == 0.0


def test_backtest_buy_hold():
    """Buy on first bar, hold forever."""
    df = sample_ohlcv()
    first_close = df["Close"].iloc[0]
    
    def buy_once(df_upto_t):
        # First signal = BUY, rest = HOLD
        return "BUY" if len(df_upto_t) == 1 else "HOLD"
    
    result = backtest(
        "TEST",
        df,
        buy_once,
        commission=0.001,
        slippage=0.0005,
        initial_capital=10000.0,
    )
    
    # Should have 1 open position at end
    assert result.n_trades == 0  # No completed trades
    assert result.final_equity != 10000.0  # Equity changed
    
    # Check direction: price went up from first to last close
    price_change = df["Close"].iloc[-1] - first_close
    assert (result.final_equity > 10000.0) == (price_change > 0)


def test_backtest_lookahead_protection():
    """Verify signal function can't peek ahead."""
    df = sample_ohlcv()
    called_lengths = []
    
    def record_lengths(df_upto_t):
        called_lengths.append(len(df_upto_t))
        return "HOLD"
    
    result = backtest(
        "TEST",
        df,
        record_lengths,
        step=1,
        initial_capital=10000.0,
    )
    
    # Signal function should be called with progressively longer windows
    # 50 (min), 51, 52, ..., 100
    assert called_lengths[0] == 50  # First call has min data
    assert called_lengths[-1] == 100  # Last call has full data
    assert called_lengths == sorted(called_lengths)


def test_backtest_metrics():
    """Verify metric calculations."""
    # Simple scenario: buy at 100, sell at 110
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 110]
    
    df = pd.DataFrame({
        "Close": closes,
        "High": closes,
        "Low": [c - 0.5 for c in closes],
        "Volume": [1_000_000] * 10,
    }, index=dates)
    
    buy_price = 100
    sell_price = 110
    
    def buy_sell(df_upto_t):
        current = df_upto_t["Close"].iloc[-1]
        if current <= buy_price + 0.5:
            return "BUY"
        elif current >= sell_price - 0.5:
            return "SELL"
        return "HOLD"
    
    result = backtest(
        "TEST",
        df,
        buy_sell,
        commission=0.0,
        slippage=0.0,
        initial_capital=10000.0,
    )
    
    # Expect 1 round-trip trade
    assert result.n_trades >= 1
    # Profit should be positive
    assert result.total_return_pct > 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

**Ejecutar**:

```bash
cd /path/to/finanzias
pytest tests/test_backtest.py -v
```

---

## Resumen: Implementar en Orden

1. **Día 1**: Context manager (1.5h) + Type hints core (3h) → 4.5h work
2. **Día 2**: Índices (0.5h) + Timeout yfinance (1h) + GARCH validation (0.5h) → 2h work
3. **Día 3**: Base QWorker (2h) + Settings validation (1h) + Logging (1h) → 4h work
4. **Semana 2**: Panel refactor (8h) + Test suite starter (8h) → 16h work

**Total Quick Wins**: ~30 horas para cobertura importante. **ROI**: 5–10x en mantenibilidad y confiabilidad.
