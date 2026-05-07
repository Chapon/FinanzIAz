"""
Centralized numeric/string constants for FinanzIAs.

Anything tunable that was previously hard-coded across modules lives here so
changes propagate consistently and are easy to audit. Group constants by
domain (technical analysis, paper trading defaults, networking, etc.).

Notes
-----
- These are *defaults* and *thresholds*. User-tunable runtime settings still
  belong in ``config/settings_manager.py``; this file is for the values that
  rarely change but were sprinkled as magic numbers throughout the codebase.
- Annualization conventions: ``TRADING_DAYS_PER_YEAR = 252`` (US equities).
"""
from __future__ import annotations


# ── General market / annualization conventions ───────────────────────────────
TRADING_DAYS_PER_YEAR: int = 252
MARKET_OPEN_HOUR_ET: int = 9        # 9:30 ET → use OPEN_HOUR + OPEN_MINUTE
MARKET_OPEN_MINUTE: int = 30
MARKET_CLOSE_HOUR_ET: int = 16
MARKET_CLOSE_MINUTE: int = 0
PRE_MARKET_OPEN_HOUR_ET: int = 4
POST_MARKET_CLOSE_HOUR_ET: int = 20


# ── Technical analysis (RSI) ─────────────────────────────────────────────────
# Six-zone interpretation:
# value < RSI_OVERSOLD_EXTREME      → BUY  STRONG
# value < RSI_OVERSOLD              → BUY  MODERATE
# value < RSI_LOW                   → BUY  WEAK
# RSI_LOW … RSI_HIGH                → HOLD (neutral)
# value > RSI_HIGH                  → SELL WEAK
# value > RSI_OVERBOUGHT            → SELL MODERATE
# value > RSI_OVERBOUGHT_EXTREME    → SELL STRONG
RSI_OVERSOLD_EXTREME:   float = 25.0
RSI_OVERSOLD:           float = 30.0
RSI_LOW:                float = 40.0
RSI_HIGH:               float = 60.0
RSI_OVERBOUGHT:         float = 70.0
RSI_OVERBOUGHT_EXTREME: float = 75.0

# Trend window inside the RSI signal description ("rising"/"falling"/"flat")
RSI_TREND_LOOKBACK_BARS: int = 5
RSI_TREND_DELTA_THRESHOLD: float = 3.0


# ── Volume trend signal ──────────────────────────────────────────────────────
VOLUME_HIGH_RATIO: float = 1.5      # current / 20-day avg ≥ this → high volume
VOLUME_LOW_RATIO:  float = 0.5      # current / 20-day avg ≤ this → low  volume


# ── Networking / yfinance ────────────────────────────────────────────────────
NETWORK_TIMEOUT_SECONDS: float = 10.0   # per-request socket timeout
NETWORK_HARD_TIMEOUT_SECONDS: float = 15.0  # absolute wall-clock cap
NETWORK_RETRY_TOTAL: int = 2
NETWORK_RETRY_BACKOFF: float = 1.0
PRICE_CACHE_TTL_MINUTES: int = 5
HISTORICAL_CACHE_TTL_HOURS: int = 1
DIVIDEND_CACHE_HOURS: int = 6
BULK_FETCH_WORKERS: int = 5             # max parallel threads


# ── Paper-trading defaults (also exposed via settings_manager) ──────────────
DEFAULT_INITIAL_CAPITAL_USD: float = 50_000.0
DEFAULT_FIXED_AMOUNT_USD:    float = 5_000.0
DEFAULT_COMMISSION_PCT:      float = 0.001     # 0.10 %
DEFAULT_SLIPPAGE_PCT:        float = 0.0005    # 0.05 %
DEFAULT_DRIFT_THRESHOLD:     float = 0.25
DEFAULT_MAX_POSITIONS:       int   = 5

PAPER_AUTO_REFRESH_SECONDS: int = 60         # portfolio price refresh tick


# ── GARCH thresholds ─────────────────────────────────────────────────────────
GARCH_MIN_ROWS: int = 120
GARCH_FORECAST_HORIZON: int = 5
GARCH_VOL_EXPAND_RATIO:   float = 1.15
GARCH_VOL_CONTRACT_RATIO: float = 0.85
GARCH_LOW_VOL_ANNUAL_PCT:  float = 18.0
GARCH_HIGH_VOL_ANNUAL_PCT: float = 40.0


# ── ML / XGBoost defaults ────────────────────────────────────────────────────
ML_HORIZON_DAYS: int = 5             # predicting price move N days ahead
ML_MIN_TRAINING_ROWS: int = 250
ML_BUY_PROBABILITY_THRESHOLD:  float = 0.60
ML_SELL_PROBABILITY_THRESHOLD: float = 0.40


# ── Display / UI ─────────────────────────────────────────────────────────────
CHART_DEFAULT_PERIOD: str = "1y"
CHART_DEFAULT_INTERVAL: str = "1d"
