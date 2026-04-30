"""
GARCH(1,1) volatility modelling for FinanzIAs.

Provides three things:

  1. GarchForecast  — dataclass with the fitted conditional volatility,
     the h-day-ahead forecast, the unconditional (long-run) volatility
     implied by the model, and the volatility regime label.

  2. fit_garch_forecast  — fits a symmetric GARCH(1,1) on log-returns
     and returns a GarchForecast.

  3. compute_annual_volatility  — returns the best available annualised
     volatility estimate (GARCH forecast when possible, EWMA fallback).
     This is what MarketContext uses so that consumers get an improved
     forward-looking estimate transparently.

  4. train_garch_signal  — emits a TechnicalSignal based on whether the
     forecasted volatility is expanding (risk-off) or contracting
     (squeeze — possible breakout).

Requires: pip install arch   (graceful fallback to EWMA if unavailable)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, Tuple

# ── Optional arch dependency ─────────────────────────────────────────────────
try:
    from arch import arch_model
    _ARCH_OK = True
except ImportError:
    _ARCH_OK = False


# ── Config ───────────────────────────────────────────────────────────────────

GARCH_MIN_ROWS      = 120    # rows of clean returns required to fit GARCH
GARCH_FORECAST_H    = 5      # default forecast horizon (trading days)
VOL_EXPAND_RATIO    = 1.15   # forecast / current >= this → EXPANSION
VOL_CONTRACT_RATIO  = 0.85   # forecast / current <= this → CONTRACTION
LOW_VOL_ANNUAL_PCT  = 18.0   # below this is considered a true squeeze setup
HIGH_VOL_ANNUAL_PCT = 40.0   # above this is considered elevated risk


# ── GarchForecast dataclass ──────────────────────────────────────────────────

@dataclass
class GarchForecast:
    """Output of a GARCH(1,1) fit on daily log-returns."""
    current_vol: float        # annualised %, conditional σ at t
    forecast_vol: float       # annualised %, mean σ over the next `horizon` days
    long_run_vol: float       # annualised %, unconditional σ implied by params
    horizon: int              # forecast horizon in trading days
    alpha: float              # short-run shock coefficient
    beta: float               # persistence coefficient
    persistence: float        # alpha + beta  (→1 = very persistent)
    vol_regime: str           # "EXPANSION" | "CONTRACTION" | "STABLE"

    @property
    def vol_regime_es(self) -> str:
        return {
            "EXPANSION":   "Expansión",
            "CONTRACTION": "Contracción",
            "STABLE":      "Estable",
        }.get(self.vol_regime, "—")

    @property
    def vol_regime_color(self) -> str:
        return {
            "EXPANSION":   "#f87171",
            "CONTRACTION": "#22c55e",
            "STABLE":      "#fbbf24",
        }.get(self.vol_regime, "#fbbf24")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _log_returns(df: pd.DataFrame) -> pd.Series:
    """Daily log-returns as a clean pd.Series (no NaNs, no zeros)."""
    close = df["Close"].squeeze()
    ret = np.log(close / close.shift(1)).dropna()
    # arch library prefers returns in percent to improve optimiser conditioning
    return ret * 100.0


def _classify_vol_regime(current_pct: float, forecast_pct: float) -> str:
    """EXPANSION / CONTRACTION / STABLE based on forecast / current ratio."""
    if current_pct <= 0:
        return "STABLE"
    ratio = forecast_pct / current_pct
    if ratio >= VOL_EXPAND_RATIO:
        return "EXPANSION"
    if ratio <= VOL_CONTRACT_RATIO:
        return "CONTRACTION"
    return "STABLE"


def _ewma_annual_vol(df: pd.DataFrame) -> float:
    """EWMA(span=20) annualised volatility %, used as fallback."""
    close = df["Close"].squeeze()
    returns = close.pct_change().dropna()
    if len(returns) < 5:
        return 0.0
    ewma = float(returns.ewm(span=20).std().iloc[-1]) * np.sqrt(252) * 100
    return round(ewma if not np.isnan(ewma) else 0.0, 1)


# ── 1. Fit GARCH(1,1) ────────────────────────────────────────────────────────

def fit_garch_forecast(
    df: pd.DataFrame,
    horizon: int = GARCH_FORECAST_H,
) -> Optional[GarchForecast]:
    """
    Fit a symmetric GARCH(1,1) model on daily log-returns and return a
    GarchForecast summarising the current and forecasted volatility.

    Mean model: Zero (appropriate for daily equity returns at this scale).
    Vol model:  GARCH(1,1) with Gaussian innovations.

    Returns
    -------
    GarchForecast or None if `arch` is not installed / insufficient data /
    the optimiser fails to converge.
    """
    if not _ARCH_OK:
        return None

    returns = _log_returns(df)
    if len(returns) < GARCH_MIN_ROWS:
        return None

    try:
        model = arch_model(
            returns,
            mean="Zero",
            vol="Garch",
            p=1,
            q=1,
            dist="normal",
            rescale=False,
        )
        res = model.fit(disp="off", show_warning=False)

        # Conditional σ series is in %-per-day (matches the input scale)
        cond_vol_daily = float(res.conditional_volatility.iloc[-1])

        # h-step-ahead variance forecast; take the mean across the horizon
        fc = res.forecast(horizon=horizon, reindex=False)
        var_path = np.asarray(fc.variance.iloc[-1].values, dtype=float)
        forecast_vol_daily = float(np.sqrt(np.mean(var_path)))

        # Parameter extraction (keys can vary slightly across arch versions)
        params = res.params
        omega = float(params.get("omega", 0.0))
        alpha = float(params.get("alpha[1]", params.get("alpha", 0.0)))
        beta  = float(params.get("beta[1]",  params.get("beta",  0.0)))
        persistence = alpha + beta

        # Unconditional σ (daily) if the model is stationary (α+β<1)
        if persistence < 0.999 and omega > 0:
            long_run_daily = float(np.sqrt(omega / (1.0 - persistence)))
        else:
            long_run_daily = cond_vol_daily

        # Annualise (daily %-σ → annual %) by √252
        annualise = lambda v: round(float(v) * np.sqrt(252), 1)
        current_annual  = annualise(cond_vol_daily)
        forecast_annual = annualise(forecast_vol_daily)
        long_run_annual = annualise(long_run_daily)

        vol_regime = _classify_vol_regime(current_annual, forecast_annual)

    except Exception as exc:
        print(f"[GARCH] fit error: {exc}")
        return None

    return GarchForecast(
        current_vol=current_annual,
        forecast_vol=forecast_annual,
        long_run_vol=long_run_annual,
        horizon=horizon,
        alpha=round(alpha, 4),
        beta=round(beta, 4),
        persistence=round(persistence, 4),
        vol_regime=vol_regime,
    )


# ── 2. Best-available annualised volatility ──────────────────────────────────

def compute_annual_volatility(df: pd.DataFrame) -> Tuple[float, float, str]:
    """
    Return the best available annualised volatility estimate.

    Returns
    -------
    (current_vol_pct, forecast_vol_pct, source)
        source ∈ {"GARCH", "EWMA"}.  When GARCH is unavailable the forecast
        equals the current estimate (no forward-looking information).
    """
    forecast = fit_garch_forecast(df)
    if forecast is not None:
        return forecast.current_vol, forecast.forecast_vol, "GARCH"
    ewma = _ewma_annual_vol(df)
    return ewma, ewma, "EWMA"


# ── 3. GARCH-based TechnicalSignal ───────────────────────────────────────────

def train_garch_signal(
    df: pd.DataFrame,
    horizon: int = GARCH_FORECAST_H,
):
    """
    Emit a TechnicalSignal based on the forecasted volatility regime.

    Interpretation (retail long-biased convention):

      • CONTRACTION + already-low forecast vol  → BUY / MODERATE
          Classic "squeeze" setup — low vol often precedes breakouts.
      • CONTRACTION + normal vol                → BUY / WEAK
      • EXPANSION   + already-high forecast vol → SELL / MODERATE
          Risk-off: elevated vol forecast, reduce exposure.
      • EXPANSION   + normal vol                → SELL / WEAK
      • STABLE                                   → HOLD / WEAK

    This is a risk-management overlay; it does not claim price direction,
    only that the distribution of future returns is widening or tightening.
    """
    if not _ARCH_OK:
        return None

    # Lazy import to avoid circular dependency
    from analysis.technical import TechnicalSignal

    forecast = fit_garch_forecast(df, horizon=horizon)
    if forecast is None:
        return None

    cur, fwd, reg = forecast.current_vol, forecast.forecast_vol, forecast.vol_regime
    ratio = (fwd / cur) if cur > 0 else 1.0

    if reg == "CONTRACTION":
        sig = "BUY"
        if fwd <= LOW_VOL_ANNUAL_PCT:
            strength = "MODERATE"
            desc = (
                f"GARCH: volatilidad contrayendo hacia {fwd:.1f}% anual "
                f"(actual {cur:.1f}%). Setup de squeeze — posible ruptura."
            )
        else:
            strength = "WEAK"
            desc = (
                f"GARCH: volatilidad contrayendo ({cur:.1f}% → {fwd:.1f}% a "
                f"{horizon} días). Condiciones más calmas."
            )
    elif reg == "EXPANSION":
        sig = "SELL"
        if fwd >= HIGH_VOL_ANNUAL_PCT:
            strength = "MODERATE"
            desc = (
                f"GARCH: volatilidad expandiendo hacia {fwd:.1f}% anual "
                f"(actual {cur:.1f}%). Riesgo elevado — reducir exposición."
            )
        else:
            strength = "WEAK"
            desc = (
                f"GARCH: volatilidad expandiendo ({cur:.1f}% → {fwd:.1f}% a "
                f"{horizon} días). Mayor riesgo a la baja."
            )
    else:
        sig, strength = "HOLD", "WEAK"
        desc = (
            f"GARCH: volatilidad estable ({cur:.1f}% → {fwd:.1f}% anual a "
            f"{horizon} días, persistencia α+β={forecast.persistence:.2f})."
        )

    return TechnicalSignal(
        indicator="GARCH Volatilidad",
        value=round(ratio, 3),
        signal=sig,
        strength=strength,
        description=desc,
    )
