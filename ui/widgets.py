"""
Reusable UI widgets for FinanzIAs — IQON design system.
"""
import math
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QPushButton, QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QRect, QRectF, QSize, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import (
    QFont, QPainter, QColor, QPen, QBrush, QConicalGradient,
    QPainterPath, QLinearGradient, QRadialGradient
)
from ui.styles import PALETTE, SIGNAL_COLORS


# ── Circular Gauge ─────────────────────────────────────────────────────────

class CircularGauge(QWidget):
    """
    Circular arc progress gauge, like the CPU/GPU temp rings in IQON.
    Shows a value (e.g. temperature) in the center with a colored arc.
    """
    def __init__(
        self,
        value: float = 0,
        max_value: float = 100,
        unit: str = "°",
        label: str = "",
        color: str = None,
        size: int = 90,
        parent=None,
    ):
        super().__init__(parent)
        self._value = value
        self._max_value = max_value
        self._unit = unit
        self._label = label
        self._color = QColor(color or PALETTE["blue"])
        self._size = size
        self.setFixedSize(size, size)

    def set_value(self, value: float):
        self._value = value
        self.update()

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        margin = 8
        radius = min(w, h) / 2 - margin

        # Background track circle
        painter.setPen(QPen(QColor(PALETTE["elevated"]), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        # Progress arc
        pct = min(self._value / self._max_value, 1.0) if self._max_value else 0
        span_angle = int(pct * 270 * 16)  # 270° sweep
        start_angle = int(225 * 16)       # start at 225° (bottom-left)

        arc_pen = QPen(self._color, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        painter.drawArc(
            QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
            start_angle,
            -span_angle,
        )

        # Center value text
        painter.setPen(QColor(PALETTE["text1"]))
        val_font = QFont("Segoe UI", int(radius * 0.38), QFont.Weight.Bold)
        painter.setFont(val_font)
        val_text = f"{self._value:.0f}{self._unit}"
        painter.drawText(QRectF(0, 0, w, h - 6), Qt.AlignmentFlag.AlignCenter, val_text)

        # Label below value
        if self._label:
            painter.setPen(QColor(PALETTE["text3"]))
            lbl_font = QFont("Segoe UI", int(radius * 0.2))
            painter.setFont(lbl_font)
            painter.drawText(
                QRectF(0, h * 0.58, w, h * 0.3),
                Qt.AlignmentFlag.AlignCenter,
                self._label,
            )

        painter.end()


# ── Mini Progress Bar ──────────────────────────────────────────────────────

class MiniProgressBar(QWidget):
    """Thin horizontal progress bar like the utilization bars in IQON."""
    def __init__(self, value: float = 0, color: str = None, parent=None):
        super().__init__(parent)
        self._value = value  # 0–100
        self._color = QColor(color or PALETTE["accent"])
        self.setFixedHeight(5)
        self.setMinimumWidth(60)

    def set_value(self, value: float, color: str = None):
        self._value = min(max(value, 0), 100)
        if color:
            self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Track
        painter.setBrush(QColor(PALETTE["elevated"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, w, h, h / 2, h / 2)

        # Fill
        fill_w = int(w * self._value / 100)
        if fill_w > 0:
            painter.setBrush(self._color)
            painter.drawRoundedRect(0, 0, fill_w, h, h / 2, h / 2)

        painter.end()


# ── Toggle Switch ──────────────────────────────────────────────────────────

class ToggleSwitch(QWidget):
    """iOS-style toggle switch."""
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool):
        self._checked = checked
        self.update()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.update()
        self.toggled.emit(self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2

        track_color = QColor(PALETTE["accent"]) if self._checked else QColor(PALETTE["border_lt"])
        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, w, h, r, r)

        # Knob
        knob_x = w - h + 2 if self._checked else 2
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawEllipse(int(knob_x), 2, h - 4, h - 4)
        painter.end()


# ── Status Dot ────────────────────────────────────────────────────────────

class StatusDot(QWidget):
    """Small colored dot for status indicators."""
    def __init__(self, color: str = None, size: int = 8, parent=None):
        super().__init__(parent)
        self._color = QColor(color or PALETTE["accent"])
        self._size = size
        self.setFixedSize(size + 4, size + 4)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = self._size / 2
        painter.setBrush(QBrush(self._color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(cx - r, cy - r, self._size, self._size))
        painter.end()


# ── Metric Card (IQON style) ───────────────────────────────────────────────

class MetricCard(QFrame):
    """Card with title + large value, optional change indicator.

    compact=True uses smaller fonts/padding — for panels where vertical
    space is limited (e.g. the analysis right panel).
    """
    def __init__(self, title: str, value: str = "—", color: str = None,
                 compact: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(110 if compact else 150)
        v_pad = 8 if compact else 14
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, v_pad, 12, v_pad)
        layout.setSpacing(2 if compact else 4)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 600; "
            f"text-transform: uppercase; letter-spacing: 0.5px;"
        )

        self.value_label = QLabel(value)
        font_size = 15 if compact else 20
        self.value_label.setFont(QFont("Segoe UI", font_size, QFont.Weight.Bold))
        self._set_color(color)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def _set_color(self, color: str | None):
        c = color or PALETTE["text1"]
        self.value_label.setStyleSheet(f"color: {c}; background: transparent;")

    def set_value(self, value: str, color: str = None):
        self.value_label.setText(value)
        self._set_color(color)


# ── Status Row (IQON left-card style) ─────────────────────────────────────

class StatusRow(QWidget):
    """A labeled row with a colored dot and status text — like the left card in IQON Home."""
    def __init__(self, icon: str, label: str, status: str, status_color: str = None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)

        dot = StatusDot(status_color or PALETTE["accent"], size=8)
        layout.addWidget(dot)

        info = QVBoxLayout()
        info.setSpacing(0)
        name_lbl = QLabel(f"{icon}  {label}")
        name_lbl.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 12px; font-weight: 600;"
        )
        stat_lbl = QLabel(status)
        stat_lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 11px;"
        )
        info.addWidget(name_lbl)
        info.addWidget(stat_lbl)
        layout.addLayout(info)
        layout.addStretch()

    @staticmethod
    def separator():
        line = QFrame()
        line.setObjectName("separator")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line


# ── Gauge Card (IQON metric with circular gauge) ───────────────────────────

class GaugeCard(QFrame):
    """Card with title, subtitle, circular gauge, and utilization bar — like CPU/GPU cards."""
    def __init__(
        self, title: str, subtitle: str = "",
        value: float = 0, max_value: float = 100,
        unit: str = "°", gauge_color: str = None,
        util_value: float = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(160)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        # Title row
        title_row = QHBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 14px; font-weight: 700;"
        )
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        self.gauge = CircularGauge(
            value=value, max_value=max_value,
            unit=unit, color=gauge_color or PALETTE["blue"],
            size=72,
        )
        title_row.addWidget(self.gauge)
        root.addLayout(title_row)

        # Subtitle
        self.sub_label = QLabel(subtitle)
        self.sub_label.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 11px;"
        )
        root.addWidget(self.sub_label)

        # Status dot + label
        status_row = QHBoxLayout()
        self.dot = StatusDot(PALETTE["accent"], size=8)
        self.status_lbl = QLabel("Óptimo")
        self.status_lbl.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 12px; font-weight: 600;"
        )
        status_row.addWidget(self.dot)
        status_row.addWidget(self.status_lbl)
        status_row.addStretch()
        root.addLayout(status_row)

        # Utilization bar
        util_lbl_row = QHBoxLayout()
        util_txt = QLabel("Utilización")
        util_txt.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 11px;"
        )
        self.util_pct_lbl = QLabel(f"{util_value:.0f}%")
        self.util_pct_lbl.setStyleSheet(
            f"color: {PALETTE['text2']}; font-size: 11px; font-weight: 600;"
        )
        util_lbl_row.addWidget(util_txt)
        util_lbl_row.addStretch()
        util_lbl_row.addWidget(self.util_pct_lbl)
        root.addLayout(util_lbl_row)

        self.util_bar = MiniProgressBar(util_value, color=gauge_color or PALETTE["blue"])
        root.addWidget(self.util_bar)

    def update_values(self, value: float, util: float, status: str = "Óptimo", ok: bool = True):
        self.gauge.set_value(value)
        self.util_bar.set_value(util)
        self.util_pct_lbl.setText(f"{util:.0f}%")
        color = PALETTE["accent"] if ok else PALETTE["red"]
        self.status_lbl.setText(status)
        self.status_lbl.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
        self.dot.set_color(color)


# ── Feature Card ──────────────────────────────────────────────────────────

class FeatureCard(QFrame):
    """
    Clickable feature card — like Performance Analyzer, Optimization, etc.
    Has title, subtitle, status dot, and an action button.
    """
    clicked = pyqtSignal()

    def __init__(
        self, title: str, subtitle: str = "",
        status: str = "", status_ok: bool = True,
        action_text: str = "Abrir →",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(140)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 14px; font-weight: 700;"
        )
        layout.addWidget(title_lbl)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px;")
            layout.addWidget(sub)

        layout.addStretch()

        dot_row = QHBoxLayout()
        dot_row.setSpacing(6)
        dot = StatusDot(
            PALETTE["accent"] if status_ok else PALETTE["yellow"],
            size=8,
        )
        status_lbl = QLabel(status)
        c = PALETTE["accent"] if status_ok else PALETTE["yellow"]
        status_lbl.setStyleSheet(f"color: {c}; font-size: 12px; font-weight: 600;")
        dot_row.addWidget(dot)
        dot_row.addWidget(status_lbl)
        dot_row.addStretch()
        layout.addLayout(dot_row)

        btn = QPushButton(action_text)
        btn.setObjectName("ghost")
        btn.setFixedHeight(32)
        btn.setStyleSheet(
            f"font-size: 12px; padding: 4px 12px; "
            f"background-color: {PALETTE['elevated']}; "
            f"color: {PALETTE['text2']}; "
            f"border: 1px solid {PALETTE['border_lt']}; "
            f"border-radius: 7px;"
        )
        btn.clicked.connect(self.clicked)
        layout.addWidget(btn)

    def mousePressEvent(self, event):
        self.clicked.emit()


# ── Settings Row ──────────────────────────────────────────────────────────

class SettingsRow(QWidget):
    """A label + toggle switch row for the Settings panel."""
    toggled = pyqtSignal(str, bool)

    def __init__(self, key: str, label: str, checked: bool = False,
                 tooltip: str = "", parent=None):
        super().__init__(parent)
        self._key = key
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(2)

        top_row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 13px;")
        top_row.addWidget(lbl)
        top_row.addStretch()

        self.toggle = ToggleSwitch(checked)
        self.toggle.toggled.connect(lambda v: self.toggled.emit(self._key, v))
        top_row.addWidget(self.toggle)
        layout.addLayout(top_row)

        if tooltip:
            tip_lbl = QLabel(tooltip)
            tip_lbl.setStyleSheet(
                f"color: {PALETTE['text3']}; font-size: 11px;"
            )
            tip_lbl.setWordWrap(True)
            layout.addWidget(tip_lbl)


# ── Signal Badge ──────────────────────────────────────────────────────────

class SignalBadge(QLabel):
    """
    Colored badge using Yahoo Finance's 5-level signal system.
    Accepts "Strong Buy", "Buy", "Hold", "Underperform", "Sell"
    (or legacy "BUY" / "SELL" / "HOLD" keys for backward compatibility).
    """

    # Spanish display labels for each level
    _LABELS = {
        "Strong Buy":   "Compra Fuerte",
        "Buy":          "Comprar",
        "Hold":         "Mantener",
        "Underperform": "Vender",
        "Sell":         "Venta Fuerte",
        # Legacy fallbacks
        "BUY":     "Comprar",
        "SELL":    "Vender",
        "HOLD":    "Mantener",
        "NEUTRAL": "Neutral",
    }

    def __init__(self, signal: str = "Hold", parent=None):
        super().__init__(parent)
        self.set_signal(signal)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(26)
        self.setMinimumWidth(112)

    def set_signal(self, signal: str):
        color = SIGNAL_COLORS.get(signal, PALETTE["text3"])
        label = self._LABELS.get(signal, signal)
        # Dot prefix mirrors Yahoo Finance's visual style
        self.setText(f"● {label}")
        self.setStyleSheet(
            f"color: {color}; "
            f"background-color: {color}1a; "
            f"border: 1px solid {color}44; "
            f"border-radius: 5px; "
            f"padding: 2px 12px; "
            f"font-weight: 700; font-size: 11px;"
        )


# ── Section Header ────────────────────────────────────────────────────────

class SectionHeader(QWidget):
    def __init__(self, title: str, action_text: str = None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 15px; font-weight: 700;"
        )
        layout.addWidget(lbl)
        layout.addStretch()
        self.action_btn = None
        if action_text:
            self.action_btn = QPushButton(action_text)
            self.action_btn.setObjectName("primary")
            self.action_btn.setFixedHeight(34)
            layout.addWidget(self.action_btn)


class HSeparator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("separator")
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
