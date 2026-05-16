"""
Yahoo Finance data layer using yfinance.
Handles fetching current prices, historical data, and company info.

Network safety
--------------
All yfinance calls share a single ``requests.Session`` configured with:
- default socket timeout (``NETWORK_TIMEOUT_SECONDS``) injected on every request
- automatic retries with exponential backoff on 429/5xx responses

Long-running blocking calls (``Ticker.info``, ``yf.download``) are additionally
guarded by ``_run_with_timeout`` so they cannot freeze the UI thread even if
the underlying socket fails to respect the timeout (e.g. SSL/DNS hangs).
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import TypeVar

import pandas as pd
import requests
import yfinance as yf
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.constants import (
    BULK_FETCH_WORKERS,
    DIVIDEND_CACHE_HOURS,
    HISTORICAL_CACHE_TTL_HOURS,
    MARKET_CLOSE_HOUR_ET,
    MARKET_CLOSE_MINUTE,
    MARKET_OPEN_HOUR_ET,
    MARKET_OPEN_MINUTE,
    NETWORK_TIMEOUT_SECONDS,
    POST_MARKET_CLOSE_HOUR_ET,
    PRE_MARKET_OPEN_HOUR_ET,
)
from config.constants import (
    NETWORK_HARD_TIMEOUT_SECONDS as HARD_TIMEOUT_SECONDS,
)
from config.constants import (
    NETWORK_RETRY_BACKOFF as RETRY_BACKOFF,
)
from config.constants import (
    NETWORK_RETRY_TOTAL as RETRY_TOTAL,
)
from config.constants import (
    PRICE_CACHE_TTL_MINUTES as CACHE_TTL_MINUTES,
)
from config.logging_config import get_logger
from data.failed_tickers import (
    get_failing_set,
    record_failure,
    record_success,
)
from data.quality import clean_ohlcv
from database.models import DividendCache, HistoricalDataCache, PriceCache, session_scope

log = get_logger(__name__)

T = TypeVar("T")


class _TimeoutHTTPAdapter(HTTPAdapter):
    """HTTPAdapter that injects a default timeout on every request."""

    def __init__(self, *args, timeout: float = NETWORK_TIMEOUT_SECONDS, **kwargs):
        self._default_timeout = timeout
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self._default_timeout
        return super().send(request, **kwargs)


def _build_yf_session() -> requests.Session:
    """Return a requests.Session with default timeout + retry policy."""
    session = requests.Session()
    retries = Retry(
        total=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = _TimeoutHTTPAdapter(max_retries=retries, timeout=NETWORK_TIMEOUT_SECONDS)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# Module-level shared session — thread-safe for reuse across worker threads.
_YF_SESSION = _build_yf_session()

# Dedicated thread pool used as a safety-net wall-clock timeout. Daemon threads
# so they don't block app shutdown if a network call hangs indefinitely.
_TIMEOUT_POOL = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="yf-timeout",
)


def _ticker(symbol: str) -> yf.Ticker:
    """Build a yfinance Ticker. yfinance 1.x manages its own curl_cffi session."""
    return yf.Ticker(symbol)


# Process-wide rate limiter (shared with MarketDataService). Acquired before
# every outbound network call below so the global QPS stays under Yahoo's
# threshold even when multiple workers fan out in parallel.
def _acquire_rate_token(n: int = 1) -> None:
    try:
        from data.market_data_service import MarketDataService

        MarketDataService.instance()._wait_token(n)
    except Exception:
        # Don't fail the request if telemetry/limiter has a hiccup.
        pass


def _run_with_timeout(
    fn: Callable[..., T],
    *args,
    timeout: float = HARD_TIMEOUT_SECONDS,
    default: T | None = None,
    **kwargs,
) -> T | None:
    """
    Run ``fn(*args, **kwargs)`` and abort if it takes longer than ``timeout``.
    On timeout / exception returns ``default`` (None by default).
    Acquires one global rate-limiter token before submitting.
    """
    _acquire_rate_token()
    future = _TIMEOUT_POOL.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        future.cancel()
        log.warning("Hard timeout (%ss) running %s", timeout, getattr(fn, "__name__", fn))
        return default
    except Exception:
        log.exception("yfinance call %s raised", getattr(fn, "__name__", fn))
        return default


def _cache_enabled() -> bool:
    try:
        from config.settings_manager import settings

        return settings.get("cache", True)
    except Exception:
        return True


def get_current_price(ticker: str) -> dict | None:
    """
    Fetch current price and key metrics for a ticker.
    Returns a dict with price, change_pct, volume, market_cap, etc.
    Uses an in-DB cache to avoid hammering the API.
    """
    try:
        # 1. Cache read (own session — released before the network call)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=CACHE_TTL_MINUTES)
        if _cache_enabled():
            with session_scope() as session:
                cached = (
                    session.query(PriceCache)
                    .filter(PriceCache.ticker == ticker.upper())
                    .filter(PriceCache.fetched_at >= cutoff)
                    .order_by(PriceCache.fetched_at.desc())
                    .first()
                )
                if cached:
                    return {
                        "ticker": cached.ticker,
                        "price": cached.price,
                        "change_pct": cached.change_pct,
                        "volume": cached.volume,
                        "market_cap": cached.market_cap,
                        "from_cache": True,
                    }

        # 2. Fetch live
        info = _fetch_ticker_info(ticker)
        if info is None:
            return None

        # 3. Cache write
        with session_scope() as session:
            session.add(
                PriceCache(
                    ticker=ticker.upper(),
                    price=info["price"],
                    change_pct=info.get("change_pct"),
                    volume=info.get("volume"),
                    market_cap=info.get("market_cap"),
                )
            )
        info["from_cache"] = False
        return info

    except Exception:
        log.exception("Error fetching price for %s", ticker)
        return None


def _fetch_ticker_info(ticker: str) -> dict | None:
    """Raw yfinance fetch — returns a clean dict. Hard-timeout protected.

    On failure (None / exception), registra el ticker en ``failed_tickers``
    para que la UI lo muestre y los próximos bulk fetch lo salteen.
    """

    last_exc: list[str] = []

    def _do_fetch() -> dict | None:
        try:
            t = _ticker(ticker)
            info = t.fast_info

            price = getattr(info, "last_price", None)
            prev_close = getattr(info, "previous_close", None)
            if price is None:
                last_exc.append("Sin precio (símbolo posiblemente deslistado)")
                return None

            change_pct = None
            if prev_close and prev_close != 0:
                change_pct = ((price - prev_close) / prev_close) * 100

            return {
                "ticker": ticker.upper(),
                "price": round(float(price), 4),
                "prev_close": round(float(prev_close), 4) if prev_close else None,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "volume": getattr(info, "three_month_average_volume", None),
                "market_cap": getattr(info, "market_cap", None),
                "fifty_two_week_high": getattr(info, "year_high", None),
                "fifty_two_week_low": getattr(info, "year_low", None),
                "currency": getattr(info, "currency", "USD"),
            }
        except Exception as e:
            last_exc.append(f"{type(e).__name__}: {e}")
            raise

    result = _run_with_timeout(_do_fetch, timeout=HARD_TIMEOUT_SECONDS, default=None)
    if result is None:
        err = last_exc[0] if last_exc else "Sin datos disponibles"
        record_failure(ticker, err, operation="price")
    else:
        # El ticker volvió a funcionar — limpiar registro previo si existía.
        record_success(ticker)
    return result


def get_company_info(ticker: str) -> dict:
    """Fetch company name, sector, description from yfinance. Hard-timeout protected."""

    def _do_fetch() -> dict:
        t = _ticker(ticker)
        info = t.info  # this is the slow scrape — timeout-guarded above
        return {
            "name": info.get("longName") or info.get("shortName") or ticker,
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "description": info.get("longBusinessSummary", ""),
            "country": info.get("country", "N/A"),
            "exchange": info.get("exchange", "N/A"),
            "pe_ratio": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
        }

    fallback = {"name": ticker, "sector": "N/A"}
    result = _run_with_timeout(_do_fetch, timeout=HARD_TIMEOUT_SECONDS, default=None)
    return result if result is not None else fallback


def get_historical_data(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
    """
    Download OHLCV historical data with SQLite cache (TTL=1h).
    Cache key: (ticker, period, interval). At most one entry per combination.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
    """
    ticker_upper = ticker.upper()

    # 1. Cache read
    if _cache_enabled():
        try:
            with session_scope() as session:
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
        except Exception:
            log.exception("Historical cache read failed for %s", ticker)

    # 2. Live download — guarded by hard timeout
    def _do_download() -> pd.DataFrame | None:
        try:
            df = yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
                timeout=NETWORK_TIMEOUT_SECONDS,
            )
            if df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.index = pd.to_datetime(df.index)
            return df
        except Exception:
            log.exception("Historical data download failed for %s", ticker)
            return None

    df = _run_with_timeout(
        _do_download,
        timeout=HARD_TIMEOUT_SECONDS * 2,  # downloads can be larger
        default=None,
    )
    if df is None:
        record_failure(
            ticker,
            f"Sin datos históricos ({period}/{interval}) — símbolo posiblemente deslistado",
            operation="historical",
        )
        return None

    # 2.5 Quality check + light cleaning. Issues get logged; unusable frames
    # (all-NaN Close) are rejected so callers don't have to defend against
    # silent garbage.
    df, report = clean_ohlcv(df, fill_method="ffill", max_fill_gap=2)
    if df is None or not report.is_usable:
        log.warning("Historical data for %s rejected after QA: %s", ticker, report.summary())
        record_failure(ticker, f"Datos rechazados por QA: {report.summary()}", operation="historical")
        return None
    if report.has_issues():
        log.info("Historical data for %s: %s", ticker, report.summary())

    # 3. Cache write — replace any existing entry for this (ticker, period, interval)
    if _cache_enabled():
        try:
            with session_scope() as session:
                session.query(HistoricalDataCache).filter(
                    HistoricalDataCache.ticker == ticker_upper,
                    HistoricalDataCache.period == period,
                    HistoricalDataCache.interval == interval,
                ).delete()
                session.add(
                    HistoricalDataCache(
                        ticker=ticker_upper,
                        period=period,
                        interval=interval,
                        data_json=df.to_json(orient="split", date_format="iso"),
                    )
                )
        except Exception:
            log.exception("Historical cache write failed for %s", ticker)

    # Descarga exitosa — limpiar registro de fallos previos si existía.
    record_success(ticker)
    return df


def get_dividends_since(ticker: str, since_date: datetime) -> float:
    """
    Return total dividends per share paid since `since_date` for `ticker`.
    Uses DividendCache to avoid repeated API calls.
    Returns 0.0 if the ticker pays no dividends or data is unavailable.
    """
    normalized_since = since_date.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DIVIDEND_CACHE_HOURS)

    try:
        # 1. Cache read
        with session_scope() as session:
            cached = (
                session.query(DividendCache)
                .filter(DividendCache.ticker == ticker.upper())
                .filter(DividendCache.since_date == normalized_since)
                .filter(DividendCache.fetched_at >= cutoff)
                .order_by(DividendCache.fetched_at.desc())
                .first()
            )
            if cached:
                return cached.total_per_share

        # 2. Network fetch (no DB session held)
        total = _fetch_dividends_since(ticker, since_date)

        # 3. Cache write
        with session_scope() as session:
            session.add(
                DividendCache(
                    ticker=ticker.upper(),
                    since_date=normalized_since,
                    total_per_share=total,
                )
            )
        return total

    except Exception:
        log.exception("Dividend fetch failed for %s", ticker)
        return 0.0


def _fetch_dividends_since(ticker: str, since_date: datetime) -> float:
    """Raw yfinance dividend fetch — returns cumulative $/share since since_date."""

    def _do_fetch() -> float:
        try:
            t = _ticker(ticker)
            divs = t.dividends  # pandas Series indexed by date
            if divs is None or divs.empty:
                return 0.0
            # Normalize timezone
            divs.index = divs.index.tz_localize(None) if divs.index.tzinfo is not None else divs.index
            since = pd.Timestamp(since_date)
            filtered = divs[divs.index >= since]
            return float(filtered.sum()) if not filtered.empty else 0.0
        except Exception:
            log.exception("Raw dividend fetch failed for %s", ticker)
            return 0.0

    result = _run_with_timeout(_do_fetch, timeout=HARD_TIMEOUT_SECONDS, default=0.0)
    return result if result is not None else 0.0


def get_bulk_dividends(tickers_since: dict[str, datetime]) -> dict[str, float]:
    """
    Fetch dividends for multiple tickers in parallel.
    tickers_since: {ticker: purchase_date}
    Returns: {ticker: total_dividends_per_share}
    """
    if not tickers_since:
        return {}

    results: dict[str, float] = {}
    max_workers = min(BULK_FETCH_WORKERS, len(tickers_since))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(get_dividends_since, ticker, since): ticker
            for ticker, since in tickers_since.items()
        }
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                results[ticker] = future.result()
            except Exception:
                log.exception("Bulk dividend fetch failed for %s", ticker)
                results[ticker] = 0.0
    return results


def is_market_open() -> tuple[bool, str]:
    """
    Returns (is_open: bool, label: str).
    Checks NYSE/NASDAQ session hours (Mon-Fri 9:30–16:00 ET).
    Does not account for US market holidays.
    """
    try:
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo("America/New_York")
        except ImportError:
            import pytz

            tz = pytz.timezone("America/New_York")

        now_et = datetime.now(tz)
        weekday = now_et.weekday()  # 0=Mon … 6=Sun

        if weekday >= 5:
            return False, "Cerrado (fin de semana)"

        open_t = now_et.replace(hour=MARKET_OPEN_HOUR_ET, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
        close_t = now_et.replace(
            hour=MARKET_CLOSE_HOUR_ET, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0
        )
        pre_t = now_et.replace(hour=PRE_MARKET_OPEN_HOUR_ET, minute=0, second=0, microsecond=0)
        post_t = now_et.replace(hour=POST_MARKET_CLOSE_HOUR_ET, minute=0, second=0, microsecond=0)

        if open_t <= now_et < close_t:
            return True, "Abierto (NYSE/NASDAQ)"
        elif pre_t <= now_et < open_t:
            return False, "Pre-market"
        elif close_t <= now_et < post_t:
            return False, "After-hours"
        else:
            return False, "Cerrado"
    except Exception:
        return False, "—"


def validate_ticker(ticker: str) -> bool:
    """Check whether a ticker symbol is valid on Yahoo Finance. Hard-timeout protected.

    Registra el resultado en ``failed_tickers`` para que la UI lo pueda mostrar
    y los próximos bulk fetch lo puedan saltear.
    """

    def _do_check() -> bool:
        try:
            t = _ticker(ticker)
            price = getattr(t.fast_info, "last_price", None)
            return price is not None
        except Exception:
            return False

    ok = bool(_run_with_timeout(_do_check, timeout=HARD_TIMEOUT_SECONDS, default=False))
    if ok:
        record_success(ticker)
    else:
        record_failure(ticker, "Símbolo no encontrado en Yahoo Finance", operation="validate")
    return ok


def get_bulk_prices(tickers: list[str]) -> dict[str, dict | None]:
    """
    Fetch current prices for multiple tickers efficiently.
    Strategy:
      0. Filtrar tickers conocidos como fallidos (status=failing/ignored).
      1. Batch DB cache read.
      2. Parallel live fetches para los misses.
      3. Batch DB cache write.

    Los tickers omitidos devuelven None en el dict resultante, igual que si
    hubieran fallado al consultarse — los consumidores ya saben manejar None.
    """
    if not tickers:
        return {}

    tickers_upper = [t.upper() for t in tickers]
    results: dict[str, dict | None] = {}

    # 0. Filtrar tickers conocidos como inválidos para no gastar QPS ni logs.
    skip_set = get_failing_set()
    if skip_set:
        active_tickers: list[str] = []
        for ticker in tickers_upper:
            if ticker in skip_set:
                results[ticker] = None  # omitidos — la UI ya los muestra en su pestaña
            else:
                active_tickers.append(ticker)
        if not active_tickers:
            log.info("Bulk fetch: todos los tickers están en la lista de fallidos, nada que consultar")
            return results
        tickers_upper = active_tickers

    cache_misses: list[str] = []

    # 1. Single batch cache read (one query for all tickers)
    if _cache_enabled():
        try:
            with session_scope() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=CACHE_TTL_MINUTES)
                cached_rows = (
                    session.query(PriceCache)
                    .filter(PriceCache.ticker.in_(tickers_upper))
                    .filter(PriceCache.fetched_at >= cutoff)
                    .all()
                )
                # Keep only the latest entry per ticker
                cached_map: dict[str, PriceCache] = {}
                for row in cached_rows:
                    if row.ticker not in cached_map or row.fetched_at > cached_map[row.ticker].fetched_at:
                        cached_map[row.ticker] = row

                for ticker in tickers_upper:
                    if ticker in cached_map:
                        row = cached_map[ticker]
                        results[ticker] = {
                            "ticker": row.ticker,
                            "price": row.price,
                            "change_pct": row.change_pct,
                            "volume": row.volume,
                            "market_cap": row.market_cap,
                            "from_cache": True,
                        }
                    else:
                        cache_misses.append(ticker)
        except Exception:
            log.exception("Bulk cache read failed")
            cache_misses = list(tickers_upper)
    else:
        cache_misses = list(tickers_upper)

    if not cache_misses:
        return results

    # 2. Parallel live fetches — pure network I/O, no DB locks
    live_results: dict[str, dict | None] = {}
    max_workers = min(BULK_FETCH_WORKERS, len(cache_misses))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {executor.submit(_fetch_ticker_info, ticker): ticker for ticker in cache_misses}
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                live_results[ticker] = future.result()
            except Exception:
                log.exception("Parallel fetch failed for %s", ticker)
                live_results[ticker] = None

    # 3. Single batch cache write for all successful fetches
    new_entries = [
        PriceCache(
            ticker=ticker,
            price=info["price"],
            change_pct=info.get("change_pct"),
            volume=info.get("volume"),
            market_cap=info.get("market_cap"),
        )
        for ticker, info in live_results.items()
        if info is not None
    ]
    if new_entries:
        try:
            with session_scope() as session:
                session.add_all(new_entries)
        except Exception:
            log.exception("Bulk cache write failed")

    # Merge live results into output
    for ticker, info in live_results.items():
        if info is not None:
            info["from_cache"] = False
        results[ticker] = info

    return results


def search_ticker(query: str) -> list[dict]:
    """
    Simple ticker search — tries direct lookup and common suffixes.
    Returns a list of candidate dicts with ticker and name. Hard-timeout protected.
    """

    def _probe(symbol: str) -> dict | None:
        try:
            t = _ticker(symbol)
            price = getattr(t.fast_info, "last_price", None)
            if price is None:
                return None
            info = t.info
            return {
                "ticker": symbol,
                "name": info.get("longName") or info.get("shortName") or symbol,
                "exchange": info.get("exchange", ""),
                "currency": info.get("currency", "USD"),
            }
        except Exception:
            return None

    candidates: list[dict] = []
    suffixes = [query.upper(), f"{query.upper()}.BA", f"{query.upper()}.L", f"{query.upper()}.AX"]
    for symbol in suffixes:
        result = _run_with_timeout(_probe, symbol, timeout=HARD_TIMEOUT_SECONDS, default=None)
        if result is not None:
            candidates.append(result)
    return candidates
