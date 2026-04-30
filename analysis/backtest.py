"""
Single-ticker backtesting framework for FinanzIAs.

Design
------
The core abstraction is a **signal function**:

    signal_fn(df_upto_t: pd.DataFrame) -> "BUY" | "SELL" | "HOLD"

It must return the trading decision at time t using ONLY the data available
up to and including t (zero look-ahead). The engine calls this function at
each bar (or every `step` bars) and simulates long-only entries/exits with
configurable commission and slippage.

Three convenience factories wrap existing FinanzIAs components:

  • signal_from_analyze        — overall_signal of analyze()
  • signal_from_ml_probability — threshold on ml_probability
  • signal_from_indicator      — signal of a single indicator by name
                                 (e.g. "RSI", "MACD", "HMM Régimen",
                                  "GARCH Volatilidad", "XGBoost ML")

Metrics
-------
Returns + equity curve, risk (volatility, Sharpe, Sortino, max drawdown),
trade stats (win rate, profit factor, average win/loss, holding period),
and a buy-and-hold benchmark with the same metrics for comparison.

No look-ahead: the engine never peeks beyond `df.iloc[:t+1]` when calling
signal_fn, and all executions happen at the close of bar t with slippage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Callable, Optional


# ── Data classes ──────────────────────────────────────────────────────────────

SignalFn = Callable[[pd.DataFrame], str]


@dataclass
class Trade:
    entry_date:   pd.Timestamp
    exit_date:    pd.Timestamp
    entry_price:  float   # execution price including slippage
    exit_price:   float   # execution price including slippage
    return_pct:   float   # net of commission on both legs
    holding_days: int

    @property
    def is_win(self) -> bool:
        return self.return_pct > 0


@dataclass
class BacktestResult:
    ticker:           str
    strategy_name:    str
    start_date:       pd.Timestamp
    end_date:         pd.Timestamp
    initial_capital:  float
    final_equity:     float
    # Strategy performance
    total_return_pct: float
    cagr:             float
    volatility:       float   # annualised daily-return vol (%)
    sharpe:           float
    sortino:          float
    max_drawdown:     float   # negative number, e.g. -0.23 = -23%
    equity_curve:     pd.Series
    # Trades
    trades:           list[Trade] = field(default_factory=list)
    n_trades:         int   = 0
    win_rate:         float = 0.0
    profit_factor:    float = 0.0
    avg_win:          float = 0.0
    avg_loss:         float = 0.0
    avg_holding_days: float = 0.0
    # Buy-and-hold benchmark
    bh_return_pct:    float = 0.0
    bh_cagr:          float = 0.0
    bh_sharpe:        float = 0.0
    bh_max_drawdown:  float = 0.0
    bh_equity_curve:  Optional[pd.Series] = None
    alpha_pct:        float = 0.0  # total_return_pct - bh_return_pct
    # Config snapshot
    commission:       float = 0.0
    slippage:         float = 0.0
    step:             int   = 1


# ── Metric helpers ────────────────────────────────────────────────────────────

TRADING_DAYS = 252


def _cagr(equity: pd.Series) -> float:
    """Compound annual growth rate from an equity curve."""
    if len(equity) < 2:
        return 0.0
    total_ret = equity.iloc[-1] / equity.iloc[0] - 1
    n_days    = (equity.index[-1] - equity.index[0]).days
    if n_days <= 0:
        return 0.0
    years = n_days / 365.25
    base  = 1.0 + total_ret
    if base <= 0:
        return -1.0  # wiped out
    return float(base ** (1.0 / years) - 1.0)


def _max_drawdown(equity: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a negative fraction (e.g. -0.23)."""
    if len(equity) < 2:
        return 0.0
    running_max = equity.cummax()
    drawdown    = (equity - running_max) / running_max
    return float(drawdown.min())


def _sharpe(daily_returns: pd.Series, rf: float = 0.0) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mu    = daily_returns.mean() - rf / TRADING_DAYS
    sigma = daily_returns.std()
    if sigma == 0 or np.isnan(sigma):
        return 0.0
    return float(mu / sigma * np.sqrt(TRADING_DAYS))


def _sortino(daily_returns: pd.Series, rf: float = 0.0) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mu       = daily_returns.mean() - rf / TRADING_DAYS
    downside = daily_returns[daily_returns < 0]
    if len(downside) < 2:
        return 0.0
    dstd = downside.std()
    if dstd == 0 or np.isnan(dstd):
        return 0.0
    return float(mu / dstd * np.sqrt(TRADING_DAYS))


def _annual_vol(daily_returns: pd.Series) -> float:
    if len(daily_returns) < 2:
        return 0.0
    v = float(daily_returns.std() * np.sqrt(TRADING_DAYS) * 100)
    return v if not np.isnan(v) else 0.0


# ── Core backtest loop ────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    signal_fn: SignalFn,
    *,
    ticker: str             = "TICKER",
    strategy_name: str      = "Custom",
    initial_capital: float  = 10_000.0,
    commission: float       = 0.001,   # 0.10 % per fill
    slippage: float         = 0.0005,  # 0.05 % adverse to the direction
    warmup: int             = 200,     # bars required before first decision
    step: int               = 1,       # re-evaluate signal every N bars
    verbose: bool           = False,
) -> Optional[BacktestResult]:
    """
    Run a long-only single-ticker backtest.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with a DatetimeIndex. Must contain a 'Close' column.
    signal_fn : callable
        Takes a DataFrame slice (up to and including t) and returns
        "BUY" / "SELL" / "HOLD".
    warmup : int
        Number of bars the signal function may need before producing its
        first meaningful decision. The loop starts at index = warmup.
    step : int
        Re-evaluate the signal every `step` bars. Between evaluations the
        position is held. Useful to speed up expensive ML signals.

    Returns
    -------
    BacktestResult or None if df has too few rows.
    """
    if df is None or len(df) < warmup + 10:
        return None
    if "Close" not in df.columns:
        return None

    close = df["Close"].astype(float).squeeze()
    n = len(close)

    # ── Simulation state ──────────────────────────────────────────────────────
    cash         = float(initial_capital)
    shares       = 0.0
    in_position  = False
    entry_date   = None
    entry_price  = 0.0
    trades: list[Trade] = []

    equity = pd.Series(index=close.index, dtype=float)
    last_signal = "HOLD"

    for i in range(n):
        date   = close.index[i]
        price  = float(close.iloc[i])

        # ── Signal evaluation (respect warmup and step) ──────────────────────
        if i >= warmup and (i - warmup) % max(1, step) == 0:
            try:
                sig = signal_fn(df.iloc[:i + 1])
            except Exception as exc:
                if verbose:
                    print(f"[backtest] signal_fn error at {date}: {exc}")
                sig = "HOLD"
            if sig not in ("BUY", "SELL", "HOLD"):
                sig = "HOLD"
            last_signal = sig
        else:
            sig = "HOLD"

        # ── Execution at this bar's close ────────────────────────────────────
        if sig == "BUY" and not in_position:
            fill_price  = price * (1 + slippage)
            # commission reduces shares purchased
            shares      = (cash * (1 - commission)) / fill_price
            cash        = 0.0
            entry_date  = date
            entry_price = fill_price
            in_position = True

        elif sig == "SELL" and in_position:
            fill_price = price * (1 - slippage)
            proceeds   = shares * fill_price * (1 - commission)
            ret_pct    = proceeds / (shares * entry_price) - 1
            holding    = (date - entry_date).days
            trades.append(Trade(
                entry_date   = entry_date,
                exit_date    = date,
                entry_price  = entry_price,
                exit_price   = fill_price,
                return_pct   = float(ret_pct),
                holding_days = int(holding),
            ))
            cash        = proceeds
            shares      = 0.0
            in_position = False

        # Mark-to-market equity at this bar's close
        equity.iloc[i] = cash + shares * price

    # ── Force-close any open position at the last bar ────────────────────────
    if in_position:
        last_price = float(close.iloc[-1]) * (1 - slippage)
        proceeds   = shares * last_price * (1 - commission)
        ret_pct    = proceeds / (shares * entry_price) - 1
        holding    = (close.index[-1] - entry_date).days
        trades.append(Trade(
            entry_date   = entry_date,
            exit_date    = close.index[-1],
            entry_price  = entry_price,
            exit_price   = last_price,
            return_pct   = float(ret_pct),
            holding_days = int(holding),
        ))
        cash   = proceeds
        shares = 0.0
        equity.iloc[-1] = cash

    # ── Metrics ──────────────────────────────────────────────────────────────
    equity = equity.ffill().fillna(initial_capital)
    daily_ret = equity.pct_change().dropna()

    total_ret = equity.iloc[-1] / initial_capital - 1
    cagr      = _cagr(equity)
    vol_pct   = _annual_vol(daily_ret)
    sharpe    = _sharpe(daily_ret)
    sortino   = _sortino(daily_ret)
    max_dd    = _max_drawdown(equity)

    # Trade stats
    n_tr = len(trades)
    if n_tr > 0:
        wins   = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]
        win_rate   = len(wins) / n_tr
        sum_wins   = sum(t.return_pct for t in wins)
        sum_losses = abs(sum(t.return_pct for t in losses))
        profit_factor = (sum_wins / sum_losses) if sum_losses > 0 else float("inf")
        avg_win    = float(np.mean([t.return_pct for t in wins]))   if wins   else 0.0
        avg_loss   = float(np.mean([t.return_pct for t in losses])) if losses else 0.0
        avg_hold   = float(np.mean([t.holding_days for t in trades]))
    else:
        win_rate = profit_factor = avg_win = avg_loss = avg_hold = 0.0

    # ── Buy-and-hold benchmark ───────────────────────────────────────────────
    bh_shares = initial_capital * (1 - commission) / close.iloc[0]
    bh_equity = close * bh_shares
    bh_equity.iloc[-1] = bh_equity.iloc[-1] * (1 - commission)  # exit fee
    bh_daily_ret = bh_equity.pct_change().dropna()

    bh_total_ret = bh_equity.iloc[-1] / initial_capital - 1
    bh_cagr      = _cagr(bh_equity)
    bh_sharpe    = _sharpe(bh_daily_ret)
    bh_max_dd    = _max_drawdown(bh_equity)

    return BacktestResult(
        ticker          = ticker,
        strategy_name   = strategy_name,
        start_date      = close.index[0],
        end_date        = close.index[-1],
        initial_capital = float(initial_capital),
        final_equity    = float(equity.iloc[-1]),
        total_return_pct = float(total_ret),
        cagr             = float(cagr),
        volatility       = float(vol_pct),
        sharpe           = float(sharpe),
        sortino          = float(sortino),
        max_drawdown     = float(max_dd),
        equity_curve     = equity,
        trades           = trades,
        n_trades         = n_tr,
        win_rate         = float(win_rate),
        profit_factor    = float(profit_factor) if np.isfinite(profit_factor) else 9999.0,
        avg_win          = float(avg_win),
        avg_loss         = float(avg_loss),
        avg_holding_days = float(avg_hold),
        bh_return_pct    = float(bh_total_ret),
        bh_cagr          = float(bh_cagr),
        bh_sharpe        = float(bh_sharpe),
        bh_max_drawdown  = float(bh_max_dd),
        bh_equity_curve  = bh_equity,
        alpha_pct        = float(total_ret - bh_total_ret),
        commission       = float(commission),
        slippage         = float(slippage),
        step             = int(step),
    )


# ── Signal function factories ─────────────────────────────────────────────────

def signal_from_analyze(
    enable_sma_cross: bool = True,
    enable_volume:    bool = True,
    enable_xgboost:   bool = True,
) -> SignalFn:
    """
    Wrap analyze() as a signal function: returns the overall_signal.

    Note: with enable_xgboost=True this is very slow because XGBoost/HMM/GARCH
    are trained for every evaluation. For long backtests consider step >= 5
    or enable_xgboost=False.
    """
    from analysis.technical import analyze

    def _fn(df_slice: pd.DataFrame) -> str:
        res = analyze(
            "BT", df_slice,
            enable_sma_cross = enable_sma_cross,
            enable_volume    = enable_volume,
            enable_xgboost   = enable_xgboost,
        )
        return res.overall_signal if res else "HOLD"

    return _fn


def signal_from_ml_probability(
    buy_threshold:  float = 0.60,
    sell_threshold: float = 0.45,
) -> SignalFn:
    """
    Threshold strategy on the regime-adjusted ml_probability.
    BUY when prob ≥ buy_threshold, SELL when prob ≤ sell_threshold, else HOLD.
    """
    from analysis.technical import analyze

    def _fn(df_slice: pd.DataFrame) -> str:
        res = analyze("BT", df_slice, enable_xgboost=True)
        if res is None or res.ml_probability is None:
            return "HOLD"
        p = res.ml_probability
        if p >= buy_threshold:  return "BUY"
        if p <= sell_threshold: return "SELL"
        return "HOLD"

    return _fn


# Indicators that require the ML block in analyze() to be computed
_ML_INDICATORS = {"XGBoost ML", "HMM Régimen", "GARCH Volatilidad"}


def signal_from_indicator(indicator_name: str) -> SignalFn:
    """
    Extract the raw BUY/SELL/HOLD of a single TechnicalSignal by name.

    Accepted names (must match TechnicalSignal.indicator exactly):
      "RSI", "MACD", "Bollinger Bands", "Golden/Death Cross", "Volumen",
      "XGBoost ML", "HMM Régimen", "GARCH Volatilidad".
    """
    from analysis.technical import analyze

    needs_ml = indicator_name in _ML_INDICATORS

    def _fn(df_slice: pd.DataFrame) -> str:
        res = analyze("BT", df_slice, enable_xgboost=needs_ml)
        if res is None:
            return "HOLD"
        for s in res.signals:
            if s.indicator == indicator_name:
                return s.signal
        return "HOLD"

    return _fn


# ── Plain-text report ─────────────────────────────────────────────────────────

def format_backtest_report(r: BacktestResult) -> str:
    """Return a human-readable multi-line report comparing strategy vs B&H."""
    def pct(x: float) -> str: return f"{x*100:+.2f}%"
    def num(x: float) -> str: return f"{x:+.2f}"

    lines = []
    lines.append(f"Backtest: {r.strategy_name} on {r.ticker}")
    lines.append(f"Período: {r.start_date.date()} → {r.end_date.date()}  "
                 f"(comisión {r.commission*100:.2f}%, slippage {r.slippage*100:.2f}%, step={r.step})")
    lines.append(f"Capital inicial: ${r.initial_capital:,.0f}  "
                 f"→  final: ${r.final_equity:,.0f}")
    lines.append("")
    lines.append(f"{'Métrica':<22} {'Estrategia':>14}    {'Buy & Hold':>14}")
    lines.append("─" * 58)
    lines.append(f"{'Retorno total':<22} {pct(r.total_return_pct):>14}    {pct(r.bh_return_pct):>14}")
    lines.append(f"{'CAGR':<22} {pct(r.cagr):>14}    {pct(r.bh_cagr):>14}")
    lines.append(f"{'Volatilidad anual':<22} {r.volatility:>13.2f}%    {'—':>14}")
    lines.append(f"{'Sharpe':<22} {num(r.sharpe):>14}    {num(r.bh_sharpe):>14}")
    lines.append(f"{'Sortino':<22} {num(r.sortino):>14}    {'—':>14}")
    lines.append(f"{'Max Drawdown':<22} {pct(r.max_drawdown):>14}    {pct(r.bh_max_drawdown):>14}")
    lines.append(f"{'Alpha vs B&H':<22} {pct(r.alpha_pct):>14}")
    lines.append("")
    lines.append("Trades")
    lines.append("─" * 58)
    if r.n_trades == 0:
        lines.append("  Sin operaciones ejecutadas.")
    else:
        pf = f"{r.profit_factor:.2f}" if r.profit_factor < 9999 else "∞"
        lines.append(f"  Nº de trades:         {r.n_trades}")
        lines.append(f"  Win rate:             {r.win_rate*100:.1f}%")
        lines.append(f"  Profit factor:        {pf}")
        lines.append(f"  Ganancia media:       {r.avg_win*100:+.2f}%")
        lines.append(f"  Pérdida media:        {r.avg_loss*100:+.2f}%")
        lines.append(f"  Duración media:       {r.avg_holding_days:.0f} días")

    return "\n".join(lines)
