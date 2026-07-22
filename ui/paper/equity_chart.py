"""
Equity-curve chart widget for the paper-trading tab.

Used to live as ``_EquityCurveChart`` inside ``paper_tab.py`` — extracted
into its own module so it can be tested in isolation and reused (e.g. by
a future "compare two accounts" view).
"""

from __future__ import annotations

import contextlib
from datetime import datetime

import matplotlib

matplotlib.use("QtAgg")
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ui.styles import CHART_STYLE, PALETTE


def build_benchmark_overlay(snapshots: list,
                            spy_pairs: list[tuple[str, float]] | None
                            ) -> list[tuple[datetime, float]]:
    """Normaliza SPY a la equity inicial sobre la ventana de los snapshots (V1).

    ``snapshots``: ``PaperEquitySnapshot`` ascendentes (``.snapshot_at``,
    ``.total_equity``). ``spy_pairs``: ``[(YYYY-MM-DD, close)]``. Devuelve
    ``[(datetime, valor)]`` por cada barra SPY dentro de ``[primer, último]``
    snapshot, escalada para arrancar en la equity inicial → una línea comparable
    en las mismas unidades ($) que la curva de equity. ``[]`` si falta data.

    Función pura (sin Qt) para poder testear la alineación sin event loop.
    """
    if not snapshots or not spy_pairs:
        return []
    try:
        start_eq = float(snapshots[0].total_equity)
        start_day = snapshots[0].snapshot_at.date().isoformat()
        end_day = snapshots[-1].snapshot_at.date().isoformat()
    except (AttributeError, TypeError, ValueError):
        return []
    if start_eq <= 0:
        return []
    pairs = sorted(spy_pairs)
    base = next((c for d, c in pairs if d >= start_day), None)
    if not base or base <= 0:
        return []
    scale = start_eq / base
    out: list[tuple[datetime, float]] = []
    for d, c in pairs:
        if d < start_day or d > end_day:
            continue
        with contextlib.suppress(ValueError):
            out.append((datetime.fromisoformat(d), c * scale))
    return out


def overlay_is_stale(snapshots: list,
                     spy_pairs: list[tuple[str, float]] | None) -> bool:
    """True si el último close de SPY quedó desactualizado vs el último snapshot.

    Reusa el umbral/lógica de ``metrics_panel`` (tarea 22) para no dibujar la
    línea corta como si fuera actual. Función pura (sin Qt). ``False`` ante datos
    faltantes o fechas inválidas — en la duda, no se marca stale.
    """
    if not snapshots or not spy_pairs:
        return False
    from analysis.metrics_panel import BENCHMARK_STALE_BDAYS, benchmark_stale_bdays

    try:
        ref_day = snapshots[-1].snapshot_at.date().isoformat()
    except (AttributeError, TypeError, ValueError):
        return False
    spy_last = max(d for d, _ in spy_pairs)
    return benchmark_stale_bdays(spy_last, ref_day) > BENCHMARK_STALE_BDAYS


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
            with contextlib.suppress(Exception):
                matplotlib.rcParams[k] = v
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
        self._line = None  # Line2D artist (kept between refreshes)
        self._fill = None  # PolyCollection from fill_between
        self._plotted_count = 0  # number of snapshots in last render
        self._first_xs = None  # first snapshot timestamp (series identity key)

    # ── Styling helpers ──────────────────────────────────────────────────────
    def _style_axes(self) -> None:
        self.ax.set_facecolor(CHART_STYLE["axes.facecolor"])
        self.ax.tick_params(colors=CHART_STYLE["xtick.color"], labelsize=9)
        for spine in ("top", "right"):
            self.ax.spines[spine].set_visible(False)
        for spine in ("bottom", "left"):
            self.ax.spines[spine].set_color(CHART_STYLE["axes.edgecolor"])
        self.ax.grid(
            True,
            color=CHART_STYLE["grid.color"],
            alpha=CHART_STYLE["grid.alpha"],
            linewidth=0.5,
        )

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

    # ── Public API ───────────────────────────────────────────────────────────
    def set_data(self, snapshots: list,
                 benchmark: list[tuple[datetime, float]] | None = None,
                 benchmark_stale: bool = False) -> None:
        """Render the equity curve from a list of ``PaperEquitySnapshot``.

        ``benchmark`` (opcional, V1): línea SPY normalizada a la equity inicial,
        ``[(datetime, valor)]`` — se dibuja punteada para comparar el modelo vs
        el mercado. Cuando hay benchmark siempre se hace un full redraw (para
        redibujar la línea y su leyenda).

        ``benchmark_stale`` (tarea 22): si el cache de SPY quedó atrás, en vez de
        dibujar una línea corta que parece actual se anota "SPY desactualizado".
        """
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
        # Con benchmark (o su marcador de stale) forzamos full redraw.
        same_series = (
            not benchmark
            and not benchmark_stale
            and self._line is not None
            and self._plotted_count > 0
            and len(snapshots) >= self._plotted_count
            and self._first_xs == xs[0]
        )

        if same_series:
            self._incremental_update(xs, ys)
        else:
            self._full_redraw(xs, ys, benchmark, benchmark_stale)

        self._plotted_count = len(snapshots)
        self._first_xs = xs[0]

    # ── Drawing internals ────────────────────────────────────────────────────
    def _full_redraw(self, xs: list, ys: list,
                     benchmark: list[tuple[datetime, float]] | None = None,
                     benchmark_stale: bool = False) -> None:
        self.ax.clear()
        self._style_axes()
        (self._line,) = self.ax.plot(
            xs, ys, color=PALETTE["accent"], linewidth=1.8, label="Equity"
        )
        self._fill = self.ax.fill_between(
            xs,
            ys,
            min(ys),
            color=PALETTE["accent"],
            alpha=0.12,
        )
        if len(ys) > 1:
            self.ax.axhline(
                ys[0],
                color=PALETTE["text3"],
                linestyle="--",
                linewidth=0.6,
                alpha=0.7,
            )
        # Overlay SPY (V1): mismo eje $, normalizado a la equity inicial.
        # tarea 22: si SPY quedó desactualizado NO dibujamos la línea corta (que
        # se leería como actual) — anotamos que el benchmark está stale.
        if benchmark_stale:
            self.ax.text(
                0.01, 0.98, "SPY desactualizado",
                transform=self.ax.transAxes, ha="left", va="top",
                fontsize=8, color=PALETTE.get("text3", "#6B7280"),
            )
        elif benchmark:
            bx = [d for d, _ in benchmark]
            by = [v for _, v in benchmark]
            self.ax.plot(
                bx, by,
                color=PALETTE.get("text2", "#9AA4B2"),
                linewidth=1.2, linestyle="--", alpha=0.9,
                label="SPY (normalizado)",
            )
            self.ax.legend(loc="upper left", fontsize=8, frameon=False)
        self.ax.set_ylabel("Equity ($)", color=PALETTE["text2"], fontsize=10)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
        self.figure.autofmt_xdate(rotation=15)
        self.canvas.draw()

    def _incremental_update(self, xs: list, ys: list) -> None:
        self._line.set_data(xs, ys)
        if self._fill is not None:
            self._fill.remove()
        self._fill = self.ax.fill_between(
            xs,
            ys,
            min(ys),
            color=PALETTE["accent"],
            alpha=0.12,
        )
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def cleanup(self) -> None:
        """Drop references to matplotlib artists so the figure can be GC'd."""
        with contextlib.suppress(Exception):
            self.figure.clear()
        self._line = None
        self._fill = None
        self._plotted_count = 0
        self._first_xs = None

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
