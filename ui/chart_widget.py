"""
Embedded matplotlib chart widget for PyQt6.
Renders candlestick / line charts with technical indicator overlays.

Hover support:
  - Emits hover_data(dict) with per-day indicator values while mouse is over any subplot.
  - Emits hover_data(None) when mouse leaves the figure.
  - Draws a vertical crosshair across all 3 subplots on hover.
"""
import math
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import pandas as pd
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal
from analysis.technical import (
    compute_rsi, compute_macd, compute_bollinger_bands, compute_sma, compute_ema,
    get_cached_indicators,
)
from ui.styles import CHART_STYLE


def _apply_style(ax):
    for k, v in CHART_STYLE.items():
        try:
            plt.rcParams[k] = v
        except Exception:
            pass
    ax.set_facecolor(CHART_STYLE["axes.facecolor"])
    ax.tick_params(colors=CHART_STYLE["xtick.color"])
    ax.spines["bottom"].set_color(CHART_STYLE["axes.edgecolor"])
    ax.spines["left"].set_color(CHART_STYLE["axes.edgecolor"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, color=CHART_STYLE["grid.color"], alpha=CHART_STYLE["grid.alpha"], linewidth=0.5)


class ChartWidget(QWidget):
    """A PyQt6 widget that embeds a matplotlib figure."""

    # Emits dict of {date, close, rsi, macd_line, …} on hover; None on leave.
    hover_data = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(figsize=(10, 7), tight_layout=True)
        self.figure.patch.set_facecolor(CHART_STYLE["figure.facecolor"])
        self.canvas = FigureCanvas(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        # Hover / crosshair state
        self._vlines: list = []         # active Line2D crosshair objects
        self._has_crosshair: bool = False
        self._hover_data: dict | None = None    # indicator Series dict after last plot
        self._date_nums: np.ndarray | None = None  # matplotlib float dates for lookup
        self._axes: list = []           # [ax_price, ax_rsi, ax_macd]

        # Connect matplotlib mouse events once (persists across replots)
        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_move)
        self.canvas.mpl_connect('figure_leave_event', self._on_figure_leave)

    # ── Main plot ──────────────────────────────────────────────────────────────

    def plot_price_with_indicators(self, ticker: str, df: pd.DataFrame, show_bb: bool = True):
        """Plot price line + Bollinger Bands + SMA overlays + RSI + MACD panels."""
        self.figure.clear()
        self._vlines = []
        self._has_crosshair = False

        # Layout: price chart (3 parts) + RSI (1 part) + MACD (1 part)
        gs = self.figure.add_gridspec(3, 1, height_ratios=[3, 1, 1], hspace=0.08)
        ax_price = self.figure.add_subplot(gs[0])
        ax_rsi   = self.figure.add_subplot(gs[1], sharex=ax_price)
        ax_macd  = self.figure.add_subplot(gs[2], sharex=ax_price)
        self._axes = [ax_price, ax_rsi, ax_macd]

        close = df["Close"].squeeze()
        dates = df.index

        # Retrieve (or compute) all indicators from the shared LRU cache.
        # If analyze() was already called for this ticker+dataset, this is free.
        indic = get_cached_indicators(ticker, df)
        sma20                            = indic['sma20']
        sma50                            = indic['sma50']
        upper, middle, lower             = indic['bollinger']
        rsi                              = indic['rsi']
        macd_line, signal_line, histogram = indic['macd']

        # ── Price ──────────────────────────────────────────────────────────────
        _apply_style(ax_price)
        ax_price.plot(dates, close, color="#58a6ff", linewidth=1.5, label="Precio")

        if sma20 is not None:
            ax_price.plot(dates, sma20, color="#d29922", linewidth=1, alpha=0.8, label="SMA 20")
        if sma50 is not None:
            ax_price.plot(dates, sma50, color="#f78166", linewidth=1, alpha=0.8, label="SMA 50")

        # ── Bollinger Bands ────────────────────────────────────────────────────
        if show_bb and upper is not None:
            ax_price.fill_between(dates, upper, lower, alpha=0.08, color="#58a6ff", label="Bollinger")
            ax_price.plot(dates, upper, color="#58a6ff", linewidth=0.6, alpha=0.4, linestyle="--")
            ax_price.plot(dates, lower, color="#58a6ff", linewidth=0.6, alpha=0.4, linestyle="--")

        ax_price.set_ylabel("Precio", color=CHART_STYLE["axes.labelcolor"], fontsize=11)
        ax_price.set_title(
            f"  {ticker}", color="#e6edf3", fontsize=13, fontweight="bold", loc="left", pad=8
        )
        ax_price.legend(
            loc="upper left", fontsize=9,
            facecolor="#161b22", edgecolor="#21262d", labelcolor="#e6edf3"
        )
        plt.setp(ax_price.get_xticklabels(), visible=False)

        # ── RSI ────────────────────────────────────────────────────────────────
        _apply_style(ax_rsi)
        ax_rsi.plot(dates, rsi, color="#a371f7", linewidth=1.2)
        ax_rsi.axhline(70, color="#f85149", linewidth=0.8, linestyle="--", alpha=0.7)
        ax_rsi.axhline(30, color="#3fb950", linewidth=0.8, linestyle="--", alpha=0.7)
        ax_rsi.fill_between(dates, rsi, 70, where=(rsi >= 70), alpha=0.15, color="#f85149")
        ax_rsi.fill_between(dates, rsi, 30, where=(rsi <= 30), alpha=0.15, color="#3fb950")
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_yticks([30, 50, 70])
        ax_rsi.set_ylabel("RSI", color=CHART_STYLE["axes.labelcolor"], fontsize=10)
        plt.setp(ax_rsi.get_xticklabels(), visible=False)

        # ── MACD ───────────────────────────────────────────────────────────────
        _apply_style(ax_macd)
        bar_colors = ["#3fb950" if h >= 0 else "#f85149" for h in histogram.fillna(0)]
        ax_macd.bar(dates, histogram, color=bar_colors, alpha=0.5, width=0.8)
        ax_macd.plot(dates, macd_line, color="#58a6ff", linewidth=1.2, label="MACD")
        ax_macd.plot(dates, signal_line, color="#d29922", linewidth=1.0, label="Signal")
        ax_macd.axhline(0, color="#30363d", linewidth=0.8)
        ax_macd.set_ylabel("MACD", color=CHART_STYLE["axes.labelcolor"], fontsize=10)
        ax_macd.legend(
            loc="upper left", fontsize=8,
            facecolor="#161b22", edgecolor="#21262d", labelcolor="#e6edf3"
        )

        # Format x-axis on bottom panel
        ax_macd.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax_macd.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.figure.autofmt_xdate(rotation=30, ha="right")

        # ── Store indicator series for hover ───────────────────────────────────
        self._hover_data = {
            'dates':       dates,
            'close':       close,
            'rsi':         rsi,
            'macd_line':   macd_line,
            'signal_line': signal_line,
            'histogram':   histogram,
            'upper':       upper,
            'lower':       lower,
            'middle':      middle,
            'sma20':       sma20,
            'sma50':       sma50,
        }
        # Pre-compute float date array for fast argmin lookup
        self._date_nums = np.array(
            mdates.date2num(
                [d.to_pydatetime() if hasattr(d, 'to_pydatetime') else d for d in dates]
            )
        )

        self.canvas.draw()

    # ── Secondary plot ─────────────────────────────────────────────────────────

    def plot_portfolio_history(self, dates, values, label="Valor"):
        """Plot a simple portfolio value over time (no hover crosshair)."""
        self.figure.clear()
        self._hover_data = None
        self._axes = []
        ax = self.figure.add_subplot(111)
        _apply_style(ax)
        ax.plot(dates, values, color="#58a6ff", linewidth=2)
        ax.fill_between(dates, values, alpha=0.1, color="#58a6ff")
        ax.set_title(label, color="#e6edf3", fontsize=13, fontweight="bold", loc="left")
        ax.set_ylabel("Valor (USD)", color=CHART_STYLE["axes.labelcolor"])
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.figure.autofmt_xdate(rotation=30, ha="right")
        self.canvas.draw()

    def clear(self):
        self.figure.clear()
        self._hover_data = None
        self._axes = []
        self.canvas.draw()

    # ── Hover / crosshair ──────────────────────────────────────────────────────

    def _on_mouse_move(self, event):
        """
        Draw a vertical crosshair at the nearest date and emit that day's data.
        Only acts when mouse is inside one of the 3 indicator axes.
        If mouse is between subplots (inaxes=None) the crosshair stays in place.
        """
        if self._hover_data is None or not self._axes:
            return

        # Ignore inter-subplot gaps (inaxes=None means between panels)
        if event.inaxes not in self._axes or event.xdata is None:
            return

        # Remove previous crosshair
        for vl in self._vlines:
            try:
                vl.remove()
            except Exception:
                pass
        self._vlines = []

        # Nearest date index
        idx = int(np.argmin(np.abs(self._date_nums - event.xdata)))
        x_val = self._date_nums[idx]

        # Draw crosshair on all 3 subplots
        for ax in self._axes:
            vl = ax.axvline(
                x=x_val, color='#c9d1d9', linewidth=0.8,
                alpha=0.55, linestyle='-', zorder=10
            )
            self._vlines.append(vl)
        self._has_crosshair = True
        self.canvas.draw_idle()

        # Emit per-day data
        d = self._hover_data

        def _safe(series, i):
            if series is None:
                return None
            try:
                v = float(series.iloc[i])
                return None if math.isnan(v) else v
            except Exception:
                return None

        self.hover_data.emit({
            'idx':         idx,
            'date':        d['dates'][idx],
            'close':       _safe(d['close'], idx),
            'rsi':         _safe(d['rsi'], idx),
            'macd_line':   _safe(d['macd_line'], idx),
            'signal_line': _safe(d['signal_line'], idx),
            'histogram':   _safe(d['histogram'], idx),
            'upper':       _safe(d['upper'], idx),
            'lower':       _safe(d['lower'], idx),
            'middle':      _safe(d['middle'], idx),
            'sma20':       _safe(d['sma20'], idx),
            'sma50':       _safe(d['sma50'], idx),
        })

    def _on_figure_leave(self, event):
        """Clear crosshair and emit None when mouse leaves the figure entirely."""
        for vl in self._vlines:
            try:
                vl.remove()
            except Exception:
                pass
        self._vlines = []
        if self._has_crosshair:
            self._has_crosshair = False
            self.canvas.draw_idle()
        self.hover_data.emit(None)
