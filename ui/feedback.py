"""
Reusable UI feedback widgets: loading spinner, toast notifications, empty state.

These are small drop-in widgets the rest of the UI can compose without
re-implementing their own. The goal is to give users immediate, consistent
visual feedback on long-running operations and "no data yet" situations.

Widgets
-------
``Spinner(parent, *, size=20)``
    Indeterminate animated rotation indicator. Use during background loads:

        self.spinner = Spinner(self)
        self.spinner.start()
        ...
        self.spinner.stop()

``EmptyState(message, *, icon="📭")``
    Centered card shown when a list/table has no rows. Drop into any layout.

``Toast.show(parent, message, *, kind="info", timeout_ms=2500)``
    Non-modal banner that appears in the top-right corner of ``parent`` and
    auto-dismisses. ``kind`` ∈ {"info", "success", "warn", "error"}.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

# ── Spinner ──────────────────────────────────────────────────────────────────


class Spinner(QWidget):
    """
    Lightweight rotating-arc spinner. Uses ``QPainter`` directly so we don't
    pull in any animation libraries. ``start()`` / ``stop()`` toggle the
    16-frame rotation timer.
    """

    def __init__(self, parent: QWidget | None = None, *, size: int = 20) -> None:
        super().__init__(parent)
        self._size = size
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)  # ~12.5 fps — smooth enough, cheap
        self._timer.timeout.connect(self._advance)
        self.setFixedSize(size, size)
        self.setVisible(False)

    def start(self) -> None:
        self.setVisible(True)
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.setVisible(False)

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#58a6ff"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        rect = QRect(2, 2, self._size - 4, self._size - 4)
        # Draw an arc that rotates (~270°-arc shifting in 30° steps)
        painter.drawArc(rect, self._angle * 16, 270 * 16)


# ── Empty state ──────────────────────────────────────────────────────────────


class EmptyState(QFrame):
    """
    Centered placeholder card with an icon glyph and a short message.
    Use as the default content of a tab/panel when there's no data yet.
    """

    def __init__(
        self,
        message: str,
        *,
        icon: str = "📭",
        hint: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("emptyState")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 36px;")
        layout.addWidget(icon_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_lbl.setStyleSheet("color: #c9d1d9; font-size: 13px; font-weight: 600;")
        layout.addWidget(msg_lbl)

        if hint:
            hint_lbl = QLabel(hint)
            hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint_lbl.setWordWrap(True)
            hint_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
            layout.addWidget(hint_lbl)


# ── Toast ────────────────────────────────────────────────────────────────────

_TOAST_PALETTE = {
    "info": ("#1f6feb", "#ffffff"),
    "success": ("#238636", "#ffffff"),
    "warn": ("#9e6a03", "#ffffff"),
    "error": ("#da3633", "#ffffff"),
}


class Toast(QFrame):
    """
    Non-modal banner that fades in/out in the top-right of ``parent``.
    Use the class method ``Toast.show(parent, msg, ...)`` — never construct
    directly unless you need to keep a handle.
    """

    def __init__(self, parent: QWidget, message: str, kind: str = "info") -> None:
        super().__init__(parent)
        bg, fg = _TOAST_PALETTE.get(kind, _TOAST_PALETTE["info"])
        self.setObjectName("toast")
        self.setStyleSheet(
            f"#toast {{ background-color: {bg}; color: {fg}; border-radius: 8px; padding: 8px 14px; }}"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(message, self)
        lbl.setStyleSheet("color: white; font-size: 12px;")
        layout.addWidget(lbl)

        self._opacity = 0.0
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # Choca a proposito con `QWidget.show()`: aca `show` es el CONSTRUCTOR del
    # toast (classmethod), no el metodo de instancia de Qt. Renombrarlo tocaria
    # todos los call sites de la app por una cuestion de nombre.
    @classmethod
    def show(  # type: ignore[override]
        cls,
        parent: QWidget,
        message: str,
        *,
        kind: str = "info",
        timeout_ms: int = 2500,
    ) -> Toast:
        toast = cls(parent, message, kind=kind)
        toast.adjustSize()
        # Top-right corner of parent
        margin = 16
        toast.move(parent.width() - toast.width() - margin, margin)
        toast.setWindowOpacity(0.0)
        super(Toast, toast).show()  # avoid recursion with class-level show

        toast._anim.stop()
        toast._anim.setDuration(180)
        toast._anim.setStartValue(0.0)
        toast._anim.setEndValue(1.0)
        toast._anim.start()

        QTimer.singleShot(max(500, timeout_ms), toast._fade_out)
        return toast

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setDuration(220)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.close)
        self._anim.start()
