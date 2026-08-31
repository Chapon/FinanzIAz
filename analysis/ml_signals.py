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

  5. compute_signal_probability  — combines the regime-weighted indicator
     consensus with volatility risk into a single 0-1 probability score.
     (Regime alignment is folded into the per-indicator weights, T04.)
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, TypeVar

import numpy as np
import pandas as pd

from config.constants import (
    RSI_HIGH,
    RSI_LOW,
    RSI_OVERBOUGHT,
    RSI_OVERBOUGHT_EXTREME,
    RSI_OVERSOLD,
    RSI_OVERSOLD_EXTREME,
    SIGNAL_STRENGTH_WEIGHTS,
)
from config.logging_config import get_logger

if TYPE_CHECKING:
    # Only used as a return-type annotation. The actual ``TechnicalSignal``
    # is imported lazily inside the functions that build one, to avoid a
    # circular import between analysis.technical and analysis.ml_signals.
    from analysis.technical import TechnicalSignal

log = get_logger(__name__)
from dataclasses import dataclass

# ── Optional XGBoost ──────────────────────────────────────────────────────────
try:
    import xgboost as xgb

    _XGB_OK = True
except ImportError:
    _XGB_OK = False


# ── Optional sklearn isotonic calibration ────────────────────────────────────
# XGBoost ships sklearn as a transitive dep, so this should never fail in
# practice — but the wrapper keeps the module importable on a broken env.
try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import TimeSeriesSplit

    _CALIBRATION_OK = True
except ImportError:
    _CALIBRATION_OK = False

# ── Optional sklearn linear models (T05 stacking meta-learner) ───────────────
try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    _SKLEARN_LINEAR_OK = True
except ImportError:
    _SKLEARN_LINEAR_OK = False

# Minimum size of the validation slice required to run isotonic calibration.
# Below this, the calibrator overfits the val set and the calibration curve
# becomes noisy — fallback to the uncalibrated model is safer. This is
# independent of MIN_TRAINING_ROWS (which gates training at all).
MIN_CALIBRATION_ROWS = 100

# ── Walk-forward validation (T03) ─────────────────────────────────────────────
# Number of expanding-window folds used to estimate val accuracy as a
# distribution (mean ± std) rather than a single 80/20 point estimate.
N_WALKFORWARD_FOLDS = 5
# A purge gap of PREDICTION_HORIZON rows is dropped from the end of each train
# fold before its val fold, so the HORIZON-day-ahead labels of the last train
# rows can't leak into the validation block (overlapping-label leakage).
# (PREDICTION_HORIZON is defined further down; the gap is wired at call time.)
# If the cross-fold std exceeds this, the model is flagged as unstable: the
# val accuracy depends heavily on which slice of history it was measured on.
#
# Calibrado con la distribución REAL (tarea 25a): medido sobre los 134 frames
# 2y/1d del cache vivo, el std entre folds tiene mediana **0.0760** y decil
# superior **0.1105**. O sea que el 0.08 original estaba clavado *en la mediana*
# y disparaba en 55/134 = **41% de los tickers de cada scan** — cientos de líneas
# WARNING que no discriminaban nada (un umbral en la mediana, por construcción,
# marca a la mitad de la población) y que enterraban los errores reales.
# 0.12 cae en la cola (dispara en 6/134 = 4.5%), así que el warning vuelve a
# significar "este ticker es un outlier de inestabilidad".
#
# Nota: la inestabilidad de fondo NO es un bug a arreglar — es inherente a una
# señal sin alpha (tarea 9: AUC OOS 0.498; el val_acc medio de estos mismos 134
# tickers da 0.5076, un coin flip). Por eso esto es higiene de log y no una
# alerta de calidad del modelo.
WALKFORWARD_STD_WARN = 0.12
# Below this many labelled rows the folds become too small to be meaningful
# (single-class train folds, ~30-row fits), so we fall back to the single
# 80/20 split + isotonic calibration path from T02.
MIN_WALKFORWARD_ROWS = 250


# ── Bounded LRU helpers (shared by the in-memory model caches) ───────────────
# Eviction happens one entry at a time, at the *insertion* site. The previous
# implementation cleared the whole cache from inside the key-building function,
# which is what stopped these caches from ever surviving a scan (T24): a single
# overflow threw away every warm model mid-scan, including the ones the other
# account had just paid to train.


# Los helpers LRU son genericos en el tipo del VALOR: los dict son invariantes,
# asi que un OrderedDict[str, tuple] no encaja en un parametro pedido como
# OrderedDict[str, object] aunque tuple sea un object.
_V = TypeVar("_V")


def _lru_get(cache: OrderedDict[str, _V], key: str, default=None):
    """Read ``key``, marking it most-recently-used. ``default`` when absent."""
    if not key or key not in cache:
        return default
    cache.move_to_end(key)
    return cache[key]


def _lru_put(cache: OrderedDict[str, _V], key: str, value: _V, max_entries: int) -> None:
    """Store ``key`` and drop the least-recently-used entries over capacity."""
    if not key:
        return
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > max_entries:
        cache.popitem(last=False)


# ── XGBoost training-result cache (in-memory only) ───────────────────────────
# Keyed by a hash of (trainable close-tail, feature-cols, sample-count, last
# trainable bar). Values are tuples of (model, val_acc, train_acc, val_std).
# ``val_acc`` is the mean cross-fold validation accuracy and ``val_std`` its
# dispersion across the walk-forward folds (0.0 when the single-split fallback
# path was used).
#
# Capacity (T24): the cache is module-level and shared by every caller, so it
# has to hold the union of what the scans touch or it thrashes. The live DB has
# 131 distinct tickers across the two accounts (52+5 and 128+10), and a cached
# entry measures ~633 KiB pickled → 192 entries ≈ 119 MiB, which covers the
# whole scan universe plus headroom for the ad-hoc analyses of the Analysis and
# Leads tabs. The old cap of 64 could not even hold one account's scan.
_XGB_CACHE: OrderedDict[str, tuple] = OrderedDict()
_XGB_CACHE_MAX = 192


def _xgb_cache_key(df: pd.DataFrame, feature_cols: list[str], n_samples: int) -> str:
    """Stable fingerprint of the *trainable* frame + feature spec.

    Only the rows that survive the label ``dropna`` in
    :func:`train_xgboost_signal` are hashed, i.e. everything up to
    ``-PREDICTION_HORIZON``. The trailing rows carry no label — and the very
    last one is the **partial bar of the open session**, whose Close ticks all
    day and comes back different from every re-fetch — so folding them into the
    key made it change on data the model never trains on, missing on every scan
    while producing a byte-identical model (T24).

    The fingerprint still moves when the training data genuinely changes: a new
    daily bar shifts both ``n_samples`` and the trainable window (so the model
    is retrained once per session, as intended), and a retroactive revision of
    the history — a split or dividend adjustment — rewrites the closes hashed.

    The digest covers the *whole* trainable series, not just its tail: the
    previous 20-row tail could not see a correction further back, which would
    have served a model trained on history that no longer exists. Measured at
    ~30 µs for a 2y frame against ~373 ms for the walk-forward fit it guards,
    so the stronger guarantee costs ~0.01% of what it saves.
    """
    if "Close" not in df.columns or len(df) <= PREDICTION_HORIZON:
        return ""
    trainable = df["Close"].iloc[:-PREDICTION_HORIZON]
    if trainable.empty:
        return ""
    try:
        closes = np.ascontiguousarray(trainable.to_numpy(dtype="float64")).round(4)
    except (TypeError, ValueError):
        # Non-numeric closes: better no caching than a key that can't tell two
        # different training sets apart.
        return ""
    payload = f"{sorted(feature_cols)}|{n_samples}|{trainable.index[-1]}".encode()
    return hashlib.sha256(closes.tobytes() + payload).hexdigest()[:16]


def clear_ml_cache() -> None:
    """Public helper to flush the cached XGBoost + stacking models (tests)."""
    _XGB_CACHE.clear()
    _STACK_CACHE.clear()


# ── Telemetría de entrenamiento (tarea 25a) ──────────────────────────────────
# El walk-forward logueaba una línea INFO por ticker entrenado. Con el cache
# arreglado (tarea 24) eso ya bajó a 1×/día/ticker, pero el primer scan del día
# seguía escupiendo ~131 líneas. Se acumulan acá y el engine emite **una** línea
# resumen por scan, al estilo de la telemetría OPS1(c).
#
# El acumulador cuenta entrenamientos *desde el último drain*, así que un
# análisis ad-hoc de la pestaña Analysis o de Leads entre dos scans se suma al
# resumen del scan siguiente. Es telemetría de log, no contabilidad: preferible
# a acoplar ml_signals con el ciclo de vida del scan.
_training_lock = threading.Lock()
_training_tally: dict[str, float] = {"n": 0, "val_acc_sum": 0.0, "unstable": 0}


def _note_training(val_acc: float, val_std: float) -> None:
    """Registra un entrenamiento walk-forward para el resumen por scan."""
    with _training_lock:
        _training_tally["n"] += 1
        _training_tally["val_acc_sum"] += val_acc
        if val_std > WALKFORWARD_STD_WARN:
            _training_tally["unstable"] += 1


def drain_training_summary() -> str | None:
    """Devuelve el resumen de entrenamientos acumulados y resetea el contador.

    ``None`` cuando no se entrenó nada — el caso normal a partir del segundo
    scan del día, ahora que el cache sobrevive (tarea 24).
    """
    with _training_lock:
        n = int(_training_tally["n"])
        if n == 0:
            return None
        val_acc_mean = _training_tally["val_acc_sum"] / n
        unstable = int(_training_tally["unstable"])
        _training_tally.update({"n": 0, "val_acc_sum": 0.0, "unstable": 0})
    return f"XGB entrenados={n} val_acc medio={val_acc_mean:.0%} inestables={unstable}"


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

    regime: str  # "BULL" | "BEAR" | "LATERAL"
    regime_confidence: float  # 0–1 (50% = barely classifiable)
    volatility_level: str  # "LOW" | "MEDIUM" | "HIGH"
    annual_volatility: float  # current conditional σ (annualised %)
    risk_score: float  # 0–1  (0 = low risk, 1 = high risk)
    # ── Forward-looking volatility (populated by GARCH when available) ────
    forecast_volatility: float | None = None  # h-day-ahead σ (annualised %)
    volatility_source: str = "EWMA"  # "GARCH" | "EWMA"

    # ── display helpers ───────────────────────────────────────────────────────

    @property
    def regime_es(self) -> str:
        return {"BULL": "Alcista", "BEAR": "Bajista", "LATERAL": "Lateral"}.get(self.regime, self.regime)

    @property
    def regime_color(self) -> str:
        return {"BULL": "#22c55e", "BEAR": "#f87171", "LATERAL": "#fbbf24"}.get(self.regime, "#fbbf24")

    @property
    def regime_icon(self) -> str:
        return {"BULL": "▲", "BEAR": "▼", "LATERAL": "→"}.get(self.regime, "→")

    @property
    def volatility_es(self) -> str:
        return {"LOW": "Baja", "MEDIUM": "Media", "HIGH": "Alta"}.get(self.volatility_level, "—")

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
    ret_5d = float(close.pct_change(5).iloc[-1]) if n >= 6 else 0.0
    ret_20d = float(close.pct_change(20).iloc[-1]) if n >= 21 else ret_5d
    ret_60d = float(close.pct_change(60).iloc[-1]) if n >= 61 else ret_20d

    # SMA positions
    def _safe_sma(period):
        if n < period:
            return None
        v = float(close.rolling(period).mean().iloc[-1])
        return None if np.isnan(v) else v

    sma50_val = _safe_sma(50)
    sma200_val = _safe_sma(200)
    above_sma50 = (current > sma50_val) if sma50_val is not None else None
    above_sma200 = (current > sma200_val) if sma200_val is not None else None

    # ── Weighted scoring ──────────────────────────────────────────────────────
    bull = 0.0
    bear = 0.0

    # 5-day momentum (weight 1)
    if ret_5d > 0.020:
        bull += 1.0
    elif ret_5d < -0.020:
        bear += 1.0
    elif ret_5d > 0.005:
        bull += 0.4
    elif ret_5d < -0.005:
        bear += 0.4

    # 20-day momentum (weight 2)
    if ret_20d > 0.050:
        bull += 2.0
    elif ret_20d < -0.050:
        bear += 2.0
    elif ret_20d > 0.010:
        bull += 0.8
    elif ret_20d < -0.010:
        bear += 0.8

    # 60-day momentum (weight 2)
    if ret_60d > 0.120:
        bull += 2.0
    elif ret_60d < -0.120:
        bear += 2.0
    elif ret_60d > 0.030:
        bull += 1.0
    elif ret_60d < -0.030:
        bear += 1.0

    # SMA positions (weight 1.5 each)
    if above_sma50 is True:
        bull += 1.5
    elif above_sma50 is False:
        bear += 1.5

    if above_sma200 is True:
        bull += 1.5
    elif above_sma200 is False:
        bear += 1.5

    total_evidence = bull + bear
    if total_evidence == 0:
        regime, confidence = "LATERAL", 0.50
    else:
        balance = (bull - bear) / total_evidence  # –1 .. +1
        if balance >= 0.25:
            regime = "BULL"
            confidence = 0.50 + balance * 0.45
        elif balance <= -0.25:
            regime = "BEAR"
            confidence = 0.50 + abs(balance) * 0.45
        else:
            regime = "LATERAL"
            confidence = 0.50 + (0.25 - abs(balance)) * 0.5

    # ── Volatility (GARCH forecast if available, EWMA fallback) ──────────────
    from analysis.garch_signals import compute_annual_volatility

    current_vol, forecast_vol, vol_source = compute_annual_volatility(df)
    annual_vol = current_vol
    vol_for_risk = forecast_vol  # forward-looking

    if vol_for_risk < 15:
        vol_level = "LOW"
    elif vol_for_risk < 30:
        vol_level = "MEDIUM"
    else:
        vol_level = "HIGH"

    # ── Risk score ────────────────────────────────────────────────────────────
    vol_risk = min(vol_for_risk / 60.0, 1.0)
    regime_risk = {"BEAR": 0.70, "LATERAL": 0.45, "BULL": 0.25}[regime]
    risk_score = float(np.clip(0.55 * vol_risk + 0.45 * regime_risk, 0.0, 1.0))

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

HMM_MIN_ROWS = 80  # minimum clean rows required to fit the HMM
HMM_N_STATES = 3  # Bull / Lateral / Bear


def _hmm_observation_matrix(df: pd.DataFrame) -> np.ndarray | None:
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
    ret = np.log(close / close.shift(1))
    vol = ret.rolling(5).std()
    X = pd.concat([ret.rename("ret"), vol.rename("vol")], axis=1).dropna()
    if len(X) < HMM_MIN_ROWS:
        return None
    Xv = X.values.astype(np.float64)
    # Standardize each feature to ~O(1). Returns (~1e-3) and 5-day vol (~1e-2)
    # live at very different, tiny scales; left raw they push the Gaussian
    # covariances toward singularity — the source of the "covars must be
    # positive-definite" failures and the negative log-likelihood deltas
    # ("Model is not converging"). z-scoring is a monotonic per-column
    # transform, so it does NOT affect the by-mean-return state ordering used
    # downstream. All callers fit and call predict_proba on this same matrix.
    mu = Xv.mean(axis=0)
    sd = Xv.std(axis=0)
    sd[sd < 1e-12] = 1.0  # guard against a (near-)constant column
    return (Xv - mu) / sd


def _fit_gaussian_hmm(X: np.ndarray, n_states: int = HMM_N_STATES) -> tuple[Any, list[int]] | None:
    """
    Fit a Gaussian HMM and return (model, state_order), where state_order
    lists state indices sorted ascending by mean log-return.

    state_order[0] = lowest mean return  → BEAR
    state_order[-1] = highest mean return → BULL
    """

    # Diagonal covariance is far more numerically robust than "full" for the
    # two tiny-scale features here: with "full", a state that collapses onto a
    # few near-identical observations can drive its covariance matrix to be
    # non-positive-definite (the "covars must be symmetric, positive-definite"
    # error). min_covar floors the variance so that can't happen. On the
    # standardized observations these defaults converge cleanly.
    def _make(cov_type: str, min_covar: float):
        return _hmm.GaussianHMM(
            n_components=n_states,
            covariance_type=cov_type,
            n_iter=200,
            tol=1e-3,
            min_covar=min_covar,
            random_state=42,
        )

    model = _make("diag", 1e-3)
    try:
        model.fit(X)
    except (ValueError, np.linalg.LinAlgError):
        # Last-resort retry with a heavier variance floor before giving up.
        model = _make("diag", 1e-2)
        model.fit(X)
    state_order = list(np.argsort(model.means_[:, 0]))  # mean of the return feature
    return model, state_order


def detect_market_regime_hmm(df: pd.DataFrame) -> MarketContext | None:
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
        lat_idx = order[1]
        bull_idx = order[-1]

        # Posterior state distribution at the most recent observation
        post = model.predict_proba(X)[-1]

        p_bear = float(post[bear_idx])
        p_lat = float(post[lat_idx])
        p_bull = float(post[bull_idx])

        top = int(np.argmax([p_bear, p_lat, p_bull]))
        if top == 2:
            regime, confidence = "BULL", p_bull
        elif top == 0:
            regime, confidence = "BEAR", p_bear
        else:
            regime, confidence = "LATERAL", p_lat
    except Exception as exc:
        log.warning("HMM regime detection error: %s", exc)
        return None

    # ── Volatility (GARCH forecast if available, EWMA fallback) ──────────────
    from analysis.garch_signals import compute_annual_volatility

    current_vol, forecast_vol, vol_source = compute_annual_volatility(df)
    annual_vol = current_vol
    vol_for_risk = forecast_vol  # forward-looking

    if vol_for_risk < 15:
        vol_level = "LOW"
    elif vol_for_risk < 30:
        vol_level = "MEDIUM"
    else:
        vol_level = "HIGH"

    # ── Risk score ────────────────────────────────────────────────────────────
    vol_risk = min(vol_for_risk / 60.0, 1.0)
    regime_risk = {"BEAR": 0.70, "LATERAL": 0.45, "BULL": 0.25}[regime]
    risk_score = float(np.clip(0.55 * vol_risk + 0.45 * regime_risk, 0.0, 1.0))

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

PREDICTION_HORIZON = 5  # days ahead to predict
MIN_TRAINING_ROWS = 100  # minimum clean rows required to train


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
        compute_bollinger_bands,
        compute_macd,
        compute_rsi,
        compute_sma,
    )

    close = df["Close"].squeeze()
    n = len(close)
    feat = pd.DataFrame(index=df.index)

    # Momentum
    for p in [1, 3, 5, 10, 20]:
        feat[f"ret_{p}d"] = np.log(close / close.shift(p))

    # RSI
    rsi = compute_rsi(df)
    feat["rsi"] = rsi
    feat["rsi_delta5"] = rsi.diff(5)

    # MACD histogram + acceleration
    _, _, hist = compute_macd(df)
    feat["macd_hist"] = hist
    feat["macd_hist_chg"] = hist.diff()

    # Bollinger position and width
    if n >= 20:
        upper, middle, lower = compute_bollinger_bands(df)
        band_range = (upper - lower).replace(0, np.nan)
        feat["bb_position"] = (close - lower) / band_range
        feat["bb_width"] = band_range / middle.replace(0, np.nan)

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


# ── Training helpers (shared by the single-split and walk-forward paths) ──────


def _make_raw_xgb() -> xgb.XGBClassifier:
    """Build the shallow, regularised XGBoost classifier used everywhere.

    Centralised so the single-split path (T02) and the walk-forward path
    (T03) train identical architectures — the only thing that differs between
    them is *how* the data is sliced for validation and calibration.
    """
    return xgb.XGBClassifier(
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


def _build_calibrator(estimator, cv):
    """Construct a CalibratedClassifierCV across sklearn API versions.

    ``cv`` is either the string ``"prefit"`` (T02 — ``estimator`` is already
    fitted and only the isotonic regressor is learned on the held-out slice)
    or a ``TimeSeriesSplit`` (T03 — ``estimator`` is an unfitted template that
    the calibrator clones and refits on each fold's train window).

    sklearn ≥ 1.2 uses ``estimator=``; older versions use ``base_estimator=``.
    """
    try:
        return CalibratedClassifierCV(estimator=estimator, cv=cv, method="isotonic")
    except TypeError:
        return CalibratedClassifierCV(base_estimator=estimator, cv=cv, method="isotonic")


def _walkforward_val_scores(
    X: np.ndarray,
    y: np.ndarray,
    n_splits: int,
    gap: int,
) -> list[float]:
    """Expanding-window walk-forward validation accuracies, one per fold.

    Each fold fits a fresh XGB on the train window and scores it on the
    immediately-following val block, with ``gap`` rows purged in between so
    the HORIZON-day labels of the last train rows don't overlap (and thus
    leak into) the val block.

    Folds with a degenerate train window (<30 rows, or single-class) are
    skipped — they'd produce a meaningless accuracy that would distort the
    mean/std. Returns ``[]`` if CV can't run at all.
    """
    if not _CALIBRATION_OK:  # sklearn gates TimeSeriesSplit too
        return []
    try:
        tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap)
        scores: list[float] = []
        for tr_idx, val_idx in tscv.split(X):
            if len(tr_idx) < 30 or len(val_idx) == 0:
                continue
            if len(np.unique(y[tr_idx])) < 2:
                continue
            m = _make_raw_xgb()
            m.fit(X[tr_idx], y[tr_idx])
            scores.append(float((m.predict(X[val_idx]) == y[val_idx]).mean()))
        return scores
    except Exception as exc:  # pragma: no cover - sklearn version guard
        log.warning("Walk-forward CV error: %s", exc)
        return []


def _train_single_split(X_all: np.ndarray, y_all: np.ndarray, valid_cols: list[str]):
    """Legacy single 80/20 split + isotonic calibration (T02 path).

    Used for short histories (< MIN_WALKFORWARD_ROWS) where walk-forward folds
    would be too small to be meaningful. Returns
    ``(model, val_acc, train_acc, val_std)`` with ``val_std = 0.0`` (a single
    split yields no dispersion estimate).
    """
    split = max(30, int(len(X_all) * 0.80))
    X_tr, y_tr = X_all[:split], y_all[:split]
    X_val, y_val = X_all[split:], y_all[split:]

    raw_model = _make_raw_xgb()
    raw_model.fit(X_tr, y_tr)

    # Isotonic calibration on the val slice — re-scales predict_proba so that
    # "model says 65%" matches the empirical 5d-up rate on the val set.
    n_val = len(X_val)
    n_classes_val = len(np.unique(y_val)) if n_val > 0 else 0
    if _CALIBRATION_OK and n_val >= MIN_CALIBRATION_ROWS and n_classes_val >= 2:
        try:
            calibrator = _build_calibrator(raw_model, cv="prefit")
            calibrator.fit(X_val, y_val)
            model = calibrator
            log.debug("XGBoost: isotonic calibration applied on %d val samples.", n_val)
        except Exception as exc:
            log.warning("XGBoost calibration failed (%s); using raw model.", exc)
            model = raw_model
    else:
        if not _CALIBRATION_OK:
            log.info("XGBoost: sklearn unavailable, calibration skipped.")
        elif n_val < MIN_CALIBRATION_ROWS:
            log.info(
                "XGBoost: val set too small (%d < %d) for isotonic calibration; using raw model.",
                n_val,
                MIN_CALIBRATION_ROWS,
            )
        elif n_classes_val < 2:
            log.info("XGBoost: val set has only one class; calibration skipped, using raw model.")
        model = raw_model

    train_acc = float((model.predict(X_tr) == y_tr).mean()) if len(X_tr) > 0 else 0.50
    val_acc = float((model.predict(X_val) == y_val).mean()) if len(X_val) > 0 else 0.50
    overfit_gap = train_acc - val_acc
    if overfit_gap > 0.20:
        log.info(
            "XGBoost: large train-val gap (%.0f%% vs %.0f%%); model may be overfitting.",
            train_acc * 100,
            val_acc * 100,
        )
    _log_top_features(raw_model, valid_cols)
    return model, val_acc, train_acc, 0.0


def _train_walkforward(X_all: np.ndarray, y_all: np.ndarray, valid_cols: list[str]):
    """Walk-forward validation + CV-calibrated final model (T03 path).

    Two distinct uses of the same TimeSeriesSplit:

    1. **Reporting** — fit a fresh XGB per fold and collect val accuracies, so
       we can report ``val_acc = mean ± std`` instead of a single lucky point.
       A std above WALKFORWARD_STD_WARN is logged as an instability warning.

    2. **Final model** — a CalibratedClassifierCV with the *same* walk-forward
       cv refits the XGB on each fold and learns an isotonic regressor on each
       fold's hold-out, then averages. The base estimator therefore sees the
       full history across folds (no single 20% block held out forever) while
       calibration stays leakage-free.

    Returns ``(model, val_acc, train_acc, val_std)``. Falls back to
    :func:`_train_single_split` if the folds are unusable.
    """
    scores = _walkforward_val_scores(X_all, y_all, N_WALKFORWARD_FOLDS, PREDICTION_HORIZON)
    if not scores:
        log.info("XGBoost: walk-forward folds unusable; falling back to single split.")
        return _train_single_split(X_all, y_all, valid_cols)

    val_acc = float(np.mean(scores))
    val_std = float(np.std(scores))
    # DEBUG y no INFO (tarea 25a): esta línea salía una vez por ticker entrenado
    # y era la mitad del volumen del log. El dato agregado va en el resumen por
    # scan (``drain_training_summary``); el detalle per-ticker queda para cuando
    # se está diagnosticando un ticker puntual y se sube el nivel a DEBUG.
    log.debug(
        "XGBoost walk-forward: val_acc=%.0f%% ± %.0f%% over %d folds.",
        val_acc * 100,
        val_std * 100,
        len(scores),
    )
    _note_training(val_acc, val_std)
    if val_std > WALKFORWARD_STD_WARN:
        # ``%.1f`` y no ``%.0f``: la comparación usa el valor sin redondear, así
        # que con val_std=8.4% el mensaje imprimía la desigualdad falsa
        # "std 8% > 8%" y confundía el diagnóstico en el log.
        log.warning(
            "XGBoost: unstable model — val_acc std %.1f%% > %.1f%% across folds; "
            "accuracy depends heavily on the validation window.",
            val_std * 100,
            WALKFORWARD_STD_WARN * 100,
        )

    # Final model: XGB refit per fold inside the calibrator, isotonic on each
    # fold's hold-out, averaged. Effectively trained over all history.
    tscv = TimeSeriesSplit(n_splits=N_WALKFORWARD_FOLDS, gap=PREDICTION_HORIZON)
    try:
        model = _build_calibrator(_make_raw_xgb(), cv=tscv)
        model.fit(X_all, y_all)
        _log_top_features(model, valid_cols)
    except Exception as exc:
        # CV calibration can fail on pathological splits (e.g. a fold with a
        # single class). Fall back to a raw XGB fit on all data — we still
        # keep the honest walk-forward val_acc ± std from above.
        log.warning("XGBoost CV calibration failed (%s); using raw model on all data.", exc)
        model = _make_raw_xgb()
        model.fit(X_all, y_all)
        _log_top_features(model, valid_cols)

    train_acc = float((model.predict(X_all) == y_all).mean())
    return model, val_acc, train_acc, val_std


def _log_top_features(model, valid_cols: list[str]) -> None:
    """Log the top-3 feature importances, pulled from the raw XGB.

    A CalibratedClassifierCV wrapper doesn't expose ``feature_importances_``
    directly; dig out an underlying fitted estimator when present.
    """
    try:
        raw = model
        if hasattr(model, "calibrated_classifiers_") and model.calibrated_classifiers_:
            inner = getattr(model.calibrated_classifiers_[0], "estimator", None)
            raw = inner if inner is not None else model
        importances = getattr(raw, "feature_importances_", None)
        if importances is None:
            return
        top = sorted(
            zip(valid_cols, importances, strict=False),
            key=lambda kv: kv[1],
            reverse=True,
        )[:3]
        log.debug("XGBoost top features: %s", top)
    except Exception:  # pragma: no cover - logging is best-effort
        pass


def train_xgboost_signal(df: pd.DataFrame) -> TechnicalSignal | None:
    """
    Train an XGBoost binary classifier on the ticker's historical data
    and return a TechnicalSignal with the predicted probability of a
    5-day price increase.

    Training approach
    -----------------
    • Features: multi-timeframe momentum, RSI, MACD, Bollinger, volume, volatility, SMA ratios
    • Label:    did close[t+5] > close[t]?  (binary, 0/1)
    • Validation: walk-forward (expanding-window TimeSeriesSplit, 5 folds,
                  PREDICTION_HORIZON-day purge gap) → val_acc reported as
                  mean ± std. Short histories (< MIN_WALKFORWARD_ROWS) fall
                  back to a single 80/20 split.
    • Model:    shallow XGBoost (max_depth=3) with L1/L2 regularisation,
                isotonic-calibrated. Final model is refit across all folds.
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
        labels = _build_labels(df)

        # Merge, drop NaN (this excludes the last HORIZON unlabelled rows)
        combined = pd.concat([features, labels.rename("label")], axis=1).dropna()

        if len(combined) < MIN_TRAINING_ROWS:
            return None

        # Determine which feature columns are available for the latest row
        latest_row = features.iloc[-1]
        valid_cols = [
            c for c in features.columns if c in combined.columns and not pd.isna(latest_row.get(c, np.nan))
        ]

        if not valid_cols:
            return None

        X_all = combined[valid_cols].values.astype(np.float32)
        y_all = combined["label"].values.astype(int)
        X_pred = latest_row[valid_cols].values.reshape(1, -1).astype(np.float32)

        # Reuse a previously trained model if the input fingerprint matches.
        # The fingerprint covers only the rows that actually train the model
        # (see ``_xgb_cache_key``), so repeated scans and UI refreshes during
        # the same session hit the cache instead of retraining on data that is
        # identical everywhere the model looks.
        cache_key = _xgb_cache_key(df, valid_cols, len(combined))
        cached = _lru_get(_XGB_CACHE, cache_key)
        if cached is not None:
            model, val_acc, train_acc, val_std = cached
        else:
            # Walk-forward validation (T03) when there's enough history for the
            # folds to be meaningful; otherwise the single 80/20 split (T02).
            if _CALIBRATION_OK and len(X_all) >= MIN_WALKFORWARD_ROWS and len(np.unique(y_all)) >= 2:
                model, val_acc, train_acc, val_std = _train_walkforward(X_all, y_all, valid_cols)
            else:
                model, val_acc, train_acc, val_std = _train_single_split(X_all, y_all, valid_cols)

            _lru_put(_XGB_CACHE, cache_key, (model, val_acc, train_acc, val_std), _XGB_CACHE_MAX)

        # Predict probability of price going UP in the next 5 days. Works
        # identically against both raw XGBClassifier and CalibratedClassifierCV
        # — both expose ``predict_proba`` returning [[p_down, p_up]].
        prob_up = float(model.predict_proba(X_pred)[0][1])

    except Exception as exc:
        log.warning("XGBoost training error: %s", exc)
        return None

    # ── Map probability → signal ──────────────────────────────────────────────
    # Walk-forward path reports dispersion (± std); the single-split fallback
    # has val_std == 0.0 and shows just the point estimate.
    if val_std > 0:
        acc_str = f"precisión histórica {val_acc:.0%} ± {val_std:.0%}"
    else:
        acc_str = f"precisión histórica {val_acc:.0%}"

    if prob_up >= 0.65:
        sig = "BUY"
        strength = "STRONG" if prob_up >= 0.75 else "MODERATE"
        desc = (
            f"Probabilidad de subida a 5 días: {prob_up:.0%}. "
            f"({acc_str}, {len(X_all)} muestras de entrenamiento)"
        )
    elif prob_up <= 0.35:
        sig = "SELL"
        strength = "STRONG" if prob_up <= 0.25 else "MODERATE"
        desc = (
            f"Probabilidad de subida a 5 días: {prob_up:.0%} — señal bajista. "
            f"({acc_str}, {len(X_all)} muestras)"
        )
    else:
        sig = "HOLD"
        strength = "WEAK"
        desc = f"Señal ML neutral — probabilidad de subida {prob_up:.0%}. ({acc_str})"

    return TechnicalSignal(
        indicator="XGBoost ML",
        value=round(prob_up, 4),
        signal=sig,
        strength=strength,
        description=desc,
    )


# ── 2b. HMM signal ────────────────────────────────────────────────────────────


def train_hmm_signal(df: pd.DataFrame, horizon: int = PREDICTION_HORIZON) -> TechnicalSignal | None:
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
        lat_idx = order[1]
        bull_idx = order[-1]

        # Posterior at the latest observation
        post = model.predict_proba(X)[-1]

        # k-step-ahead state distribution
        T = model.transmat_
        T_k = np.linalg.matrix_power(T, max(1, horizon))
        future = post @ T_k

        p_bear = float(future[bear_idx])
        p_lat = float(future[lat_idx])
        p_bull = float(future[bull_idx])

        # Bullish score in [0, 1]: 0 = bear regime, 0.5 = lateral, 1 = bull
        bullish_score = float(np.clip(p_bull + 0.5 * p_lat, 0.0, 1.0))
    except Exception as exc:
        log.warning("HMM signal training error: %s", exc)
        return None

    # ── Map state distribution → signal ───────────────────────────────────────
    if p_bull >= 0.55 and p_bull > p_bear:
        sig = "BUY"
        strength = "STRONG" if p_bull >= 0.70 else "MODERATE"
        desc = (
            f"HMM: probabilidad de régimen alcista a {horizon} días: {p_bull:.0%} "
            f"(bajista {p_bear:.0%}, lateral {p_lat:.0%})."
        )
    elif p_bear >= 0.55 and p_bear > p_bull:
        sig = "SELL"
        strength = "STRONG" if p_bear >= 0.70 else "MODERATE"
        desc = (
            f"HMM: probabilidad de régimen bajista a {horizon} días: {p_bear:.0%} "
            f"(alcista {p_bull:.0%}, lateral {p_lat:.0%})."
        )
    else:
        sig = "HOLD"
        strength = "WEAK"
        desc = (
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
    raw_prob   : regime-weighted indicator consensus (buy weight vs sell weight)
    vol_penalty: high volatility reduces edge

    The regime tilt now lives *inside* the weights (T04): each signal is
    weighted by ``regime_adjusted_weight``, so a MACD crossover counts more in
    a trending market and an oversold RSI counts more in a range. This replaces
    the old additive ``reg_boost`` term, which double-counted regime once the
    weights themselves became regime-aware. Only ``vol_penalty`` remains as a
    standalone adjustment.

    Returns 0.5 for a perfectly neutral market with no edge.
    >0.65 → meaningful buy probability  |  <0.35 → meaningful sell probability.
    """
    if not signals:
        return 0.50

    # Lazy import avoids the circular dependency (technical ← ml_signals).
    from analysis.technical import regime_adjusted_weight

    regime = market_context.regime if market_context is not None else None

    def _w(s) -> float:
        return regime_adjusted_weight(s.indicator, s.strength, regime)

    buy_w = sum(_w(s) for s in signals if s.signal == "BUY")
    sell_w = sum(_w(s) for s in signals if s.signal == "SELL")
    hold_w = sum(_w(s) for s in signals if s.signal == "HOLD")
    total = buy_w + sell_w + hold_w

    if total == 0:
        return 0.50

    # Maps (buy_w - sell_w) ∈ [-total, +total] → [0, 1]. Because the weights are
    # already regime-tilted, this consensus carries the regime signal directly.
    raw_prob = (buy_w - sell_w + total) / (2.0 * total)

    # Volatility reduces the edge for any direction
    vol_penalty = market_context.risk_score * 0.08

    return float(np.clip(raw_prob - vol_penalty, 0.05, 0.95))


# ── 4. Stacking meta-learner (T05) ────────────────────────────────────────────
# A trainable logistic combiner that replaces the hand-weighted heuristic in
# ``compute_signal_probability``. It learns, from the ticker's own history, how
# much each indicator's signal should count toward the 5-day-up probability.
#
# Feature vector (one column per indicator, exactly the roadmap list):
#   RSI, MACD, Bollinger, SMA_cross, Volumen  → signed strength score in
#     {-3,-2,-1,0,+1,+2,+3} (BUY positive, SELL negative, HOLD 0), computed per
#     row with the *same* thresholds as the scalar signal functions.
#   GARCH  → signed volatility-expansion score (cheap per-row proxy of the
#     GARCH expand/contract signal; the real GARCH model is too costly to refit
#     at every row, so we use a short/long realised-vol ratio that captures the
#     same expansion/contraction idea).
#   HMM    → bullish posterior in [0,1] from a single Gaussian-HMM fit.
#   XGB_prob → walk-forward out-of-fold P(up) in [0,1] (leakage-free, reuses the
#     T03 TimeSeriesSplit).
# Regime/volatility are NOT separate columns — the GARCH and HMM columns already
# carry that information, per the roadmap's feature list.

MIN_STACKING_ROWS = 25  # below this, fall back to the heuristic combiner
# History of this threshold:
#   200 → original Sprint 1 value. Never reached in the harness (17,047
#         fallbacks vs 0 successful trains on 2y/42 tickers).
#   50  → Sprint 2 A1 trim. Activated on 2y continuous data (ΔSharpe -0.19)
#         but NOT on 12m walk-forward windows (~200 usable rows is borderline).
#   25  → Sprint 2 walk-forward retry (Enmienda 3 of kill_criteria.md). With
#         12m windows there are ~200 raw bars, ~150 post-warmup, and ~100-120
#         labelled rows after the forward-return lookahead. 25 leaves margin
#         for the early steps of a window to start training before
#         half-window. Lower than this risks training on so little data
#         the meta-learner is more noise than signal.
# tests/test_stacking.py still uses the 200 sanity bound for one fallback test.

# Stable feature-column order for the meta-feature matrix.
STACKING_FEATURE_COLS = [
    "RSI",
    "MACD",
    "Bollinger",
    "SMA_cross",
    "Volumen",
    "GARCH",
    "HMM",
    "XGB_prob",
]

# Trained-combiner cache (in-memory). Keyed by a dataset fingerprint so repeated
# analyze_stacked() calls on the same data — and the train+predict round-trip —
# don't refit the whole XGB-OOF + HMM + logistic stack. Mirrors _XGB_CACHE.
# A trained ``dict`` *and* a ``None`` outcome (e.g. too few rows) are both cached,
# so the expensive feature build isn't repeated just to re-learn it's a no-go.
_STACK_CACHE: OrderedDict[str, object] = OrderedDict()
_STACK_CACHE_MAX = 64
_STACK_MISS = object()  # sentinel: distinguishes "not cached" from "cached None"


def _stack_cache_key(df: pd.DataFrame) -> str:
    """Stable fingerprint of the training set for the stacking combiner cache.

    Note (T24): unlike ``_xgb_cache_key`` this still hashes the live bar, so it
    misses on every intraday re-fetch. Left as-is deliberately — the stacking
    path is off in the live account (``stacking_enabled=False``, kill_only), so
    it is not in the scan hot path and re-keying it was not pre-registered. Only
    the eviction bug it shared with the XGB cache is fixed here.
    """
    if "Close" not in df.columns or len(df) == 0:
        return ""
    tail = df["Close"].tail(20).round(4).tolist()
    payload = f"stack|{tail}|{len(df)}|{df.index[-1]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _signal_score(signal: str, strength: str) -> float:
    """Signed strength score: +w for BUY, -w for SELL, 0 for HOLD.

    ``w`` is the base strength weight (STRONG=3, MODERATE=2, WEAK=1) shared with
    the regime-weighting of T04. This is the scalar building block; the
    ``*_score_series`` helpers below produce the same value per row, vectorised.
    """
    w = SIGNAL_STRENGTH_WEIGHTS.get(strength, 1.0)
    if signal == "BUY":
        return w
    if signal == "SELL":
        return -w
    return 0.0


def _rsi_score_series(rsi: pd.Series) -> pd.Series:
    """Per-row signed RSI score, matching ``_rsi_signal``'s six zones."""
    conds = [
        rsi < RSI_OVERSOLD_EXTREME,  # < 25  → BUY STRONG
        rsi < RSI_OVERSOLD,  # < 30  → BUY MODERATE
        rsi < RSI_LOW,  # < 40  → BUY WEAK
        rsi > RSI_OVERBOUGHT_EXTREME,  # > 75 → SELL STRONG
        rsi > RSI_OVERBOUGHT,  # > 70  → SELL MODERATE
        rsi > RSI_HIGH,  # > 60  → SELL WEAK
    ]
    vals = [3.0, 2.0, 1.0, -3.0, -2.0, -1.0]
    out = np.select(conds, vals, default=0.0)
    return pd.Series(out, index=rsi.index).where(rsi.notna())


def _macd_score_series(df: pd.DataFrame) -> pd.Series:
    """Per-row signed MACD score, matching ``_macd_signal``.

    ``hist = macd_line - signal_line``; ``macd_val > signal_val`` ⇔ ``hist > 0``.
    Crossovers (sign flip of hist) are STRONG; otherwise momentum direction
    (hist rising/falling) decides MODERATE vs WEAK.
    """
    from analysis.technical import compute_macd

    _, _, hist = compute_macd(df)
    hist_prev = hist.shift(1)
    growing = hist > hist_prev
    conds = [
        (hist_prev < 0) & (hist > 0),  # crossover  → BUY STRONG
        (hist_prev > 0) & (hist < 0),  # crossunder → SELL STRONG
        (hist > 0) & growing,  # up + accelerating  → BUY MODERATE
        (hist > 0) & ~growing,  # up + fading        → BUY WEAK
        (hist <= 0) & ~growing,  # down + accelerating → SELL MODERATE
        (hist <= 0) & growing,  # down + braking      → SELL WEAK
    ]
    vals = [3.0, -3.0, 2.0, 1.0, -2.0, -1.0]
    out = np.select(conds, vals, default=0.0)
    return pd.Series(out, index=hist.index).where(hist.notna() & hist_prev.notna())


def _bollinger_score_series(df: pd.DataFrame) -> pd.Series:
    """Per-row signed Bollinger score, matching ``_bollinger_signal``."""
    from analysis.technical import compute_bollinger_bands

    upper, _, lower = compute_bollinger_bands(df)
    close = df["Close"].squeeze()
    conds = [
        close < lower * 0.99,  # deep below lower → BUY STRONG
        close <= lower,  # at/under lower   → BUY MODERATE
        close > upper * 1.01,  # well above upper → SELL STRONG
        close >= upper,  # at/over upper    → SELL MODERATE
    ]
    vals = [3.0, 2.0, -3.0, -2.0]
    out = np.select(conds, vals, default=0.0)
    return pd.Series(out, index=close.index).where(upper.notna() & lower.notna())


def _sma_cross_score_series(df: pd.DataFrame) -> pd.Series:
    """Per-row signed SMA-50/200 cross score, matching ``_sma_cross_signal``."""
    from analysis.technical import compute_sma

    sma50 = compute_sma(df, 50)
    sma200 = compute_sma(df, 200)
    p50, p200 = sma50.shift(1), sma200.shift(1)
    golden = (p50 <= p200) & (sma50 > sma200)
    death = (p50 >= p200) & (sma50 < sma200)
    conds = [golden, death, sma50 > sma200]
    vals = [3.0, -3.0, 1.0]
    out = np.select(conds, vals, default=-1.0)  # else → SELL WEAK
    return pd.Series(out, index=sma50.index).where(sma50.notna() & sma200.notna())


def _volume_score_series(df: pd.DataFrame) -> pd.Series:
    """Per-row signed volume accumulation/distribution score.

    Mirrors ``_volume_signal``: over the trailing 10 sessions, compare mean
    volume on up-days vs down-days. ratio≥1.5 → accumulation (BUY), ≤0.67 →
    distribution (SELL); STRONG when the imbalance is ≥2×. Rows without a valid
    20-day volume baseline or without both up- and down-day volume score 0.
    """
    close = df["Close"].squeeze()
    if "Volume" not in df.columns:
        return pd.Series(0.0, index=close.index)
    volume = df["Volume"].squeeze().replace(0, np.nan)
    vol_sma20 = volume.rolling(20).mean()
    ret = close.pct_change()
    pos_vol = volume.where(ret > 0)
    neg_vol = volume.where(ret < 0)
    with np.errstate(invalid="ignore"):
        up = pos_vol.rolling(10, min_periods=1).apply(np.nanmean, raw=True)
        down = neg_vol.rolling(10, min_periods=1).apply(np.nanmean, raw=True)
    ratio = up / down
    valid = vol_sma20.notna() & (vol_sma20 > 0) & up.notna() & down.notna() & (down > 0)
    conds = [
        valid & (ratio <= 0.5),  # SELL STRONG (inv ≥ 2×)
        valid & (ratio <= 0.67),  # SELL MODERATE
        valid & (ratio >= 2.0),  # BUY STRONG
        valid & (ratio >= 1.5),  # BUY MODERATE
    ]
    vals = [-3.0, -2.0, 3.0, 2.0]
    out = np.select(conds, vals, default=0.0)
    return pd.Series(out, index=close.index)


def build_signal_score_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Per-row signed scores for the five rule-based indicators.

    Columns: RSI, MACD, Bollinger, SMA_cross, Volumen. Each cell is the same
    value the corresponding scalar signal function would assign to that row,
    encoded as a signed strength score (see :func:`_signal_score`). The GARCH,
    HMM and XGB_prob columns are added later in the meta-feature builder.
    """
    from analysis.technical import compute_rsi

    rsi = compute_rsi(df)
    return pd.DataFrame(
        {
            "RSI": _rsi_score_series(rsi),
            "MACD": _macd_score_series(df),
            "Bollinger": _bollinger_score_series(df),
            "SMA_cross": _sma_cross_score_series(df),
            "Volumen": _volume_score_series(df),
        },
        index=df.index,
    )


def _garch_vol_ratio_series(df: pd.DataFrame) -> pd.Series:
    """Per-row realised-volatility expansion ratio — cheap proxy for the GARCH
    column.

    The real GARCH model can't be refit at every historical row (too costly),
    so we use ``σ_short / σ_long`` (10-day vs 60-day realised vol of returns).
    >1 means volatility is expanding, <1 contracting — the same regime info the
    GARCH expand/contract signal carries, as a plain numeric feature the
    logistic standardises.
    """
    ret = df["Close"].squeeze().pct_change()
    short = ret.rolling(10).std()
    long = ret.rolling(60).std()
    return (short / long.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def _hmm_bullish_series(df: pd.DataFrame) -> pd.Series:
    """Per-row bullish-state posterior in [0,1] from a single Gaussian-HMM fit.

    ``p_bull + 0.5·p_lateral`` (same convention as :func:`train_hmm_signal`).
    Returns a neutral 0.5 everywhere if hmmlearn is unavailable or the fit
    fails, so the column is always present (a constant column just gets a
    near-zero logistic coefficient).
    """
    close = df["Close"].squeeze()
    if not _HMM_OK:
        return pd.Series(0.5, index=close.index)
    ret = np.log(close / close.shift(1))
    vol = ret.rolling(5).std()
    X = pd.concat([ret.rename("ret"), vol.rename("vol")], axis=1).dropna()
    if len(X) < HMM_MIN_ROWS:
        return pd.Series(0.5, index=close.index)
    try:
        model, order = _fit_gaussian_hmm(X.values.astype(np.float64), n_states=HMM_N_STATES)
        bull_idx, lat_idx = order[-1], order[1]
        post = model.predict_proba(X.values.astype(np.float64))
        bullish = post[:, bull_idx] + 0.5 * post[:, lat_idx]
        return pd.Series(bullish, index=X.index).reindex(close.index)
    except Exception as exc:  # pragma: no cover - hmm numerical guard
        log.warning("HMM bullish series error: %s", exc)
        return pd.Series(0.5, index=close.index)


def _xgb_oof_proba_series(df: pd.DataFrame) -> pd.Series:
    """Walk-forward out-of-fold P(5d-up) per row — the leakage-free XGB column.

    Uses the same TimeSeriesSplit(gap=PREDICTION_HORIZON) as T03: each fold's
    val block is scored by a model trained only on prior rows, so no row's
    feature was produced by a model that saw its own label. Rows before the
    first val block (and the trailing unlabelled rows) stay NaN and are dropped
    by the meta-feature builder. Returns a neutral 0.5 if xgboost/sklearn are
    unavailable.
    """
    close = df["Close"].squeeze()
    if not (_XGB_OK and _CALIBRATION_OK):
        return pd.Series(0.5, index=close.index)
    feats = _build_features(df)
    labels = _build_labels(df)
    combined = pd.concat([feats, labels.rename("label")], axis=1).dropna()
    if len(combined) < MIN_TRAINING_ROWS:
        return pd.Series(0.5, index=close.index)
    cols = [c for c in feats.columns if c in combined.columns]
    X = combined[cols].values.astype(np.float32)
    y = combined["label"].values.astype(int)
    oof = pd.Series(np.nan, index=combined.index, dtype=float)
    try:
        tscv = TimeSeriesSplit(n_splits=N_WALKFORWARD_FOLDS, gap=PREDICTION_HORIZON)
        for tr_idx, val_idx in tscv.split(X):
            if len(tr_idx) < 30 or len(val_idx) == 0 or len(np.unique(y[tr_idx])) < 2:
                continue
            m = _make_raw_xgb()
            m.fit(X[tr_idx], y[tr_idx])
            oof.iloc[val_idx] = m.predict_proba(X[val_idx])[:, 1]
    except Exception as exc:  # pragma: no cover - sklearn/xgb guard
        log.warning("XGB OOF error: %s", exc)
        return pd.Series(0.5, index=close.index)
    return oof.reindex(close.index)


def build_stacking_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Assemble the full per-row meta-feature matrix and the 5-day-up label.

    Columns (exactly the roadmap list, in ``STACKING_FEATURE_COLS`` order):
    the five rule-based signed scores, the GARCH vol-ratio proxy, the HMM
    bullish posterior, and the walk-forward OOF XGB probability. Regime and
    volatility are not separate columns — GARCH and HMM already carry them.
    """
    feats = build_signal_score_matrix(df)
    feats["GARCH"] = _garch_vol_ratio_series(df)
    feats["HMM"] = _hmm_bullish_series(df)
    feats["XGB_prob"] = _xgb_oof_proba_series(df)
    feats = feats[STACKING_FEATURE_COLS]
    label = _build_labels(df).rename("label")
    return feats, label


def _logit_walkforward_scores(X: np.ndarray, y: np.ndarray, penalty: str) -> list[float]:
    """Walk-forward val accuracies for a logistic with the given penalty.

    Mirrors the XGB walk-forward: a fresh scaler+logistic is fit on each fold's
    train window and scored on the immediately-following val block, with a
    PREDICTION_HORIZON purge gap. Used only to pick L1 vs L2 honestly.
    """
    scores: list[float] = []
    try:
        tscv = TimeSeriesSplit(n_splits=N_WALKFORWARD_FOLDS, gap=PREDICTION_HORIZON)
        for tr_idx, val_idx in tscv.split(X):
            if len(tr_idx) < 30 or len(val_idx) == 0 or len(np.unique(y[tr_idx])) < 2:
                continue
            sc = StandardScaler().fit(X[tr_idx])
            m = LogisticRegression(penalty=penalty, solver="liblinear", max_iter=1000)
            m.fit(sc.transform(X[tr_idx]), y[tr_idx])
            scores.append(float((m.predict(sc.transform(X[val_idx])) == y[val_idx]).mean()))
    except Exception as exc:  # pragma: no cover - sklearn guard
        log.warning("Logit walk-forward error: %s", exc)
        return []
    return scores


def train_stacking_combiner(df: pd.DataFrame) -> dict | None:
    """Train the logistic stacking meta-learner on the ticker's own history.

    Replaces the hand-weighted heuristic of :func:`compute_signal_probability`
    by learning, from data, how much each indicator's signal counts toward the
    5-day-up probability. Tries both L2 and L1 penalties and keeps whichever has
    the higher mean walk-forward validation accuracy (L1 also gives sparse,
    interpretable feature selection — roadmap note). Coefficients are logged.

    Returns
    -------
    dict with keys ``model, scaler, cols, coefs, val_acc, val_std, penalty, n``
    or ``None`` when the combiner can't / shouldn't be used (sklearn missing,
    < MIN_STACKING_ROWS labelled rows, or a single-class label) — callers then
    fall back to the T04 heuristic combiner.

    Results are cached per dataset fingerprint (``_STACK_CACHE``) so repeated
    calls within a session — and the live train+predict round-trip — don't
    refit the XGB-OOF + HMM + logistic stack from scratch on identical data.
    """
    if not (_SKLEARN_LINEAR_OK and _CALIBRATION_OK):
        return None
    key = _stack_cache_key(df)
    if key:
        cached = _lru_get(_STACK_CACHE, key, _STACK_MISS)
        if cached is not _STACK_MISS:
            return cached  # type: ignore[return-value]
    combiner = _train_stacking_combiner_uncached(df)
    if key:
        _lru_put(_STACK_CACHE, key, combiner, _STACK_CACHE_MAX)
    return combiner


def _train_stacking_combiner_uncached(df: pd.DataFrame) -> dict | None:
    """Actual stacking training (no cache). See :func:`train_stacking_combiner`."""
    feats, label = build_stacking_features(df)
    data = pd.concat([feats, label], axis=1).dropna()
    if len(data) < MIN_STACKING_ROWS:
        log.info(
            "Stacking: only %d usable rows (< %d); falling back to heuristic combiner.",
            len(data),
            MIN_STACKING_ROWS,
        )
        return None
    X = data[STACKING_FEATURE_COLS].values.astype(np.float64)
    y = data["label"].values.astype(int)
    if len(np.unique(y)) < 2:
        return None

    best: tuple[str, float, float] | None = None
    for penalty in ("l2", "l1"):
        scores = _logit_walkforward_scores(X, y, penalty)
        if not scores:
            continue
        acc, std = float(np.mean(scores)), float(np.std(scores))
        if best is None or acc > best[1]:
            best = (penalty, acc, std)

    if best is None:  # walk-forward unusable (tiny/degenerate) → default L2, no WF estimate
        penalty, val_acc, val_std = "l2", float("nan"), 0.0
    else:
        penalty, val_acc, val_std = best

    try:
        scaler = StandardScaler().fit(X)
        model = LogisticRegression(penalty=penalty, solver="liblinear", max_iter=1000)
        model.fit(scaler.transform(X), y)
    except Exception as exc:
        log.warning("Stacking logistic fit failed (%s); falling back to heuristic.", exc)
        return None

    coefs = dict(zip(STACKING_FEATURE_COLS, model.coef_[0], strict=False))
    log.info(
        "Stacking logistic (%s): val_acc=%.0f%% ± %.0f%% on %d rows; coefs=%s",
        penalty,
        (val_acc * 100) if val_acc == val_acc else float("nan"),  # nan-safe
        val_std * 100,
        len(data),
        {k: round(v, 3) for k, v in coefs.items()},
    )
    return {
        "model": model,
        "scaler": scaler,
        "cols": STACKING_FEATURE_COLS,
        "coefs": coefs,
        "val_acc": val_acc,
        "val_std": val_std,
        "penalty": penalty,
        "n": len(data),
    }


def _live_stacking_features(df: pd.DataFrame) -> np.ndarray | None:
    """Feature vector for the most recent row, for live prediction.

    The five rule-based scores, the GARCH ratio and the HMM posterior are taken
    at the last row. ``XGB_prob`` uses the *full-data* model's live P(up) (via
    :func:`train_xgboost_signal`) rather than an OOF value — there's no label
    for the latest row, so leakage isn't a concern at prediction time. Returns
    None if any required value is missing.
    """
    feats = build_signal_score_matrix(df)
    feats["GARCH"] = _garch_vol_ratio_series(df)
    feats["HMM"] = _hmm_bullish_series(df)
    last = feats.iloc[-1]
    # Live XGB probability for the latest row (full-data model).
    xgb_sig = train_xgboost_signal(df) if _XGB_OK else None
    xgb_prob = float(xgb_sig.value) if xgb_sig is not None else 0.5
    row = {
        "RSI": last.get("RSI"),
        "MACD": last.get("MACD"),
        "Bollinger": last.get("Bollinger"),
        "SMA_cross": last.get("SMA_cross"),
        "Volumen": last.get("Volumen"),
        "GARCH": last.get("GARCH"),
        "HMM": last.get("HMM"),
        "XGB_prob": xgb_prob,
    }
    vec = [row[c] for c in STACKING_FEATURE_COLS]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vec):
        return None
    return np.array(vec, dtype=np.float64).reshape(1, -1)


def compute_stacking_probability(df: pd.DataFrame, combiner: dict) -> float | None:
    """P(5d-up) for the latest row from a trained stacking ``combiner``.

    Returns None when the live feature vector can't be built (caller should
    then fall back to the heuristic). Output is a probability in [0,1].
    """
    if combiner is None:
        return None
    vec = _live_stacking_features(df)
    if vec is None:
        return None
    try:
        Xs = combiner["scaler"].transform(vec)
        return float(combiner["model"].predict_proba(Xs)[0][1])
    except Exception as exc:  # pragma: no cover - inference guard
        log.warning("Stacking inference error: %s", exc)
        return None
