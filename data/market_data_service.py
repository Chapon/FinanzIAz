"""
MarketDataService — single front door to all market-data fetches.

Why
---
The codebase currently calls ``data.yahoo_finance`` from many places (UI
tabs, paper-trading engine, alerts, backtest). Each call site has its own
caching expectations, error handling, and rate-limiting assumptions. That
fragmentation makes it hard to:

- enforce a global rate limit on the Yahoo Finance API
- collect telemetry on hit/miss/error counts
- swap the data source (e.g. for tests, or to add a paid provider later)

This module provides one class with a small surface area that all callers
should migrate to over time. The legacy ``yahoo_finance.get_*`` functions
remain available — they're now thin wrappers over the same primitives.

Public API
----------
    svc = MarketDataService.instance()
    px  = svc.get_price("AAPL")
    df  = svc.get_history("AAPL", period="1y")
    divs = svc.get_dividends("AAPL", since=datetime(...))
    svc.invalidate("AAPL")          # drop cache for one ticker
    svc.stats()                     # {"hits": …, "misses": …, "errors": …}

Concurrency
-----------
- Module-level ``MarketDataService.instance()`` returns a process-wide
  singleton; it's safe to share across threads.
- A token-bucket ``RateLimiter`` limits the *combined* request rate across
  all callers (default 5 requests/second — well below Yahoo's documented
  thresholds and conservative enough that bursty UI scans don't get 429s).

This module deliberately re-uses ``data.yahoo_finance`` for the actual
network calls so the timeout/retry/QA pipeline already implemented there
is preserved.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from config.logging_config import get_logger

log = get_logger(__name__)


# ── Token-bucket rate limiter ────────────────────────────────────────────────


class RateLimiter:
    """
    Thread-safe token-bucket limiter.

    ``rate_per_sec`` tokens are added per second up to a cap of ``burst``.
    ``acquire(n=1)`` blocks until ``n`` tokens are available. Designed for
    "be polite to the upstream API" use cases, not microsecond accuracy.
    """

    def __init__(self, rate_per_sec: float = 5.0, burst: int = 10) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        self.rate = float(rate_per_sec)
        self.burst = float(burst)
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)

    def acquire(self, n: int = 1) -> None:
        """Block until ``n`` tokens are available, then consume them."""
        if n <= 0:
            return
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= n:
                    self._tokens -= n
                    return
                # Sleep just long enough for the next token to materialise.
                wait = (n - self._tokens) / self.rate
            time.sleep(max(0.005, wait))

    def try_acquire(self, n: int = 1) -> bool:
        """Non-blocking variant; returns False if not enough tokens."""
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False


# ── Service-level telemetry ──────────────────────────────────────────────────


@dataclass
class _Stats:
    price_hits: int = 0
    price_misses: int = 0
    history_hits: int = 0
    history_misses: int = 0
    errors: int = 0
    rate_waits: int = 0
    last_error: str = ""

    def as_dict(self) -> dict:
        return {
            "price_hits": self.price_hits,
            "price_misses": self.price_misses,
            "history_hits": self.history_hits,
            "history_misses": self.history_misses,
            "errors": self.errors,
            "rate_waits": self.rate_waits,
            "last_error": self.last_error,
        }


# ── MarketDataService singleton ──────────────────────────────────────────────


class MarketDataService:
    """
    Front-door for all market-data fetches.

    Internally delegates to ``data.yahoo_finance`` for actual network I/O
    (which already handles timeouts, retries, the request session, and
    OHLCV quality checks). This class adds rate limiting + telemetry on
    top.

    Use ``MarketDataService.instance()`` instead of constructing directly
    so the rate limiter and stats counters are shared process-wide.
    """

    _instance: MarketDataService | None = None
    _instance_lock = threading.Lock()

    def __init__(self, *, rate_per_sec: float = 5.0, burst: int = 10) -> None:
        self._limiter = RateLimiter(rate_per_sec=rate_per_sec, burst=burst)
        self._stats = _Stats()
        self._stats_lock = threading.Lock()

    # ── singleton ────────────────────────────────────────────────────────────
    @classmethod
    def instance(cls) -> MarketDataService:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── public fetches ───────────────────────────────────────────────────────
    # NOTE: rate limiting is enforced inside ``data.yahoo_finance`` (every
    # ``_run_with_timeout`` call acquires one token via ``_wait_token``).
    # We deliberately DO NOT acquire here too — that would double-count the
    # token for callers that go through this façade.

    def get_price(self, ticker: str) -> dict | None:
        from data import yahoo_finance as yf

        try:
            result = yf.get_current_price(ticker)
            self._record(
                price_hit=result is not None and result.get("from_cache"),
                price_miss=result is not None and not result.get("from_cache"),
            )
            return result
        except Exception as exc:
            self._record(error=str(exc))
            return None

    def get_bulk_prices(self, tickers: list[str]) -> dict[str, dict | None]:
        from data import yahoo_finance as yf

        try:
            return yf.get_bulk_prices(tickers)
        except Exception as exc:
            self._record(error=str(exc))
            return {t: None for t in tickers}

    def get_history(self, ticker: str, *, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
        from data import yahoo_finance as yf

        try:
            df = yf.get_historical_data(ticker, period=period, interval=interval)
            with self._stats_lock:
                if df is not None:
                    self._stats.history_hits += 1  # cache or live, both count
                else:
                    self._stats.history_misses += 1
            return df
        except Exception as exc:
            self._record(error=str(exc))
            return None

    def get_dividends(self, ticker: str, *, since: datetime) -> float:
        from data import yahoo_finance as yf

        try:
            return yf.get_dividends_since(ticker, since)
        except Exception as exc:
            self._record(error=str(exc))
            return 0.0

    # ── cache control ────────────────────────────────────────────────────────
    def invalidate(self, ticker: str) -> None:
        """Drop cached price + history rows for a single ticker."""
        from database.models import (
            DividendCache,
            HistoricalDataCache,
            PriceCache,
            session_scope,
        )

        sym = ticker.upper()
        try:
            with session_scope() as session:
                session.query(PriceCache).filter(PriceCache.ticker == sym).delete()
                session.query(HistoricalDataCache).filter(HistoricalDataCache.ticker == sym).delete()
                session.query(DividendCache).filter(DividendCache.ticker == sym).delete()
        except Exception:
            log.exception("invalidate(%s) failed", sym)
        # ARQ1: limpiar también el cache Parquet (si existe) — independiente del
        # backend activo, para no dejar archivos stale al alternar de backend.
        try:
            from data import parquet_cache

            parquet_cache.invalidate(sym)
        except Exception:
            log.exception("invalidate parquet(%s) failed", sym)

    # ── telemetry ────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        with self._stats_lock:
            return self._stats.as_dict()

    def reset_stats(self) -> None:
        with self._stats_lock:
            self._stats = _Stats()

    # ── internals ────────────────────────────────────────────────────────────
    def _wait_token(self, n: int = 1) -> None:
        if not self._limiter.try_acquire(n):
            with self._stats_lock:
                self._stats.rate_waits += 1
            self._limiter.acquire(n)

    def _record(
        self,
        *,
        price_hit: bool = False,
        price_miss: bool = False,
        error: str | None = None,
    ) -> None:
        with self._stats_lock:
            if price_hit:
                self._stats.price_hits += 1
            if price_miss:
                self._stats.price_misses += 1
            if error:
                self._stats.errors += 1
                self._stats.last_error = error
