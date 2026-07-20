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

import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from config.constants import (
    GARCH_FORECAST_HORIZON as GARCH_FORECAST_H,
)
from config.constants import (
    GARCH_HIGH_VOL_ANNUAL_PCT as HIGH_VOL_ANNUAL_PCT,
)
from config.constants import (
    GARCH_LOW_VOL_ANNUAL_PCT as LOW_VOL_ANNUAL_PCT,
)
from config.constants import (
    GARCH_MIN_ROWS,
    TRADING_DAYS_PER_YEAR,
)
from config.constants import (
    GARCH_VOL_CONTRACT_RATIO as VOL_CONTRACT_RATIO,
)
from config.constants import (
    GARCH_VOL_EXPAND_RATIO as VOL_EXPAND_RATIO,
)
from config.logging_config import get_logger

log = get_logger(__name__)

# ── Optional arch dependency ─────────────────────────────────────────────────
try:
    from arch import arch_model

    _ARCH_OK = True
except ImportError:
    _ARCH_OK = False


# ── GarchForecast dataclass ──────────────────────────────────────────────────


@dataclass
class GarchForecast:
    """Output of a GARCH(1,1) fit on daily log-returns."""

    current_vol: float  # annualised %, conditional σ at t
    forecast_vol: float  # annualised %, mean σ over the next `horizon` days
    long_run_vol: float  # annualised %, unconditional σ implied by params
    horizon: int  # forecast horizon in trading days
    alpha: float  # short-run shock coefficient
    beta: float  # persistence coefficient
    persistence: float  # alpha + beta  (→1 = very persistent)
    vol_regime: str  # "EXPANSION" | "CONTRACTION" | "STABLE"

    @property
    def vol_regime_es(self) -> str:
        return {
            "EXPANSION": "Expansión",
            "CONTRACTION": "Contracción",
            "STABLE": "Estable",
        }.get(self.vol_regime, "—")

    @property
    def vol_regime_color(self) -> str:
        return {
            "EXPANSION": "#f87171",
            "CONTRACTION": "#22c55e",
            "STABLE": "#fbbf24",
        }.get(self.vol_regime, "#fbbf24")


# ── Helpers ──────────────────────────────────────────────────────────────────

# ── Memo del fit (GARCH2X) ───────────────────────────────────────────────────
# Un mismo análisis de ticker fitea el MISMO df dos veces: vía `train_garch_signal`
# (la señal) y vía `compute_annual_volatility` (dentro de `detect_market_regime*`).
# Memoizamos por huella del contenido del frame para pagar un solo fit.
#
# Tres detalles que importan:
#   1. **Se cachea también el `None`.** Los fits degenerados (no converge, params
#      fuera de la región válida) devuelven None, y son justo los que el log
#      2026-07-15 mostraba duplicados. Si solo se cachea el éxito, el caso que
#      motivó la tarea sigue fiteando dos veces.
#   2. **Tamaño acotado.** La app corre horas y cada barra nueva genera una huella
#      distinta, así que un dict sin tope crece sin límite. FIFO simple.
#   3. **La huella nunca puede tirar.** Si no se puede calcular (frame raro), se
#      devuelve None y se saltea el cache: fitear de más es barato, romper el scan no.

_GARCH_CACHE_MAXSIZE = 256
_garch_cache: OrderedDict[tuple, GarchForecast | None] = OrderedDict()
_garch_cache_lock = threading.Lock()


def _fingerprint(df: pd.DataFrame, horizon: int) -> tuple | None:
    """Huella estable del contenido del frame, o ``None`` si no se puede calcular.

    Se basa en el contenido (largo + último timestamp + primeros/últimos closes)
    y no en el ticker: dos frames con esos cinco componentes iguales son el mismo
    frame a todos los efectos del fit, y ningún caller tiene el ticker a mano.
    """
    try:
        close = np.asarray(_close_series(df), dtype=float).ravel()
        if close.size == 0:
            return None
        index = df.index
        last_ts = str(index[-1]) if len(index) else ""
        return (
            horizon,
            len(df),
            last_ts,
            tuple(np.round(close[:5], 6)),
            tuple(np.round(close[-5:], 6)),
        )
    except Exception:
        return None


def _cache_lookup(key: tuple) -> tuple[bool, GarchForecast | None]:
    """``(hit, valor)`` — ``hit`` distingue "cacheado como None" de "no está"."""
    with _garch_cache_lock:
        if key in _garch_cache:
            return True, _garch_cache[key]
    return False, None


def _cache_store(key: tuple, value: GarchForecast | None) -> None:
    with _garch_cache_lock:
        _garch_cache[key] = value
        while len(_garch_cache) > _GARCH_CACHE_MAXSIZE:
            _garch_cache.popitem(last=False)  # FIFO: sale la más vieja


def reset_garch_cache() -> None:
    """Vacía el memo — para tests y para forzar un refit."""
    with _garch_cache_lock:
        _garch_cache.clear()


def _close_series(df: pd.DataFrame) -> pd.Series:
    """La columna ``Close`` SIEMPRE como Series.

    ``df["Close"].squeeze()`` —que era el idiom acá— devuelve un **escalar** cuando
    el frame tiene una sola fila, y entonces `.shift`/`.pct_change`/`.head` explotan
    con AttributeError en pleno scan. `squeeze` se usaba para aplanar el caso de
    columnas ``Close`` duplicadas; eso se resuelve tomando la primera columna.
    """
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return pd.Series(close, dtype="float64")


def _log_returns(df: pd.DataFrame) -> pd.Series:
    """Daily log-returns as a clean pd.Series (no NaNs, no zeros)."""
    close = _close_series(df)
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
    close = _close_series(df)
    returns = close.pct_change().dropna()
    if len(returns) < 5:
        return 0.0
    ewma = float(returns.ewm(span=20).std().iloc[-1]) * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    return round(ewma if not np.isnan(ewma) else 0.0, 1)


# ── 1. Fit GARCH(1,1) ────────────────────────────────────────────────────────


def fit_garch_forecast(
    df: pd.DataFrame,
    horizon: int = GARCH_FORECAST_H,
) -> GarchForecast | None:
    """
    Fit a symmetric GARCH(1,1) model on daily log-returns and return a
    GarchForecast summarising the current and forecasted volatility.

    Mean model: Zero (appropriate for daily equity returns at this scale).
    Vol model:  GARCH(1,1) with Gaussian innovations.

    El resultado se memoiza por huella del frame (incluyendo el ``None`` de los
    fits degenerados) para no pagar dos veces el mismo fit dentro de un análisis.

    Returns
    -------
    GarchForecast or None if `arch` is not installed / insufficient data /
    the optimiser fails to converge.
    """
    if not _ARCH_OK:
        return None

    key = _fingerprint(df, horizon)
    if key is not None:
        hit, cached = _cache_lookup(key)
        if hit:
            return cached

    result = _fit_garch_forecast_uncached(df, horizon)

    if key is not None:
        _cache_store(key, result)
    return result


def _fit_garch_forecast_uncached(
    df: pd.DataFrame,
    horizon: int,
) -> GarchForecast | None:
    """El fit real. Separado para que TODOS sus ``return`` pasen por el memo."""
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

        # ── Convergence guard ───────────────────────────────────────────────
        # ``arch`` exposes ``convergence_flag``: 0 means the optimiser
        # converged successfully. Anything else (1=max-iters, 2=line-search
        # failure, etc.) means the parameter estimates are unreliable and we
        # must NOT propagate them to consumers — return None instead.
        conv_flag = getattr(res, "convergence_flag", None)
        if conv_flag is not None and conv_flag != 0:
            log.debug(
                "GARCH did not converge (flag=%s, n=%d) — falling back to EWMA.",
                conv_flag,
                len(returns),
            )
            return None

        # Conditional σ series is in %-per-day (matches the input scale)
        cond_vol_daily = float(res.conditional_volatility.iloc[-1])
        if not np.isfinite(cond_vol_daily) or cond_vol_daily <= 0:
            log.debug("GARCH conditional vol non-finite/non-positive (%s)", cond_vol_daily)
            return None

        # h-step-ahead variance forecast; take the mean across the horizon
        fc = res.forecast(horizon=horizon, reindex=False)
        var_path = np.asarray(fc.variance.iloc[-1].values, dtype=float)
        if var_path.size == 0 or not np.all(np.isfinite(var_path)) or np.any(var_path <= 0):
            log.debug("GARCH forecast variance invalid: %s", var_path.tolist())
            return None
        forecast_vol_daily = float(np.sqrt(np.mean(var_path)))
        if not np.isfinite(forecast_vol_daily) or forecast_vol_daily <= 0:
            return None

        # Parameter extraction (keys can vary slightly across arch versions)
        params = res.params
        omega = float(params.get("omega", 0.0))
        alpha = float(params.get("alpha[1]", params.get("alpha", 0.0)))
        beta = float(params.get("beta[1]", params.get("beta", 0.0)))
        persistence = alpha + beta

        # Sanity-check parameters: a usable GARCH(1,1) needs ω>0, α≥0, β≥0,
        # and α+β<1 for stationarity. Anything else means the optimiser
        # parked on a corner of the parameter space and the forecast is junk.
        if not (
            np.isfinite(omega)
            and omega > 0
            and np.isfinite(alpha)
            and alpha >= 0
            and np.isfinite(beta)
            and beta >= 0
            and persistence < 1.0
        ):
            log.debug(
                "GARCH parameters out of valid region (ω=%.4g α=%.4g β=%.4g α+β=%.4g)",
                omega,
                alpha,
                beta,
                persistence,
            )
            return None

        # Unconditional σ (daily) if the model is stationary (α+β<1)
        if persistence < 0.999 and omega > 0:
            long_run_daily = float(np.sqrt(omega / (1.0 - persistence)))
        else:
            long_run_daily = cond_vol_daily

        # Annualise (daily %-σ → annual %) by √(trading days/year)
        annualise = lambda v: round(float(v) * np.sqrt(TRADING_DAYS_PER_YEAR), 1)
        current_annual = annualise(cond_vol_daily)
        forecast_annual = annualise(forecast_vol_daily)
        long_run_annual = annualise(long_run_daily)

        vol_regime = _classify_vol_regime(current_annual, forecast_annual)

    except Exception as exc:
        log.warning("GARCH fit error: %s", exc)
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


def compute_annual_volatility(df: pd.DataFrame) -> tuple[float, float, str]:
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
