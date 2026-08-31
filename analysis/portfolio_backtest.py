"""
Multi-ticker portfolio backtesting framework for FinanzIAs.

Extends the single-ticker engine in ``analysis.backtest`` to a full portfolio
with four comparable allocation modes, a configurable slot limit, and a hybrid
rebalancing policy (signal-driven + drift-based + monthly safety net).

Allocation modes
----------------
``EQUAL_WEIGHT``     Every active position gets 1/N of portfolio equity.
``SIGNAL_WEIGHTED``  Weights proportional to each ticker's conviction score
                     (via ``strength_fn`` or a BUY/HOLD/SELL → 1.0/0.5/0.0
                     fallback).
``INVERSE_VOL``      Weights proportional to 1/σ_60d — low-vol names get more
                     capital, high-vol names get less.
``FIXED_AMOUNT``     Each active slot holds a fixed dollar target. Cash above
                     that target is kept idle; cash below triggers a top-up.
``VOL_TARGET``       Per-name volatility targeting (T06). Each active slot
                     gets weight ``(vol_target_annual / σ_ticker) / N`` so that
                     more volatile names receive less exposure. Capped per
                     ticker at ``max_position_weight`` and scaled down if the
                     total would exceed 1.0 (long-only, no leverage).
``KELLY_FRACTIONAL`` Fractional-Kelly sizing (T06). Weight per ticker is
                     ``kelly_fraction × edge / variance`` with
                     ``edge = 2·prob_up − 1`` (calibrated buy probability) and
                     ``variance = σ_ticker²``. Negative-edge names are dropped
                     (long-only); tickers without a calibrated probability are
                     skipped entirely. Same per-ticker cap + scale-down.

Rebalancing triggers (evaluated at every ``step``)
--------------------------------------------------
1. Signal change    — any SELL on an existing position or BUY that fills a
                      free slot.
2. Drift            — any position's actual weight deviates from its target
                      by more than ``drift_threshold`` (default 25 %).
3. Monthly backstop — on the first trading day of each month, always rebalance.

Data interface
--------------
Either pass a preloaded ``data={'AAPL': df_aapl, ...}`` dict (OHLCV with a
DatetimeIndex and a Close column), or let the engine auto-fetch via
``data.yahoo_finance.get_historical_data`` using ``period``. All ticker
DataFrames are aligned to their common date index, and tickers that can't be
loaded are dropped with a warning.

Everything is long-only, no shorting, no leverage, no options.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

from config.logging_config import get_logger

log = get_logger(__name__)

from analysis.backtest import (
    TRADING_DAYS,
    SignalFn,
    _annual_vol,
    _cagr,
    _max_drawdown,
    _sharpe,
    _sortino,
)

# ── Config enums & type aliases ───────────────────────────────────────────────


class AllocationMode(str, Enum):
    EQUAL_WEIGHT = "equal_weight"
    SIGNAL_WEIGHTED = "signal_weighted"
    INVERSE_VOL = "inverse_vol"
    FIXED_AMOUNT = "fixed_amount"
    VOL_TARGET = "vol_target"
    KELLY_FRACTIONAL = "kelly_fractional"


# ── T06 sizing defaults (mirrored in config.settings_manager SCHEMA) ──────────
# These are the fallback values used when a caller does not pass explicit
# params (e.g. direct unit tests of ``_compute_target_weights``). The live
# strategies read the user-tunable values from ``settings`` and pass them in.
DEFAULT_KELLY_FRACTION = 0.25  # quarter-Kelly — conservative
DEFAULT_VOL_TARGET_ANNUAL = 0.20  # 20 % annualised per-name vol target
DEFAULT_MAX_POSITION_WEIGHT = 0.25  # hard cap: no ticker > 25 % of portfolio
_VOL_FALLBACK = 0.20  # used when a ticker's σ is unknown / zero


# Optional convenience: a callable that scores BUY conviction in [0, 1].
StrengthFn = Callable[[pd.DataFrame], float]


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class PortfolioTrade:
    """A completed round-trip position (opened + fully closed)."""

    ticker: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float  # VWAP average cost net of commission/slippage
    exit_price: float  # last execution price net of commission/slippage
    shares: float  # shares held when closed (at exit time)
    return_pct: float  # P&L as % of avg cost basis (net of fees)
    pnl: float  # dollar P&L net of fees
    holding_days: int
    entry_reason: str  # "BUY signal", "slot fill", "monthly rebalance"…
    exit_reason: str  # "SELL signal", "drift cut", "forced close (end)"…

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


@dataclass
class _PositionState:
    """Mutable per-ticker state held inside the backtest loop."""

    shares: float = 0.0
    avg_cost: float = 0.0  # VWAP including fees/slippage
    entry_date: pd.Timestamp | None = None
    entry_reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.shares > 0


@dataclass
class PortfolioBacktestResult:
    strategy_name: str
    allocation_mode: str
    tickers: list[str]
    max_positions: int
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    initial_capital: float
    final_equity: float
    # Strategy performance
    total_return_pct: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    equity_curve: pd.Series
    # Trade stats
    trades: list[PortfolioTrade] = field(default_factory=list)
    n_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_holding_days: float = 0.0
    # Rebalance stats
    n_rebalances_signal: int = 0
    n_rebalances_drift: int = 0
    n_rebalances_month: int = 0
    n_slot_fills: int = 0
    n_breaker_suppressed: int = 0
    # Buy-and-hold equal-weight benchmark
    bh_return_pct: float = 0.0
    bh_cagr: float = 0.0
    bh_sharpe: float = 0.0
    bh_max_drawdown: float = 0.0
    bh_equity_curve: pd.Series | None = None
    alpha_pct: float = 0.0
    # Config snapshot
    commission: float = 0.0
    slippage: float = 0.0
    drift_threshold: float = 0.25
    monthly_rebalance: bool = True
    step: int = 1
    warnings: list[str] = field(default_factory=list)


# ── Data loading & alignment ──────────────────────────────────────────────────


def _load_prices(
    tickers: list[str],
    data: dict[str, pd.DataFrame] | None,
    period: str,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """
    Return a {ticker: DataFrame} dict aligned to the intersection of all
    ticker date indices, plus a list of warnings for tickers that couldn't be
    loaded.
    """
    warnings: list[str] = []
    frames: dict[str, pd.DataFrame] = {}

    if data is None:
        # Auto-fetch via yfinance — en lote: un crumb compartido por chunk
        # reduce los 401 "Invalid Crumb" vs. pedir ticker por ticker.
        from data.yahoo_finance import get_historical_data_batch

        fetched = get_historical_data_batch(tickers, period=period)
        for t in tickers:
            df = fetched.get(t.upper())
            if df is None or df.empty or "Close" not in df.columns:
                warnings.append(f"{t}: no data, skipped.")
                continue
            frames[t] = df
    else:
        for t in tickers:
            df = data.get(t)
            if df is None or df.empty or "Close" not in df.columns:
                warnings.append(f"{t}: missing 'Close' or empty, skipped.")
                continue
            frames[t] = df

    if not frames:
        return {}, warnings

    # Align on common index (intersection)
    common_idx = None
    for df in frames.values():
        idx = df.index
        common_idx = idx if common_idx is None else common_idx.intersection(idx)

    if common_idx is None or len(common_idx) == 0:
        warnings.append("No common date index across tickers.")
        return {}, warnings

    common_idx = common_idx.sort_values()
    frames = {t: df.loc[common_idx].copy() for t, df in frames.items()}
    return frames, warnings


# ── Signal strength fallback ──────────────────────────────────────────────────

_DEFAULT_STRENGTH = {"BUY": 1.0, "HOLD": 0.5, "SELL": 0.0}


def _strength(signal: str, df_slice: pd.DataFrame, strength_fn: StrengthFn | None) -> float:
    if strength_fn is not None:
        try:
            val = float(strength_fn(df_slice))
            return max(0.0, min(1.0, val))
        except Exception:
            pass
    return _DEFAULT_STRENGTH.get(signal, 0.0)


# ── Target weight computation ─────────────────────────────────────────────────


def _realized_vol(close: pd.Series, lookback: int = 60) -> float:
    """Annualised std-dev of daily log-returns over the last `lookback` bars."""
    r = np.log(close).diff().dropna()
    if len(r) < 10:
        return 0.0
    tail = r.tail(lookback)
    v = float(tail.std() * np.sqrt(TRADING_DAYS))
    return v if np.isfinite(v) and v > 0 else 0.0


def _cap_and_scale(raw: dict[str, float], max_weight: float) -> dict[str, float]:
    """
    Apply the T06 per-ticker hard cap, then scale the whole book down if the
    total still exceeds 1.0.

    Order matters: cap first (so a single dominant name can't eat the book),
    then scale (which only ever reduces weights, so the cap is never violated
    by the scaling step). When the post-cap total is ≤ 1.0 it is left as-is —
    the residual stays in cash (long-only, no leverage).
    """
    capped = {t: min(max(0.0, w), max_weight) for t, w in raw.items() if w > 0}
    total = sum(capped.values())
    if total > 1.0:
        capped = {t: w / total for t, w in capped.items()}
    return capped


def _compute_target_weights(
    active_tickers: list[str],
    strengths: dict[str, float],
    vols: dict[str, float],
    mode: AllocationMode,
    *,
    # `Mapping` y no `dict`: los dict son invariantes en el tipo del valor, asi
    # que un dict[str, float] no encaja en dict[str, float | None] aunque cada
    # valor sirva. Mapping es covariante y expresa lo que la funcion necesita.
    probs: Mapping[str, float | None] | None = None,
    kelly_fraction: float = DEFAULT_KELLY_FRACTION,
    vol_target_annual: float = DEFAULT_VOL_TARGET_ANNUAL,
    max_weight: float = DEFAULT_MAX_POSITION_WEIGHT,
) -> dict[str, float]:
    """
    Return target weights summing to ≤ 1.0 for the given active tickers.
    For FIXED_AMOUNT the caller converts target dollars, not weights.

    ``probs`` maps ticker → calibrated buy probability in [0,1] (or None when
    no model probability is available). It is only consulted by
    ``KELLY_FRACTIONAL``; the heuristic modes ignore it.
    """
    if not active_tickers:
        return {}

    if mode == AllocationMode.VOL_TARGET:
        # Per-name vol targeting: weight = (vol_target / σ) / N. Unknown/zero
        # vols fall back to the median (or a fixed prior) so they don't blow up.
        n = len(active_tickers)
        known = [vols[t] for t in active_tickers if vols.get(t, 0.0) > 0]
        fallback = float(np.median(known)) if known else _VOL_FALLBACK
        raw = {t: (vol_target_annual / (vols.get(t, 0.0) or fallback)) / n for t in active_tickers}
        return _cap_and_scale(raw, max_weight)

    if mode == AllocationMode.KELLY_FRACTIONAL:
        # Fractional Kelly: w = f · edge / variance, edge = 2p − 1.
        # Long-only → drop negative edge. Skip tickers without a calibrated
        # probability entirely (per user decision: never treat the BUY/HOLD/
        # SELL fallback strength as a probability here).
        probs = probs or {}
        known = [vols[t] for t in active_tickers if vols.get(t, 0.0) > 0]
        fallback = float(np.median(known)) if known else _VOL_FALLBACK
        raw_w: dict[str, float] = {}
        for t in active_tickers:
            p = probs.get(t)
            if p is None or not np.isfinite(p):
                continue  # no calibrated prob → skip
            sigma = vols.get(t, 0.0) or fallback
            variance = sigma * sigma
            if variance <= 0:
                continue
            edge = 2.0 * float(p) - 1.0
            w = kelly_fraction * (edge / variance)
            if w > 0:  # drop non-positive edge (long-only)
                raw_w[t] = w
        return _cap_and_scale(raw_w, max_weight)

    if mode == AllocationMode.EQUAL_WEIGHT:
        w = 1.0 / len(active_tickers)
        return {t: w for t in active_tickers}

    if mode == AllocationMode.SIGNAL_WEIGHTED:
        raw = {t: max(0.0, strengths.get(t, 0.0)) for t in active_tickers}
        total = sum(raw.values())
        if total <= 0:
            w = 1.0 / len(active_tickers)
            return {t: w for t in active_tickers}
        return {t: v / total for t, v in raw.items()}

    if mode == AllocationMode.INVERSE_VOL:
        # Weight ∝ 1/vol.  Tickers with zero/unknown vol get the median.
        known = [vols[t] for t in active_tickers if vols.get(t, 0.0) > 0]
        fallback = float(np.median(known)) if known else 0.20  # 20 % fallback
        inv = {t: 1.0 / (vols.get(t, 0.0) or fallback) for t in active_tickers}
        total = sum(inv.values())
        if total <= 0:
            w = 1.0 / len(active_tickers)
            return {t: w for t in active_tickers}
        return {t: v / total for t, v in inv.items()}

    # FIXED_AMOUNT is handled by caller (dollar targets, not weights).
    return {t: 0.0 for t in active_tickers}


# ── Rebalance execution ───────────────────────────────────────────────────────


def _execute_rebalance(
    *,
    date: pd.Timestamp,
    prices: dict[str, float],
    positions: dict[str, _PositionState],
    target_dollars: dict[str, float],
    cash: float,
    commission: float,
    slippage: float,
    reason: str,
    trades_log: list[PortfolioTrade],
    forced_exit_reasons: dict[str, str] | None = None,
    exit_fill_prices: dict[str, float] | None = None,
) -> float:
    """
    Bring actual dollar exposure in line with target_dollars for every ticker
    that appears in positions OR target_dollars. Closes positions whose target
    is zero; partial-sells or partial-buys otherwise.
    Returns updated cash.

    ``exit_fill_prices`` (opcional): precio de fill *base* por ticker para
    salidas forzadas por nivel (ATR), modelado con el gap/touch de la barra.
    Cuando está presente para un ticker, su SELL se ejecuta a ese precio (el
    slippage se aplica encima) en vez de al close. El sizing/exposición sigue
    usando el close. Sin el dict (default) el comportamiento es idéntico al
    histórico.
    """
    all_tickers = set(positions.keys()) | set(target_dollars.keys())

    # Pass 1 — sells (free up cash first so pass-2 buys have liquidity)
    for t in all_tickers:
        st = positions.setdefault(t, _PositionState())
        price = prices.get(t)
        if price is None or not np.isfinite(price) or price <= 0:
            continue
        target = target_dollars.get(t, 0.0)
        current = st.shares * price
        if current - target > 1e-6:
            # Sell difference
            sell_dollars = current - target
            sell_shares = min(st.shares, sell_dollars / price)
            if sell_shares <= 0:
                continue
            # Precio de fill: por defecto el close; si hay un fill modelado para
            # una salida ATR de este ticker, se usa como base (slippage encima).
            base_px = (exit_fill_prices or {}).get(t)
            exec_px = base_px if (base_px is not None and np.isfinite(base_px) and base_px > 0) else price
            fill_price = exec_px * (1 - slippage)
            proceeds = sell_shares * fill_price * (1 - commission)
            cash += proceeds
            st.shares -= sell_shares

            # If fully closed → record a completed trade
            if st.shares <= 1e-9 and st.entry_date is not None:
                cost_basis = sell_shares * st.avg_cost
                pnl = proceeds - cost_basis
                ret = (proceeds / cost_basis - 1.0) if cost_basis > 0 else 0.0
                holding = (date - st.entry_date).days
                # Use forced_exit_reason if this ticker was force-exited, otherwise use global reason
                exit_reason = (forced_exit_reasons or {}).get(t, reason)
                trades_log.append(
                    PortfolioTrade(
                        ticker=t,
                        entry_date=st.entry_date,
                        exit_date=date,
                        entry_price=st.avg_cost,
                        exit_price=fill_price,
                        shares=sell_shares,
                        return_pct=float(ret),
                        pnl=float(pnl),
                        holding_days=int(holding),
                        entry_reason=st.entry_reason,
                        exit_reason=exit_reason,
                    )
                )
                st.shares = 0.0
                st.avg_cost = 0.0
                st.entry_date = None
                st.entry_reason = ""

    # Pass 2 — buys
    for t in all_tickers:
        st = positions.setdefault(t, _PositionState())
        price = prices.get(t)
        if price is None or not np.isfinite(price) or price <= 0:
            continue
        target = target_dollars.get(t, 0.0)
        current = st.shares * price
        if target - current > 1e-6 and cash > 0:
            buy_dollars = min(target - current, cash)
            fill_price = price * (1 + slippage)
            shares_got = (buy_dollars * (1 - commission)) / fill_price
            if shares_got <= 0:
                continue
            cost_in = shares_got * fill_price  # what those shares cost before fee refund
            # VWAP update
            if st.shares > 0:
                new_total_cost = st.shares * st.avg_cost + cost_in
                st.avg_cost = new_total_cost / (st.shares + shares_got)
            else:
                st.avg_cost = fill_price
                st.entry_date = date
                st.entry_reason = reason
            st.shares += shares_got
            cash -= buy_dollars

    # Drop stale zero-share entries to keep the dict clean
    for t in list(positions.keys()):
        if positions[t].shares <= 1e-9:
            positions[t].shares = 0.0
            positions[t].avg_cost = 0.0
            positions[t].entry_date = None
            positions[t].entry_reason = ""

    return cash


# ── Drift check ───────────────────────────────────────────────────────────────


def _needs_drift_rebalance(
    *,
    positions: dict[str, _PositionState],
    prices: dict[str, float],
    target_weights: dict[str, float],
    portfolio_val: float,
    threshold: float,
) -> bool:
    """True if any position's weight drifts > threshold (relative) from target."""
    if portfolio_val <= 0 or not target_weights:
        return False
    for t, w_target in target_weights.items():
        st = positions.get(t)
        if st is None:
            continue
        price = prices.get(t)
        if price is None:
            continue
        actual = (st.shares * price) / portfolio_val
        if w_target <= 0:
            if actual > threshold:
                return True
            continue
        rel_drift = abs(actual - w_target) / w_target
        if rel_drift > threshold:
            return True
    return False


# ── Main entry point ──────────────────────────────────────────────────────────


def portfolio_backtest(
    signal_fn: SignalFn,
    *,
    tickers: list[str],
    data: dict[str, pd.DataFrame] | None = None,
    period: str = "2y",
    strategy_name: str = "Custom",
    allocation_mode: AllocationMode = AllocationMode.EQUAL_WEIGHT,
    max_positions: int = 5,
    fixed_amount: float = 5_000.0,
    initial_capital: float = 50_000.0,
    commission: float = 0.001,
    slippage: float = 0.0005,
    drift_threshold: float = 0.25,
    monthly_rebalance: bool = True,
    warmup: int = 200,
    step: int = 5,  # evaluate every 5 bars by default
    strength_fn: StrengthFn | None = None,
    kelly_fraction: float = DEFAULT_KELLY_FRACTION,
    vol_target_annual: float = DEFAULT_VOL_TARGET_ANNUAL,
    max_position_weight: float = DEFAULT_MAX_POSITION_WEIGHT,
    # El hook puede devolver (should_exit, reason) o, para salidas por nivel (ATR),
    # (should_exit, reason, trigger_level) → habilita el fill realista gap/touch.
    forced_exit_fn: (
        Callable[[str, pd.DataFrame, _PositionState], tuple[bool, str] | tuple[bool, str, float | None]]
        | None
    ) = None,
    vol_overlay_fn: (Callable[[dict[str, float], dict[str, pd.Series]], float] | None) = None,
    # R1 account-level drawdown breaker (harness-only hook). Given the bar date,
    # the current portfolio value and the equity curve so far, returns True to
    # SUPPRESS new BUY entries this step — held positions still exit / rebalance
    # (the breaker never blocks a way out). None = legacy behavior (no
    # suppression). The live gate lives in ``run_scan``; this hook exists to
    # validate the guardrail against the pre-registered kill-criteria.
    breaker_fn: Callable[[pd.Timestamp, float, pd.Series], bool] | None = None,
    verbose: bool = False,
) -> PortfolioBacktestResult | None:
    """
    Run a long-only multi-ticker backtest with a configurable allocation mode.
    See module docstring for full parameter semantics.
    """
    frames, load_warnings = _load_prices(tickers, data, period)
    if not frames:
        return None

    tickers_ok = list(frames.keys())
    # Canonical index (already aligned in _load_prices)
    master_idx = next(iter(frames.values())).index
    n = len(master_idx)
    if n < warmup + 10:
        return None

    # Pre-extract close series for speed
    closes: dict[str, pd.Series] = {t: frames[t]["Close"].astype(float).squeeze() for t in tickers_ok}

    # ── Simulation state ──────────────────────────────────────────────────────
    cash = float(initial_capital)
    positions: dict[str, _PositionState] = {t: _PositionState() for t in tickers_ok}
    trades_log: list[PortfolioTrade] = []
    equity = pd.Series(index=master_idx, dtype=float)

    # Memoised per-ticker last signal (to detect changes vs step-cadence reuse)
    last_signal: dict[str, str] = {t: "HOLD" for t in tickers_ok}

    n_reb_signal = 0
    n_reb_drift = 0
    n_reb_month = 0
    n_slot_fills = 0
    n_breaker_suppressed = 0

    last_rebalance_month: tuple[int, int] | None = None

    # ── Main loop ─────────────────────────────────────────────────────────────
    for i in range(n):
        date = master_idx[i]
        prices = {t: float(closes[t].iloc[i]) for t in tickers_ok}

        # Mark-to-market before any decisions
        portfolio_val = cash + sum(positions[t].shares * prices[t] for t in tickers_ok)

        if i < warmup or (i - warmup) % max(1, step) != 0:
            equity.iloc[i] = portfolio_val
            continue

        # ── Compute fresh signals for every ticker ────────────────────────────
        signals: dict[str, str] = {}
        strengths: dict[str, float] = {}
        vols: dict[str, float] = {}
        for t in tickers_ok:
            df_slice = frames[t].iloc[: i + 1]
            try:
                sig = signal_fn(df_slice)
            except Exception as exc:
                if verbose:
                    log.warning("portfolio_backtest %s@%s: signal_fn error: %s", t, date, exc)
                sig = "HOLD"
            if sig not in ("BUY", "SELL", "HOLD"):
                sig = "HOLD"
            signals[t] = sig
            strengths[t] = _strength(sig, df_slice, strength_fn)
            vols[t] = _realized_vol(closes[t].iloc[: i + 1])

        # ── Determine active set (positions + candidate entries) ──────────────
        # (1) Mandatory exits — any open position with SELL signal + forced_exit_fn
        forced_exits = [t for t, st in positions.items() if st.is_open and signals[t] == "SELL"]
        forced_exit_reasons: dict[str, str] = {}
        # Nivel-gatillo por ticker cuando el hook lo provee (3-tuple) → habilita
        # el fill realista (gap/touch) en vez de llenar al close.
        forced_exit_levels: dict[str, float] = {}

        # Evaluate forced_exit_fn hook for all open positions (not already exiting via signal)
        if forced_exit_fn is not None:
            for t in tickers_ok:
                if positions[t].is_open and t not in forced_exits:
                    df_slice = frames[t].iloc[: i + 1]
                    try:
                        res = forced_exit_fn(t, df_slice, positions[t])
                        # Backward-compatible: (should, reason) o (should, reason, level).
                        should_exit, reason = res[0], res[1]
                        level = res[2] if len(res) > 2 else None
                        if should_exit:
                            forced_exits.append(t)
                            forced_exit_reasons[t] = reason
                            if level is not None and np.isfinite(level) and level > 0:
                                forced_exit_levels[t] = float(level)
                    except Exception as exc:
                        if verbose:
                            log.warning("forced_exit_fn(%s@%s) error: %s", t, date, exc)

        # Fill realista para las salidas ATR con nivel conocido: modela el precio
        # de ejecución con el OHLC de la barra (gap-open vs touch intradía).
        exit_fill_prices: dict[str, float] = {}
        if forced_exit_levels:
            from paper_trading.gates import model_exit_fill_price

            for t, lvl in forced_exit_levels.items():
                reason_t = forced_exit_reasons.get(t, "")
                if not reason_t.startswith("atr_"):
                    continue
                try:
                    bar = frames[t].iloc[i]
                    bo = float(bar["Open"]) if "Open" in bar else None
                    bh = float(bar["High"]) if "High" in bar else None
                    bl = float(bar["Low"]) if "Low" in bar else None
                except (KeyError, IndexError, ValueError, TypeError):
                    bo = bh = bl = None
                cur = float(closes[t].iloc[i])
                exit_fill_prices[t] = model_exit_fill_price(
                    reason=reason_t,
                    trigger_level=lvl,
                    bar_open=bo,
                    bar_high=bh,
                    bar_low=bl,
                    current_price=cur,
                )

        # (2) Open slots after forced exits
        still_open = [t for t, st in positions.items() if st.is_open and t not in forced_exits]
        free_slots = max_positions - len(still_open)

        # (3) Candidates ranked by strength (only BUYs — HOLD never triggers a new entry).
        # Tickers force-exited this bar are blocked from immediate re-entry; otherwise the
        # forced exit would silently turn into a same-bar rebalance and the exit_reason
        # from forced_exit_fn would never reach trades_log.
        #
        # Sprint 4 / T05: when ``cross_sectional_enabled`` is on, the rank key
        # blends the absolute strength with a cross-sectional momentum
        # percentile against the rest of the universe. Toggle OFF preserves the
        # legacy ``key=strengths[t]`` path exactly. Computed inside the loop
        # so per-step settings flips (harness ablations) take effect.
        candidate_pool = [
            t for t in tickers_ok if signals[t] == "BUY" and t not in still_open and t not in forced_exits
        ]
        rank_key = strengths
        if candidate_pool:
            from config.settings_manager import settings as _settings

            if bool(_settings.get("cross_sectional_enabled", False)):
                from analysis.ranking import blended_scores

                lookback = max(2, int(_settings.get("cross_sectional_lookback", 120)))
                weight = float(_settings.get("cross_sectional_weight", 0.5))
                weight = min(1.0, max(0.0, weight))
                # Universe for the cross-sectional rank = every ticker with
                # data at this bar (not only the BUY pool) so a percentile
                # reflects the candidate's standing in the full watchlist.
                closes_at_bar = {t: closes[t].iloc[: i + 1] for t in tickers_ok}
                rank_key = blended_scores(
                    {t: strengths[t] for t in candidate_pool},
                    closes_at_bar,
                    lookback,
                    weight,
                )
        candidates = sorted(
            candidate_pool,
            key=lambda t: rank_key[t] if t in rank_key else strengths[t],
            reverse=True,
        )

        # T09 correlation_filter_fn hook removed in Sprint 3 — attribution
        # showed the gate never rejected a candidate in any realistic setup
        # (analyze_stacked threshold 0.55 produces 1-2 BUYs per step, never
        # reaching "candidates > slots"). See docs/sprint2_kill_criteria.md.
        free_slots = max(0, free_slots)
        new_entries = candidates[:free_slots]

        # R1 drawdown breaker: when armed, suppress *new* entries only. Held
        # positions keep their forced exits / rebalance (the breaker never blocks
        # a way out, same rule as the live gate). Evaluated before ``active`` so
        # suppressed names never open. ``equity.iloc[:i]`` is the curve up to the
        # previous bar; ``portfolio_val`` is this bar's mark-to-market.
        if breaker_fn is not None and new_entries:
            try:
                if breaker_fn(date, portfolio_val, equity.iloc[:i]):
                    new_entries = []
                    n_breaker_suppressed += 1
            except Exception as exc:
                if verbose:
                    log.warning("breaker_fn@%s error: %s", date, exc)

        # Final active set after this step's decisions
        active = [t for t in tickers_ok if t in still_open or t in new_entries]

        # ── Reason flags ──────────────────────────────────────────────────────
        signal_changed = (
            bool(forced_exits)
            or bool(new_entries)
            or any(signals[t] != last_signal.get(t, "HOLD") for t in tickers_ok)
        )
        month_tick = monthly_rebalance and (date.year, date.month) != (last_rebalance_month or (0, 0))

        # ── Target dollars by allocation mode ─────────────────────────────────
        if allocation_mode == AllocationMode.FIXED_AMOUNT:
            # Every active slot gets `fixed_amount` of dollars, capped at cash+equity.
            target_dollars = {t: float(fixed_amount) for t in active}
            total_target = sum(target_dollars.values())
            if total_target > portfolio_val > 0:
                # Scale down proportionally if we can't afford N×fixed_amount.
                scale = portfolio_val / total_target
                target_dollars = {t: v * scale for t, v in target_dollars.items()}
            # Non-active tickers → 0 (close)
            for t in tickers_ok:
                target_dollars.setdefault(t, 0.0)
            target_weights = {
                t: v / portfolio_val if portfolio_val > 0 else 0.0 for t, v in target_dollars.items()
            }
        else:
            # In the backtest the conviction strength doubles as the Kelly
            # probability proxy (there is no separate calibrated model here);
            # the VOL_TARGET / heuristic modes ignore ``probs``.
            target_weights = _compute_target_weights(
                active,
                strengths,
                vols,
                allocation_mode,
                probs=strengths,
                kelly_fraction=kelly_fraction,
                vol_target_annual=vol_target_annual,
                max_weight=max_position_weight,
            )

            # T10 hook: portfolio vol overlay. Caller's ``vol_overlay_fn``
            # returns a scale factor in (0, 1] that we apply uniformly to the
            # target weights; ``factor >= 1.0`` is a no-op. Hook is responsible
            # for honoring any "enabled" toggle.
            if vol_overlay_fn is not None and target_weights:
                window_lo = max(0, i - 60)
                returns_by_ticker = {
                    t: closes[t].iloc[window_lo : i + 1].pct_change().dropna() for t in tickers_ok
                }
                try:
                    factor = float(vol_overlay_fn(dict(target_weights), returns_by_ticker))
                except Exception as exc:
                    if verbose:
                        log.warning("vol_overlay_fn@%s error: %s", date, exc)
                    factor = 1.0
                if np.isfinite(factor) and 0.0 < factor < 1.0:
                    target_weights = {t: w * factor for t, w in target_weights.items()}

            target_dollars = {t: target_weights.get(t, 0.0) * portfolio_val for t in tickers_ok}

        # ── Rebalance triggers ────────────────────────────────────────────────
        drift_trigger = _needs_drift_rebalance(
            positions=positions,
            prices=prices,
            target_weights=target_weights,
            portfolio_val=portfolio_val,
            threshold=drift_threshold,
        )

        do_rebalance = signal_changed or drift_trigger or month_tick

        if do_rebalance:
            reason_parts = []
            if signal_changed:
                reason_parts.append("signal")
                n_reb_signal += 1
            if drift_trigger:
                reason_parts.append("drift")
                n_reb_drift += 1
            if month_tick:
                reason_parts.append("monthly")
                n_reb_month += 1
            if new_entries:
                n_slot_fills += len(new_entries)
            reason = "+".join(reason_parts) or "rebalance"

            cash = _execute_rebalance(
                date=date,
                prices=prices,
                positions=positions,
                target_dollars=target_dollars,
                cash=cash,
                commission=commission,
                slippage=slippage,
                reason=reason,
                trades_log=trades_log,
                forced_exit_reasons=forced_exit_reasons,
                exit_fill_prices=exit_fill_prices,
            )
            last_rebalance_month = (date.year, date.month)

        # Update last_signal cache
        last_signal = signals

        # Mark-to-market at end of bar
        portfolio_val = cash + sum(positions[t].shares * prices[t] for t in tickers_ok)
        equity.iloc[i] = portfolio_val

    # ── Force-close at the last bar ────────────────────────────────────────────
    last_date = master_idx[-1]
    last_prices = {t: float(closes[t].iloc[-1]) for t in tickers_ok}
    cash = _execute_rebalance(
        date=last_date,
        prices=last_prices,
        positions=positions,
        target_dollars={t: 0.0 for t in tickers_ok},
        cash=cash,
        commission=commission,
        slippage=slippage,
        reason="forced close (end)",
        trades_log=trades_log,
    )
    equity.iloc[-1] = cash

    # ── Metrics ────────────────────────────────────────────────────────────────
    equity = equity.ffill().fillna(initial_capital)
    daily_ret = equity.pct_change().dropna()
    total_ret = equity.iloc[-1] / initial_capital - 1
    cagr = _cagr(equity)
    vol_pct = _annual_vol(daily_ret)
    sharpe = _sharpe(daily_ret)
    sortino = _sortino(daily_ret)
    max_dd = _max_drawdown(equity)

    # Trade stats
    n_tr = len(trades_log)
    if n_tr > 0:
        wins = [t for t in trades_log if t.is_win]
        losses = [t for t in trades_log if not t.is_win]
        win_rate = len(wins) / n_tr
        sum_w = sum(t.pnl for t in wins)
        sum_l = abs(sum(t.pnl for t in losses))
        profit_factor = (sum_w / sum_l) if sum_l > 0 else float("inf")
        avg_win_pct = float(np.mean([t.return_pct for t in wins])) if wins else 0.0
        avg_loss_pct = float(np.mean([t.return_pct for t in losses])) if losses else 0.0
        avg_hold = float(np.mean([t.holding_days for t in trades_log]))
    else:
        win_rate = profit_factor = avg_win_pct = avg_loss_pct = avg_hold = 0.0

    # ── Buy-and-hold equal-weight benchmark ──────────────────────────────────
    per_ticker = (initial_capital * (1 - commission)) / len(tickers_ok)
    bh_shares = {t: per_ticker / closes[t].iloc[0] for t in tickers_ok}
    bh_equity = pd.Series(0.0, index=master_idx)
    for t in tickers_ok:
        bh_equity = bh_equity.add(closes[t] * bh_shares[t], fill_value=0.0)
    bh_equity.iloc[-1] = bh_equity.iloc[-1] * (1 - commission)
    bh_daily = bh_equity.pct_change().dropna()

    bh_ret = bh_equity.iloc[-1] / initial_capital - 1
    bh_cagr = _cagr(bh_equity)
    bh_sharpe = _sharpe(bh_daily)
    bh_max_dd = _max_drawdown(bh_equity)

    return PortfolioBacktestResult(
        strategy_name=strategy_name,
        allocation_mode=allocation_mode.value,
        tickers=tickers_ok,
        max_positions=int(max_positions),
        start_date=master_idx[0],
        end_date=master_idx[-1],
        initial_capital=float(initial_capital),
        final_equity=float(equity.iloc[-1]),
        total_return_pct=float(total_ret),
        cagr=float(cagr),
        volatility=float(vol_pct),
        sharpe=float(sharpe),
        sortino=float(sortino),
        max_drawdown=float(max_dd),
        equity_curve=equity,
        trades=trades_log,
        n_trades=int(n_tr),
        win_rate=float(win_rate),
        profit_factor=float(profit_factor) if np.isfinite(profit_factor) else 9999.0,
        avg_win_pct=float(avg_win_pct),
        avg_loss_pct=float(avg_loss_pct),
        avg_holding_days=float(avg_hold),
        n_rebalances_signal=int(n_reb_signal),
        n_rebalances_drift=int(n_reb_drift),
        n_rebalances_month=int(n_reb_month),
        n_slot_fills=int(n_slot_fills),
        n_breaker_suppressed=int(n_breaker_suppressed),
        bh_return_pct=float(bh_ret),
        bh_cagr=float(bh_cagr),
        bh_sharpe=float(bh_sharpe),
        bh_max_drawdown=float(bh_max_dd),
        bh_equity_curve=bh_equity,
        alpha_pct=float(total_ret - bh_ret),
        commission=float(commission),
        slippage=float(slippage),
        drift_threshold=float(drift_threshold),
        monthly_rebalance=bool(monthly_rebalance),
        step=int(step),
        warnings=load_warnings,
    )


# ── Comparator across allocation modes ────────────────────────────────────────


def compare_allocation_modes(
    signal_fn: SignalFn,
    *,
    tickers: list[str],
    data: dict[str, pd.DataFrame] | None = None,
    period: str = "2y",
    modes: list[AllocationMode] | None = None,
    **kwargs,
) -> dict[str, PortfolioBacktestResult]:
    """
    Run the same strategy under several allocation modes and return a dict
    keyed by mode.value. All kwargs are passed through to portfolio_backtest.
    Data is loaded once and reused to keep the comparison apples-to-apples.
    """
    modes = modes or list(AllocationMode)

    # Preload once (avoid re-fetching per mode)
    if data is None:
        frames, _ = _load_prices(tickers, None, period)
        data = frames

    results: dict[str, PortfolioBacktestResult] = {}
    for mode in modes:
        r = portfolio_backtest(
            signal_fn,
            tickers=tickers,
            data=data,
            period=period,
            allocation_mode=mode,
            **kwargs,
        )
        if r is not None:
            results[mode.value] = r
    return results


# ── Report formatters ─────────────────────────────────────────────────────────


def format_portfolio_report(r: PortfolioBacktestResult) -> str:
    """Human-readable multi-line report for a single allocation-mode run."""

    def pct(x: float) -> str:
        return f"{x * 100:+.2f}%"

    def num(x: float) -> str:
        return f"{x:+.2f}"

    lines = []
    lines.append(f"Portfolio backtest: {r.strategy_name}  ·  modo: {r.allocation_mode}")
    lines.append(f"Universo: {len(r.tickers)} tickers  ·  max_positions: {r.max_positions}")
    lines.append(
        f"Período: {r.start_date.date()} → {r.end_date.date()}  "
        f"(comisión {r.commission * 100:.2f}%, slippage {r.slippage * 100:.2f}%, "
        f"step={r.step})"
    )
    lines.append(f"Capital inicial: ${r.initial_capital:,.0f}  →  final: ${r.final_equity:,.0f}")
    lines.append("")
    lines.append(f"{'Métrica':<22} {'Estrategia':>14}    {'B&H eq-wt':>14}")
    lines.append("─" * 58)
    lines.append(f"{'Retorno total':<22} {pct(r.total_return_pct):>14}    {pct(r.bh_return_pct):>14}")
    lines.append(f"{'CAGR':<22} {pct(r.cagr):>14}    {pct(r.bh_cagr):>14}")
    lines.append(f"{'Volatilidad anual':<22} {r.volatility:>13.2f}%    {'—':>14}")
    lines.append(f"{'Sharpe':<22} {num(r.sharpe):>14}    {num(r.bh_sharpe):>14}")
    lines.append(f"{'Sortino':<22} {num(r.sortino):>14}    {'—':>14}")
    lines.append(f"{'Max Drawdown':<22} {pct(r.max_drawdown):>14}    {pct(r.bh_max_drawdown):>14}")
    lines.append(f"{'Alpha vs B&H':<22} {pct(r.alpha_pct):>14}")
    lines.append("")
    lines.append("Rebalances")
    lines.append("─" * 58)
    lines.append(f"  Por señal:             {r.n_rebalances_signal}")
    lines.append(f"  Por drift:             {r.n_rebalances_drift}")
    lines.append(f"  Mensual:               {r.n_rebalances_month}")
    lines.append(f"  Slot fills (altas):    {r.n_slot_fills}")
    lines.append("")
    lines.append("Trades")
    lines.append("─" * 58)
    if r.n_trades == 0:
        lines.append("  Sin operaciones cerradas.")
    else:
        pf = f"{r.profit_factor:.2f}" if r.profit_factor < 9999 else "∞"
        lines.append(f"  Nº de trades cerrados: {r.n_trades}")
        lines.append(f"  Win rate:              {r.win_rate * 100:.1f}%")
        lines.append(f"  Profit factor:         {pf}")
        lines.append(f"  Ganancia media:        {r.avg_win_pct * 100:+.2f}%")
        lines.append(f"  Pérdida media:         {r.avg_loss_pct * 100:+.2f}%")
        lines.append(f"  Duración media:        {r.avg_holding_days:.0f} días")

    if r.warnings:
        lines.append("")
        lines.append("Avisos de carga de datos:")
        for w in r.warnings:
            lines.append(f"  - {w}")

    return "\n".join(lines)


def format_portfolio_comparison(results: dict[str, PortfolioBacktestResult]) -> str:
    """
    Side-by-side comparison table across allocation modes.

    Intended to be printed after ``compare_allocation_modes(...)`` — shows
    the key metrics stacked so the user can see which mode won.
    """
    if not results:
        return "(sin resultados)"

    modes = list(results.keys())
    rows = [
        ("Retorno total", lambda r: f"{r.total_return_pct * 100:+.2f}%"),
        ("CAGR", lambda r: f"{r.cagr * 100:+.2f}%"),
        ("Volatilidad", lambda r: f"{r.volatility:.2f}%"),
        ("Sharpe", lambda r: f"{r.sharpe:+.2f}"),
        ("Sortino", lambda r: f"{r.sortino:+.2f}"),
        ("Max DD", lambda r: f"{r.max_drawdown * 100:+.2f}%"),
        ("Alpha vs B&H", lambda r: f"{r.alpha_pct * 100:+.2f}%"),
        ("# Trades", lambda r: f"{r.n_trades}"),
        ("Win rate", lambda r: f"{r.win_rate * 100:.1f}%"),
        ("Rebal. señal", lambda r: f"{r.n_rebalances_signal}"),
        ("Rebal. drift", lambda r: f"{r.n_rebalances_drift}"),
        ("Rebal. mensual", lambda r: f"{r.n_rebalances_month}"),
    ]

    any_r = next(iter(results.values()))
    header_left = "Métrica"
    col_w = max(14, max(len(m) for m in modes) + 2)

    lines = []
    lines.append(f"Comparación de modos de asignación  ·  {any_r.strategy_name}")
    lines.append(
        f"Universo: {len(any_r.tickers)} tickers  ·  max_positions: {any_r.max_positions}  "
        f"·  período: {any_r.start_date.date()} → {any_r.end_date.date()}"
    )
    lines.append("")

    header = f"{header_left:<18}" + "".join(f"{m:>{col_w}}" for m in modes)
    lines.append(header)
    lines.append("─" * len(header))

    for label, fn in rows:
        row_str = f"{label:<18}" + "".join(f"{fn(results[m]):>{col_w}}" for m in modes)
        lines.append(row_str)

    # Identify winner by CAGR for a quick summary
    winner = max(modes, key=lambda m: results[m].cagr)
    lines.append("")
    lines.append(
        f"🏆 Ganador por CAGR: {winner}  "
        f"({results[winner].cagr * 100:+.2f}%, "
        f"Sharpe {results[winner].sharpe:+.2f}, "
        f"MaxDD {results[winner].max_drawdown * 100:+.2f}%)"
    )

    return "\n".join(lines)


# Sprint 4 / T05 — cross-sectional ranking wired in portfolio_backtest() at the
# candidate ranking step. See docs/sprint4_t05_cross_sectional_spec.md.
