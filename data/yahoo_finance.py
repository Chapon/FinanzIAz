"""
Yahoo Finance data layer using yfinance.
Handles fetching current prices, historical data, and company info.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from database.models import get_session, PriceCache, DividendCache


CACHE_TTL_MINUTES = 5  # Refresh price cache every 5 minutes

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
        cutoff = datetime.utcnow() - timedelta(minutes=CACHE_TTL_MINUTES)
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
    Download OHLCV historical data.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
    """
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            return None
        # Flatten multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        print(f"[YF] Historical data failed for {ticker}: {e}")
        return None


DIVIDEND_CACHE_HOURS = 6  # Re-fetch dividends every 6 hours


def get_dividends_since(ticker: str, since_date: datetime) -> float:
    """
    Return total dividends per share paid since `since_date` for `ticker`.
    Uses DividendCache to avoid repeated API calls.
    Returns 0.0 if the ticker pays no dividends or data is unavailable.
    """
    session = get_session()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=DIVIDEND_CACHE_HOURS)
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
    Fetch dividends for multiple tickers efficiently.
    tickers_since: {ticker: purchase_date}
    Returns: {ticker: total_dividends_per_share}
    """
    results = {}
    for ticker, since in tickers_since.items():
        results[ticker] = get_dividends_since(ticker, since)
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
    """Fetch current prices for multiple tickers efficiently."""
    results = {}
    for ticker in tickers:
        results[ticker] = get_current_price(ticker)
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
