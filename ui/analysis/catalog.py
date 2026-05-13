"""
Static autocompletion catalog + period-mapping for the Analysis tab.

These are pure data; extracting them out of ``analysis_tab.py`` keeps the
orchestrator file from being dominated by 150+ lines of ticker rows.
"""

from __future__ import annotations

# ── Static ticker database for autocomplete ──────────────────────────────────
# Format: (SYMBOL, "Company / description")
TICKER_DB: list[tuple[str, str]] = [
    # ── US Tech ───────────────────────────────────────────────────────────────
    ("AAPL", "Apple Inc."),
    ("MSFT", "Microsoft Corporation"),
    ("GOOGL", "Alphabet Inc. (Google)"),
    ("GOOG", "Alphabet Inc. Class C"),
    ("AMZN", "Amazon.com Inc."),
    ("META", "Meta Platforms Inc. (Facebook)"),
    ("TSLA", "Tesla Inc."),
    ("NVDA", "NVIDIA Corporation"),
    ("AMD", "Advanced Micro Devices"),
    ("INTC", "Intel Corporation"),
    ("NFLX", "Netflix Inc."),
    ("ADBE", "Adobe Inc."),
    ("CRM", "Salesforce Inc."),
    ("ORCL", "Oracle Corporation"),
    ("IBM", "IBM Corporation"),
    ("CSCO", "Cisco Systems Inc."),
    ("QCOM", "Qualcomm Inc."),
    ("TXN", "Texas Instruments"),
    ("AVGO", "Broadcom Inc."),
    ("AMAT", "Applied Materials"),
    ("MU", "Micron Technology"),
    ("SNOW", "Snowflake Inc."),
    ("UBER", "Uber Technologies"),
    ("LYFT", "Lyft Inc."),
    ("SPOT", "Spotify Technology"),
    ("SQ", "Block Inc. (Square)"),
    ("PYPL", "PayPal Holdings"),
    ("COIN", "Coinbase Global"),
    ("PLTR", "Palantir Technologies"),
    # ── US Finance ────────────────────────────────────────────────────────────
    ("JPM", "JPMorgan Chase & Co."),
    ("BAC", "Bank of America Corp."),
    ("WFC", "Wells Fargo & Co."),
    ("GS", "Goldman Sachs Group"),
    ("MS", "Morgan Stanley"),
    ("V", "Visa Inc."),
    ("MA", "Mastercard Inc."),
    ("AXP", "American Express Co."),
    ("BRK-B", "Berkshire Hathaway Inc."),
    ("C", "Citigroup Inc."),
    ("BLK", "BlackRock Inc."),
    ("SCHW", "Charles Schwab Corp."),
    # ── US Healthcare ─────────────────────────────────────────────────────────
    ("JNJ", "Johnson & Johnson"),
    ("UNH", "UnitedHealth Group"),
    ("PFE", "Pfizer Inc."),
    ("ABBV", "AbbVie Inc."),
    ("MRK", "Merck & Co."),
    ("LLY", "Eli Lilly and Co."),
    ("AMGN", "Amgen Inc."),
    ("GILD", "Gilead Sciences"),
    # ── US Consumer ───────────────────────────────────────────────────────────
    ("WMT", "Walmart Inc."),
    ("COST", "Costco Wholesale"),
    ("HD", "Home Depot Inc."),
    ("NKE", "Nike Inc."),
    ("MCD", "McDonald's Corp."),
    ("SBUX", "Starbucks Corp."),
    ("KO", "Coca-Cola Co."),
    ("PEP", "PepsiCo Inc."),
    ("PG", "Procter & Gamble"),
    ("DIS", "Walt Disney Co."),
    # ── US Energy ─────────────────────────────────────────────────────────────
    ("XOM", "Exxon Mobil Corp."),
    ("CVX", "Chevron Corp."),
    ("COP", "ConocoPhillips"),
    ("SLB", "SLB (Schlumberger)"),
    # ── US Industrial / Other ─────────────────────────────────────────────────
    ("BA", "Boeing Co."),
    ("CAT", "Caterpillar Inc."),
    ("GE", "GE Aerospace"),
    ("HON", "Honeywell International"),
    ("UPS", "United Parcel Service"),
    ("FDX", "FedEx Corp."),
    ("LMT", "Lockheed Martin"),
    ("RTX", "RTX Corporation (Raytheon)"),
    ("T", "AT&T Inc."),
    ("VZ", "Verizon Communications"),
    ("TMUS", "T-Mobile US Inc."),
    ("CMCSA", "Comcast Corp."),
    # ── ETFs ──────────────────────────────────────────────────────────────────
    ("SPY", "SPDR S&P 500 ETF"),
    ("QQQ", "Invesco QQQ Trust — Nasdaq 100"),
    ("IWM", "iShares Russell 2000 ETF"),
    ("VTI", "Vanguard Total Stock Market ETF"),
    ("VOO", "Vanguard S&P 500 ETF"),
    ("GLD", "SPDR Gold Shares ETF"),
    ("SLV", "iShares Silver Trust ETF"),
    ("TLT", "iShares 20+ Year Treasury Bond ETF"),
    ("HYG", "iShares High Yield Corporate Bond ETF"),
    ("EEM", "iShares MSCI Emerging Markets ETF"),
    ("XLK", "Technology Select Sector SPDR ETF"),
    ("XLF", "Financial Select Sector SPDR ETF"),
    ("XLE", "Energy Select Sector SPDR ETF"),
    ("XLV", "Health Care Select Sector SPDR ETF"),
    ("ARKK", "ARK Innovation ETF"),
    ("BND", "Vanguard Total Bond Market ETF"),
    # ── Argentina — Merval ────────────────────────────────────────────────────
    ("GGAL.BA", "Grupo Financiero Galicia"),
    ("YPF", "YPF S.A."),
    ("BMA.BA", "Banco Macro S.A."),
    ("SUPV.BA", "Supervielle S.A."),
    ("PAMP.BA", "Pampa Energía S.A."),
    ("TGNO4.BA", "Transportadora Gas del Norte"),
    ("TGSU2.BA", "Transportadora Gas del Sur"),
    ("TXAR.BA", "Ternium Argentina S.A."),
    ("ALUA.BA", "Aluar Aluminio Argentino"),
    ("CRES.BA", "Cresud S.A."),
    ("EDN.BA", "Edenor S.A."),
    ("LOMA.BA", "Loma Negra C.I.A.S.A."),
    ("CEPU.BA", "Central Puerto S.A."),
    ("BYMA.BA", "Bolsas y Mercados Argentinos"),
    ("COME.BA", "Sociedad Comercial del Plata"),
    ("MOLI.BA", "Molinos Río de la Plata"),
    ("MIRG.BA", "Mirgor S.A."),
    # ── Argentina — ADRs en NYSE ──────────────────────────────────────────────
    ("GGAL", "Grupo Financiero Galicia ADR"),
    ("BMA", "Banco Macro ADR"),
    ("SUPV", "Supervielle ADR"),
    ("LOMA", "Loma Negra ADR"),
    ("CEPU", "Central Puerto ADR"),
    ("PAM", "Pampa Energía ADR"),
    ("TGS", "Transportadora Gas del Sur ADR"),
    # ── Cripto ────────────────────────────────────────────────────────────────
    ("BTC-USD", "Bitcoin USD"),
    ("ETH-USD", "Ethereum USD"),
    ("SOL-USD", "Solana USD"),
    ("BNB-USD", "Binance Coin USD"),
    ("XRP-USD", "XRP USD"),
    # ── Índices ───────────────────────────────────────────────────────────────
    ("^GSPC", "S&P 500 Index"),
    ("^IXIC", "NASDAQ Composite"),
    ("^DJI", "Dow Jones Industrial Average"),
    ("^RUT", "Russell 2000 Index"),
    ("^VIX", "CBOE Volatility Index (VIX)"),
    ("^MERV", "MERVAL Index — Argentina"),
    ("^FTSE", "FTSE 100 Index — UK"),
    ("^N225", "Nikkei 225 — Japan"),
]


# Prebuilt completion strings: "AAPL — Apple Inc."
COMPLETION_LIST: list[str] = [f"{sym} — {name}" for sym, name in TICKER_DB]


# Period dropdown labels mapped to yfinance period codes.
PERIODS: dict[str, str] = {
    "1 mes": "1mo",
    "3 meses": "3mo",
    "6 meses": "6mo",
    "1 año": "1y",
    "2 años": "2y",
    "5 años": "5y",
}
