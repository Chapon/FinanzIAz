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

import threading
import time
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
    EARNINGS_CACHE_HOURS,
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
    NETWORK_THROTTLE_COOLDOWN_SECONDS as THROTTLE_COOLDOWN_SECONDS,
)
from config.constants import (
    PRICE_CACHE_TTL_MINUTES as CACHE_TTL_MINUTES,
)
from config.logging_config import get_logger
from data.failed_tickers import (
    get_failing_set,
    record_failure,
    record_success,
    record_transient,
)
from data.quality import clean_ohlcv
from database.models import (
    AnalystDataCache,
    DividendCache,
    EarningsCache,
    HistoricalDataCache,
    PriceCache,
    session_scope,
)

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


# Firmas de errores transitorios de Yahoo que vale la pena reintentar y que NO
# merecen un traceback completo en el log. El caso típico: Yahoo invalida el
# "crumb" anti-bot (HTTP 401 "Invalid Crumb"/"Unauthorized") o nos throttlea
# (429). yfinance 1.x ya no usa nuestra requests.Session con retry adapter
# (maneja su propio curl_cffi), así que el reintento tiene que vivir acá.
_TRANSIENT_HINTS = (
    "401",
    "invalid crumb",
    "unauthorized",
    "429",
    "too many requests",
    "rate limit",
)


def _is_transient(exc: BaseException) -> bool:
    """True si ``exc`` parece un fallo transitorio de auth/throttle de Yahoo.

    Incluye el ``TypeError: argument of type 'NoneType' is not iterable`` que
    yfinance tira desde su scraper de crumb cuando Yahoo devuelve ``result:
    null`` — es síntoma de un 401, no un bug de datos.
    """
    if isinstance(exc, TypeError) and "nonetype" in str(exc).lower():
        return True
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(hint in msg for hint in _TRANSIENT_HINTS)


# ── Circuit-breaker de throttle (bug B3) ─────────────────────────────────────
# Cuando Yahoo deja de responder (hard-timeout, 401/crumb/429 repetido, o un lote
# entero vuelve vacío) abrimos un breaker por ``THROTTLE_COOLDOWN_SECONDS``.
# Mientras está abierto:
#   1. Las nuevas llamadas de red fallan rápido (no se queman 15s×N tickers) →
#      el scan termina en segundos en vez de colgarse minutos.
#   2. Los fallos se clasifican como TRANSITORIOS (no delisting permanente), así
#      un large-cap real que falló por el throttle NO queda excluido del universo.
_throttle_lock = threading.Lock()
_throttle_until = 0.0  # time.monotonic() hasta cuando el breaker está abierto


def _note_throttle(cooldown: float = THROTTLE_COOLDOWN_SECONDS) -> None:
    """Abre (o extiende) el breaker: Yahoo está throttleando/no responde."""
    global _throttle_until
    with _throttle_lock:
        _throttle_until = max(_throttle_until, time.monotonic() + cooldown)


def _is_throttled() -> bool:
    """True si el breaker está abierto (cooldown vigente)."""
    with _throttle_lock:
        return time.monotonic() < _throttle_until


def reset_throttle() -> None:
    """Cierra el breaker. Para tests — el estado es global al proceso."""
    global _throttle_until
    with _throttle_lock:
        _throttle_until = 0.0


def _record_miss(ticker: str, error: str, operation: str) -> None:
    """Registra un fetch fallido clasificándolo según el breaker.

    Con el breaker abierto (throttle activo) el fallo es casi seguro culpa de
    Yahoo, no del símbolo → ``record_transient`` (no envenena el failing set).
    Con el breaker cerrado el símbolo falló en una red sana → ``record_failure``
    (delisting/ticker inválido genuino, se saltea en adelante).
    """
    if _is_throttled():
        record_transient(ticker, error, operation)
    else:
        record_failure(ticker, error, operation)


def _run_with_timeout(
    fn: Callable[..., T],
    *args,
    timeout: float = HARD_TIMEOUT_SECONDS,
    default: T | None = None,
    retries: int = RETRY_TOTAL,
    retry_backoff: float = RETRY_BACKOFF,
    **kwargs,
) -> T | None:
    """
    Run ``fn(*args, **kwargs)`` and abort if it takes longer than ``timeout``.
    On timeout / exception returns ``default`` (None by default).
    Acquires one global rate-limiter token before each submit.

    Errores transitorios de Yahoo (401/crumb/429) se reintentan hasta
    ``retries`` veces con backoff exponencial y se loguean en una línea
    (sin traceback). Cualquier otro error se loguea con traceback una sola vez.

    Si el circuit-breaker de throttle está abierto, retorna ``default`` de
    inmediato sin tocar la red (fail-fast) — evita quemar el timeout completo
    en cada ticker mientras Yahoo no responde.
    """
    if _is_throttled():
        log.debug("Throttle breaker abierto: %s salteado (fail-fast)", getattr(fn, "__name__", fn))
        return default
    attempt = 0
    fn_name = getattr(fn, "__name__", fn)
    while True:
        _acquire_rate_token()
        future = _TIMEOUT_POOL.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            future.cancel()
            log.warning("Hard timeout (%ss) running %s", timeout, fn_name)
            _note_throttle()  # Yahoo colgó → abrir breaker para los próximos tickers
            return default
        except Exception as exc:
            transient = _is_transient(exc)
            if transient and attempt < retries:
                attempt += 1
                sleep_s = retry_backoff * (2 ** (attempt - 1))
                log.warning(
                    "Transient yfinance error on %s (attempt %d/%d): %s — retry in %.1fs",
                    fn_name,
                    attempt,
                    retries,
                    exc,
                    sleep_s,
                )
                time.sleep(sleep_s)
                continue
            if transient:
                log.warning("yfinance call %s failed (transient, gave up): %s", fn_name, exc)
                _note_throttle()  # throttle persistente → abrir breaker
            else:
                log.exception("yfinance call %s raised", fn_name)
            return default


def _cache_enabled() -> bool:
    try:
        from config.settings_manager import settings

        return settings.get("cache", True)
    except Exception:
        return True


# ── Sanity de precios fuera de banda (E5) ─────────────────────────────────────
# Yahoo devuelve ocasionalmente una cotización con la escala corrupta (~10× por
# la familia "Invalid Crumb"/401 o un split mal conciliado). El caso KLAC
# 2026-06-01/05 se abrió y cerró un round-trip entero a ~$1.940 cuando el precio
# real era ~$194 → el notional quedó 10× inflado y contaminó métricas, DD, ADV y
# hasta la muestra de salidas ATR. Un precio así difiere del último close diario
# cacheado por > banda: lo tratamos como basura, no como precio real. Misma
# lógica de higiene que ``scripts/run_atr_stop_recalib.partition_atr_events``.

# Banda por defecto: un salto > 50% vs el último close diario es basura, no una
# cotización real (un movimiento day-over-day de esa magnitud es un halt raro,
# no lo normal). Override vía setting ``price_sanity_band_pct``; 0 desactiva.
_DEFAULT_PRICE_SANITY_BAND = 0.5


def _price_sanity_band() -> float:
    """Banda relativa aceptada vs el close de referencia (fracción). 0 = off."""
    try:
        from config.settings_manager import settings

        band = float(settings.get("price_sanity_band_pct", _DEFAULT_PRICE_SANITY_BAND))
    except Exception:
        band = _DEFAULT_PRICE_SANITY_BAND
    return band if band > 0 else 0.0


def reference_close(ticker: str) -> float | None:
    """Último close diario válido del cache OHLCV, como ancla de escala.

    Devuelve None si no hay frame cacheado (cold cache / cache off) → el guard
    debe fail-open cuando no puede juzgar la escala. Lee el frame ``1d`` más
    fresco sin importar el ``period`` con que se haya cacheado.
    """
    if not _cache_enabled():
        return None
    try:
        with session_scope() as session:
            cached = (
                session.query(HistoricalDataCache)
                .filter(HistoricalDataCache.ticker == ticker.upper())
                .filter(HistoricalDataCache.interval == "1d")
                .order_by(HistoricalDataCache.fetched_at.desc())
                .first()
            )
            if cached is None:
                return None
            df = pd.read_json(StringIO(cached.data_json), orient="split")
        if "Close" not in df.columns or df.empty:
            return None
        closes = pd.to_numeric(df["Close"], errors="coerce").dropna()
        closes = closes[closes > 0]
        if closes.empty:
            return None
        return float(closes.iloc[-1])
    except Exception:
        log.exception("reference_close failed for %s", ticker)
        return None


def is_price_out_of_band(
    price: float | None, reference: float | None, band: float | None = None
) -> bool:
    """True si ``price`` difiere de ``reference`` por más de ``band`` (fracción).

    Fail-open: si falta el precio, la referencia o la banda está en 0, devuelve
    False (no podemos juzgar la escala → no bloqueamos).
    """
    b = _price_sanity_band() if band is None else float(band)
    if b <= 0 or reference is None or price is None:
        return False
    try:
        ref = float(reference)
        px = float(price)
    except (TypeError, ValueError):
        return False
    if ref <= 0 or px <= 0:
        return False
    return abs(px / ref - 1.0) > b


def _reject_if_out_of_band(ticker_upper: str, info: dict | None) -> dict | None:
    """Descarta un fetch en vivo cuyo precio esté fuera de banda vs el histórico.

    Devuelve el ``info`` intacto si el precio es sano (o no hay referencia), o
    None si es basura de escala. NO envenena el ``failing`` set: la corrupción es
    transitoria (símbolo vivo, dato podrido) → el próximo scan reintenta.
    """
    if info is None:
        return None
    price = info.get("price")
    ref = reference_close(ticker_upper)
    if is_price_out_of_band(price, ref):
        log.warning(
            "Precio fuera de banda para %s: %.4f vs último close %.4f "
            "(desvío %.0f%% > %.0f%%) — descartado como cotización corrupta",
            ticker_upper,
            float(price),
            float(ref),
            abs(float(price) / float(ref) - 1.0) * 100,
            _price_sanity_band() * 100,
        )
        return None
    return info


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

        # 2b. Guard de sanity (E5): descartar cotizaciones con escala corrupta
        # (~10× tipo KLAC) antes de cachearlas o devolverlas.
        info = _reject_if_out_of_band(ticker.upper(), info)
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


def _safe_fast_info(info: object, name: str, default: T | None = None) -> T | None:
    """Lee una property de ``fast_info`` sin que un atributo roto tumbe el fetch.

    Las properties de ``fast_info`` (``last_price``, ``previous_close``, …) son
    lazy: pegan a la red y parsean metadata, así que pueden **lanzar** en vez de
    devolver ``None`` — el caso típico es ``KeyError: 'exchangeTimezoneName'`` en
    símbolos con metadata incompleta/deslistados (bug B1). ``getattr(obj, name,
    default)`` solo cae al default ante ``AttributeError``, así que esa excepción
    se filtraba, subía por todo el fetch y terminaba en ``log.exception`` con un
    traceback ruidoso (y podía cascada a hard-timeouts).

    Tratamos cualquier fallo estructural de lectura como "dato ausente"
    (``default``). Los errores **transitorios** de Yahoo (401/crumb/429) sí se
    re-lanzan para que ``_run_with_timeout`` los reintente: un throttle no es un
    símbolo muerto.
    """
    try:
        value = getattr(info, name, default)
    except Exception as exc:
        if _is_transient(exc):
            raise
        return default
    return value if value is not None else default


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

            price = _safe_fast_info(info, "last_price")
            prev_close = _safe_fast_info(info, "previous_close")
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
                "volume": _safe_fast_info(info, "three_month_average_volume"),
                "market_cap": _safe_fast_info(info, "market_cap"),
                "fifty_two_week_high": _safe_fast_info(info, "year_high"),
                "fifty_two_week_low": _safe_fast_info(info, "year_low"),
                "currency": _safe_fast_info(info, "currency", "USD"),
            }
        except Exception as e:
            last_exc.append(f"{type(e).__name__}: {e}")
            raise

    result = _run_with_timeout(_do_fetch, timeout=HARD_TIMEOUT_SECONDS, default=None)
    if result is None:
        err = last_exc[0] if last_exc else "Sin datos disponibles"
        # _record_miss: con el breaker abierto (throttle) lo marca transitorio en
        # vez de envenenar el failing set con un símbolo real (bug B3).
        _record_miss(ticker, err, operation="price")
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


# Tamaño de lote por defecto para get_historical_data_batch. Yahoo tolera mal
# payloads gigantes (sube el riesgo de timeout y de respuestas parciales), así
# que partimos universos grandes en chunks de este tamaño.
_DEFAULT_BATCH_SIZE = 20


def _read_historical_cache(
    ticker_upper: str, period: str, interval: str
) -> pd.DataFrame | None:
    """Devuelve el frame cacheado fresco para (ticker, period, interval) o None.

    Misma lógica de lectura que usaba ``get_historical_data`` inline; extraída
    para que la versión single y la batch compartan exactamente el mismo cache.
    """
    if not _cache_enabled():
        return None
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
        log.exception("Historical cache read failed for %s", ticker_upper)
    return None


def _write_historical_cache(
    ticker_upper: str, period: str, interval: str, df: pd.DataFrame
) -> None:
    """Reemplaza la entrada de cache para (ticker, period, interval)."""
    if not _cache_enabled():
        return
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
        log.exception("Historical cache write failed for %s", ticker_upper)


def _normalize_ohlcv(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Aplana el MultiIndex de columnas de una descarga single-ticker.

    ``yf.download`` para un solo símbolo devuelve columnas MultiIndex
    ``(field, ticker)`` con el field en el nivel 0. Devuelve None si el frame
    viene vacío.
    """
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    return df


def _finalize_historical(
    ticker_upper: str, df: pd.DataFrame | None, period: str, interval: str
) -> pd.DataFrame | None:
    """QA + cache write + record_success/failure para un frame ya descargado.

    Punto único de finalización compartido por ``get_historical_data`` y
    ``get_historical_data_batch`` para que ambos hagan exactamente la misma
    limpieza, validación y registro de fallos por ticker.
    """
    if df is None:
        # _record_miss: bajo throttle (breaker abierto) es transitorio, no delisting.
        _record_miss(
            ticker_upper,
            f"Sin datos históricos ({period}/{interval}) — símbolo posiblemente deslistado",
            operation="historical",
        )
        return None

    # Quality check + light cleaning. Issues get logged; unusable frames
    # (all-NaN Close) are rejected so callers don't have to defend against
    # silent garbage.
    df, report = clean_ohlcv(df, fill_method="ffill", max_fill_gap=2)
    if df is None or not report.is_usable:
        log.warning("Historical data for %s rejected after QA: %s", ticker_upper, report.summary())
        record_failure(ticker_upper, f"Datos rechazados por QA: {report.summary()}", operation="historical")
        return None
    if report.has_issues():
        log.info("Historical data for %s: %s", ticker_upper, report.summary())

    _write_historical_cache(ticker_upper, period, interval, df)
    # Descarga exitosa — limpiar registro de fallos previos si existía.
    record_success(ticker_upper)
    return df


def get_historical_data(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
    """
    Download OHLCV historical data with SQLite cache (TTL=1h).
    Cache key: (ticker, period, interval). At most one entry per combination.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo

    Para varios tickers preferí ``get_historical_data_batch``: agrupa los
    cache-misses en una sola llamada que reutiliza un único crumb de Yahoo,
    reduciendo los 401 "Invalid Crumb".
    """
    ticker_upper = ticker.upper()

    # 1. Cache read
    cached = _read_historical_cache(ticker_upper, period, interval)
    if cached is not None:
        return cached

    # 2. Live download — guarded by hard timeout
    def _do_download() -> pd.DataFrame | None:
        try:
            df = yf.download(
                ticker_upper,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
                timeout=NETWORK_TIMEOUT_SECONDS,
            )
            return _normalize_ohlcv(df)
        except Exception:
            log.exception("Historical data download failed for %s", ticker_upper)
            return None

    df = _run_with_timeout(
        _do_download,
        timeout=HARD_TIMEOUT_SECONDS * 2,  # downloads can be larger
        default=None,
    )
    # 3. QA + cache + record (shared finalizer)
    return _finalize_historical(ticker_upper, df, period, interval)


def _chunked(seq: list[str], size: int):
    """Parte ``seq`` en sublistas de a lo sumo ``size`` elementos."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _slice_ticker(batch_df: pd.DataFrame | None, ticker_upper: str) -> pd.DataFrame | None:
    """Extrae el sub-frame OHLCV de ``ticker_upper`` de una descarga batch.

    ``yf.download(..., group_by="ticker")`` con varios símbolos devuelve
    columnas MultiIndex ``(ticker, field)`` (ticker en nivel 0). Con un solo
    símbolo en el lote devuelve columnas planas (solo field). Yahoo además
    rellena con NaN los símbolos que fallaron dentro del lote, así que se
    descartan las filas all-NaN y se trata como fallo si no queda nada.
    """
    if batch_df is None:
        return None
    try:
        if isinstance(batch_df.columns, pd.MultiIndex):
            if ticker_upper not in batch_df.columns.get_level_values(0):
                return None
            sub = batch_df[ticker_upper].copy()
        else:
            # Lote de un solo símbolo → columnas planas, ya es el frame del ticker.
            sub = batch_df.copy()
        sub.index = pd.to_datetime(sub.index)
        sub = sub.dropna(how="all")
        if sub.empty:
            return None
        return sub
    except Exception:
        log.exception("Failed slicing batch frame for %s", ticker_upper)
        return None


def _download_batch(
    chunk: list[str], period: str, interval: str
) -> pd.DataFrame | None:
    """Una sola descarga yf.download para todo ``chunk`` (un crumb compartido)."""

    def _do_download() -> pd.DataFrame | None:
        try:
            df = yf.download(
                " ".join(chunk),
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
                group_by="ticker",
                threads=False,  # serial: comparte crumb, más amable con el rate limit
                timeout=NETWORK_TIMEOUT_SECONDS,
            )
            if df is None or df.empty:
                return None
            return df
        except Exception:
            log.exception("Batch historical download failed for %s", chunk)
            return None

    return _run_with_timeout(
        _do_download,
        timeout=HARD_TIMEOUT_SECONDS * 3,  # un lote es más grande que una descarga single
        default=None,
    )


def get_historical_data_batch(
    tickers: list[str],
    period: str = "1y",
    interval: str = "1d",
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> dict[str, pd.DataFrame | None]:
    """Versión por lotes de ``get_historical_data``.

    Lee el cache por ticker (idéntico a la versión single), agrupa SOLO los
    cache-misses en llamadas ``yf.download`` de a ``batch_size`` símbolos y
    reparte el resultado. Reutilizar un único crumb/cookie para todo el lote en
    vez de pedir uno por ticker reduce drásticamente los 401 "Invalid Crumb".

    La calidad de los datos es idéntica a la versión single: mismo endpoint,
    mismo ``auto_adjust``, misma QA (``clean_ohlcv``) y mismo registro de fallos
    por ticker — un símbolo deslistado dentro del lote se marca individualmente
    sin tumbar a los demás.

    Resiliencia (bug B3/B2):
    - Saltea los tickers ya conocidos como ``failing``/``ignored`` (igual que
      ``get_bulk_prices``) para no re-consultar símbolos muertos cada scan.
    - Si un chunk **entero** vuelve vacío (``_download_batch`` → None) es casi
      seguro un throttle/timeout de Yahoo, NO N delistings simultáneos: abre el
      breaker y marca a esos tickers como TRANSITORIOS (no envenena el failing
      set con large-caps reales). Solo los slices vacíos dentro de un lote que
      SÍ trajo datos se tratan como fallo individual.

    Devuelve un dict ``{TICKER: DataFrame | None}`` con todos los símbolos
    pedidos (de-duplicados, en mayúsculas).
    """
    result: dict[str, pd.DataFrame | None] = {}
    misses: list[str] = []
    seen: set[str] = set()

    # 0. Saltear tickers conocidos como permanentemente malos (cierra B2: no
    #    re-consultar un símbolo muerto en cada warm-up del scan).
    skip_set = get_failing_set()

    # 1. Cache read por ticker (los hits no entran al lote).
    for raw in tickers:
        t = raw.upper()
        if t in seen:
            continue
        seen.add(t)
        if t in skip_set:
            result[t] = None
            continue
        cached = _read_historical_cache(t, period, interval)
        if cached is not None:
            result[t] = cached
        else:
            misses.append(t)

    # 2. Una descarga por chunk para los misses → 3. slice + QA + cache por ticker.
    for chunk in _chunked(misses, max(1, batch_size)):
        batch = _download_batch(chunk, period, interval)
        if batch is None:
            # Falla wholesale del chunk = throttle/timeout, no N delistings.
            # No envenenamos el failing set; estos tickers simplemente faltan
            # este scan y se reintentan el próximo.
            _note_throttle()
            for t in chunk:
                result[t] = None
                record_transient(
                    t, f"Lote histórico vacío ({period}/{interval}) — throttle probable", "historical"
                )
            log.warning(
                "Histórico batch vacío para %d tickers (throttle probable): %s",
                len(chunk),
                ", ".join(chunk),
            )
            continue
        for t in chunk:
            df_t = _slice_ticker(batch, t)
            result[t] = _finalize_historical(t, df_t, period, interval)

    return result


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


def _coerce_earnings_datetime(value) -> datetime | None:
    """Best-effort convert a yfinance calendar entry to a naive ``datetime``.

    yfinance hands back ``datetime.date``, ``datetime.datetime``,
    ``pd.Timestamp`` or ISO strings depending on version. Returns ``None`` for
    anything unparseable.
    """
    import datetime as _dt

    if value is None:
        return None
    # pandas Timestamp is a subclass of datetime, handled by the isinstance below
    if isinstance(value, _dt.datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day)
    try:
        ts = pd.Timestamp(value)
        if ts is pd.NaT:
            return None
        py = ts.to_pydatetime()
        return py.replace(tzinfo=None) if py.tzinfo is not None else py
    except Exception:
        return None


def _parse_next_earnings(calendar, *, now: datetime | None = None) -> datetime | None:
    """Extract the next upcoming earnings ``datetime`` from a yfinance calendar.

    Handles both calendar shapes yfinance has shipped:
    - **dict** (recent versions): ``{"Earnings Date": [date, ...], ...}``
    - **DataFrame** (older versions): a frame whose ``Earnings Date`` row /
      column holds one or more dates.

    Returns the earliest earnings date that is **today or in the future**; if
    every parsed date is in the past, returns the latest past date (so a
    just-reported ticker still trips the ±window). Returns ``None`` if no
    date can be parsed.
    """
    if calendar is None:
        return None

    raw_values: list = []
    try:
        if isinstance(calendar, dict):
            raw_values = calendar.get("Earnings Date") or calendar.get("earningsDate") or []
            if not isinstance(raw_values, (list, tuple)):
                raw_values = [raw_values]
        elif isinstance(calendar, pd.DataFrame):
            if "Earnings Date" in calendar.index:
                raw_values = list(calendar.loc["Earnings Date"].values)
            elif "Earnings Date" in calendar.columns:
                raw_values = list(calendar["Earnings Date"].values)
        else:
            return None
    except Exception:
        return None

    parsed = [d for d in (_coerce_earnings_datetime(v) for v in raw_values) if d is not None]
    if not parsed:
        return None

    ref = now or datetime.now()
    future = sorted(d for d in parsed if d >= ref)
    if future:
        return future[0]
    # All in the past — return the most recent one (post-earnings gap window).
    return max(parsed)


def get_next_earnings_date(ticker: str) -> datetime | None:
    """Return the next scheduled earnings ``datetime`` for ``ticker``.

    Reads ``yfinance.Ticker(t).calendar``, cached for ``EARNINGS_CACHE_HOURS``
    in the ``earnings_cache`` table. **Fail-open**: any error (unknown ticker,
    API failure, unparseable calendar) returns ``None`` so the caller's gate
    can default to not blocking. A cached row with NULL ``earnings_date``
    encodes "asked recently, nothing upcoming" and is honoured for the TTL so
    we don't re-hit the API on every scan.
    """
    ticker_upper = ticker.upper()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=EARNINGS_CACHE_HOURS)

    # 1. Cache read (own session, released before the network call)
    if _cache_enabled():
        try:
            with session_scope() as session:
                cached = (
                    session.query(EarningsCache)
                    .filter(EarningsCache.ticker == ticker_upper)
                    .filter(EarningsCache.fetched_at >= cutoff)
                    .order_by(EarningsCache.fetched_at.desc())
                    .first()
                )
                if cached is not None:
                    return cached.earnings_date
        except Exception:
            log.exception("Earnings cache read failed for %s", ticker)

    # 2. Network fetch — hard-timeout protected, fail-open
    def _do_fetch() -> datetime | None:
        t = _ticker(ticker)
        return _parse_next_earnings(t.calendar)

    earnings_dt = _run_with_timeout(_do_fetch, timeout=HARD_TIMEOUT_SECONDS, default=None)

    # 3. Cache write (including the negative result — earnings_dt may be None)
    if _cache_enabled():
        try:
            with session_scope() as session:
                session.query(EarningsCache).filter(EarningsCache.ticker == ticker_upper).delete()
                session.add(EarningsCache(ticker=ticker_upper, earnings_date=earnings_dt))
        except Exception:
            log.exception("Earnings cache write failed for %s", ticker)

    return earnings_dt


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

    # 2b. Guard de sanity (E5): descartar cotizaciones con escala corrupta
    # (~10× tipo KLAC) antes de cachearlas/mergearlas. Solo sobre los fetch en
    # vivo — lo que salió del cache ya pasó el guard cuando se trajo por primera
    # vez. Un precio fuera de banda queda como miss (None) y se reintenta el
    # próximo scan; NO envenena el failing set (la corrupción es transitoria).
    for ticker in list(live_results):
        live_results[ticker] = _reject_if_out_of_band(ticker, live_results[ticker])

    # 2c. Detección wholesale (bug B3): si había ≥2 misses y TODOS fallaron, no son
    # N símbolos muertos a la vez — es throttle de Yahoo. Abrimos el breaker y, por
    # si alguno alcanzó a quedar 'failing' antes de abrirlo (carrera al inicio del
    # throttle), lo degradamos a transitorio para no excluir large-caps reales.
    failed = [t for t in cache_misses if live_results.get(t) is None]
    if len(cache_misses) >= 2 and len(failed) == len(cache_misses):
        _note_throttle()
        log.warning(
            "Bulk prices: %d/%d tickers sin precio a la vez (throttle probable) — no se envenena el failing set",
            len(failed),
            len(cache_misses),
        )
        for t in failed:
            record_transient(t, "Bulk de precios vacío — throttle probable", "price", override=True)

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


# ── Analyst recommendations + price targets ─────────────────────────────────
# Yahoo expone snapshots mensuales (mes actual + 3 anteriores) con conteos por
# bucket (strongBuy, buy, hold, sell, strongSell), más un dict de price targets
# (mean/median/low/high/current). No cambia con frecuencia (~semanal), así que
# usamos cache en memoria con TTL para evitar re-fetch al cambiar de ticker.

_ANALYST_CACHE_TTL_SECONDS: int = 24 * 60 * 60  # 24h — sobrevive a reinicios via DB
_analyst_cache: dict[str, tuple[float, dict]] = {}  # warm cache in-RAM dentro de la sesión


def _analyst_cache_read_db(ticker_upper: str) -> dict | None:
    """Lee la última entrada vigente de ``AnalystDataCache`` para el ticker.

    Devuelve el dict deserializado si está dentro de la ventana TTL, ``None``
    en caso contrario (cache miss, expirado, o error de DB).
    """
    import json

    try:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=_ANALYST_CACHE_TTL_SECONDS
        )
        with session_scope() as session:
            row = (
                session.query(AnalystDataCache)
                .filter(AnalystDataCache.ticker == ticker_upper)
                .filter(AnalystDataCache.fetched_at >= cutoff)
                .order_by(AnalystDataCache.fetched_at.desc())
                .first()
            )
            if row is None:
                return None
            try:
                return json.loads(row.data_json)
            except Exception:
                log.exception("Failed to parse cached analyst JSON for %s", ticker_upper)
                return None
    except Exception:
        # DB hiccup no debe romper el fetch — caemos a la red.
        log.exception("Analyst cache DB read failed for %s", ticker_upper)
        return None


def _analyst_cache_write_db(ticker_upper: str, payload: dict) -> None:
    """Persiste la respuesta a DB reemplazando entradas previas del mismo ticker."""
    import json

    try:
        with session_scope() as session:
            session.query(AnalystDataCache).filter(
                AnalystDataCache.ticker == ticker_upper
            ).delete()
            session.add(
                AnalystDataCache(
                    ticker=ticker_upper,
                    data_json=json.dumps(payload),
                )
            )
    except Exception:
        log.exception("Analyst cache DB write failed for %s", ticker_upper)


def _bucket_recommendations(df: pd.DataFrame | None) -> list[dict]:
    """Normaliza el DataFrame de ``Ticker.recommendations`` a una lista de buckets
    por mes ordenada del más antiguo al más reciente.

    Cada entrada: ``{"period": "0m"|"-1m"|"-2m"|"-3m", "strongBuy": int,
    "buy": int, "hold": int, "sell": int, "strongSell": int, "total": int}``.
    Devuelve ``[]`` si no hay datos.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []

    buckets = ["strongBuy", "buy", "hold", "sell", "strongSell"]
    # Algunas versiones de yfinance no traen columna ``period``; en ese caso
    # asumimos orden 0m, -1m, -2m, -3m por índice.
    has_period = "period" in df.columns
    out: list[dict] = []
    for i, row in df.iterrows():
        try:
            period = str(row["period"]) if has_period else f"-{i}m" if i > 0 else "0m"
            entry = {"period": period}
            total = 0
            for b in buckets:
                v = int(row[b]) if b in row and pd.notna(row[b]) else 0
                entry[b] = v
                total += v
            entry["total"] = total
            if total > 0:
                out.append(entry)
        except Exception:
            continue

    # Ordenar de más antiguo (-3m) a más reciente (0m) — Google muestra el mes
    # más reciente abajo o arriba según el layout; lo dejamos cronológico y la
    # UI decide el orden visual.
    def _key(b: dict) -> int:
        p = b["period"]
        try:
            return int(p.replace("m", ""))  # "-3m" -> -3, "0m" -> 0
        except Exception:
            return 0

    out.sort(key=_key)
    return out


def _normalize_price_targets(raw) -> dict | None:
    """Convierte el dict de ``Ticker.analyst_price_targets`` a un formato uniforme.

    Devuelve ``{"current": float|None, "mean": float|None, "median": float|None,
    "low": float|None, "high": float|None}`` o ``None`` si no hay datos útiles.
    """
    if not raw or not isinstance(raw, dict):
        return None
    keys = ("current", "mean", "median", "low", "high")
    out = {}
    for k in keys:
        v = raw.get(k)
        try:
            out[k] = float(v) if v is not None and pd.notna(v) else None
        except (TypeError, ValueError):
            out[k] = None
    # Si todos los targets relevantes son None, no vale la pena
    if out["mean"] is None and out["median"] is None and out["high"] is None:
        return None
    return out


def get_analyst_data(ticker: str) -> dict:
    """Fetch recomendaciones de analistas + price targets para ``ticker``.

    Devuelve un dict con dos llaves:
      - ``recommendations``: lista de buckets mensuales (ver ``_bucket_recommendations``)
      - ``price_targets``: dict normalizado o ``None``

    Hard-timeout protegido. Si Yahoo no devuelve nada, ambas llaves quedan vacías
    pero la función nunca tira excepción al caller.
    """
    import time

    ticker_upper = ticker.upper()
    now = time.time()

    # 1. Cache hit en RAM (instantáneo dentro de la sesión)
    cached = _analyst_cache.get(ticker_upper)
    if cached and (now - cached[0]) < _ANALYST_CACHE_TTL_SECONDS:
        return cached[1]

    # 2. Cache hit en DB (sobrevive a reinicios; TTL 24h)
    db_payload = _analyst_cache_read_db(ticker_upper)
    if db_payload is not None:
        _analyst_cache[ticker_upper] = (now, db_payload)
        return db_payload

    # 3. Fetch live + write-through a ambos caches
    def _do_fetch() -> dict:
        out: dict = {"recommendations": [], "price_targets": None}
        try:
            t = _ticker(ticker_upper)
            # Recomendaciones (mensuales, 4 snapshots)
            try:
                recs = t.recommendations
                out["recommendations"] = _bucket_recommendations(recs)
            except Exception:
                log.exception("Recommendations fetch failed for %s", ticker_upper)
            # Price targets
            try:
                pt = getattr(t, "analyst_price_targets", None)
                out["price_targets"] = _normalize_price_targets(pt)
            except Exception:
                log.exception("Price target fetch failed for %s", ticker_upper)
        except Exception:
            log.exception("Analyst data fetch failed for %s", ticker_upper)
        return out

    result = _run_with_timeout(
        _do_fetch,
        timeout=HARD_TIMEOUT_SECONDS,
        default={"recommendations": [], "price_targets": None},
    )
    if result is None:
        result = {"recommendations": [], "price_targets": None}

    _analyst_cache[ticker_upper] = (now, result)
    # Persistir incluso resultados vacíos — Yahoo no cubre todos los tickers
    # y no querés re-fetcharlos en cada apertura. La negativa también es info.
    _analyst_cache_write_db(ticker_upper, result)
    return result
