"""
Universe of tickers para scanners masivos (Leads tab, etc.).

Función principal: ``get_sp500_tickers()`` que devuelve los constituyentes del
S&P 500. Estrategia:

1. Intenta fetch live desde Wikipedia (``pd.read_html`` sobre la página de
   ``List of S&P 500 companies``). Solo si el cache local expiró.
2. Si Wikipedia falla, cae a una lista hardcoded en este módulo (snapshot
   2026). Esto garantiza que el scanner funcione offline.

El resultado se cachea en memoria por 24h. No necesitamos persistir esto a la
DB — son 500 strings y se regenera rápido.

**User-Agent (UNIV1, 2026-07-20).** ``pd.read_html(url)`` baja la página con el
UA default de urllib (``Python-urllib/3.x``) y Wikipedia lo rebota con **HTTP 403
Forbidden** — el fetch estuvo roto en silencio (403 → ``log.exception`` → fallback,
en cada refresh) durante meses. Por eso bajamos el HTML con ``requests`` + un UA
de browser real y recién ahí se lo damos a ``read_html``. Mismo patrón de etiqueta
que la infra EDGAR de ``data/news_sources.py``, que ya pagaba este peaje con la SEC.

**Mantenimiento del fallback.** ``_SP500_FALLBACK`` se regenera con
``python scripts/refresh_sp500_fallback.py --apply`` (valida contra Yahoo antes de
escribir). Un fallback stale no es cosmético: los símbolos que dejaron de existir
—por adquisición (ANSS, DFS, JNPR) o por *rename* del ticker (MMC→MRSH, BK→BNY,
PARA→PSKY)— se consultan igual en cada run y devuelven 404.
"""

from __future__ import annotations

import io
import time

from config.logging_config import get_logger

log = get_logger(__name__)

_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h
_cache: dict[str, tuple[float, list[str]]] = {}

WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKIPEDIA_TIMEOUT_SECONDS = 20

# Wikipedia responde 403 a los UA "de script" (urllib/requests default). Un UA de
# browser real es lo que espera su capa anti-bot.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Si el parse devuelve menos que esto, algo cambió en la página → mejor el fallback
# conocido que un universo truncado.
MIN_EXPECTED_SYMBOLS = 400

_warned_missing_parser = False


# ── Hardcoded fallback ───────────────────────────────────────────────────────
# Snapshot de constituyentes del S&P 500. Si Wikipedia no responde, este fallback
# garantiza ~500 tickers líquidos para escanear.
# NO editar a mano: regenerar con ``python scripts/refresh_sp500_fallback.py --apply``.
# Última regeneración: 2026-07-20 (503 símbolos, 503/503 validados contra Yahoo).

# fmt: off
# >>> SP500_FALLBACK_START (generado — no editar a mano)
_SP500_FALLBACK: tuple[str, ...] = (
    "MMM", "AOS", "ABT", "ABBV", "ACN", "ADBE", "AMD", "AES", "AFL", "A",
    "APD", "ABNB", "AKAM", "ALB", "ARE", "ALGN", "ALLE", "LNT", "ALL", "GOOGL",
    "GOOG", "MO", "AMZN", "AMCR", "AEE", "AEP", "AXP", "AIG", "AMT", "AWK",
    "AMP", "AME", "AMGN", "APH", "ADI", "AON", "APA", "APO", "AAPL", "AMAT",
    "APP", "APTV", "ACGL", "ADM", "ARES", "ANET", "AJG", "AIZ", "T", "ATO",
    "ADSK", "ADP", "AZO", "AVB", "AVY", "AXON", "BKR", "BALL", "BAC", "BAX",
    "BDX", "BRK-B", "BBY", "TECH", "BIIB", "BLK", "BX", "XYZ", "BNY", "BA",
    "BKNG", "BSX", "BMY", "AVGO", "BR", "BRO", "BF-B", "BLDR", "BG", "BXP",
    "CHRW", "CDNS", "CPT", "COF", "CAH", "CCL", "CARR", "CVNA", "CASY", "CAT",
    "CBOE", "CBRE", "CDW", "COR", "CNC", "CNP", "CF", "CRL", "SCHW", "CHTR",
    "CVX", "CMG", "CB", "CHD", "CIEN", "CI", "CINF", "CTAS", "CSCO", "C",
    "CFG", "CLX", "CME", "CMS", "KO", "CTSH", "COHR", "COIN", "CL", "CMCSA",
    "FIX", "COP", "ED", "STZ", "CEG", "COO", "CPRT", "GLW", "CPAY", "CTVA",
    "CSGP", "COST", "CRH", "CRWD", "CCI", "CSX", "CMI", "CVS", "DHR", "DRI",
    "DDOG", "DVA", "DECK", "DE", "DELL", "DAL", "DVN", "DXCM", "FANG", "DLR",
    "DG", "DLTR", "D", "DPZ", "DASH", "DOV", "DOW", "DHI", "DTE", "DUK",
    "DD", "ETN", "EBAY", "ECHO", "ECL", "EIX", "EW", "EA", "ELV", "EME",
    "EMR", "ETR", "EOG", "EQT", "EFX", "EQIX", "EQR", "ERIE", "ESS", "EL",
    "EG", "EVRG", "ES", "EXC", "EXE", "EXPE", "EXPD", "EXR", "XOM", "FFIV",
    "FDS", "FICO", "FAST", "FRT", "FDX", "FDXF", "FIS", "FITB", "FSLR", "FE",
    "FISV", "FLEX", "F", "FTNT", "FTV", "FOXA", "FOX", "BEN", "FCX", "GRMN",
    "IT", "GE", "GEHC", "GEV", "GEN", "GNRC", "GD", "GIS", "GM", "GPC",
    "GILD", "GPN", "GL", "GDDY", "GS", "HAL", "HIG", "HAS", "HCA", "DOC",
    "HSIC", "HSY", "HPE", "HLT", "HD", "HONA", "HON", "HRL", "HST", "HWM",
    "HPQ", "HUBB", "HUM", "HBAN", "HII", "IBM", "IEX", "IDXX", "ITW", "INCY",
    "IR", "PODD", "INTC", "IBKR", "ICE", "IFF", "IP", "INTU", "ISRG", "IVZ",
    "INVH", "IQV", "IRM", "JBHT", "JBL", "JKHY", "J", "JNJ", "JCI", "JPM",
    "KVUE", "KDP", "KEY", "KEYS", "KMB", "KIM", "KMI", "KKR", "KLAC", "KHC",
    "KR", "LHX", "LH", "LRCX", "LVS", "LDOS", "LEN", "LII", "LLY", "LIN",
    "LYV", "LMT", "L", "LOW", "LULU", "LITE", "LYB", "MTB", "MPC", "MAR",
    "MRSH", "MLM", "MRVL", "MAS", "MA", "MKC", "MCD", "MCK", "MDT", "MRK",
    "META", "MET", "MTD", "MGM", "MCHP", "MU", "MSFT", "MAA", "MRNA", "TAP",
    "MDLZ", "MPWR", "MNST", "MCO", "MS", "MOS", "MSI", "MSCI", "NDAQ", "NTAP",
    "NFLX", "NEM", "NWSA", "NWS", "NEE", "NKE", "NI", "NDSN", "NSC", "NTRS",
    "NOC", "NCLH", "NRG", "NUE", "NVDA", "NVR", "NXPI", "ORLY", "OXY", "ODFL",
    "OMC", "ON", "OKE", "ORCL", "OTIS", "PCAR", "PKG", "PLTR", "PANW", "PSKY",
    "PH", "PAYX", "PYPL", "PNR", "PEP", "PFE", "PCG", "PM", "PSX", "PNW",
    "PNC", "PPG", "PPL", "PFG", "PG", "PGR", "PLD", "PRU", "PEG", "PTC",
    "PSA", "PHM", "PWR", "QCOM", "DGX", "Q", "RL", "RJF", "RTX", "O",
    "REG", "REGN", "RF", "RSG", "RMD", "RVTY", "HOOD", "ROK", "ROL", "ROP",
    "ROST", "RCL", "SPGI", "CRM", "SNDK", "SBAC", "SLB", "STX", "SRE", "NOW",
    "SHW", "SPG", "SWKS", "SJM", "SW", "SNA", "SOLV", "SO", "LUV", "SWK",
    "SBUX", "STT", "STLD", "STE", "SYK", "SMCI", "SYF", "SNPS", "SYY", "TMUS",
    "TROW", "TTWO", "TPR", "TRGP", "TGT", "TEL", "TDY", "TER", "TSLA", "TXN",
    "TPL", "TXT", "TMO", "TJX", "TKO", "TTD", "TSCO", "TT", "TDG", "TRV",
    "TRMB", "TFC", "TYL", "TSN", "USB", "UBER", "UDR", "ULTA", "UNP", "UAL",
    "UPS", "URI", "UNH", "UHS", "VLO", "VEEV", "VTR", "VLTO", "VRSN", "VRSK",
    "VZ", "VRTX", "VRT", "VTRS", "VICI", "V", "VST", "VMC", "WRB", "GWW",
    "WAB", "WMT", "DIS", "WBD", "WM", "WAT", "WEC", "WFC", "WELL", "WST",
    "WDC", "WY", "WSM", "WMB", "WTW", "WDAY", "WYNN", "XEL", "XYL", "YUM",
    "ZBRA", "ZBH", "ZTS",
)
# <<< SP500_FALLBACK_END
# fmt: on


def normalize_symbols(raw: list[str]) -> list[str]:
    """Normaliza símbolos crudos de la tabla de Wikipedia al formato de yfinance.

    ``BRK.B`` → ``BRK-B``; descarta strings vacíos, no-ASCII o demasiado largos
    (filas de nota al pie que se cuelan en la columna). Función pura — el grueso
    del parseo se testea acá sin depender de un parser de HTML.
    """
    out: list[str] = []
    for value in raw:
        symbol = str(value).strip().replace(".", "-")
        if symbol and symbol.isascii() and len(symbol) <= 6:
            out.append(symbol)
    return out


def _fetch_sp500_html() -> str | None:
    """Baja el HTML de la tabla de Wikipedia con un UA de browser. ``None`` si falla."""
    import requests

    resp = requests.get(
        WIKIPEDIA_SP500_URL,
        headers={
            "User-Agent": _BROWSER_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=WIKIPEDIA_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.text


def _fetch_sp500_from_wikipedia() -> list[str] | None:
    """Intenta scrapear la lista oficial de Wikipedia. Devuelve ``None`` si falla.

    Wikipedia mantiene la tabla en ``WIKIPEDIA_SP500_URL`` — el primer DataFrame
    que devuelve ``read_html`` tiene una columna ``Symbol``.
    """
    global _warned_missing_parser
    try:
        import pandas as pd

        html = _fetch_sp500_html()
        if not html:
            return None
        try:
            tables = pd.read_html(io.StringIO(html), header=0)
        except ImportError:
            # pandas necesita lxml (o bs4+html5lib) para parsear HTML. Sin eso el
            # fetch nunca puede funcionar: avisamos una vez y usamos el fallback en
            # silencio a partir de ahí, en vez de un traceback por refresh.
            if not _warned_missing_parser:
                log.warning(
                    "SP500 live fetch deshabilitado: falta el parser de HTML de pandas "
                    "(pip install lxml). Se usa el fallback hardcoded."
                )
                _warned_missing_parser = True
            return None
        if not tables:
            return None
        df = tables[0]
        if "Symbol" not in df.columns:
            log.warning("La tabla de Wikipedia no tiene columna 'Symbol', usando fallback")
            return None
        symbols = normalize_symbols(df["Symbol"].astype(str).tolist())
        if len(symbols) < MIN_EXPECTED_SYMBOLS:
            log.warning(
                "SP500 fetch from Wikipedia returned only %d symbols, using fallback",
                len(symbols),
            )
            return None
        return symbols
    except Exception:
        log.exception("Failed to fetch SP500 list from Wikipedia, will use fallback")
        return None


def get_sp500_tickers(force_refresh: bool = False) -> list[str]:
    """Devuelve la lista de tickers del S&P 500.

    Try Wikipedia primero (cacheado 24h), fallback a la lista hardcoded.
    Nunca tira excepción — siempre devuelve al menos la lista fallback.
    """
    now = time.time()
    cached = _cache.get("sp500")
    if not force_refresh and cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    fetched = _fetch_sp500_from_wikipedia()
    if fetched is None:
        log.info("Using hardcoded SP500 fallback (%d tickers)", len(_SP500_FALLBACK))
        fetched = list(_SP500_FALLBACK)
    else:
        log.info("SP500 list fetched from Wikipedia (%d tickers)", len(fetched))

    _cache["sp500"] = (now, fetched)
    return fetched


def get_sp500_fallback() -> list[str]:
    """Acceso directo a la lista hardcoded — útil para tests deterministas."""
    return list(_SP500_FALLBACK)
