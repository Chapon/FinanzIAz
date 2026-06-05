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
"""

from __future__ import annotations

import time

from config.logging_config import get_logger

log = get_logger(__name__)

_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h
_cache: dict[str, tuple[float, list[str]]] = {}


# ── Hardcoded fallback ───────────────────────────────────────────────────────
# Snapshot de constituyentes del S&P 500 (2026). Si Wikipedia no responde,
# este fallback garantiza ~500 tickers líquidos para escanear. Lista mantenida
# manualmente — desactualizar si pasa un año entero sin tocar.

_SP500_FALLBACK: tuple[str, ...] = (
    "MMM", "AOS", "ABT", "ABBV", "ACN", "ADBE", "AMD", "AES", "AFL", "A",
    "APD", "ABNB", "AKAM", "ALB", "ARE", "ALGN", "ALLE", "LNT", "ALL", "GOOGL",
    "GOOG", "MO", "AMZN", "AMCR", "AEE", "AEP", "AXP", "AIG", "AMT", "AWK",
    "AMP", "AME", "AMGN", "APH", "ADI", "ANSS", "AON", "APA", "AAPL", "AMAT",
    "APTV", "ACGL", "ADM", "ANET", "AJG", "AIZ", "T", "ATO", "ADSK", "ADP",
    "AZO", "AVB", "AVY", "AXON", "BKR", "BALL", "BAC", "BK", "BBWI", "BAX",
    "BDX", "BRK-B", "BBY", "TECH", "BIIB", "BLK", "BX", "BA", "BKNG", "BWA",
    "BSX", "BMY", "AVGO", "BR", "BRO", "BF-B", "BLDR", "BG", "CHRW", "CDNS",
    "CZR", "CPT", "CPB", "COF", "CAH", "KMX", "CCL", "CARR", "CTLT", "CAT",
    "CBOE", "CBRE", "CDW", "CE", "COR", "CNC", "CNP", "CF", "CRL", "SCHW",
    "CHTR", "CVX", "CMG", "CB", "CHD", "CI", "CINF", "CTAS", "CSCO", "C",
    "CFG", "CLX", "CME", "CMS", "KO", "CTSH", "CL", "CMCSA", "CMA", "CAG",
    "COP", "ED", "STZ", "CEG", "COO", "CPRT", "GLW", "CPAY", "CTVA", "CSGP",
    "COST", "CTRA", "CRWD", "CCI", "CSX", "CMI", "CVS", "DHR", "DRI", "DVA",
    "DAY", "DECK", "DE", "DAL", "DVN", "DXCM", "FANG", "DLR", "DFS", "DG",
    "DLTR", "D", "DPZ", "DOV", "DOW", "DHI", "DTE", "DUK", "DD", "EMN",
    "ETN", "EBAY", "ECL", "EIX", "EW", "EA", "ELV", "LLY", "EMR", "ENPH",
    "ETR", "EOG", "EPAM", "EQT", "EFX", "EQIX", "EQR", "ERIE", "ESS", "EL",
    "EG", "EVRG", "ES", "EXC", "EXPE", "EXPD", "EXR", "XOM", "FFIV", "FDS",
    "FICO", "FAST", "FRT", "FDX", "FIS", "FITB", "FSLR", "FE", "FI", "F",
    "FTNT", "FTV", "FOXA", "FOX", "BEN", "FCX", "GRMN", "IT", "GE", "GEHC",
    "GEV", "GEN", "GNRC", "GD", "GIS", "GM", "GPC", "GILD", "GPN", "GL",
    "GS", "HAL", "HIG", "HAS", "HCA", "DOC", "HSIC", "HSY", "HES", "HPE",
    "HLT", "HOLX", "HD", "HON", "HRL", "HST", "HWM", "HPQ", "HUBB", "HUM",
    "HBAN", "HII", "IBM", "IEX", "IDXX", "ITW", "INCY", "IR", "PODD", "INTC",
    "ICE", "IFF", "IP", "IPG", "INTU", "ISRG", "IVZ", "INVH", "IQV", "IRM",
    "JBHT", "JBL", "JKHY", "J", "JNJ", "JCI", "JPM", "JNPR", "K", "KVUE",
    "KDP", "KEY", "KEYS", "KMB", "KIM", "KMI", "KKR", "KLAC", "KHC", "KR",
    "LHX", "LH", "LRCX", "LW", "LVS", "LDOS", "LEN", "LIN", "LYV", "LKQ",
    "LMT", "L", "LOW", "LULU", "LYB", "MTB", "MPC", "MKTX", "MAR", "MMC",
    "MLM", "MAS", "MA", "MTCH", "MKC", "MCD", "MCK", "MDT", "MRK", "META",
    "MET", "MTD", "MGM", "MCHP", "MU", "MSFT", "MAA", "MRNA", "MHK", "MOH",
    "TAP", "MDLZ", "MPWR", "MNST", "MCO", "MS", "MOS", "MSI", "MSCI", "NDAQ",
    "NTAP", "NFLX", "NEM", "NWSA", "NWS", "NEE", "NKE", "NI", "NDSN", "NSC",
    "NTRS", "NOC", "NCLH", "NRG", "NUE", "NVDA", "NVR", "NXPI", "ORLY", "OXY",
    "ODFL", "OMC", "ON", "OKE", "ORCL", "OTIS", "PCAR", "PKG", "PANW", "PARA",
    "PH", "PAYX", "PAYC", "PYPL", "PNR", "PEP", "PFE", "PCG", "PM", "PSX",
    "PNW", "PNC", "POOL", "PPG", "PPL", "PFG", "PG", "PGR", "PLD", "PRU",
    "PEG", "PTC", "PSA", "PHM", "PWR", "QCOM", "DGX", "RL", "RJF", "RTX",
    "O", "REG", "REGN", "RF", "RSG", "RMD", "RVTY", "ROK", "ROL", "ROP",
    "ROST", "RCL", "SPGI", "CRM", "SBAC", "SLB", "STX", "SRE", "NOW", "SHW",
    "SPG", "SWKS", "SJM", "SW", "SNA", "SOLV", "SO", "LUV", "SWK", "SBUX",
    "STT", "STLD", "STE", "SYK", "SMCI", "SYF", "SNPS", "SYY", "TMUS", "TROW",
    "TTWO", "TPR", "TRGP", "TGT", "TEL", "TDY", "TFX", "TER", "TSLA", "TXN",
    "TPL", "TXT", "TMO", "TJX", "TSCO", "TT", "TDG", "TRV", "TRMB", "TFC",
    "TYL", "TSN", "USB", "UBER", "UDR", "ULTA", "UNP", "UAL", "UPS", "URI",
    "UNH", "UHS", "VLO", "VTR", "VLTO", "VRSN", "VRSK", "VZ", "VRTX", "VTRS",
    "VICI", "V", "VST", "VMC", "WRB", "GWW", "WAB", "WBA", "WMT", "DIS",
    "WBD", "WM", "WAT", "WEC", "WFC", "WELL", "WST", "WDC", "WY", "WMB",
    "WTW", "WYNN", "XEL", "XYL", "YUM", "ZBRA", "ZBH", "ZTS",
)


def _fetch_sp500_from_wikipedia() -> list[str] | None:
    """Intenta scrapear la lista oficial de Wikipedia. Devuelve ``None`` si falla.

    Wikipedia mantiene la tabla en
    ``https://en.wikipedia.org/wiki/List_of_S%26P_500_companies`` — el primer
    DataFrame que devuelve ``read_html`` tiene una columna ``Symbol``.
    """
    try:
        import pandas as pd

        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url, header=0)
        if not tables:
            return None
        df = tables[0]
        if "Symbol" not in df.columns:
            return None
        symbols = (
            df["Symbol"]
            .astype(str)
            .str.strip()
            .str.replace(".", "-", regex=False)  # BRK.B -> BRK-B (formato yfinance)
            .tolist()
        )
        symbols = [s for s in symbols if s and s.isascii() and len(s) <= 6]
        if len(symbols) < 400:
            log.warning("SP500 fetch from Wikipedia returned only %d symbols, using fallback", len(symbols))
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

    _cache["sp500"] = (now, fetched)
    return fetched


def get_sp500_fallback() -> list[str]:
    """Acceso directo a la lista hardcoded — útil para tests deterministas."""
    return list(_SP500_FALLBACK)
