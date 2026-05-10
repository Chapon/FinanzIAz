"""
Equity-curve chart widget for the paper-trading tab.

Used to live as ``_EquityCurveChart`` inside ``paper_tab.py`` — extracted
into its own module so it can be tested in isolation and reused (e.g. by
a future "compare two accounts" view).
"""
from __future__ import annotations

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ui.styles import CHART_STYLE, PALETTE


class EquityCurveChart(QWidget):
    """
    Minimal line chart for the equity curve. Supports incremental updates
    when a new snapshot is appended to an existing series, falling back to
    a full redraw when the data identity changes (account switch, history
    rewrite, etc.).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        for k, v in CHART_STYLE.items():
            try:
                matplotlib.rcParams[k] = v
            except Exception:
                pass
        self.figure = Figure(figsize=(8, 3), tight_layout=True)
        self.figure.patch.set_facecolor(CHART_STYLE["figure.facecolor"])
        self.canvas = FigureCanvas(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)
        self._style_axes()
        self._render_empty()

        # Incremental-update state
        self._line = None            # Line2D artist (kept between refreshes)
        self._fill = None            # PolyCollection from fill_between
        self._plotted_count = 0      # number of snapshots in last render
        self._first_xs = None        # first snapshot timestamp (series identity key)

    # ── Styling helpers ──────────────────────────────────────────────────────
    def _style_axes(self) -> None:
        self.ax.set_facecolor(CHART_STYLE["axes.facecolor"])
        self.ax.tick_params(colors=CHART_STYLE["xtick.color"], labelsize=9)
        for spine in ("top", "right"):
            self.ax.spines[spine].set_visible(False)
        for spine in ("bottom", "left"):
            self.ax.spines[spine].set_color(CHART_STYLE["axes.edgecolor"])
        self.ax.grid(
            True, color=CHART_STYLE["grid.color"],
            alpha=CHART_STYLE["grid.alpha"], linewidth=0.5,
        )

    def _render_empty(self) -> None:
        self.ax.clear()
        self._style_axes()
        self.ax.text(
            0.5, 0.5, "Sin datos de equity todavía.",
            transform=self.ax.transAxes,
            color=PALETTE["text3"], ha="center", va="center", fontsize=11,
        )
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.canvas.draw()

    # ── Public API ───────────────────────────────────────────────────────────
    def set_data(self, snapshots: list) -> None:
        """Render the equity curve from a list of ``PaperEquitySnapshot``."""
        if not snapshots:
            if self._plotted_count > 0:
                self._line = None
                self._fill = None
                self._plotted_count = 0
                self._first_xs = None
                self._render_empty()
            return

        xs = [s.snapshot_at for s in snapshots]
        ys = [float(s.total_equity) for s in snapshots]

        # Incremental update when appending to the same series; full redraw otherwise.
        same_series = (
            self._line is not None
            and self._plotted_count > 0
            and len(snapshots) >= self._plotted_count
            and self._first_xs == xs[0]
        )

        if same_series:
            self._incremental_update(xs, ys)
        else:
            self._full_redraw(xs, ys)

        self._plotted_count = len(snapshots)
        self._first_xs = xs[0]

    # ── Drawing internals ────────────────────────────────────────────────────
    def _full_redraw(self, xs: list, ys: list) -> None:
        self.ax.clear()
        self._style_axes()
        self._line, = self.ax.plot(xs, ys, color=PALETTE["accent"], linewidth=1.8)
        self._fill = self.ax.fill_between(
            xs, ys, min(ys), color=PALETTE["accent"], alpha=0.12,
        )
        if len(ys) > 1:
            self.ax.axhline(
                ys[0], color=PALETTE["text3"],
                linestyle="--", linewidth=0.6, alpha=0.7,
            )
        self.ax.set_ylabel("Equity ($)", color=PALETTE["text2"], fontsize=10)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
        self.figure.autofmt_xdate(rotation=15)
        self.canvas.draw()

    def _incremental_update(self, xs: list, ys: list) -> None:
        self._line.set_data(xs, ys)
        if self._fill is not None:
            self._fill.remove()
        self._fill = self.ax.fill_between(
            xs, ys, min(ys), color=PALETTE["accent"], alpha=0.12,
        )
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def cleanup(self) -> None:
        """Drop references to matplotlib artists so the figure can be GC'd."""
        try:
            self.figure.clear()
        except Exception:
            pass
        self._line = None
        self._fill = None
        self._plotted_count = 0
        self._first_xs = None

    def closeEvent(self, event):  # noqa: N802 — Qt naming
        self.cleanup()
        super().closeEvent(event)
