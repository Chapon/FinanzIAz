"""
Machine-learning signals for FinanzIAs.

Provides the following:

  1. MarketContext  — regime detection (BULL / BEAR / LATERAL) using rolling
     multi-timeframe statistics.  No external ML library required.

  2. detect_market_regime_hmm  — regime detection via a 3-state Gaussian
     Hidden Markov Model on 1-day log-returns and 5-day rolling volatility.
     Returns the same MarketContext dataclass.
     Requires: pip install hmmlearn

  3. train_xgboost_signal  — trains an XGBoost binary classifier on the
     ticker's own historical features and returns a TechnicalSignal with the
     predicted probability of a 5-day price increase.
     Requires: pip install xgboost

  4. train_hmm_signal  — fits a 3-state Gaussian HMM and returns a
     TechnicalSignal based on the 5-day-ahead probability of being in the
     bullish hidden state (via the transition matrix).
     Requires: pip install hmmlearn

  5. compute_signal_probability  — combines the raw indicator consensus with
     regime alignment and volatility risk into a single 0-1 probability score.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional

# ── Optional XGBoost ──────────────────────────────────────────────────────────
try:
    import xgboost as xgb
    _XGB_OK = True
except ImportError:
    _XGB_OK = False

# ── Optional hmmlearn ─────────────────────────────────────────────────────────
try:
    from hmmlearn import hmm as _hmm
    _HMM_OK = True
except ImportError:
    _HMM_OK = False


# ── 1. Market Context ─────────────────────────────────────────────────────────

@dataclass
class MarketContext:
    """Encapsulates the current market regime and risk assessment."""
    regime: str               # "BULL" | "BEAR" | "LATERAL"
    regime_confidence: float  # 0–1 (50% = barely classifiable)
    volatility_level: str     # "LOW" | "MEDIUM" | "HIGH"
    annual_volatility: float  # current conditional σ (annualised %)
    risk_score: float         # 0–1  (0 = low risk, 1 = high risk)
    # ── Forward-looking volatility (populated by GARCH when available) ────
    forecast_volatility: Optional[float] = None  # h-day-ahead σ (annualised %)
    volatility_source: str = "EWMA"              # "GARCH" | "EWMA"

    # ── display helpers ───────────────────────────────────────────────────────

    @property
    def regime_es(self) -> str:
        return {"BULL": "Alcista", "BEAR": "Bajista", "LATERAL": "Lateral"}.get(
            self.regime, self.regime
        )

    @property
    def regime_color(self) -> str:
        return {"BULL": "#22c55e", "BEAR": "#f87171", "LATERAL": "#fbbf24"}.get(
            self.regime, "#fbbf24"
        )

    @property
    def regime_icon(self) -> str:
        return {"BULL": "▲", "BEAR": "▼", "LATERAL": "→"}.get(self.regime, "→")

    @property
    def volatility_es(self) -> str:
        return {"LOW": "Baja", "MEDIUM": "Media", "HIGH": "Alta"}.get(
            self.volatility_level, "—"
        )

    @property
    def risk_color(self) -> str:
        if self.risk_score < 0.35:
            return "#22c55e"
        if self.risk_score < 0.65:
            return "#fbbf24"
        return "#f87171"

    @property
    def risk_es(self) -> str:
        if self.risk_score < 0.35:
            return "Bajo"
        if self.risk_score < 0.65:
            return "Moderado"
        return "Alto"


def detect_market_regime(df: pd.DataFrame) -> MarketContext:
    """
    Classify the current market regime using multi-timeframe scoring.

    Strategy
    --------
    Accumulates evidence from:
      • Short-term return  (5d)
      • Medium-term return (20d)
      • Long-term return   (60d)
      • Price vs SMA50
      • Price vs SMA200

    Each piece of evidence adds weighted bull or bear points.
    The balance determines BULL / BEAR / LATERAL and the confidence level.

    Pure pandas/numpy — no external ML dependency.
    """
    close = df["Close"].squeeze()
    n = len(close)
    current = float(close.iloc[-1])

    # Rolling returns (safe fallback when history is short)
    ret_5d  = float(close.pct_change(5).iloc[-1])  if n >= 6  else 0.0
    ret_20d = float(close.pct_change(20).iloc[-1]) if n >= 21 else ret_5d
    ret_60d = float(close.pct_change(60).iloc[-1]) if n >= 61 else ret_20d

    # SMA positions
    def _safe_sma(period):
        if n < period:
            return None
        v = float(close.rolling(period).mean().iloc[-1])
        return None if np.isnan(v) else v

    sma50_val  = _safe_sma(50)
    sma200_val = _safe_sma(200)
    above_sma50  = (current > sma50_val)  if sma50_val  is not None else None
    above_sma200 = (current > sma200_val) if sma200_val is not None else None

    # ── Weighted scoring ──────────────────────────────────────────────────────
    bull = 0.0
    bear = 0.0

    # 5-day momentum (weight 1)
    if   ret_5d >  0.020:  bull += 1.0
    elif ret_5d < -0.020:  bear += 1.0
    elif ret_5d >  0.005:  bull += 0.4
    elif ret_5d < -0.005:  bear += 0.4

    # 20-day momentum (weight 2)
    if   ret_20d >  0.050:  bull += 2.0
    elif ret_20d < -0.050:  bear += 2.0
    elif ret_20d >  0.010:  bull += 0.8
    elif ret_20d < -0.010:  bear += 0.8

    # 60-day momentum (weight 2)
    if   ret_60d >  0.120:  bull += 2.0
    elif ret_60d < -0.120:  bear += 2.0
    elif ret_60d >  0.030:  bull += 1.0
    elif ret_60d < -0.030:  bear += 1.0

    # SMA positions (weight 1.5 each)
    if   above_sma50 is True:  bull += 1.5
    elif above_sma50 is False: bear += 1.5

    if   above_sma200 is True:  bull += 1.5
    elif above_sma200 is False: bear += 1.5

    total_evidence = bull + bear
    if total_evidence == 0:
        regime, confidence = "LATERAL", 0.50
    else:
        balance = (bull - bear) / total_evidence  # –1 .. +1
        if   balance >= 0.25:  regime = "BULL";    confidence = 0.50 + balance * 0.45
        elif balance <= -0.25: regime = "BEAR";    confidence = 0.50 + abs(balance) * 0.45
        else:                  regime = "LATERAL"; confidence = 0.50 + (0.25 - abs(balance)) * 0.5

    # ── Volatility (GARCH forecast if available, EWMA fallback) ──────────────
    from analysis.garch_signals import compute_annual_volatility
    current_vol, forecast_vol, vol_source = compute_annual_volatility(df)
    annual_vol    = current_vol
    vol_for_risk  = forecast_vol  # forward-looking

    if   vol_for_risk < 15: vol_level = "LOW"
    elif vol_for_risk < 30: vol_level = "MEDIUM"
    else:                   vol_level = "HIGH"

    # ── Risk score ────────────────────────────────────────────────────────────
    vol_risk    = min(vol_for_risk / 60.0, 1.0)
    regime_risk = {"BEAR": 0.70, "LATERAL": 0.45, "BULL": 0.25}[regime]
    risk_score  = float(np.clip(0.55 * vol_risk + 0.45 * regime_risk, 0.0, 1.0))

    return MarketContext(
        regime=regime,
        regime_confidence=float(np.clip(confidence, 0.50, 0.95)),
        volatility_level=vol_level,
        annual_volatility=annual_vol,
        risk_score=round(risk_score, 3),
        forecast_volatility=round(forecast_vol, 1),
        volatility_source=vol_source,
    )


# ── 1b. HMM regime detection ──────────────────────────────────────────────────

HMM_MIN_ROWS   = 80    # minimum clean rows required to fit the HMM
HMM_N_STATES   = 3     # Bull / Lateral / Bear


def _hmm_observation_matrix(df: pd.DataFrame) -> Optional[np.ndarray]:
    """
    Build the observation matrix for the HMM.

    Two features per timestep — the minimal set commonly used in regime-
    switching models à la Hamilton (1989):

      • 1-day log-return        (captures drift)
      • 5-day rolling std       (captures local volatility)

    Returns
    -------
    np.ndarray of shape (n_obs, 2) or None if there is too little clean data.
    """
    close = df["Close"].squeeze()
    ret   = np.log(close / close.shift(1))
    vol   = ret.rolling(5).std()
    X     = pd.concat([ret.rename("ret"), vol.rename("vol")], axis=1).dropna()
    if len(X) < HMM_MIN_ROWS:
        return None
    return X.values.astype(np.float64)


def _fit_gaussian_hmm(X: np.ndarray, n_states: int = HMM_N_STATES):
    """
    Fit a Gaussian HMM and return (model, state_order), where state_order
    lists state indices sorted ascending by mean log-return.

    state_order[0] = lowest mean return  → BEAR
    state_order[-1] = highest mean return → BULL
    """
    model = _hmm.GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        n_iter=200,
        tol=1e-3,
        random_state=42,
    )
    model.fit(X)
    state_order = list(np.argsort(model.means_[:, 0]))  # mean of the return feature
    return model, state_order


def detect_market_regime_hmm(df: pd.DataFrame) -> Optional[MarketContext]:
    """
    Classify the current market regime using a 3-state Gaussian Hidden Markov
    Model fit on 1-day log-returns and 5-day rolling volatility.

    States are mapped to BULL / LATERAL / BEAR based on their learned mean
    return (highest → BULL, lowest → BEAR). The returned confidence is the
    posterior probability of the winning state at the latest observation.

    Returns
    -------
    MarketContext if hmmlearn is installed and the fit succeeds, else None.
    Callers should fall back to the rule-based detect_market_regime().
    """
    if not _HMM_OK:
        return None
    X = _hmm_observation_matrix(df)
    if X is None:
        return None

    try:
        model, order = _fit_gaussian_hmm(X, n_states=HMM_N_STATES)
        bear_idx = order[0]
        lat_idx  = order[1]
        bull_idx = order[-1]

        # Posterior state distribution at the most recent observation
        post = model.predict_proba(X)[-1]

        p_bear = float(post[bear_idx])
        p_lat  = float(post[lat_idx])
        p_bull = float(post[bull_idx])

        top = int(np.argmax([p_bear, p_lat, p_bull]))
        if   top == 2: regime, confidence = "BULL",    p_bull
        elif top == 0: regime, confidence = "BEAR",    p_bear
        else:          regime, confidence = "LATERAL", p_lat
    except Exception as exc:
        print(f"[HMM] regime detection error: {exc}")
        return None

    # ── Volatility (GARCH forecast if available, EWMA fallback) ──────────────
    from analysis.garch_signals import compute_annual_volatility
    current_vol, forecast_vol, vol_source = compute_annual_volatility(df)
    annual_vol    = current_vol
    vol_for_risk  = forecast_vol  # forward-looking

    if   vol_for_risk < 15: vol_level = "LOW"
    elif vol_for_risk < 30: vol_level = "MEDIUM"
    else:                   vol_level = "HIGH"

    # ── Risk score ────────────────────────────────────────────────────────────
    vol_risk    = min(vol_for_risk / 60.0, 1.0)
    regime_risk = {"BEAR": 0.70, "LATERAL": 0.45, "BULL": 0.25}[regime]
    risk_score  = float(np.clip(0.55 * vol_risk + 0.45 * regime_risk, 0.0, 1.0))

    return MarketContext(
        regime=regime,
        regime_confidence=float(np.clip(confidence, 0.50, 0.95)),
        volatility_level=vol_level,
        annual_volatility=annual_vol,
        risk_score=round(risk_score, 3),
        forecast_volatility=round(forecast_vol, 1),
        volatility_source=vol_source,
    )


# ── 2. XGBoost signal ─────────────────────────────────────────────────────────

PREDICTION_HORIZON = 5    # days ahead to predict
MIN_TRAINING_ROWS  = 100  # minimum clean rows required to train


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Engineer predictive features from OHLCV data.

    All features at row i use only data up to row i — zero look-ahead.

    Features
    --------
    - Momentum: log-returns at 1 / 3 / 5 / 10 / 20 days
    - RSI(14) and its 5-day change
    - MACD histogram and its 1-day change (momentum acceleration)
    - Bollinger position (0=at lower band, 1=at upper band)
    - Bollinger width (squeeze detector)
    - Volume ratio vs 20-day SMA
    - 20-day annualised rolling volatility
    - Price / SMA20 ratio
    - Price / SMA50 ratio
    """
    # Lazy import avoids circular dependency (ml_signals ← technical ← ml_signals)
    from analysis.technical import (
        compute_rsi, compute_macd, compute_bollinger_bands, compute_sma,
    )

    close = df["Close"].squeeze()
    n = len(close)
    feat = pd.DataFrame(index=df.index)

    # Momentum
    for p in [1, 3, 5, 10, 20]:
        feat[f"ret_{p}d"] = np.log(close / close.shift(p))

    # RSI
    rsi = compute_rsi(df)
    feat["rsi"]        = rsi
    feat["rsi_delta5"] = rsi.diff(5)

    # MACD histogram + acceleration
    _, _, hist = compute_macd(df)
    feat["macd_hist"]     = hist
    feat["macd_hist_chg"] = hist.diff()

    # Bollinger position and width
    if n >= 20:
        upper, middle, lower = compute_bollinger_bands(df)
        band_range = (upper - lower).replace(0, np.nan)
        feat["bb_position"] = (close - lower) / band_range
        feat["bb_width"]    = band_range / middle.replace(0, np.nan)

    # Volume ratio
    if "Volume" in df.columns:
        vol = df["Volume"].squeeze().replace(0, np.nan)
        vol_sma = vol.rolling(20).mean()
        feat["volume_ratio"] = vol / vol_sma

    # Realised volatility (annualised)
    feat["volatility_20"] = close.pct_change().rolling(20).std() * np.sqrt(252)

    # Price / SMA ratios
    if n >= 20:
        feat["price_sma20"] = close / compute_sma(df, 20).replace(0, np.nan)
    if n >= 50:
        feat["price_sma50"] = close / compute_sma(df, 50).replace(0, np.nan)

    return feat


def _build_labels(df: pd.DataFrame, horizon: int = PREDICTION_HORIZON) -> pd.Series:
    """
    Binary label: 1 if close[t + horizon] > close[t], else 0.
    The last `horizon` rows have NaN labels (future unknown).
    """
    close = df["Close"].squeeze()
    future_close = close.shift(-horizon)
    result = pd.Series(np.nan, index=close.index, dtype=float)
    valid = future_close.notna()
    result[valid] = (future_close[valid] > close[valid]).astype(float)
    return result


def train_xgboost_signal(df: pd.DataFrame):
    """
    Train an XGBoost binary classifier on the ticker's historical data
    and return a TechnicalSignal with the predicted probability of a
    5-day price increase.

    Training approach
    -----------------
    • Features: multi-timeframe momentum, RSI, MACD, Bollinger, volume, volatility, SMA ratios
    • Label:    did close[t+5] > close[t]?  (binary, 0/1)
    • Split:    80% training (chronological) / 20% time-series validation
    • Model:    shallow XGBoost (max_depth=3) with L1/L2 regularisation
    • Prediction: on the last available row (no label yet)

    Returns
    -------
    TechnicalSignal or None if xgboost is not installed / insufficient data.
    """
    if not _XGB_OK:
        return None

    # Lazy import to avoid circular dependency
    from analysis.technical import TechnicalSignal

    try:
        features = _build_features(df)
        labels   = _build_labels(df)

        # Merge, drop NaN (this excludes the last HORIZON unlabelled rows)
        combined = pd.concat([features, labels.rename("label")], axis=1).dropna()

        if len(combined) < MIN_TRAINING_ROWS:
            return None

        # Determine which feature columns are available for the latest row
        latest_row = features.iloc[-1]
        valid_cols = [c for c in features.columns
                      if c in combined.columns
                      and not pd.isna(latest_row.get(c, np.nan))]

        if not valid_cols:
            return None

        X_all   = combined[valid_cols].values.astype(np.float32)
        y_all   = combined["label"].values.astype(int)
        X_pred  = latest_row[valid_cols].values.reshape(1, -1).astype(np.float32)

        # Time-series split: first 80% → train, last 20% → validation
        split       = max(30, int(len(X_all) * 0.80))
        X_tr, y_tr  = X_all[:split], y_all[:split]
        X_val, y_val = X_all[split:], y_all[split:]

        model = xgb.XGBClassifier(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.80,
            colsample_bytree=0.75,
            reg_alpha=0.10,
            reg_lambda=1.00,
            random_state=42,
            eval_metric="logloss",
            verbosity=0,
        )
        model.fit(X_tr, y_tr)

        # Validation accuracy on held-out recent data
        val_acc = (
            float((model.predict(X_val) == y_val).mean())
            if len(X_val) > 0 else 0.50
        )

        # Predict probability of price going UP in the next 5 days
        prob_up = float(model.predict_proba(X_pred)[0][1])

    except Exception as exc:
        print(f"[XGBoost] training error: {exc}")
        return None

    # ── Map probability → signal ──────────────────────────────────────────────
    acc_str = f"precisión histórica {val_acc:.0%}"

    if prob_up >= 0.65:
        sig      = "BUY"
        strength = "STRONG" if prob_up >= 0.75 else "MODERATE"
        desc     = (
            f"Probabilidad de subida a 5 días: {prob_up:.0%}. "
            f"({acc_str}, {len(X_all)} muestras de entrenamiento)"
        )
    elif prob_up <= 0.35:
        sig      = "SELL"
        strength = "STRONG" if prob_up <= 0.25 else "MODERATE"
        desc     = (
            f"Probabilidad de subida a 5 días: {prob_up:.0%} — señal bajista. "
            f"({acc_str}, {len(X_all)} muestras)"
        )
    else:
        sig      = "HOLD"
        strength = "WEAK"
        desc     = (
            f"Señal ML neutral — probabilidad de subida {prob_up:.0%}. "
            f"({acc_str})"
        )

    return TechnicalSignal(
        indicator="XGBoost ML",
        value=round(prob_up, 4),
        signal=sig,
        strength=strength,
        description=desc,
    )


# ── 2b. HMM signal ────────────────────────────────────────────────────────────

def train_hmm_signal(df: pd.DataFrame, horizon: int = PREDICTION_HORIZON):
    """
    Fit a 3-state Gaussian HMM on price dynamics and return a TechnicalSignal
    based on the forecast `horizon`-day-ahead probability of being in the
    bullish hidden state.

    Method
    ------
    • Observations: 1-day log-returns and 5-day rolling volatility.
    • Model:        Gaussian HMM with 3 states (Bull / Lateral / Bear),
                    states labelled by mean return.
    • Forecast:     distribution over states at t+horizon  =  post @ T^horizon,
                    where `post` is the posterior at the latest observation
                    and T is the learned transition matrix.

    Returns
    -------
    TechnicalSignal or None if hmmlearn is not installed / insufficient data.
    """
    if not _HMM_OK:
        return None

    # Lazy import to avoid circular dependency
    from analysis.technical import TechnicalSignal

    X = _hmm_observation_matrix(df)
    if X is None:
        return None

    try:
        model, order = _fit_gaussian_hmm(X, n_states=HMM_N_STATES)
        bear_idx = order[0]
        lat_idx  = order[1]
        bull_idx = order[-1]

        # Posterior at the latest observation
        post = model.predict_proba(X)[-1]

        # k-step-ahead state distribution
        T      = model.transmat_
        T_k    = np.linalg.matrix_power(T, max(1, horizon))
        future = post @ T_k

        p_bear = float(future[bear_idx])
        p_lat  = float(future[lat_idx])
        p_bull = float(future[bull_idx])

        # Bullish score in [0, 1]: 0 = bear regime, 0.5 = lateral, 1 = bull
        bullish_score = float(np.clip(p_bull + 0.5 * p_lat, 0.0, 1.0))
    except Exception as exc:
        print(f"[HMM] signal training error: {exc}")
        return None

    # ── Map state distribution → signal ───────────────────────────────────────
    if p_bull >= 0.55 and p_bull > p_bear:
        sig      = "BUY"
        strength = "STRONG" if p_bull >= 0.70 else "MODERATE"
        desc     = (
            f"HMM: probabilidad de régimen alcista a {horizon} días: {p_bull:.0%} "
            f"(bajista {p_bear:.0%}, lateral {p_lat:.0%})."
        )
    elif p_bear >= 0.55 and p_bear > p_bull:
        sig      = "SELL"
        strength = "STRONG" if p_bear >= 0.70 else "MODERATE"
        desc     = (
            f"HMM: probabilidad de régimen bajista a {horizon} días: {p_bear:.0%} "
            f"(alcista {p_bull:.0%}, lateral {p_lat:.0%})."
        )
    else:
        sig      = "HOLD"
        strength = "WEAK"
        desc     = (
            f"HMM: régimen mixto a {horizon} días — alcista {p_bull:.0%}, "
            f"bajista {p_bear:.0%}, lateral {p_lat:.0%}."
        )

    return TechnicalSignal(
        indicator="HMM Régimen",
        value=round(bullish_score, 4),
        signal=sig,
        strength=strength,
        description=desc,
    )


# ── 3. Overall probability score ──────────────────────────────────────────────

def compute_signal_probability(signals, market_context: MarketContext) -> float:
    """
    Compute a regime-aware 0-1 probability that the current overall signal
    will be correct.

    Components
    ----------
    raw_prob   : indicator consensus  (buy weight vs sell weight)
    reg_boost  : regime alignment bonus/penalty
    vol_penalty: high volatility reduces edge

    Returns 0.5 for a perfectly neutral market with no edge.
    >0.65 → meaningful buy probability  |  <0.35 → meaningful sell probability.
    """
    if not signals:
        return 0.50

    WEIGHTS = {"STRONG": 3.0, "MODERATE": 2.0, "WEAK": 1.0}

    buy_w  = sum(WEIGHTS.get(s.strength, 1.0) for s in signals if s.signal == "BUY")
    sell_w = sum(WEIGHTS.get(s.strength, 1.0) for s in signals if s.signal == "SELL")
    hold_w = sum(WEIGHTS.get(s.strength, 1.0) for s in signals if s.signal == "HOLD")
    total  = buy_w + sell_w + hold_w

    if total == 0:
        return 0.50

    # Maps (buy_w - sell_w) ∈ [-total, +total] → [0, 1]
    raw_prob = (buy_w - sell_w + total) / (2.0 * total)

    # Regime alignment
    conf = market_context.regime_confidence
    if market_context.regime == "BULL":
        reg_boost = (+0.06 * conf) if raw_prob > 0.5 else (-0.04 * conf)
    elif market_context.regime == "BEAR":
        # Buying against a bear regime gets a larger penalty
        reg_boost = (-0.06 * conf) if raw_prob < 0.5 else (-0.09 * conf)
    else:
        reg_boost = 0.0

    # Volatility reduces the edge for any direction
    vol_penalty = market_context.risk_score * 0.08

    return float(np.clip(raw_prob + reg_boost - vol_penalty, 0.05, 0.95))
