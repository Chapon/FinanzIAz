"""
IQON-style sidebar navigation for FinanzIAs.
"""
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QWidget, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor, QBrush, QPen
from ui.styles import PALETTE


class LogoWidget(QWidget):
    """App logo + name at top of sidebar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(10)

        # Logo square
        logo_frame = QFrame()
        logo_frame.setFixedSize(32, 32)
        logo_frame.setStyleSheet(
            f"background-color: {PALETTE['accent']}; "
            f"border-radius: 8px;"
        )
        logo_lbl = QLabel("Fi", logo_frame)
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lbl.setGeometry(0, 0, 32, 32)
        logo_lbl.setStyleSheet(
            "color: #000000; font-weight: 800; font-size: 14px; background: transparent;"
        )
        layout.addWidget(logo_frame)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        name_lbl = QLabel("FinanzIAs")
        name_lbl.setStyleSheet(
            f"color: {PALETTE['text1']}; font-weight: 800; font-size: 14px;"
        )
        tag_lbl = QLabel("v1.0")
        tag_lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px;"
        )
        text_col.addWidget(name_lbl)
        text_col.addWidget(tag_lbl)
        layout.addLayout(text_col)
        layout.addStretch()


class SectionLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; padding: 14px 16px 4px 16px;"
        )


class NavButton(QPushButton):
    """Single navigation item in the sidebar."""
    def __init__(self, icon: str, text: str, active: bool = False, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._text = text
        self.setCheckable(True)
        self.setChecked(active)
        self._update_style()
        self.toggled.connect(lambda _: self._update_style())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(f"  {icon}  {text}")
        self.setFixedHeight(40)

    def _update_style(self):
        if self.isChecked():
            self.setObjectName("nav_item_active")
        else:
            self.setObjectName("nav_item")
        self.style().unpolish(self)
        self.style().polish(self)


class SubNavButton(QPushButton):
    """Sub-navigation item (indented)."""
    def __init__(self, icon: str, text: str, active: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(active)
        self._update_style(active)
        self.toggled.connect(lambda c: self._update_style(c))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(f"{icon}  {text}")
        self.setFixedHeight(34)

    def _update_style(self, active: bool = False):
        obj = "nav_sub_active" if active else "nav_sub"
        self.setObjectName(obj)
        self.style().unpolish(self)
        self.style().polish(self)


class HelpCard(QFrame):
    talk_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card_flat")
        self.setStyleSheet(
            f"background-color: {PALETTE['accent_bg']}; "
            f"border: 1px solid #1a4a2a; border-radius: 10px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title = QLabel("¿Necesitás ayuda?")
        title.setStyleSheet(
            f"color: {PALETTE['text1']}; font-weight: 700; font-size: 12px;"
        )
        sub = QLabel("Documentación disponible")
        sub.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px;")

        btn = QPushButton("📖  Ver documentación")
        btn.setObjectName("success")
        btn.setFixedHeight(32)
        btn.setStyleSheet(
            f"font-size: 11px; padding: 4px 12px; "
            f"background-color: {PALETTE['accent']}; color: #000; "
            f"border: none; border-radius: 7px; font-weight: 700;"
        )
        btn.clicked.connect(self.talk_clicked)

        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addWidget(btn)


class Sidebar(QFrame):
    """
    Full sidebar widget.
    Emits navigate(page_key) when a nav item is clicked.
    page_key: "home" | "portfolio" | "analysis" | "alerts" | "reports" | "settings"
    """
    navigate = pyqtSignal(str)

    PAGES = [
        ("home",      "🏠", "Home"),
        ("portfolio", "📊", "Portafolio"),
        ("analysis",  "📈", "Análisis"),
        ("alerts",    "🔔", "Alertas"),
        ("paper",     "🧪", "Paper Trading"),
        ("reports",   "📄", "Reportes"),
        ("settings",  "⚙️", "Ajustes"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(200)
        self._buttons: dict[str, NavButton] = {}
        self._current = "home"
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 16)
        layout.setSpacing(0)

        # Logo
        layout.addWidget(LogoWidget())

        # Separator
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        layout.addSpacing(8)
        layout.addWidget(SectionLabel("MENÚ"))

        # Nav buttons
        for key, icon, label in self.PAGES:
            btn = NavButton(icon, label, active=(key == "home"))
            btn.setChecked(key == "home")
            btn.clicked.connect(lambda checked, k=key: self._on_nav(k))
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # Help card
        help_card = HelpCard()
        layout.addWidget(help_card)

        layout.addSpacing(8)

        # User info strip
        user_strip = QFrame()
        user_strip.setStyleSheet(
            f"background-color: {PALETTE['elevated']}; "
            f"border: 1px solid {PALETTE['border']}; border-radius: 10px;"
        )
        us_layout = QHBoxLayout(user_strip)
        us_layout.setContentsMargins(10, 8, 10, 8)
        us_layout.setSpacing(8)

        avatar = QLabel("👤")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background-color: {PALETTE['accent_bg']}; "
            f"border-radius: 15px; font-size: 14px;"
        )

        info_col = QVBoxLayout()
        info_col.setSpacing(0)
        name_lbl = QLabel("Mi Cuenta")
        name_lbl.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 11px; font-weight: 600;"
        )
        status_lbl = QLabel("● Conectado")
        status_lbl.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 10px;"
        )
        info_col.addWidget(name_lbl)
        info_col.addWidget(status_lbl)

        us_layout.addWidget(avatar)
        us_layout.addLayout(info_col)
        layout.addWidget(user_strip)

    def _on_nav(self, key: str):
        if self._current == key:
            return
        # Deactivate old
        if self._current in self._buttons:
            self._buttons[self._current].setChecked(False)
        # Activate new
        self._current = key
        self._buttons[key].setChecked(True)
        self.navigate.emit(key)

    def set_active(self, key: str):
        self._on_nav(key)
