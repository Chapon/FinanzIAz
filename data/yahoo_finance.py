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

import math
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
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
    NETWORK_THROTTLE_BACKOFF_FACTOR as THROTTLE_BACKOFF_FACTOR,
)
from config.constants import (
    NETWORK_THROTTLE_COOLDOWN_SECONDS as THROTTLE_COOLDOWN_SECONDS,
)
from config.constants import (
    NETWORK_THROTTLE_MAX_COOLDOWN_SECONDS as THROTTLE_MAX_COOLDOWN_SECONDS,
)
from config.constants import (
    NETWORK_THROTTLE_PROBE_TIMEOUT_SECONDS as THROTTLE_PROBE_TIMEOUT_SECONDS,
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
from data.yf_noise import install as _install_yf_noise_filter
from data.yf_noise import is_unknown_symbol
from database.models import (
    AnalystDataCache,
    CompanyInfoCache,
    DividendCache,
    EarningsCache,
    HistoricalDataCache,
    PriceCache,
    session_scope,
    utcnow_naive,
)

log = get_logger(__name__)

# yfinance loguea sus 404 de quoteSummary él mismo (no los tira como excepción),
# así que el filtro tiene que estar puesto antes del primer fetch. Ver data/yf_noise.py.
_install_yf_noise_filter()

T = TypeVar("T")


class _TimeoutHTTPAdapter(HTTPAdapter):
    """HTTPAdapter that injects a default timeout on every request."""

    def __init__(self, *args, timeout: float = NETWORK_TIMEOUT_SECONDS, **kwargs):
        self._default_timeout = timeout
        super().__init__(*args, **kwargs)

    # La firma de `requests` enumera diez parametros; acá sólo se intercepta el
    # timeout y se delega, así que `**kwargs` es lo correcto y reproducirla sería
    # duplicarla para que mypy quede contento.
    def send(self, request, **kwargs):  # type: ignore[override]
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


# ── Circuit-breaker de throttle (bug B3 + NET1 backoff/probe) ────────────────
# Cuando Yahoo deja de responder (hard-timeout, 401/crumb/429 repetido, o un lote
# entero vuelve vacío) abrimos un breaker. Mientras está abierto:
#   1. Las nuevas llamadas de red fallan rápido (no se queman 15s×N tickers) →
#      el scan termina en segundos en vez de colgarse minutos.
#   2. Los fallos se clasifican como TRANSITORIOS (no delisting permanente), así
#      un large-cap real que falló por el throttle NO queda excluido del universo.
# NET1: el cooldown ESCALA (90s → 4.5m → 13.5m → 30m…) por cada ventana fallida
# consecutiva, y al expirar UN solo thread paga un probe de 1 ticker antes de
# liberar el batch completo. Esto evita martillear a Yahoo con el universo entero
# cada 60s (lo que prolongaba el propio throttle). El logging de WARNING vive acá
# (transiciones); los checks repetidos con el breaker abierto son debug.
_throttle_lock = threading.Lock()
_throttle_until = 0.0  # time.monotonic() hasta cuando el cooldown está vigente
_throttle_level = 0  # nivel de escalada (0 = breaker cerrado)
_throttle_since = 0.0  # time.monotonic() del inicio del incidente actual
_throttle_probing = False  # un thread está pagando el probe canario
_outage_notified = False  # ya se avisó (Slack) de este incidente (NET1 pieza 3c)


def _throttle_cooldown_for(level: int) -> float:
    """Cooldown del nivel dado: base × factor^(nivel-1), capeado (NET1)."""
    raw = THROTTLE_COOLDOWN_SECONDS * (THROTTLE_BACKOFF_FACTOR ** max(0, level - 1))
    return min(raw, THROTTLE_MAX_COOLDOWN_SECONDS)


def _note_throttle() -> None:
    """Abre o ESCALA el breaker: Yahoo throttlea/no responde.

    De-bounce (NET1): escala a lo sumo una vez por ventana de cooldown, así N
    tickers fallando a la vez = un solo salto de nivel. La siguiente escalada solo
    ocurre cuando el cooldown expira y un nuevo intento (el probe) vuelve a fallar.
    """
    global _throttle_until, _throttle_level, _throttle_since, _outage_notified
    with _throttle_lock:
        now = time.monotonic()
        if now < _throttle_until:
            return  # ya abierto en esta ventana → no re-escalar (de-bounce)
        was_closed = _throttle_level == 0
        _throttle_level += 1
        cooldown = _throttle_cooldown_for(_throttle_level)
        _throttle_until = now + cooldown
        if was_closed:
            _throttle_since = now
        level = _throttle_level
        elapsed = now - _throttle_since
        # Aviso de outage: UN mensaje por incidente, al persistir (nivel ≥2).
        notify_outage = level >= 2 and not _outage_notified
        if notify_outage:
            _outage_notified = True
    if was_closed:
        log.warning(
            "Throttle de Yahoo detectado — breaker abierto (nivel 1, cooldown %.0fs)",
            cooldown,
        )
    else:
        log.warning(
            "Throttle de Yahoo persiste — breaker escalado a nivel %d "
            "(cooldown %.0fs, %.0f min de incidente)",
            level,
            cooldown,
            elapsed / 60.0,
        )
    if notify_outage:  # fuera del lock (NET1 pieza 3c)
        _maybe_notify_outage("open", minutes=elapsed / 60.0, level=level)


def _note_fetch_success() -> None:
    """Un fetch real funcionó → Yahoo volvió: cierra el breaker y resetea el nivel.

    Fast-path silencioso cuando ya estaba cerrado (se llama en cada fetch OK).
    """
    global _throttle_until, _throttle_level, _throttle_since, _outage_notified
    with _throttle_lock:
        if _throttle_level == 0:
            return
        elapsed = time.monotonic() - _throttle_since
        was_notified = _outage_notified
        _throttle_until = 0.0
        _throttle_level = 0
        _throttle_since = 0.0
        _outage_notified = False
    log.warning("Yahoo se recuperó tras %.0f min — breaker de throttle cerrado", elapsed / 60.0)
    if was_notified:  # solo si avisamos la apertura (fuera del lock)
        _maybe_notify_outage("recovered", minutes=elapsed / 60.0, level=0)


def _maybe_notify_outage(kind: str, *, minutes: float, level: int) -> None:
    """Aviso Slack opcional del outage de datos (NET1 pieza 3c). Fail-open total,
    fuera de locks, gated por ``slack_data_outage_enabled`` (default True). No-op
    sin token/canal (misma infra T12). El notifier es un hook a nivel de módulo
    (``_outage_notifier``) para que los tests puedan inyectar un mock."""
    try:
        from config.settings_manager import settings

        if not bool(settings.get("slack_data_outage_enabled", True)):
            return
        from integrations.slack import default_notifier, format_outage_message

        text = format_outage_message(kind, minutes=minutes, level=level)
        if not text:
            return
        (_outage_notifier or default_notifier)(text)
    except Exception:
        log.debug("Slack outage notify falló (fail-open): %s", kind, exc_info=True)


_outage_notifier = None  # inyectable en tests; None → integrations.slack.default_notifier


def _is_throttled() -> bool:
    """True si el cooldown está vigente (fail-fast).

    Ojo (NET1): cuando el cooldown ya expiró pero el nivel es ≥1, devuelve False;
    el gate ``_should_attempt_fetch`` (no esta función) es quien decide, vía el
    probe canario, si Yahoo realmente volvió.
    """
    with _throttle_lock:
        return time.monotonic() < _throttle_until


def reset_throttle() -> None:
    """Cierra el breaker sin log. Para tests — el estado es global al proceso."""
    global _throttle_until, _throttle_level, _throttle_since, _throttle_probing, _outage_notified
    with _throttle_lock:
        _throttle_until = 0.0
        _throttle_level = 0
        _throttle_since = 0.0
        _throttle_probing = False
        _outage_notified = False


def throttle_state() -> dict:
    """Snapshot del breaker para telemetría/UI (NET1): open/level/cooldown/incidente."""
    with _throttle_lock:
        now = time.monotonic()
        return {
            "open": _throttle_level > 0,
            "level": _throttle_level,
            "cooldown_remaining": max(0.0, _throttle_until - now),
            "incident_seconds": (now - _throttle_since) if _throttle_level > 0 else 0.0,
        }


def _probe_yahoo_alive() -> bool:
    """Probe canario NET1: ¿responde Yahoo? Sondea SPY (1 ticker, timeout corto).

    SPY es líquido y ya se cachea por V1. Un éxito resetea el breaker vía
    ``_note_fetch_success`` (dentro de ``_fetch_ticker_info``); un fallo re-escala
    vía ``_note_throttle`` (dentro de ``_run_with_timeout``).
    """
    return _fetch_ticker_info("SPY", timeout=THROTTLE_PROBE_TIMEOUT_SECONDS) is not None


def _should_attempt_fetch(probe_fn: "Callable[[], bool]" = _probe_yahoo_alive) -> bool:
    """Gate NET1 del batch: ¿puede este caller pegar a la red?

    - nivel 0 (breaker cerrado) → True.
    - cooldown vigente → False (fail-fast, sin red).
    - cooldown expirado, nivel ≥1 → UN thread paga ``probe_fn`` (1 ticker); los
      demás fail-fast mientras corre. probe OK → el fetch exitoso ya reseteó el
      breaker → True (se libera el batch). probe falla → ya re-escaló → False.
    """
    global _throttle_probing
    with _throttle_lock:
        if _throttle_level == 0:
            return True
        if time.monotonic() < _throttle_until:
            return False
        if _throttle_probing:
            return False  # otro thread ya está sondeando
        _throttle_probing = True
    try:
        return bool(probe_fn())
    except Exception:
        return False
    finally:
        with _throttle_lock:
            _throttle_probing = False


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
            # NET1: la transición la loguea _note_throttle (WARNING una vez por
            # ventana); acá bajamos a debug para no repetir por cada ticker.
            log.debug("Hard timeout (%ss) running %s", timeout, fn_name)
            _note_throttle()  # Yahoo colgó → abrir/escalar breaker
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
                # NET1: transición logueada por _note_throttle; acá debug.
                log.debug("yfinance call %s failed (transient, gave up): %s", fn_name, exc)
                _note_throttle()  # throttle persistente → abrir/escalar breaker
            else:
                log.exception("yfinance call %s raised", fn_name)
            return default


def _cache_enabled() -> bool:
    try:
        from config.settings_manager import settings

        return settings.get("cache", True)
    except Exception:
        return True


def _historical_cache_backend() -> str:
    """Backend del cache OHLCV (ARQ1): 'sqlite' | 'parquet' | 'dual'.

    Default 'sqlite' (paridad, cero cambio de comportamiento). El import de
    ``parquet_cache`` es lazy (solo cuando el backend lo usa) para que el modo
    legacy no dependa de pyarrow/duckdb.
    """
    try:
        from config.settings_manager import settings

        val = settings.get("historical_cache_backend", "sqlite")
        return val if val in ("sqlite", "parquet", "dual") else "sqlite"
    except Exception:
        return "sqlite"


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


def _sqlite_latest_1d(ticker_upper: str) -> pd.DataFrame | None:
    """Frame ``1d`` más fresco del ticker desde SQLite (sin importar el period)."""
    with session_scope() as session:
        cached = (
            session.query(HistoricalDataCache)
            .filter(HistoricalDataCache.ticker == ticker_upper)
            .filter(HistoricalDataCache.interval == "1d")
            .order_by(HistoricalDataCache.fetched_at.desc())
            .first()
        )
        if cached is None:
            return None
        return pd.read_json(StringIO(cached.data_json), orient="split")


def _read_latest_1d_frame(ticker_upper: str) -> pd.DataFrame | None:
    """Frame ``1d`` más fresco según el backend activo (ARQ1). Sin TTL."""
    backend = _historical_cache_backend()
    if backend in ("parquet", "dual"):
        try:
            from data import parquet_cache

            df = parquet_cache.latest_1d(ticker_upper)
        except Exception:
            log.exception("parquet latest_1d failed for %s", ticker_upper)
            df = None
        if df is not None:
            return df
        if backend == "parquet":
            return None
    return _sqlite_latest_1d(ticker_upper)


def _sqlite_all_1d(ticker_upper: str) -> list[pd.DataFrame]:
    """Todos los frames ``1d`` del ticker en SQLite, del más fresco al más viejo."""
    out: list[pd.DataFrame] = []
    with session_scope() as session:
        rows = (
            session.query(HistoricalDataCache)
            .filter(HistoricalDataCache.ticker == ticker_upper)
            .filter(HistoricalDataCache.interval == "1d")
            .order_by(HistoricalDataCache.fetched_at.desc())
            .all()
        )
        for row in rows:
            try:
                out.append(pd.read_json(StringIO(row.data_json), orient="split"))
            except Exception:
                log.exception("cache 1d ilegible para %s", ticker_upper)
    return out


def _read_all_1d_frames(ticker_upper: str) -> list[pd.DataFrame]:
    """Todos los frames ``1d`` cacheados del ticker según el backend activo (ARQ1).

    El par de ``_read_latest_1d_frame``: aquél **elige** uno, éste los devuelve
    todos para poder **cruzarlos** (tarea 63).
    """
    backend = _historical_cache_backend()
    if backend in ("parquet", "dual"):
        try:
            from data import parquet_cache

            frames = parquet_cache.all_1d(ticker_upper)
        except Exception:
            log.exception("parquet all_1d failed for %s", ticker_upper)
            frames = []
        if frames or backend == "parquet":
            return frames
    return _sqlite_all_1d(ticker_upper)


def _last_close(df: pd.DataFrame | None) -> float | None:
    """Último close positivo de un frame OHLCV, o None si no hay ninguno."""
    if df is None or "Close" not in df.columns or df.empty:
        return None
    closes = pd.to_numeric(df["Close"], errors="coerce").dropna()
    closes = closes[closes > 0]
    if closes.empty:
        return None
    return float(closes.iloc[-1])


def reference_close(ticker: str) -> float | None:
    """Último close diario válido del cache OHLCV, como ancla de escala.

    Devuelve None si no hay frame cacheado (cold cache / cache off) → el guard
    debe fail-open cuando no puede juzgar la escala. Lee el frame ``1d`` más
    fresco sin importar el ``period`` con que se haya cacheado.
    """
    if not _cache_enabled():
        return None
    try:
        return _last_close(_read_latest_1d_frame(ticker.upper()))
    except Exception:
        log.exception("reference_close failed for %s", ticker)
        return None


# ── Cuando la sospechosa es la REFERENCIA, no el precio (tarea 63) ────────────
# El guard de arriba toma el cache como verdad. Eso alcanza para el caso KLAC
# (cotización corrupta, cache sano), pero el caso SIMÉTRICO —cache corrupto,
# cotización sana— lo deja descartando el precio bueno en cada fetch, para
# siempre, porque nada en este path corrige ni invalida el cache. Pasó con AVB
# 2026-08-27: Yahoo le aplicó un split FANTASMA de 2.793 al frame ``2y`` y no al
# ``10y`` ni a la cotización, y el ticker quedó invisible 4 días con 927 WARNINGs.
#
# El modo de falla que fija la severidad: los dos guards del engine
# (``_price_out_of_band`` en el fill y en la aprobación) **no miran el lado**, así
# que con una posición abierta esto también bloquea la SELL. O sea que el riesgo
# no es "no entramos": es **"no podemos salir"**. De ahí el principio que ordena
# todo lo que sigue: **cuando la referencia misma es dudosa, bloquear es peor que
# no bloquear**.

# Ventana hacia atrás para atribuirle el desvío a un split del proveedor.
_SPLIT_LOOKBACK_DAYS = 30

# Tolerancia con la que el factor de split tiene que explicar el desvío. Es
# generosa a propósito: comparamos una cotización de HOY contra un close que
# puede tener días, así que el precio se movió por su cuenta. Un error de escala
# tipo KLAC (~10×) no cae dentro de esta tolerancia de ningún split real salvo
# que la empresa haya partido ~10:1 — y en ese caso fail-open es lo correcto.
_SPLIT_MATCH_TOL = 0.20

# Denominadores de un split de verdad: 2:1, 3:1, 3:2, 5:2, 1:10… Un ratio que no
# es una fracción simple (2.793) es dato podrido del proveedor, no un ajuste.
_PLAUSIBLE_SPLIT_DENOMS = (1, 2, 3, 4, 5, 8, 10)

# A partir de cuántos rechazos seguidos el WARNING pasa a ERROR. Un rechazo
# aislado es la corrupción transitoria que E5 espera; una racha es un ticker
# invisible, y hoy los dos se ven igual en el log.
_ESCALATE_AFTER = 3

# El lookup de splits pega a la red, así que se memoiza: un ticker roto consulta
# ~4 veces por día en vez de una por minuto.
_SPLIT_CACHE_TTL_SECONDS = 6 * 3600
_split_factor_cache: dict[str, tuple[float, float | None]] = {}
_split_cache_lock = threading.Lock()

# Racha de rechazos por ticker: {ticker: (n, primer_rechazo, ya_anunciado)}.
# ``ya_anunciado`` es lo que corta el spam: se loguea al **cambiar de estado**
# (bloqueado → escalado → referencia dudosa), no una vez por fetch. Sin esto el
# caso AVB dejó 927 líneas idénticas en el log (misma familia que la T25).
_out_of_band_streak: dict[str, tuple[int, str, str]] = {}
_streak_lock = threading.Lock()


def is_plausible_split(factor: float | None) -> bool:
    """True si ``factor`` se parece a un split real (una fracción simple).

    Las empresas parten 2:1, 3:1, 3:2, 5:2, 1:10 — no **2.793:1**. Distinguirlos
    no cambia si se bloquea o no (en los dos casos la referencia es dudosa), pero
    sí qué se hace con el cache y qué dice el log: un split real deja el cache
    **desactualizado** (se invalida y se rebaja solo), uno fantasma lo deja
    **podrido** (invalidarlo sólo re-baja la misma basura).
    """
    if factor is None:
        return False
    try:
        f = float(factor)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(f) or f <= 0:
        return False
    for den in _PLAUSIBLE_SPLIT_DENOMS:
        num = f * den
        if abs(num - round(num)) <= 1e-6 and 1 <= round(num) <= 50:
            return True
    return False


def recent_split_factor(
    ticker: str,
    lookback_days: int = _SPLIT_LOOKBACK_DAYS,
    allow_network: bool = True,
) -> float | None:
    """Factor acumulado de los splits reportados en los últimos N días, o None.

    Se consulta **sólo en el camino de excepción** (un precio ya fuera de banda),
    así que no agrega latencia al scan. Fail-safe: cualquier error devuelve None,
    que deja el guard exactamente como estaba antes de esta tarea.

    ``allow_network=False`` responde **sólo con lo memoizado**: es lo que usa el
    guard del engine, que no puede permitirse una llamada de red en medio de un
    fill pero sí aprovechar lo que el fetch ya aprendió.
    """
    key = ticker.upper()
    now = time.time()
    with _split_cache_lock:
        hit = _split_factor_cache.get(key)
        if hit is not None and now - hit[0] < _SPLIT_CACHE_TTL_SECONDS:
            return hit[1]
    if not allow_network:
        return None

    factor: float | None = None
    try:
        splits = _run_with_timeout(lambda: _ticker(key).splits, default=None)
        if splits is not None and len(splits) > 0:
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=lookback_days)
            idx = pd.to_datetime(splits.index, utc=True, errors="coerce")
            recent = pd.to_numeric(pd.Series(splits.values, index=idx), errors="coerce").dropna()
            recent = recent[(recent.index >= cutoff) & (recent > 0)]
            if not recent.empty:
                factor = float(recent.prod())
    except Exception:
        log.exception("recent_split_factor failed for %s", key)
        factor = None

    with _split_cache_lock:
        _split_factor_cache[key] = (now, factor)
    return factor


def split_explains(
    price: float | None,
    reference: float | None,
    factor: float | None,
    tol: float = _SPLIT_MATCH_TOL,
) -> bool:
    """True si ``factor`` (o su inverso) explica el desvío ``price/reference``."""
    if factor is None or price is None or reference is None:
        return False
    try:
        observed = float(price) / float(reference)
        f = float(factor)
    except (TypeError, ValueError, ZeroDivisionError):
        return False
    if not math.isfinite(observed) or observed <= 0 or not math.isfinite(f) or f <= 0:
        return False
    return any(abs(observed / cand - 1.0) <= tol for cand in (f, 1.0 / f))


def scale_is_disputed(price: float | None, ticker: str, band: float | None = None) -> bool:
    """True si los frames ``1d`` cacheados NO coinciden sobre ``price``.

    **Sin umbral nuevo a propósito:** la disputa se define por el *veredicto*, no
    por un porcentaje de diferencia entre frames. Así el drift normal del
    re-ajuste por dividendos (unos pocos puntos entre dos fetches separados)
    nunca la dispara, y un cambio de escala —que mueve el precio por un factor—
    sí. Si un frame dice "en banda" y otro "fuera de banda", el cache **no puede
    arbitrar**: no hay referencia con la cual acusar.
    """
    if price is None:
        return False
    try:
        refs = [c for c in (_last_close(df) for df in _read_all_1d_frames(ticker.upper())) if c is not None]
    except Exception:
        log.exception("scale_is_disputed failed for %s", ticker)
        return False
    if len(refs) < 2:
        return False
    return len({is_price_out_of_band(price, r, band) for r in refs}) > 1


# ── Drift de escala por DEBAJO de la banda — Tarea 64 (SCALEDRIFT) ───────────
#
# Todo el aparato de escala —E5 y la **63** encima— se dispara **sólo cuando el
# precio vivo sale de la banda** (``price_sanity_band_pct``, 50%). Un ajuste
# espurio **menor** —un split fantasma de 1.3, un re-ajuste mal conciliado— deja
# el histórico fuera de escala con el precio vivo **adentro** de la banda: no hay
# WARNING, no se evalúa disputa, no corre nada. Y la cotización no es lo único que
# se usa: el **ATR y las barreras** salen del histórico (``paper_history_period``,
# default ``2y``), así que un histórico 1,3× chico da un stop 1,3× más ajustado que
# el que la política dice, sin que nada lo declare.
#
# ACÁ NO SIRVE EL TRUCO DE LA 63, y por eso hizo falta un umbral propio. Aquélla
# define la disputa por el **veredicto** (un frame dice "en banda", otro dice
# "fuera") y así no necesita ningún porcentaje. Sin rechazo previo no hay veredicto
# que comparar: hay que mirar la **magnitud** de la diferencia entre frames.
#
# EL UMBRAL ESTÁ CALIBRADO SOBRE LOS FRAMES REALES, no elegido de memoria
# (``docs/scale_drift_t64_2026-09-01.md``). Barrido del cache vivo: **514** tickers
# con parquet ``1d``, **140** con dos o más frames ⇒ **365** pares comparables.
#
#   * El drift **legítimo** (re-ajuste por dividendos entre dos fetches separados)
#     llega hasta **1,719%** (PFE). p50 **0,000%** · p90 **0,741%** · p99 **1,702%**.
#   * El único par por encima del 2% es **AVB**, con **64,196%** — el split fantasma
#     de 2.793 que destapó la 63.
#   * **Entre 1,72% y 64,2% no hay NADA.** El hueco es de 37×.
#
# ⇒ ``10%`` es **5,8×** el máximo legítimo observado y queda **muy** por debajo del
# split más chico que existe en la práctica (3:2 ⇒ 33% de desvío). Falsos positivos
# medidos sobre el cache real: **0 de 364** pares legítimos.
#
# Y LO QUE LA MEDICIÓN CORRIGIÓ DEL ENUNCIADO: el backlog daba por sentado que
# *"por debajo de ~10% el drift legítimo se vuelve indistinguible de una
# corrupción"*. **No se sostiene**: el drift legítimo se termina en 1,72%, así que
# el 10% no está al filo de nada. Lo que sí se midió y **no** discrimina es la
# **dispersión**: el ratio entre frames es constante por fecha en los 365 pares
# (spread máx **1,0140**), legítimos incluidos. Un re-ajuste por dividendos también
# es un re-escalado; la única diferencia es el tamaño.
_DEFAULT_SCALE_DRIFT_TOLERANCE = 0.10

# Con menos fechas solapadas, un par de días raros pesarían como si fueran la
# escala. AVB —el único caso real— solapa 16.
_SCALE_DRIFT_MIN_DATES = 5


def _scale_drift_tolerance() -> float:
    """Desvío relativo entre frames ``1d`` a partir del cual se declara drift. 0 = off."""
    try:
        from config.settings_manager import settings

        tol = float(settings.get("scale_drift_tolerance_pct", _DEFAULT_SCALE_DRIFT_TOLERANCE))
    except Exception:
        tol = _DEFAULT_SCALE_DRIFT_TOLERANCE
    return tol if tol > 0 else 0.0


@dataclass(frozen=True)
class ScaleDrift:
    """Dos frames ``1d`` del mismo ticker que no están en la misma escala."""

    ticker: str
    factor: float
    n_dates: int
    fresh_label: str
    other_label: str

    @property
    def deviation(self) -> float:
        """Cuánto se apartan, en fracción. Es lo que se compara contra la tolerancia."""
        return abs(self.factor - 1.0)

    def __str__(self) -> str:
        return (
            f"{self.ticker}: los frames 1d '{self.fresh_label}' y '{self.other_label}' "
            f"difieren por un factor de {self.factor:.4f} ({100 * self.deviation:.2f}%) "
            f"sobre {self.n_dates} fechas solapadas"
        )


def _labelled_1d_frames(ticker_upper: str) -> list[tuple[str, pd.DataFrame]]:
    """``(etiqueta, frame)`` de cada ``1d`` cacheado según el backend activo (ARQ1)."""
    backend = _historical_cache_backend()
    if backend in ("parquet", "dual"):
        try:
            from data import parquet_cache

            frames = parquet_cache.labelled_1d(ticker_upper)
        except Exception:
            log.exception("parquet labelled_1d failed for %s", ticker_upper)
            frames = []
        if frames or backend == "parquet":
            return frames
    out: list[tuple[str, pd.DataFrame]] = []
    with session_scope() as session:
        rows = (
            session.query(HistoricalDataCache)
            .filter(HistoricalDataCache.ticker == ticker_upper)
            .filter(HistoricalDataCache.interval == "1d")
            .order_by(HistoricalDataCache.fetched_at.desc())
            .all()
        )
        for row in rows:
            try:
                out.append((str(row.period), pd.read_json(StringIO(row.data_json), orient="split")))
            except Exception:
                log.exception("cache 1d ilegible para %s", ticker_upper)
    return out


def scale_drift(ticker: str, tol: float | None = None) -> ScaleDrift | None:
    """El peor desalineamiento de escala entre los frames ``1d`` del ticker, o None.

    Compara el frame **más fresco** contra cada uno de los otros sobre las fechas
    que **solapan** —el mismo cruce intra-proveedor de la 63, pero sin necesitar un
    rechazo previo que lo dispare— y devuelve el par que más se aparta, si supera
    la tolerancia.

    Se compara sobre fechas solapadas y no sobre el último close de cada frame **a
    propósito**: los frames se bajan en momentos distintos, así que sus últimos
    closes difieren por el movimiento real del precio. Sobre las mismas fechas, lo
    único que puede quedar es la escala.

    No dice **cuál** de los dos está mal, y no hace falta: la política que cuelga de
    esto (bloquear la entrada, dejar salir) es la misma sea cual sea. Es pura: no
    pega a la red. Fail-open ante cualquier problema — un guard nuevo que rompe un
    scan es peor que el problema que resuelve.
    """
    t = _scale_drift_tolerance() if tol is None else float(tol)
    if t <= 0:
        return None
    try:
        frames = _labelled_1d_frames(ticker.upper())
        if len(frames) < 2:
            return None
        fresh_label, fresh = frames[0]
        fresh_close = fresh.get("Close")
        if fresh_close is None:
            return None
        peor: ScaleDrift | None = None
        for label, other in frames[1:]:
            other_close = other.get("Close")
            if other_close is None:
                continue
            common = fresh_close.index.intersection(other_close.index)
            if len(common) < _SCALE_DRIFT_MIN_DATES:
                continue
            ratio = (fresh_close.loc[common] / other_close.loc[common]).dropna()
            ratio = ratio[ratio > 0]
            if len(ratio) < _SCALE_DRIFT_MIN_DATES:
                continue
            cand = ScaleDrift(
                ticker=ticker.upper(),
                factor=float(ratio.median()),
                n_dates=len(ratio),
                fresh_label=fresh_label,
                other_label=label,
            )
            if cand.deviation > t and (peor is None or cand.deviation > peor.deviation):
                peor = cand
        return peor
    except Exception:
        log.exception("scale_drift failed for %s", ticker)
        return None


def _invalidate_history_cache(ticker_upper: str) -> None:
    """Borra los frames cacheados del ticker para que el próximo fetch los rebaje."""
    backend = _historical_cache_backend()
    if backend in ("parquet", "dual"):
        try:
            from data import parquet_cache

            parquet_cache.invalidate(ticker_upper)
        except Exception:
            log.exception("parquet invalidate failed for %s", ticker_upper)
    if backend in ("sqlite", "dual"):
        try:
            with session_scope() as session:
                (
                    session.query(HistoricalDataCache)
                    .filter(HistoricalDataCache.ticker == ticker_upper)
                    .filter(HistoricalDataCache.interval == "1d")
                    .delete(synchronize_session=False)
                )
        except Exception:
            log.exception("sqlite invalidate failed for %s", ticker_upper)


def _note_out_of_band(ticker_upper: str) -> tuple[int, str]:
    """Suma uno a la racha de rechazos del ticker → ``(n, desde)``."""
    with _streak_lock:
        n, since, announced = _out_of_band_streak.get(
            ticker_upper, (0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "")
        )
        n += 1
        _out_of_band_streak[ticker_upper] = (n, since, announced)
        return n, since


def _already_announced(ticker_upper: str, kind: str) -> bool:
    """True si ya se logueó ``kind`` para esta racha (y lo marca si no)."""
    with _streak_lock:
        entry = _out_of_band_streak.get(ticker_upper)
        if entry is None:
            return False
        n, since, announced = entry
        if announced == kind:
            return True
        _out_of_band_streak[ticker_upper] = (n, since, kind)
        return False


def _clear_out_of_band_streak(ticker_upper: str) -> None:
    """Corta la racha: el ticker volvió a dar un precio **en banda**.

    Ojo con lo que NO la corta: un fail-open por referencia dudosa. Si lo hiciera,
    el contador volvería a cero y el ticker oscilaría —bloqueado, bloqueado,
    aceptado, bloqueado— porque la investigación de la referencia depende
    justamente de la racha.
    """
    with _streak_lock:
        _out_of_band_streak.pop(ticker_upper, None)


def unreliable_reference(
    ticker: str, price: float | None, reference: float | None, *, allow_network: bool
) -> str | None:
    """Motivo por el que la REFERENCIA no sirve para acusar, o None si sirve.

    El orden separa lo **gratis** de lo **caro**, y no es cosmético:

    1. Cruzar los frames cacheados no pega a la red, así que corre **siempre** y
       resuelve el caso AVB en el primer rechazo.
    2. Consultar los splits del proveedor **sí** pega a la red, así que sólo corre
       con ``allow_network``. En el fetch eso lo habilita la racha, cuando ya
       probó que no es transitorio; un rechazo aislado es la corrupción pasajera
       que E5 espera y se sigue bloqueando como siempre. En el engine nunca: un
       fill no puede colgarse esperando a Yahoo, pero sí aprovecha lo memoizado.

    Es **pública a propósito**: el guard del fetch y el del engine tienen que
    decidir con la misma función. Que uno acepte un precio y el otro lo rechace
    —con la misma referencia— es cómo una posición queda sin poder venderse.
    """
    if price is None or reference is None:
        return None
    if scale_is_disputed(price, ticker):
        return "los frames 1d cacheados no coinciden sobre este precio (escala en disputa entre períodos)"
    ticker_upper = ticker.upper()
    factor = recent_split_factor(ticker_upper, allow_network=allow_network)
    if not split_explains(price, reference, factor):
        return None
    if is_plausible_split(factor):
        # Split real: el cache quedó viejo, no podrido → se rebaja solo.
        _invalidate_history_cache(ticker_upper)
        return (
            f"un split reciente de {factor:g} explica el desvío y el cache quedó "
            "pre-split — invalidado para que se rebaje"
        )
    # Ratio que no es un split (2.793): invalidar sólo re-bajaría la misma basura.
    return (
        f"el proveedor reporta un split de {factor:g}, que no es un ratio real "
        "— dato podrido del histórico, el cache NO se invalida"
    )


def is_price_out_of_band(price: float | None, reference: float | None, band: float | None = None) -> bool:
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

    Devuelve el ``info`` intacto si el precio es sano (o **si la referencia no es
    confiable**, tarea 63), o None si es basura de escala. NO envenena el
    ``failing`` set: la corrupción es transitoria (símbolo vivo, dato podrido) →
    el próximo scan reintenta.
    """
    if info is None:
        return None
    price = info.get("price")
    ref = reference_close(ticker_upper)
    if not is_price_out_of_band(price, ref):
        _clear_out_of_band_streak(ticker_upper)
        return info

    # `is_price_out_of_band` devolvio True, y eso ya exige que los dos sean
    # no-None (fail-open si falta cualquiera). El assert-libre queda explicito
    # para que el tipo lo diga y no dependa de leer la otra funcion.
    assert price is not None and ref is not None
    n, since = _note_out_of_band(ticker_upper)
    px, rf = float(price), float(ref)
    args = (ticker_upper, px, rf, abs(px / rf - 1.0) * 100, _price_sanity_band() * 100)

    reason = unreliable_reference(ticker_upper, px, rf, allow_network=(n >= _ESCALATE_AFTER))
    if reason is not None:
        if not _already_announced(ticker_upper, "unreliable"):
            log.error(
                "Referencia de escala NO confiable para %s: %.4f vs último close "
                "%.4f (desvío %.0f%% > %.0f%%) — %s. El precio se ACEPTA: "
                "bloquear contra una referencia dudosa deja la posición sin "
                "salida, porque los guards del fill no miran el lado.",
                *args,
                reason,
            )
        return info

    if n >= _ESCALATE_AFTER:
        if not _already_announced(ticker_upper, "escalated"):
            log.error(
                "Precio fuera de banda para %s: %.4f vs último close %.4f "
                "(desvío %.0f%% > %.0f%%) — %d rechazos seguidos desde %s: el "
                "ticker está INVISIBLE (sin precio para entrar ni para salir). "
                "Revisar la escala del histórico cacheado.",
                *args,
                n,
                since,
            )
    elif not _already_announced(ticker_upper, "blocked"):
        log.warning(
            "Precio fuera de banda para %s: %.4f vs último close %.4f "
            "(desvío %.0f%% > %.0f%%) — descartado como cotización corrupta",
            *args,
        )
    else:
        # Ni una línea más por minuto: la racha ya se anunció (higiene, T25).
        log.debug(
            "Precio fuera de banda para %s (rechazo #%d desde %s)",
            ticker_upper,
            n,
            since,
        )
    return None


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


def _fetch_ticker_info(ticker: str, *, timeout: float = HARD_TIMEOUT_SECONDS) -> dict | None:
    """Raw yfinance fetch — returns a clean dict. Hard-timeout protected.

    On failure (None / exception), registra el ticker en ``failed_tickers``
    para que la UI lo muestre y los próximos bulk fetch lo salteen. ``timeout``
    es parametrizable para el probe canario de NET1 (sondeo corto de 1 ticker).

    **Una línea de ERROR de ``yfinance`` NO significa que este fetch falló**
    (tarea 91). ``fast_info`` intenta varias fuentes y **loguea la que falla**
    antes de caer a la que funciona. El caso medido el 2026-09-02: AVB emite
    ``$AVB: possibly delisted; no price data found (period=5d)`` **dos veces por
    scan** y este fetch devuelve ``price=184.06`` igual — o sea que es un
    **éxito** con ruido adentro, y por eso el ticker **no aparece** en
    ``failed_tickers``: no hay nada que registrar, y el circuito de tickers
    muertos está haciendo exactamente lo que tiene que hacer.

    Se escribe acá porque la inferencia contraria —*"hay un ERROR repetido ⇒ el
    circuito no lo está viendo"*— es la que hizo la auditoría `estado`, y el
    atajo que sugería (`record_failure`) habría **envenenado el failing set con un
    ticker que funciona**, sacándolo del universo sin motivo.
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

    result = _run_with_timeout(_do_fetch, timeout=timeout, default=None)
    if result is None:
        err = last_exc[0] if last_exc else "Sin datos disponibles"
        # _record_miss: con el breaker abierto (throttle) lo marca transitorio en
        # vez de envenenar el failing set con un símbolo real (bug B3).
        _record_miss(ticker, err, operation="price")
    else:
        # El ticker volvió a funcionar — limpiar registro previo si existía.
        record_success(ticker)
        _note_fetch_success()  # NET1: un fetch OK cierra el breaker (recovery)
    return result


# TTL del cache de company-info (nombre/sector/industria). La clasificación
# sectorial es esencialmente estática → TTL larga (7 días) para no re-scrapear.
COMPANY_INFO_CACHE_TTL_HOURS = 24 * 7


def _read_company_info_cache(ticker_upper: str) -> dict | None:
    """Fila vigente de ``CompanyInfoCache`` como dict parcial, o None."""
    if not _cache_enabled():
        return None
    try:
        with session_scope() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=COMPANY_INFO_CACHE_TTL_HOURS)
            row = (
                session.query(CompanyInfoCache)
                .filter(CompanyInfoCache.ticker == ticker_upper)
                .filter(CompanyInfoCache.fetched_at >= cutoff)
                .order_by(CompanyInfoCache.fetched_at.desc())
                .first()
            )
            if row is None:
                return None
            return {
                "name": row.name or ticker_upper,
                "sector": row.sector or "N/A",
                "industry": row.industry or "N/A",
            }
    except Exception:
        return None


def _write_company_info_cache(ticker_upper: str, info: dict) -> None:
    """Upsert por ticker de la metadata de compañía (best-effort)."""
    if not _cache_enabled():
        return
    try:
        with session_scope() as session:
            session.query(CompanyInfoCache).filter(CompanyInfoCache.ticker == ticker_upper).delete()
            session.add(
                CompanyInfoCache(
                    ticker=ticker_upper,
                    name=info.get("name"),
                    sector=info.get("sector"),
                    industry=info.get("industry"),
                )
            )
    except Exception:
        log.debug("company_info cache write failed for %s", ticker_upper, exc_info=True)


def get_company_info(ticker: str) -> dict:
    """Company name, sector, description desde yfinance (cache-first, hard-timeout).

    Lee primero ``CompanyInfoCache`` (TTL 7d); solo si no hay fila vigente hace el
    scrape lento de ``.info`` y persiste nombre/sector/industria. El cache habilita
    la exposición sectorial del panel de concentración (V2) sin red.
    """
    ticker_upper = ticker.upper()
    cached = _read_company_info_cache(ticker_upper)
    if cached is not None:
        return cached

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
    if result is not None:
        _write_company_info_cache(ticker_upper, result)
        return result
    return fallback


# Tamaño de lote por defecto para get_historical_data_batch. Yahoo tolera mal
# payloads gigantes (sube el riesgo de timeout y de respuestas parciales), así
# que partimos universos grandes en chunks de este tamaño.
_DEFAULT_BATCH_SIZE = 20


def _sqlite_read_historical_cache(ticker_upper: str, period: str, interval: str) -> pd.DataFrame | None:
    """Lectura del cache OHLCV desde SQLite (backend legacy)."""
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


def _parquet_read_historical_cache(ticker_upper: str, period: str, interval: str) -> pd.DataFrame | None:
    """Lectura del cache OHLCV desde Parquet (backend ARQ1). Mismo TTL."""
    try:
        from data import parquet_cache

        return parquet_cache.read(ticker_upper, period, interval, HISTORICAL_CACHE_TTL_HOURS)
    except Exception:
        log.exception("Parquet historical cache read failed for %s", ticker_upper)
        return None


def _read_historical_cache(ticker_upper: str, period: str, interval: str) -> pd.DataFrame | None:
    """Devuelve el frame cacheado fresco para (ticker, period, interval) o None.

    Puerta única de lectura compartida por la versión single y la batch. Despacha
    al backend activo (ARQ1): en 'dual' lee parquet y cae a SQLite si falta (así
    sirve claves aún no migradas).
    """
    if not _cache_enabled():
        return None
    backend = _historical_cache_backend()
    if backend in ("parquet", "dual"):
        df = _parquet_read_historical_cache(ticker_upper, period, interval)
        if df is not None:
            return df
        if backend == "parquet":
            return None
    return _sqlite_read_historical_cache(ticker_upper, period, interval)


def _sqlite_write_historical_cache(ticker_upper: str, period: str, interval: str, df: pd.DataFrame) -> None:
    """Reemplaza la entrada de cache en SQLite (backend legacy)."""
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


def _parquet_write_historical_cache(ticker_upper: str, period: str, interval: str, df: pd.DataFrame) -> None:
    """Reemplaza la entrada de cache en Parquet (backend ARQ1)."""
    try:
        from data import parquet_cache

        parquet_cache.write(ticker_upper, period, interval, df)
    except Exception:
        log.exception("Parquet historical cache write failed for %s", ticker_upper)


def _write_historical_cache(ticker_upper: str, period: str, interval: str, df: pd.DataFrame) -> None:
    """Reemplaza la entrada de cache para (ticker, period, interval).

    Despacha al backend activo (ARQ1); en 'dual' escribe a ambos (SQLite +
    Parquet) para la migración incremental.
    """
    if not _cache_enabled():
        return
    backend = _historical_cache_backend()
    if backend in ("sqlite", "dual"):
        _sqlite_write_historical_cache(ticker_upper, period, interval, df)
    if backend in ("parquet", "dual"):
        _parquet_write_historical_cache(ticker_upper, period, interval, df)


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


def _download_batch(chunk: list[str], period: str, interval: str) -> pd.DataFrame | None:
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

    # NET1: gate del breaker — con throttle vigente NO se lanza el batch (fail-fast,
    # sin red); al expirar el cooldown, un probe de 1 ticker decide si Yahoo volvió
    # antes de liberar el lote completo. Evita martillear con el universo entero.
    if misses and not _should_attempt_fetch():
        for t in misses:
            result[t] = None
            record_transient(t, "Breaker de throttle abierto — batch histórico salteado", "historical")
        return result

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
            # NET1: la transición la loguea _note_throttle (WARNING una vez por
            # ventana); acá debug para no repetir en cada check bajo throttle.
            log.debug(
                "Histórico batch vacío para %d tickers (throttle probable): %s",
                len(chunk),
                ", ".join(chunk),
            )
            continue
        _note_fetch_success()  # NET1: chunk con datos → Yahoo responde, cerrar breaker
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
        _write_earnings_cache(ticker_upper, earnings_dt)

    return earnings_dt


def _is_sqlite_locked(exc: BaseException) -> bool:
    """True si ``exc`` es la contención de escritura de SQLite (``database is locked``).

    WAL permite muchos lectores pero un solo escritor; bajo el harvest horario
    (T-CAT) el classify y el scan compiten por el lock. Es transitorio: reintentar
    con un backoff corto lo resuelve casi siempre.
    """
    return "database is locked" in str(exc).lower()


def _write_earnings_cache(ticker_upper: str, earnings_dt: "datetime | None", *, attempts: int = 3) -> None:
    """Upsert in-place la fila de earnings_cache de un ticker, tolerando el lock.

    OPS1(b): reemplaza el delete+insert por un update de la fila más reciente
    (o insert si no hay), lo que **acorta la ventana de lock** — el harvest
    horario multiplica la contención scan-vs-harvest. El ``database is locked`` se
    trata como transitorio (reintento con backoff corto); en el fallo final se
    loguea **warning**, no exception, porque es fail-open esperable bajo
    contención (el próximo scan re-pega a Yahoo por su calendario). ``fetched_at``
    se refresca en el update para que el TTL de lectura lo tome como fresco.
    """
    for i in range(attempts):
        try:
            with session_scope() as session:
                row = (
                    session.query(EarningsCache)
                    .filter(EarningsCache.ticker == ticker_upper)
                    .order_by(EarningsCache.fetched_at.desc())
                    .first()
                )
                if row is None:
                    session.add(EarningsCache(ticker=ticker_upper, earnings_date=earnings_dt))
                else:
                    row.earnings_date = earnings_dt
                    row.fetched_at = utcnow_naive()
            return
        except Exception as exc:
            if _is_sqlite_locked(exc) and i < attempts - 1:
                time.sleep(0.1 * (i + 1))  # backoff corto: 0.1s, 0.2s
                continue
            log.warning("Earnings cache write failed for %s: %s", ticker_upper, exc)
            return


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


_TZ_FALLO_AVISADO = False


def market_timezone():
    """La zona de NYSE/NASDAQ, o ``None`` si no se puede resolver — **y lo dice**.

    **La cadena estaba mal cableada (tarea 104).** Atrapaba ``ImportError``, pero el
    fallo realista en Windows no es que falte el módulo: es que
    ``ZoneInfo("America/New_York")`` no encuentre la base IANA, y eso levanta
    ``ZoneInfoNotFoundError``, que es subclase de **``KeyError``** — verificado:
    ``ZoneInfoNotFoundError.__mro__`` es ``(…, KeyError, LookupError, Exception)``.
    O sea que la rama de ``pytz`` —la que existe justamente para ese caso— era
    **inalcanzable**, y el ``except Exception`` de más afuera se comía todo.

    Vivía duplicada en ``is_market_open`` y en ``scheduler._now_et``, con un
    comentario en el scheduler que decía *«reuse the same logic as
    is_market_open»* mientras la copiaba. Ahora es una sola.

    El aviso sale **una vez por proceso**: lo llaman el scheduler en cada tick y la
    UI en cada refresh, así que un WARNING por llamada sería spam — y un guard que
    hace ruido se termina apagando.
    """
    global _TZ_FALLO_AVISADO

    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except (ImportError, KeyError):
        # KeyError cubre ZoneInfoNotFoundError, que es lo que pasa sin `tzdata`.
        pass

    try:
        import pytz

        return pytz.timezone("America/New_York")
    except Exception:
        pass

    if not _TZ_FALLO_AVISADO:
        _TZ_FALLO_AVISADO = True
        # Sin `settings` a proposito: este modulo es la capa de datos y no lee
        # config. El numero concreto (16:05 ET por default) vive en el scheduler.
        log.warning(
            "No se pudo resolver la zona horaria 'America/New_York' (ni zoneinfo/tzdata "
            "ni pytz). Todo lo que dependa de la hora de Nueva York cae a UTC, ~4 h "
            "adelantado: el scan diario configurado para despues del cierre se "
            "disparia en pleno mercado. Instalar `tzdata` o `pytz`."
        )
    return None


def is_market_open() -> tuple[bool, str]:
    """
    Returns (is_open: bool, label: str).
    Checks NYSE/NASDAQ session hours (Mon-Fri 9:30–16:00 ET).
    Does not account for US market holidays.
    """
    try:
        tz = market_timezone()
        if tz is None:
            # Falla CERRADO, que es la dirección segura para trading, y el porqué
            # ya lo avisó `market_timezone`. El "—" de antes salía igual pero sin
            # que nada dijera que la causa era la zona horaria (tarea 104).
            return False, "—"

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

                # `fetched_at` es nullable: una fila sin sello se toma como la
                # MAS VIEJA (no pisa a una con sello), que es lo conservador. Antes
                # la comparacion con None hubiera reventado con TypeError.
                def _sello(r: PriceCache) -> datetime:
                    return r.fetched_at or datetime.min

                for row in cached_rows:
                    prev = cached_map.get(row.ticker)
                    if prev is None or _sello(row) > _sello(prev):
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

    # NET1: gate del breaker — con throttle vigente NO se lanza el batch (fail-fast);
    # al expirar el cooldown un probe de 1 ticker decide si Yahoo volvió antes de
    # liberar el lote. Los misses quedan transitorios (no se envenena el failing set).
    if not _should_attempt_fetch():
        for t in cache_misses:
            record_transient(
                t, "Breaker de throttle abierto — batch de precios salteado", "price", override=True
            )
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
        # NET1: la transición la loguea _note_throttle (WARNING una vez por
        # ventana); acá debug para no repetir en cada check bajo throttle.
        log.debug(
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
            session.query(AnalystDataCache).filter(AnalystDataCache.ticker == ticker_upper).delete()
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
            entry: dict[str, object] = {"period": period}
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
            # UNIV1: si el primer módulo reveló que el símbolo no existe, no gastamos
            # el segundo request — un "Quote not found" es permanente, no transitorio.
            if is_unknown_symbol(ticker_upper):
                return out
            # Price targets
            try:
                pt = getattr(t, "analyst_price_targets", None)
                out["price_targets"] = _normalize_price_targets(pt)
            except Exception:
                log.exception("Price target fetch failed for %s", ticker_upper)
        except Exception:
            log.exception("Analyst data fetch failed for %s", ticker_upper)
        return out

    result: dict | None = _run_with_timeout(
        _do_fetch,
        timeout=HARD_TIMEOUT_SECONDS,
        default={"recommendations": [], "price_targets": None},
    )
    if result is None:
        result = {"recommendations": [], "price_targets": None}

    # UNIV1: Yahoo dijo que el símbolo no existe (deslistado o renombrado). Lo
    # registramos acá —fuera del handler de logging, ver data/yf_noise.py— para que
    # _record_miss aplique la lógica B3: delisting genuino solo con el breaker
    # cerrado; bajo throttle queda transitorio y se reintenta.
    if is_unknown_symbol(ticker_upper):
        _record_miss(
            ticker_upper,
            "Quote not found: el símbolo no existe en Yahoo (deslistado o renombrado)",
            operation="analyst",
        )

    _analyst_cache[ticker_upper] = (now, result)
    # Persistir incluso resultados vacíos — Yahoo no cubre todos los tickers
    # y no querés re-fetcharlos en cada apertura. La negativa también es info.
    _analyst_cache_write_db(ticker_upper, result)
    return result
