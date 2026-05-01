"""
Yahoo Finance data layer using yfinance.
Handles fetching current prices, historical data, and company info.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from database.models import get_session, PriceCache, DividendCache, HistoricalDataCache

BULK_FETCH_WORKERS = 5        # Max parallel threads for bulk price fetches
CACHE_TTL_MINUTES = 5         # Price cache TTL
HISTORICAL_CACHE_TTL_HOURS = 1  # OHLCV cache TTL

def _cache_enabled() -> bool:
    try:
        from config.settings_manager import settings
        return settings.get("cache", True)
    except Exception:
        return True


def get_current_price(ticker: str) -> Optional[dict]:
    """
    Fetch current price and key metrics for a ticker.
    Returns a dict with price, change_pct, volume, market_cap, etc.
    Uses an in-DB cache to avoid hammering the API.
    """
    session = get_session()
    try:
        # Check cache first (skip if cache setting is disabled)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=CACHE_TTL_MINUTES)
        cached = None
        if _cache_enabled():
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

        # Fetch live
        info = _fetch_ticker_info(ticker)
        if info is None:
            return None

        # Store in cache
        entry = PriceCache(
            ticker=ticker.upper(),
            price=info["price"],
            change_pct=info.get("change_pct"),
            volume=info.get("volume"),
            market_cap=info.get("market_cap"),
        )
        session.add(entry)
        session.commit()
        info["from_cache"] = False
        return info

    except Exception as e:
        print(f"[YF] Error fetching {ticker}: {e}")
        return None
    finally:
        session.close()


def _fetch_ticker_info(ticker: str) -> Optional[dict]:
    """Raw yfinance fetch — returns a clean dict."""
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info

        price = getattr(info, "last_price", None)
        prev_close = getattr(info, "previous_close", None)
        if price is None:
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
        print(f"[YF] Raw fetch failed for {ticker}: {e}")
        return None


def get_company_info(ticker: str) -> dict:
    """Fetch company name, sector, description from yfinance."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
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
    except Exception as e:
        print(f"[YF] Company info failed for {ticker}: {e}")
        return {"name": ticker, "sector": "N/A"}


def get_historical_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d"
) -> Optional[pd.DataFrame]:
    """
    Download OHLCV historical data with SQLite cache (TTL=1h).
    Cache key: (ticker, period, interval). At most one entry per combination.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
    """
    ticker_upper = ticker.upper()

    # 1. Cache read
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
            print(f"[YF] Historical cache read failed for {ticker}: {e}")
        finally:
            session.close()

    # 2. Live download
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
    except Exception as e:
        print(f"[YF] Historical data failed for {ticker}: {e}")
        return None

    # 3. Cache write — replace any existing entry for this (ticker, period, interval)
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
            print(f"[YF] Historical cache write failed for {ticker}: {e}")
            session.rollback()
        finally:
            session.close()

    return df


DIVIDEND_CACHE_HOURS = 6  # Re-fetch dividends every 6 hours


def get_dividends_since(ticker: str, since_date: datetime) -> float:
    """
    Return total dividends per share paid since `since_date` for `ticker`.
    Uses DividendCache to avoid repeated API calls.
    Returns 0.0 if the ticker pays no dividends or data is unavailable.
    """
    session = get_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=DIVIDEND_CACHE_HOURS)
        cached = (
            session.query(DividendCache)
            .filter(DividendCache.ticker == ticker.upper())
            .filter(DividendCache.since_date == since_date.replace(hour=0, minute=0, second=0, microsecond=0))
            .filter(DividendCache.fetched_at >= cutoff)
            .order_by(DividendCache.fetched_at.desc())
            .first()
        )
        if cached:
            return cached.total_per_share

        # Fetch from Yahoo Finance
        total = _fetch_dividends_since(ticker, since_date)

        # Store in cache
        entry = DividendCache(
            ticker=ticker.upper(),
            since_date=since_date.replace(hour=0, minute=0, second=0, microsecond=0),
            total_per_share=total,
        )
        session.add(entry)
        session.commit()
        return total

    except Exception as e:
        print(f"[YF] Dividend fetch failed for {ticker}: {e}")
        return 0.0
    finally:
        session.close()


def _fetch_dividends_since(ticker: str, since_date: datetime) -> float:
    """Raw yfinance dividend fetch — returns cumulative $/share since since_date."""
    try:
        t = yf.Ticker(ticker)
        divs = t.dividends  # pandas Series indexed by date
        if divs is None or divs.empty:
            return 0.0
        # Normalize timezone
        divs.index = divs.index.tz_localize(None) if divs.index.tzinfo is not None else divs.index
        since = pd.Timestamp(since_date)
        filtered = divs[divs.index >= since]
        return float(filtered.sum()) if not filtered.empty else 0.0
    except Exception as e:
        print(f"[YF] Raw dividend fetch failed for {ticker}: {e}")
        return 0.0


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
            except Exception as e:
                print(f"[YF] Bulk dividend fetch failed for {ticker}: {e}")
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
        weekday = now_et.weekday()          # 0=Mon … 6=Sun

        if weekday >= 5:
            return False, "Cerrado (fin de semana)"

        open_t  = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
        close_t = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)
        pre_t   = now_et.replace(hour=4,  minute=0,  second=0, microsecond=0)
        post_t  = now_et.replace(hour=20, minute=0,  second=0, microsecond=0)

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
    """Check whether a ticker symbol is valid on Yahoo Finance."""
    try:
        t = yf.Ticker(ticker)
        price = getattr(t.fast_info, "last_price", None)
        return price is not None
    except Exception:
        return False


def get_bulk_prices(tickers: list[str]) -> dict[str, Optional[dict]]:
    """
    Fetch current prices for multiple tickers efficiently.
    Strategy: 1 batch DB read → parallel live fetches for misses → 1 batch DB write.
    """
    if not tickers:
        return {}

    tickers_upper = [t.upper() for t in tickers]
    results: dict[str, Optional[dict]] = {}
    cache_misses: list[str] = []

    # 1. Single batch cache read (one query for all tickers)
    if _cache_enabled():
        session = get_session()
        try:
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
        except Exception as e:
            print(f"[YF] Bulk cache read failed: {e}")
            cache_misses = list(tickers_upper)
        finally:
            session.close()
    else:
        cache_misses = list(tickers_upper)

    if not cache_misses:
        return results

    # 2. Parallel live fetches — pure network I/O, no DB locks
    live_results: dict[str, Optional[dict]] = {}
    max_workers = min(BULK_FETCH_WORKERS, len(cache_misses))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(_fetch_ticker_info, ticker): ticker
            for ticker in cache_misses
        }
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                live_results[ticker] = future.result()
            except Exception as e:
                print(f"[YF] Parallel fetch failed for {ticker}: {e}")
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
        session = get_session()
        try:
            session.add_all(new_entries)
            session.commit()
        except Exception as e:
            print(f"[YF] Bulk cache write failed: {e}")
            session.rollback()
        finally:
            session.close()

    # Merge live results into output
    for ticker, info in live_results.items():
        if info is not None:
            info["from_cache"] = False
        results[ticker] = info

    return results


def search_ticker(query: str) -> list[dict]:
    """
    Simple ticker search — tries direct lookup and common suffixes.
    Returns a list of candidate dicts with ticker and name.
    """
    candidates = []
    for symbol in [query.upper(), f"{query.upper()}.BA", f"{query.upper()}.L", f"{query.upper()}.AX"]:
        try:
            t = yf.Ticker(symbol)
            price = getattr(t.fast_info, "last_price", None)
            if price is not None:
                info = t.info
                candidates.append({
                    "ticker": symbol,
                    "name": info.get("longName") or info.get("shortName") or symbol,
                    "exchange": info.get("exchange", ""),
                    "currency": info.get("currency", "USD"),
                })
        except Exception:
            continue
    return candidates
