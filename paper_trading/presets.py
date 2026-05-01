"""
Preset watchlists organized by sector / theme.

Each preset is a curated list of US tickers representative of its sector.
Used by the paper-trading tab to bulk-add tickers to an account's watchlist
without typing them one by one.

Tickers follow the symbol used by Yahoo Finance (which is what
``data.yahoo_finance.get_bulk_prices`` consumes). Berkshire Hathaway B-class
shares are written as ``BRK-B`` (not ``BRK.B``) for that reason.

Adding or editing a preset only requires touching this dict — the UI in
``ui.paper_tab`` reads from it at runtime, no other wiring needed.
"""
from __future__ import annotations


WATCHLIST_PRESETS: dict[str, list[str]] = {
    # Mega-cap concentrated bet — the usual suspects.
    "Magníficos 7": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    ],

    # Broad tech: software, hardware, services. Overlaps with Semis but
    # leans toward "Magnificent 7 + classic tech".
    "Tecnología": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL",
        "ADBE", "CRM", "ACN", "IBM", "CSCO", "NOW", "INTU",
    ],

    # Semiconductores — fabricación + diseño + equipos.
    "Semiconductores": [
        "NVDA", "AMD", "AVGO", "TSM", "ASML", "QCOM", "INTC", "MU",
        "AMAT", "KLAC", "LRCX", "MRVL", "TXN", "ON",
    ],

    # Petróleo/gas + servicios + midstream.
    "Energía": [
        "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "PSX", "MPC", "VLO",
        "KMI", "WMB", "OKE", "HAL", "BKR",
    ],

    # Retail discrecional, autos, viajes, restaurantes.
    "Consumo discrecional": [
        "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "BKNG",
        "TJX", "ROST", "TGT", "F", "GM",
    ],

    # Staples: alimentos, bebidas, hogar — defensivo clásico.
    "Consumo defensivo": [
        "PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "MDLZ", "CL",
        "KMB", "GIS", "K",
    ],

    # Pharma + dispositivos + seguros de salud.
    "Salud": [
        "JNJ", "UNH", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR",
        "BMY", "AMGN", "CVS", "GILD", "ELV",
    ],

    # Bancos, brokers, payments, asset managers.
    "Financieros": [
        "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "AXP",
        "V", "MA", "BRK-B", "PYPL",
    ],

    # Aeroespacial, defensa, transporte, maquinaria pesada.
    "Industriales": [
        "BA", "CAT", "GE", "HON", "RTX", "UPS", "LMT", "DE", "MMM",
        "UNP", "FDX", "NOC",
    ],

    # Telecom, streaming, redes sociales — services + media.
    "Comunicaciones": [
        "GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS",
        "CHTR", "WBD",
    ],

    # Utilities reguladas — alta yield, baja beta.
    "Utilities": [
        "NEE", "DUK", "SO", "AEP", "EXC", "XEL", "SRE", "D", "PCG",
    ],

    # REITs — exposición a real estate vía equity.
    "REITs": [
        "PLD", "AMT", "EQIX", "CCI", "SPG", "O", "PSA", "AVB", "WELL",
    ],
}


def list_preset_names() -> list[str]:
    """Return preset names in display order (insertion order)."""
    return list(WATCHLIST_PRESETS.keys())


def get_preset(name: str) -> list[str]:
    """Look up a preset by name. Returns [] if unknown."""
    return list(WATCHLIST_PRESETS.get(name, []))
