"""
Technical analysis engine.

Computes RSI, MACD, Bollinger Bands, SMA cross, and Volume Trend signals,
then aggregates them into a weighted overall signal.

Optionally integrates:
  • MarketContext  — regime detection (HMM-based if hmmlearn is available,
                     otherwise rule-based detect_market_regime)
  • GARCH Volatilidad — volatility regime (expansion/contraction/stable)
                        and forward-looking σ forecast (train_garch_signal)
  • HMM Régimen    — 5-day-ahead bull/bear state probability (train_hmm_signal)
  • XGBoost ML    — probability of 5-day price increase (train_xgboost_signal)
  • ml_probability — regime-adjusted overall probability (compute_signal_probability)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional
from dataclasses import dataclass, field


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TechnicalSignal:
    indicator: str
    value: float
    signal: str      # "BUY" | "SELL" | "HOLD"
    strength: str    # "STRONG" | "MODERATE" | "WEAK"
    description: str


def to_yahoo_level(signal: str, strength: str) -> str:
    """Map internal BUY/SELL/HOLD + strength to Yahoo Finance 5-level system."""
    if signal == "BUY":
        return "Strong Buy" if strength == "STRONG" else "Buy"
    elif signal == "SELL":
        return "Sell" if strength == "STRONG" else "Underperform"
    return "Hold"


@dataclass
class AnalysisResult:
    ticker: str
    overall_signal: str      # "BUY" | "SELL" | "HOLD"
    overall_strength: str    # "STRONG" | "MODERATE" | "WEAK"
    confidence_score: float  # 0-100 (raw indicator consensus)
    signals: list[TechnicalSignal] = field(default_factory=list)
    summary: str = ""
    # ── ML extensions (populated when enable_xgboost=True) ───────────────────
    market_context: Optional[object] = None  # analysis.ml_signals.MarketContext
    ml_probability: Optional[float]  = None  # 0-1, regime-adjusted buy probability

    @property
    def yahoo_level(self) -> str:
        """Overall signal mapped to Yahoo Finance 5-level system."""
        return to_yahoo_level(self.overall_signal, self.overall_strength)


# ── Indicator computation ─────────────────────────────────────────────────────

def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder smoothing)."""
    close = df["Close"].squeeze()
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    close = df["Close"].squeeze()
    ema_fast   = close.ewm(span=fast,   adjust=False).mean()
    ema_slow   = close.ewm(span=slow,   adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper_band, middle_band, lower_band)."""
    close  = df["Close"].squeeze()
    middle = close.rolling(window=period).mean()
    std    = close.rolling(window=period).std()
    return middle + std * std_dev, middle, middle - std * std_dev


def compute_sma(df: pd.DataFrame, period: int) -> pd.Series:
    return df["Close"].squeeze().rolling(window=period).mean()


def compute_ema(df: pd.DataFrame, period: int) -> pd.Series:
    return df["Close"].squeeze().ewm(span=period, adjust=False).mean()


def compute_volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["Volume"].squeeze().rolling(window=period).mean()


# ── Signal generators ─────────────────────────────────────────────────────────

def _rsi_signal(rsi_series: pd.Series) -> TechnicalSignal:
    """
    RSI with extended zones:
      <25  STRONG BUY   · 25-30 MODERATE BUY  · 30-40 WEAK BUY
      >75  STRONG SELL  · 70-75 MODERATE SELL · 60-70 WEAK SELL
      40-60 HOLD
    Includes 5-day trend in the description.
    """
    rsi_val  = float(rsi_series.iloc[-1])
    rsi_prev = float(rsi_series.iloc[-6]) if len(rsi_series) >= 6 else rsi_val
    trend    = rsi_val - rsi_prev
    trend_txt = f", {'↑ subiendo' if trend > 3 else '↓ bajando' if trend < -3 else 'estable'}"

    if rsi_val < 25:
        return TechnicalSignal("RSI", round(rsi_val, 2), "BUY", "STRONG",
            f"RSI {rsi_val:.1f} — sobreventa extrema{trend_txt}. Rebote técnico probable.")
    elif rsi_val < 30:
        return TechnicalSignal("RSI", round(rsi_val, 2), "BUY", "MODERATE",
            f"RSI {rsi_val:.1f} — sobreventa{trend_txt}. Posible rebote.")
    elif rsi_val < 40:
        return TechnicalSignal("RSI", round(rsi_val, 2), "BUY", "WEAK",
            f"RSI {rsi_val:.1f} — zona baja{trend_txt}. Acercándose a sobreventa.")
    elif rsi_val > 75:
        return TechnicalSignal("RSI", round(rsi_val, 2), "SELL", "STRONG",
            f"RSI {rsi_val:.1f} — sobrecompra extrema{trend_txt}. Corrección probable.")
    elif rsi_val > 70:
        return TechnicalSignal("RSI", round(rsi_val, 2), "SELL", "MODERATE",
            f"RSI {rsi_val:.1f} — sobrecompra{trend_txt}. Posible corrección.")
    elif rsi_val > 60:
        return TechnicalSignal("RSI", round(rsi_val, 2), "SELL", "WEAK",
            f"RSI {rsi_val:.1f} — zona alta{trend_txt}. Acercándose a sobrecompra.")
    else:
        return TechnicalSignal("RSI", round(rsi_val, 2), "HOLD", "WEAK",
            f"RSI {rsi_val:.1f} — zona neutral (40-60).")


def _macd_signal(
    macd_val: float,
    signal_val: float,
    hist_prev: float,
    hist_curr: float,
) -> TechnicalSignal:
    """
    MACD with histogram momentum awareness.
    Crossovers → STRONG.  Existing trend + growing momentum → MODERATE.
    Existing trend + fading momentum → WEAK.
    """
    crossover = hist_prev < 0 and hist_curr > 0
    crossunder = hist_prev > 0 and hist_curr < 0
    hist_growing = hist_curr > hist_prev   # histogram accelerating

    if crossover:
        return TechnicalSignal("MACD", round(macd_val, 4), "BUY", "STRONG",
            "MACD cruzó por encima de la señal — nuevo impulso alcista.")
    elif crossunder:
        return TechnicalSignal("MACD", round(macd_val, 4), "SELL", "STRONG",
            "MACD cruzó por debajo de la señal — nuevo impulso bajista.")
    elif macd_val > signal_val:
        if hist_growing:
            return TechnicalSignal("MACD", round(macd_val, 4), "BUY", "MODERATE",
                "MACD sobre señal y momentum creciendo — tendencia alcista acelerando.")
        else:
            return TechnicalSignal("MACD", round(macd_val, 4), "BUY", "WEAK",
                "MACD sobre señal pero momentum decreciendo — tendencia alcista perdiendo fuerza.")
    else:
        if not hist_growing:  # histogram getting more negative
            return TechnicalSignal("MACD", round(macd_val, 4), "SELL", "MODERATE",
                "MACD bajo señal y momentum bajista acelerando.")
        else:
            return TechnicalSignal("MACD", round(macd_val, 4), "SELL", "WEAK",
                "MACD bajo señal pero momentum bajista frenando — posible reversión.")


def _bollinger_signal(
    price: float,
    upper: float,
    lower: float,
    middle: float,
) -> TechnicalSignal:
    bandwidth = (upper - lower) / middle if middle != 0 else 0
    if price <= lower:
        return TechnicalSignal("Bollinger Bands", round(price, 4), "BUY",
            "STRONG" if price < lower * 0.99 else "MODERATE",
            f"Precio tocó la banda inferior (ancho {bandwidth:.1%}). Rebote hacia ${middle:.2f}.")
    elif price >= upper:
        return TechnicalSignal("Bollinger Bands", round(price, 4), "SELL",
            "STRONG" if price > upper * 1.01 else "MODERATE",
            f"Precio tocó la banda superior (ancho {bandwidth:.1%}). Retroceso hacia ${middle:.2f}.")
    else:
        return TechnicalSignal("Bollinger Bands", round(price, 4), "HOLD", "WEAK",
            f"Precio dentro de las bandas (${lower:.2f} — ${upper:.2f}).")


def _sma_cross_signal(
    sma50: float,
    sma200: float,
    prev_sma50: float,
    prev_sma200: float,
) -> TechnicalSignal:
    golden = prev_sma50 <= prev_sma200 and sma50 > sma200
    death  = prev_sma50 >= prev_sma200 and sma50 < sma200
    diff   = round(sma50 - sma200, 4)

    if golden:
        return TechnicalSignal("Golden/Death Cross", diff, "BUY", "STRONG",
            "Golden Cross: SMA50 cruzó sobre SMA200 — señal alcista de largo plazo.")
    elif death:
        return TechnicalSignal("Golden/Death Cross", diff, "SELL", "STRONG",
            "Death Cross: SMA50 cruzó bajo SMA200 — señal bajista de largo plazo.")
    elif sma50 > sma200:
        return TechnicalSignal("Golden/Death Cross", diff, "BUY", "WEAK",
            f"SMA50 ({sma50:.2f}) sobre SMA200 ({sma200:.2f}) — tendencia alcista de fondo.")
    else:
        return TechnicalSignal("Golden/Death Cross", diff, "SELL", "WEAK",
            f"SMA50 ({sma50:.2f}) bajo SMA200 ({sma200:.2f}) — tendencia bajista de fondo.")


def _volume_signal(df: pd.DataFrame) -> Optional[TechnicalSignal]:
    """
    Volume trend: compare average volume on up-days vs down-days over last 10 sessions.
    High volume on up-days → accumulation (BUY).
    High volume on down-days → distribution (SELL).
    """
    if "Volume" not in df.columns or len(df) < 25:
        return None

    close  = df["Close"].squeeze()
    volume = df["Volume"].squeeze().replace(0, np.nan)
    vol_sma = volume.rolling(20).mean()

    # Avoid division by zero
    current_avg = float(vol_sma.iloc[-1])
    if current_avg == 0 or np.isnan(current_avg):
        return None

    # Last 10 sessions
    ret10 = close.pct_change().tail(10)
    vol10 = volume.tail(10)

    up_vol   = float(vol10[ret10 > 0].mean())
    down_vol = float(vol10[ret10 < 0].mean())

    if np.isnan(up_vol) or np.isnan(down_vol):
        return None

    ratio = up_vol / down_vol if down_vol > 0 else 1.0

    if ratio >= 1.5:
        strength = "STRONG" if ratio >= 2.0 else "MODERATE"
        return TechnicalSignal("Volumen", round(ratio, 2), "BUY", strength,
            f"Vol. en días alcistas {ratio:.1f}× mayor — acumulación institucional.")
    elif ratio <= 0.67:
        inv = 1 / ratio
        strength = "STRONG" if inv >= 2.0 else "MODERATE"
        return TechnicalSignal("Volumen", round(ratio, 2), "SELL", strength,
            f"Vol. en días bajistas {inv:.1f}× mayor — distribución / presión vendedora.")
    else:
        return TechnicalSignal("Volumen", round(ratio, 2), "HOLD", "WEAK",
            "Volumen neutro — sin señal de acumulación ni distribución.")


# ── Full analysis ─────────────────────────────────────────────────────────────

def analyze(
    ticker: str,
    df: pd.DataFrame,
    enable_sma_cross: bool = True,
    enable_volume: bool = True,
    enable_xgboost: bool = True,
) -> Optional[AnalysisResult]:
    """
    Run full technical + ML analysis on a DataFrame of OHLCV data.

    Parameters
    ----------
    enable_sma_cross : include Golden/Death Cross signal (requires 200 days)
    enable_volume    : include Volume accumulation/distribution signal
    enable_xgboost   : train XGBoost classifier and include its signal
                       (set False for fast batch portfolio scans)

    Returns None if df has fewer than 50 rows.
    """
    if df is None or len(df) < 50:
        return None

    signals: list[TechnicalSignal] = []

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_series = compute_rsi(df)
    if not rsi_series.dropna().empty:
        signals.append(_rsi_signal(rsi_series))

    # ── MACD ──────────────────────────────────────────────────────────────────
    macd_line, signal_line, histogram = compute_macd(df)
    if len(histogram.dropna()) >= 2:
        signals.append(_macd_signal(
            float(macd_line.iloc[-1]),
            float(signal_line.iloc[-1]),
            float(histogram.iloc[-2]),
            float(histogram.iloc[-1]),
        ))

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    upper, middle, lower = compute_bollinger_bands(df)
    if not upper.dropna().empty:
        price = df["Close"].iloc[-1]
        price = float(price.iloc[-1]) if hasattr(price, '__iter__') else float(price)
        signals.append(_bollinger_signal(
            price,
            float(upper.iloc[-1]),
            float(lower.iloc[-1]),
            float(middle.iloc[-1]),
        ))

    # ── SMA 50/200 cross ──────────────────────────────────────────────────────
    if enable_sma_cross and len(df) >= 200:
        sma50 = compute_sma(df, 50)
        sma200 = compute_sma(df, 200)
        if not sma50.dropna().empty and not sma200.dropna().empty and len(sma50.dropna()) >= 2:
            signals.append(_sma_cross_signal(
                float(sma50.iloc[-1]),  float(sma200.iloc[-1]),
                float(sma50.iloc[-2]),  float(sma200.iloc[-2]),
            ))

    # ── Volume trend ──────────────────────────────────────────────────────────
    if enable_volume:
        vol_sig = _volume_signal(df)
        if vol_sig:
            signals.append(vol_sig)

    # ── XGBoost ML ────────────────────────────────────────────────────────────
    market_context = None
    ml_probability = None

    if enable_xgboost:
        try:
            from analysis.ml_signals import (
                detect_market_regime,
                detect_market_regime_hmm,
                train_xgboost_signal,
                train_hmm_signal,
                compute_signal_probability,
            )
            from analysis.garch_signals import train_garch_signal

            # Prefer HMM-based regime detection; fall back to rule-based.
            # (Both detectors use GARCH volatility internally when available.)
            market_context = detect_market_regime_hmm(df) or detect_market_regime(df)

            # GARCH volatility-regime signal (no-op if arch is not installed)
            garch_sig = train_garch_signal(df)
            if garch_sig:
                signals.append(garch_sig)

            # HMM state-forecast signal (no-op if hmmlearn is not installed)
            hmm_sig = train_hmm_signal(df)
            if hmm_sig:
                signals.append(hmm_sig)

            xgb_sig = train_xgboost_signal(df)
            if xgb_sig:
                signals.append(xgb_sig)
        except Exception as exc:
            print(f"[analyze] ML error for {ticker}: {exc}")

    if not signals:
        return None

    # ── Aggregate weighted score ───────────────────────────────────────────────
    WEIGHTS = {"STRONG": 3, "MODERATE": 2, "WEAK": 1}
    buy_score  = sum(WEIGHTS[s.strength] for s in signals if s.signal == "BUY")
    sell_score = sum(WEIGHTS[s.strength] for s in signals if s.signal == "SELL")
    total      = sum(WEIGHTS[s.strength] for s in signals)

    if total == 0:
        overall, strength, confidence = "HOLD", "WEAK", 0.0
    elif buy_score == sell_score:
        overall, strength = "HOLD", "WEAK"
        confidence = round(max(buy_score, sell_score) / (3 * len(signals)) * 100, 1)
    else:
        max_possible     = 3 * len(signals)
        dominant_score   = max(buy_score, sell_score)
        dominant_fraction = dominant_score / total

        overall    = "BUY" if buy_score > sell_score else "SELL"
        confidence = round(dominant_score / max_possible * 100, 1)

        if   dominant_fraction >= 0.60: strength = "STRONG"
        elif dominant_fraction >= 0.40: strength = "MODERATE"
        else:                           strength = "WEAK"

    # ── Regime-aware probability ───────────────────────────────────────────────
    if market_context is not None:
        try:
            from analysis.ml_signals import compute_signal_probability
            ml_probability = compute_signal_probability(signals, market_context)
        except Exception:
            pass

    # ── Summary ───────────────────────────────────────────────────────────────
    counts = {
        "BUY":  sum(1 for s in signals if s.signal == "BUY"),
        "SELL": sum(1 for s in signals if s.signal == "SELL"),
        "HOLD": sum(1 for s in signals if s.signal == "HOLD"),
    }

    if ml_probability is not None:
        direction = "compra" if ml_probability >= 0.55 else "venta" if ml_probability <= 0.45 else "neutral"
        prob_txt  = f"Prob. {direction}: {ml_probability:.0%}."
    else:
        prob_txt  = f"Confianza: {confidence:.0f}%."

    summary = (
        f"{counts['BUY']} alcistas · "
        f"{counts['SELL']} bajistas · "
        f"{counts['HOLD']} neutrales. "
        f"{prob_txt}"
    )

    return AnalysisResult(
        ticker=ticker,
        overall_signal=overall,
        overall_strength=strength,
        confidence_score=confidence,
        signals=signals,
        summary=summary,
        market_context=market_context,
        ml_probability=ml_probability,
    )


# ── Utilities ─────────────────────────────────────────────────────────────────

def get_support_resistance(df: pd.DataFrame, window: int = 20) -> dict:
    """Simple swing high/low support and resistance levels."""
    if len(df) < window * 2:
        return {}
    close   = df["Close"].squeeze()
    recent  = close.tail(window * 3)
    support    = float(recent.rolling(window).min().iloc[-1])
    resistance = float(recent.rolling(window).max().iloc[-1])
    return {"support": round(support, 4), "resistance": round(resistance, 4)}
