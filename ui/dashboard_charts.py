"""
Fuse-style dashboard chart widgets for the Home tab.

Three reusable matplotlib-backed widgets, all themed from ``ui.styles``:

* ``AreaChartHero``  — full-width equity area chart with a gradient fill.
* ``KpiCard``        — big number + delta + a small sparkline (area/bar/spike).
* ``DonutChart``     — portfolio-allocation donut with a percentage legend.

They follow the same embedding pattern as ``ui/paper/equity_chart.py``
(QtAgg canvas + ``CHART_STYLE`` rcParams) so the look stays consistent.
"""

from __future__ import annotations

import contextlib

import matplotlib

matplotlib.use("QtAgg")
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Polygon
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ui.styles import CHART_STYLE, PALETTE

# Pastel triad for categorical charts (cyan / orange / soft-red), then extras.
CATEGORICAL_COLORS = [
    PALETTE["accent"],  # cyan
    PALETTE["orange"],  # orange
    PALETTE["red"],  # soft red
    PALETTE["purple"],  # violet
    PALETTE["blue"],  # blue
    PALETTE["yellow"],  # amber
    PALETTE["positive"],  # green
]


def _apply_chart_rcparams() -> None:
    for k, v in CHART_STYLE.items():
        with contextlib.suppress(Exception):
            matplotlib.rcParams[k] = v


def _gradient_under_line(ax, x_num, ys, color, alpha_top: float = 0.38) -> None:
    """Paint a vertical gradient under the line, clipped to the area polygon.

    ``x_num`` must already be numeric (e.g. ``mdates.date2num`` for dates).
    Falls back to a flat ``fill_between`` if anything goes wrong.
    """
    try:
        xmin, xmax = float(min(x_num)), float(max(x_num))
        ymin, ymax = float(min(ys)), float(max(ys))
        if xmax <= xmin or ymax <= ymin:
            raise ValueError("degenerate extent")

        rgb = mcolors.to_rgb(color)
        grad = np.empty((256, 1, 4), dtype=float)
        grad[:, :, :3] = rgb
        grad[:, :, 3] = np.linspace(0.0, alpha_top, 256)[:, None]  # transparent bottom → tinted top

        im = ax.imshow(
            grad,
            aspect="auto",
            extent=[xmin, xmax, ymin, ymax],
            origin="lower",
            zorder=1,
        )
        verts = np.column_stack([np.asarray(x_num, dtype=float), np.asarray(ys, dtype=float)])
        verts = np.vstack([[xmin, ymin], verts, [xmax, ymin], [xmin, ymin]])
        clip = Polygon(verts, closed=True, facecolor="none", edgecolor="none")
        ax.add_patch(clip)
        im.set_clip_path(clip)
    except Exception:
        ax.fill_between(x_num, ys, min(ys), color=color, alpha=0.12, zorder=1)


# ──────────────────────────────────────────────────────────────────────────
# Hero area chart
# ──────────────────────────────────────────────────────────────────────────
class AreaChartHero(QWidget):
    """Full-width equity area chart with a subtle gradient under the line."""

    def __init__(self, parent=None, height_in: float = 3.2):
        super().__init__(parent)
        _apply_chart_rcparams()
        self.figure = Figure(figsize=(10, height_in), tight_layout=True)
        self.figure.patch.set_facecolor(CHART_STYLE["figure.facecolor"])
        self.canvas = FigureCanvas(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)
        self._style_axes()
        self._render_empty()

    def _style_axes(self) -> None:
        self.ax.set_facecolor(CHART_STYLE["axes.facecolor"])
        self.ax.tick_params(colors=CHART_STYLE["xtick.color"], labelsize=9)
        for spine in ("top", "right"):
            self.ax.spines[spine].set_visible(False)
        for spine in ("bottom", "left"):
            self.ax.spines[spine].set_color(CHART_STYLE["axes.edgecolor"])
        self.ax.grid(True, color=CHART_STYLE["grid.color"], alpha=CHART_STYLE["grid.alpha"], linewidth=0.5)

    def _render_empty(self) -> None:
        self.ax.clear()
        self._style_axes()
        self.ax.text(
            0.5,
            0.5,
            "Sin datos de equity todavía.",
            transform=self.ax.transAxes,
            color=PALETTE["text3"],
            ha="center",
            va="center",
            fontsize=11,
        )
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.canvas.draw()

    def set_data(self, snapshots: list) -> None:
        """Render from a list of ``PaperEquitySnapshot`` (``snapshot_at``/``total_equity``)."""
        if not snapshots:
            self._render_empty()
            return

        xs = [s.snapshot_at for s in snapshots]
        ys = [float(s.total_equity) for s in snapshots]
        x_num = mdates.date2num(xs)

        self.ax.clear()
        self._style_axes()
        self.ax.plot(x_num, ys, color=PALETTE["accent"], linewidth=2.0, zorder=3)
        _gradient_under_line(self.ax, x_num, ys, PALETTE["accent"])
        if len(ys) > 1:
            self.ax.axhline(ys[0], color=PALETTE["text3"], linestyle="--", linewidth=0.6, alpha=0.7)
        self.ax.set_ylabel("Equity ($)", color=PALETTE["text2"], fontsize=10)
        self.ax.xaxis_date()
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
        self.figure.autofmt_xdate(rotation=15)
        self.canvas.draw()

    def cleanup(self) -> None:
        with contextlib.suppress(Exception):
            self.figure.clear()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────────
# Sparkline (used inside KpiCard)
# ──────────────────────────────────────────────────────────────────────────
class _Sparkline(QWidget):
    """Tiny chart with no axes: area, bar, or spike."""

    def __init__(self, kind: str = "area", color: str | None = None, parent=None):
        super().__init__(parent)
        _apply_chart_rcparams()
        self._kind = kind
        self._color = color or PALETTE["accent"]
        self.figure = Figure(figsize=(3.0, 0.85), tight_layout=True)
        self.figure.patch.set_facecolor(CHART_STYLE["figure.facecolor"])
        self.canvas = FigureCanvas(self.figure)
        self.setFixedHeight(58)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)
        self._bare_axes()

    def _bare_axes(self) -> None:
        self.ax.set_facecolor("none")
        self.ax.margins(x=0.01, y=0.18)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in self.ax.spines.values():
            spine.set_visible(False)

    def set_series(self, series: list[float]) -> None:
        self.ax.clear()
        self._bare_axes()
        if not series:
            self.canvas.draw()
            return
        ys = [float(v) for v in series]
        xs = list(range(len(ys)))
        c = self._color
        if self._kind == "bar":
            self.ax.bar(xs, ys, color=c, width=0.7, align="center")
        elif self._kind == "spike":
            self.ax.vlines(xs, 0, ys, color=c, linewidth=1.6)
            self.ax.plot(xs, ys, "o", color=c, markersize=2.2)
        else:  # area
            self.ax.plot(xs, ys, color=c, linewidth=1.8)
            base = min(ys) if len(ys) > 1 else 0
            self.ax.fill_between(xs, ys, base, color=c, alpha=0.18)
        self.canvas.draw()

    def cleanup(self) -> None:
        with contextlib.suppress(Exception):
            self.figure.clear()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────────
# KPI card
# ──────────────────────────────────────────────────────────────────────────
class KpiCard(QFrame):
    """Big metric + delta + a sparkline below — the Fuse KPI tile."""

    def __init__(
        self,
        title: str,
        value: str = "—",
        delta: str = "",
        *,
        delta_positive: bool | None = None,
        kind: str = "area",
        color: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(150)
        color = color or PALETTE["accent"]

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(2)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 11px; font-weight: 700; letter-spacing: 0.6px;"
        )
        root.addWidget(self.title_lbl)

        self.value_lbl = QLabel(value)
        self.value_lbl.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 30px; font-weight: 800;")
        root.addWidget(self.value_lbl)

        self.delta_lbl = QLabel(delta)
        root.addWidget(self.delta_lbl)
        self._set_delta_style(delta_positive)

        root.addSpacing(4)
        self.spark = _Sparkline(kind=kind, color=color)
        root.addWidget(self.spark)

    def _set_delta_style(self, positive: bool | None) -> None:
        if positive is None:
            color = PALETTE["text2"]
        elif positive:
            color = PALETTE["positive"]
        else:
            color = PALETTE["red"]
        self.delta_lbl.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")

    def set_value(self, value: str, delta: str = "", delta_positive: bool | None = None) -> None:
        self.value_lbl.setText(value)
        self.delta_lbl.setText(delta)
        self._set_delta_style(delta_positive)

    def set_series(self, series: list[float]) -> None:
        self.spark.set_series(series)


# ──────────────────────────────────────────────────────────────────────────
# Donut chart
# ──────────────────────────────────────────────────────────────────────────
class DonutChart(QFrame):
    """Allocation donut + percentage legend (replaces 'Sessions by device')."""

    def __init__(self, title: str = "Distribución de cartera", parent=None, max_legend: int = 6):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(240)
        self.setMinimumHeight(260)
        self._max_legend = max_legend
        _apply_chart_rcparams()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(8)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 15px; font-weight: 700;")
        root.addWidget(self.title_lbl)

        self.figure = Figure(figsize=(3.2, 2.4), tight_layout=True)
        self.figure.patch.set_facecolor(CHART_STYLE["figure.facecolor"])
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_aspect("equal")
        root.addWidget(self.canvas, stretch=1)

        self.legend_box = QVBoxLayout()
        self.legend_box.setSpacing(4)
        root.addLayout(self.legend_box)

        self._render_empty()

    def _clear_legend(self) -> None:
        while self.legend_box.count():
            item = self.legend_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_empty(self) -> None:
        self.ax.clear()
        self.ax.axis("off")
        self.ax.text(
            0.5,
            0.5,
            "Sin posiciones abiertas.",
            transform=self.ax.transAxes,
            color=PALETTE["text3"],
            ha="center",
            va="center",
            fontsize=10,
        )
        self.canvas.draw()
        self._clear_legend()

    def set_data(self, data: list[tuple[str, float]]) -> None:
        """``data``: list of ``(label, value)``; values need not be normalised."""
        data = [(str(label), float(v)) for label, v in data if float(v) > 0]
        if not data:
            self._render_empty()
            return

        data.sort(key=lambda kv: kv[1], reverse=True)
        # Collapse the long tail into "Resto" so the legend stays readable.
        if len(data) > self._max_legend:
            head = data[: self._max_legend - 1]
            rest = sum(v for _, v in data[self._max_legend - 1 :])
            data = [*head, ("Resto", rest)]

        labels = [d[0] for d in data]
        values = [d[1] for d in data]
        total = sum(values)
        colors = [CATEGORICAL_COLORS[i % len(CATEGORICAL_COLORS)] for i in range(len(values))]

        self.ax.clear()
        self.ax.set_aspect("equal")
        self.ax.axis("off")
        self.ax.pie(
            values,
            colors=colors,
            startangle=90,
            counterclock=False,
            wedgeprops={"width": 0.42, "edgecolor": PALETTE["card"], "linewidth": 2},
        )
        self.canvas.draw()

        # Legend rows
        self._clear_legend()
        # strict=True: las tres listas salen de `data` cinco líneas más arriba, así
        # que tienen el mismo largo por construcción. Si alguna vez dejan de tenerlo
        # es un bug, y es mejor que grite acá que dibujar una leyenda incompleta.
        for label, value, color in zip(labels, values, colors, strict=True):
            pct = (value / total * 100.0) if total else 0.0
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)

            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 11px;")
            name = QLabel(label)
            name.setStyleSheet(f"color: {PALETTE['text2']}; font-size: 12px;")
            pct_lbl = QLabel(f"{pct:.1f}%")
            pct_lbl.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 12px; font-weight: 700;")
            pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            rl.addWidget(dot)
            rl.addWidget(name)
            rl.addStretch()
            rl.addWidget(pct_lbl)
            self.legend_box.addWidget(row)

    def cleanup(self) -> None:
        with contextlib.suppress(Exception):
            self.figure.clear()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
