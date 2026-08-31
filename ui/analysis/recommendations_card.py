"""
Analyst recommendations card for the Analysis tab.

Renders a collapsible block, Google-Finance-style, with one stacked horizontal
bar per month (4 most recent snapshots from Yahoo: 0m, -1m, -2m, -3m) showing
how many analysts rate the ticker Strong Buy / Buy / Hold / Sell / Strong Sell.
Below the bars, a one-line summary with mean / median / low / high price targets
plus the implied % move vs the current price.

Data source: ``data.yahoo_finance.get_analyst_data`` — a dict with two keys::

    {
      "recommendations": [
        {"period": "-3m", "strongBuy": 12, "buy": 18, "hold": 7, "sell": 1,
         "strongSell": 0, "total": 38},
        ...  # chronological, oldest first
      ],
      "price_targets": {"current": 192.5, "mean": 215.4, "median": 220.0,
                        "low": 165.0, "high": 280.0} | None
    }

The card is silent when ``recommendations`` is empty AND ``price_targets`` is
``None`` — it hides itself so it doesn't add visual noise for tickers Yahoo
doesn't cover.
"""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# Colores estilo Google Finance / Yahoo. Verde fuerte → verde claro → gris/amarillo
# → naranja → rojo. Manteniéndolos sólidos sin transparencia para legibilidad
# sobre el fondo de card oscuro.
BUCKET_COLORS = {
    "strongBuy": "#0b5d2a",  # verde muy oscuro
    "buy": "#7cd992",  # verde claro (mucho más contraste vs strongBuy)
    "hold": "#fbbc04",  # amarillo (Google usa gris claro pero amarillo legibiliza mejor sobre dark)
    "sell": "#ff7043",  # naranja
    "strongSell": "#ea4335",  # rojo
}
BUCKET_LABELS_ES = {
    "strongBuy": "Compra fuerte",
    "buy": "Compra",
    "hold": "Mantener",
    "sell": "Venta",
    "strongSell": "Venta fuerte",
}
BUCKET_ORDER = ["strongBuy", "buy", "hold", "sell", "strongSell"]

MONTH_NAMES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _period_to_month_label(period: str, today: date | None = None) -> str:
    """Convierte un período tipo ``"0m" | "-1m" | "-2m" | "-3m"`` al nombre de
    mes en español abreviado (``"jun"``, ``"may"``...). Si no se puede parsear,
    devuelve el string original.
    """
    today = today or date.today()
    try:
        offset = int(period.replace("m", ""))  # "0m" -> 0, "-3m" -> -3
    except (ValueError, AttributeError):
        return period
    # offset es 0, -1, -2, -3. Calcular el mes resultante.
    month_idx = (today.month - 1 + offset) % 12  # negativos OK en Python
    return MONTH_NAMES_ES[month_idx]


class StackedBar(QWidget):
    """Una barra horizontal apilada: pinta los 5 segmentos proporcionalmente
    al total de analistas del mes. No dibuja labels — esos los pone el row."""

    def __init__(self, bucket: dict, parent=None):
        super().__init__(parent)
        self._bucket = bucket
        self.setMinimumHeight(20)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(200, 20)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        w = rect.width()
        h = rect.height()
        total = max(int(self._bucket.get("total", 0)), 1)

        radius = h / 2
        # Fondo redondeado (track) por si el total es 0 o quedan huecos por redondeo.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1f2937"))
        p.drawRoundedRect(rect, radius, radius)

        # Clip a la pill para que los segmentos rectos queden redondeados en los bordes.
        path = p.clipRegion()
        from PyQt6.QtGui import QPainterPath

        clip_path = QPainterPath()
        clip_path.addRoundedRect(float(rect.x()), float(rect.y()), float(w), float(h), radius, radius)
        p.setClipPath(clip_path)

        x = 0.0
        for bucket in BUCKET_ORDER:
            count = int(self._bucket.get(bucket, 0))
            if count <= 0:
                continue
            seg_w = w * (count / total)
            p.setBrush(QColor(BUCKET_COLORS[bucket]))
            p.drawRect(int(x), 0, int(seg_w) + 1, h)  # +1 evita huecos de pixel por redondeo
            x += seg_w

        p.end()
        # Avoid unused-variable warnings from clip-region capture above
        _ = path


class RecommendationsCard(QFrame):
    """Bloque colapsable con barras stacked mensuales + price targets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._expanded = False  # cerrado por default

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # ── Header (siempre visible, clickeable para expandir) ────────────
        header = QHBoxLayout()
        header.setSpacing(8)

        self._toggle_btn = QToolButton()
        self._toggle_btn.setText("▶")
        self._toggle_btn.setStyleSheet(
            "QToolButton { border: none; color: #94a3b8; font-size: 11px; padding: 0; }"
            "QToolButton:hover { color: #e2e8f0; }"
        )
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle)
        header.addWidget(self._toggle_btn)

        title = QLabel("Recomendaciones de analistas")
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        title.setCursor(Qt.CursorShape.PointingHandCursor)
        # Hacer que click en el título también haga toggle
        title.mousePressEvent = lambda _ev: self._toggle()
        header.addWidget(title)
        header.addStretch()

        # Resumen compacto (visible cerrado): "N analistas · Compra"
        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header.addWidget(self._summary_lbl)
        root.addLayout(header)

        # ── Body (oculto cuando colapsado) ─────────────────────────────────
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 6, 0, 0)
        body_layout.setSpacing(10)

        # Container para las filas de barras (se rellena en set_data)
        self._bars_container = QWidget()
        self._bars_layout = QVBoxLayout(self._bars_container)
        self._bars_layout.setContentsMargins(0, 0, 0, 0)
        self._bars_layout.setSpacing(6)
        body_layout.addWidget(self._bars_container)

        # Leyenda de colores
        legend = QHBoxLayout()
        legend.setSpacing(12)
        for bucket in BUCKET_ORDER:
            chip = self._make_legend_chip(BUCKET_COLORS[bucket], BUCKET_LABELS_ES[bucket])
            legend.addWidget(chip)
        legend.addStretch()
        body_layout.addLayout(legend)

        # Price targets (línea de texto)
        self._targets_lbl = QLabel("")
        self._targets_lbl.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        self._targets_lbl.setWordWrap(True)
        body_layout.addWidget(self._targets_lbl)

        self._body.setVisible(False)
        root.addWidget(self._body)

        # Estado vacío
        self._empty = True
        self.set_data({"recommendations": [], "price_targets": None})

    # ── Helpers ──────────────────────────────────────────────────────────
    def _make_legend_chip(self, color_hex: str, label: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background:{color_hex}; border-radius:5px;")
        h.addWidget(dot)
        lbl = QLabel(label)
        lbl.setStyleSheet("color:#94a3b8; font-size:11px;")
        h.addWidget(lbl)
        return w

    def _toggle(self):
        if self._empty:
            return  # sin datos no se puede expandir
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._toggle_btn.setText("▼" if self._expanded else "▶")

    # ── API pública ───────────────────────────────────────────────────────
    def set_data(self, analyst: dict | None) -> None:
        """Refresca el contenido con la respuesta de ``get_analyst_data``.

        Si no hay ni recomendaciones ni price targets, el card se oculta del
        layout completo (no queda un bloque vacío arriba del panel).
        """
        recs: list[dict] = (analyst or {}).get("recommendations") or []
        targets: dict | None = (analyst or {}).get("price_targets")

        # Limpiar filas previas
        while self._bars_layout.count():
            item = self._bars_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        has_data = bool(recs) or bool(targets)
        self._empty = not has_data
        self.setVisible(has_data)
        if not has_data:
            return

        # ── Filas: la más reciente arriba (Google Finance las muestra así) ──
        # recs viene ordenado de -3m → 0m; invertimos para 0m → -3m
        for bucket in reversed(recs):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)

            # Label del período (nombre del mes, ej. "jun", "may")
            month_label = _period_to_month_label(bucket["period"])
            period_lbl = QLabel(month_label)
            period_lbl.setStyleSheet("color:#cbd5e1; font-size:12px; font-weight:600;")
            period_lbl.setFixedWidth(48)
            row_layout.addWidget(period_lbl)

            # Barra stacked
            bar = StackedBar(bucket)
            row_layout.addWidget(bar, stretch=1)

            # Total a la derecha
            total_lbl = QLabel(f"{bucket['total']}")
            total_lbl.setStyleSheet("color:#e2e8f0; font-size:12px; font-weight:600;")
            total_lbl.setFixedWidth(28)
            total_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(total_lbl)

            # Tooltip con desglose
            tooltip_parts = [
                f"<b>{month_label.capitalize()}</b>",
                f"Total: <b>{bucket['total']}</b> analistas",
                "",
            ]
            for b in BUCKET_ORDER:
                c = bucket.get(b, 0)
                if c > 0:
                    tooltip_parts.append(
                        f"<span style='color:{BUCKET_COLORS[b]}'>●</span> {BUCKET_LABELS_ES[b]}: <b>{c}</b>"
                    )
            row.setToolTip("<br>".join(tooltip_parts))

            self._bars_layout.addWidget(row)

        # ── Summary text (visible cuando está colapsado) ──────────────────
        if recs:
            latest = recs[-1]  # 0m
            verdict = self._consensus_label(latest)
            self._summary_lbl.setText(f"{latest['total']} analistas · {verdict}")
        else:
            self._summary_lbl.setText("Sólo price targets")

        # ── Price targets line ────────────────────────────────────────────
        if targets:
            self._targets_lbl.setText(self._format_targets(targets))
            self._targets_lbl.setVisible(True)
        else:
            self._targets_lbl.setVisible(False)

    # ── Internals ─────────────────────────────────────────────────────────
    @staticmethod
    def _consensus_label(bucket: dict) -> str:
        """Devuelve un veredicto agregado simple usando el bucket mayoritario
        weighted: strongBuy=2, buy=1, hold=0, sell=-1, strongSell=-2."""
        weights = {"strongBuy": 2, "buy": 1, "hold": 0, "sell": -1, "strongSell": -2}
        total = max(int(bucket.get("total", 0)), 1)
        score = sum(weights[b] * int(bucket.get(b, 0)) for b in BUCKET_ORDER) / total
        if score >= 1.5:
            return "Compra fuerte"
        if score >= 0.5:
            return "Compra"
        if score >= -0.5:
            return "Mantener"
        if score >= -1.5:
            return "Venta"
        return "Venta fuerte"

    @staticmethod
    def _format_targets(t: dict) -> str:
        """Formatea la línea de price targets con porcentajes vs precio actual."""
        cur = t.get("current")
        parts: list[str] = []

        def _fmt_with_pct(label: str, val: float | None) -> str | None:
            if val is None:
                return None
            txt = f"{label}: <b>${val:,.2f}</b>"
            if cur is not None and cur > 0:
                pct = (val / cur - 1) * 100
                color = "#4ade80" if pct >= 0 else "#fb7185"
                sign = "+" if pct >= 0 else ""
                txt += f" <span style='color:{color}'>({sign}{pct:.1f}%)</span>"
            return txt

        for key, label in [("mean", "Promedio"), ("median", "Mediana"), ("low", "Mín"), ("high", "Máx")]:
            piece = _fmt_with_pct(label, t.get(key))
            if piece:
                parts.append(piece)

        prefix = "<b>Price targets</b> "
        if cur is not None:
            prefix += f"<span style='color:#94a3b8'>(actual ${cur:,.2f})</span> · "
        return prefix + " · ".join(parts)
