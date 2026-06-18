"""
Fuse-style sidebar navigation for FinanzIAs.
Collapsible: toggles between a wide (labels) and narrow (icons-only) rail.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.styles import PALETTE

EXPANDED_WIDTH = 200
COLLAPSED_WIDTH = 64


class LogoWidget(QWidget):
    """App logo + name at top of sidebar. Text hides when collapsed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 20, 12, 20)
        layout.setSpacing(10)

        # Logo square (brand — stays cyan)
        logo_frame = QFrame()
        logo_frame.setFixedSize(32, 32)
        logo_frame.setStyleSheet(f"background-color: {PALETTE['accent']}; border-radius: 8px;")
        logo_lbl = QLabel("Fi", logo_frame)
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lbl.setGeometry(0, 0, 32, 32)
        logo_lbl.setStyleSheet("color: #000000; font-weight: 800; font-size: 14px; background: transparent;")
        layout.addWidget(logo_frame)

        self.text_col = QWidget()
        text_col = QVBoxLayout(self.text_col)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        name_lbl = QLabel("FinanzIAs")
        name_lbl.setStyleSheet(f"color: {PALETTE['text1']}; font-weight: 800; font-size: 14px;")
        tag_lbl = QLabel("v1.0")
        tag_lbl.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 10px;")
        text_col.addWidget(name_lbl)
        text_col.addWidget(tag_lbl)
        layout.addWidget(self.text_col)
        layout.addStretch()

    def set_collapsed(self, collapsed: bool):
        self.text_col.setVisible(not collapsed)


class SectionLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; padding: 14px 16px 4px 16px;"
        )


class NavButton(QPushButton):
    """Single navigation item in the sidebar. Supports icon-only collapsed mode."""

    def __init__(self, icon: str, text: str, active: bool = False, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._text = text
        self._collapsed = False
        self.setCheckable(True)
        self.setChecked(active)
        self._update_style()
        self.toggled.connect(lambda _: self._update_style())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._render_text()
        self.setFixedHeight(40)

    def _render_text(self):
        if self._collapsed:
            self.setText(self._icon)
            self.setToolTip(self._text)
        else:
            self.setText(f"  {self._icon}  {self._text}")
            self.setToolTip("")

    def set_collapsed(self, collapsed: bool):
        self._collapsed = collapsed
        self._render_text()

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
            f"background-color: {PALETTE['accent_bg']}; border: 1px solid {PALETTE['border_lt']}; "
            f"border-radius: 10px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title = QLabel("¿Necesitás ayuda?")
        title.setStyleSheet(f"color: {PALETTE['text1']}; font-weight: 700; font-size: 12px;")
        sub = QLabel("Documentación disponible")
        sub.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px;")

        btn = QPushButton("📖  Ver documentación")
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
    page_key: "home" | "portfolio" | "analysis" | "alerts" | "paper" | "reports" | "failed" | "settings"
    """

    navigate = pyqtSignal(str)
    collapsed_changed = pyqtSignal(bool)

    PAGES = [
        ("home", "🏠", "Home"),
        ("portfolio", "📊", "Portafolio"),
        ("analysis", "📈", "Análisis"),
        ("leads", "🎯", "Leads"),
        ("news", "📰", "Noticias"),
        ("alerts", "🔔", "Alertas"),
        ("paper", "🧪", "Paper Trading"),
        ("metrics", "📊", "Métricas"),
        ("reports", "📄", "Reportes"),
        ("failed", "⚠️", "Tickers fallidos"),
        ("settings", "⚙️", "Ajustes"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(EXPANDED_WIDTH)
        self._buttons: dict[str, NavButton] = {}
        self._current = "home"
        self._collapsed = False
        self._collapsible_labels: list[QWidget] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 16)
        layout.setSpacing(0)

        # Logo + collapse toggle
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(0, 0, 0, 0)
        self.logo = LogoWidget()
        logo_row.addWidget(self.logo, stretch=1)

        self.toggle_btn = QPushButton("«")
        self.toggle_btn.setFixedSize(28, 28)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setToolTip("Colapsar/expandir el menú")
        self.toggle_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {PALETTE['text3']}; "
            f"border: none; border-radius: 6px; font-size: 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {PALETTE['card_hover']}; color: {PALETTE['text1']}; }}"
        )
        self.toggle_btn.clicked.connect(self.toggle_collapsed)
        logo_row.addWidget(self.toggle_btn, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(logo_row)

        # Separator
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        layout.addSpacing(8)
        menu_label = SectionLabel("MENÚ")
        self._collapsible_labels.append(menu_label)
        layout.addWidget(menu_label)

        # Nav buttons
        for key, icon, label in self.PAGES:
            btn = NavButton(icon, label, active=(key == "home"))
            btn.setChecked(key == "home")
            btn.clicked.connect(lambda checked, k=key: self._on_nav(k))
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # Help card
        self.help_card = HelpCard()
        layout.addWidget(self.help_card)

        layout.addSpacing(8)

        # User info strip
        self.user_strip = QFrame()
        self.user_strip.setStyleSheet(
            f"background-color: {PALETTE['elevated']}; "
            f"border: 1px solid {PALETTE['border']}; border-radius: 10px;"
        )
        us_layout = QHBoxLayout(self.user_strip)
        us_layout.setContentsMargins(10, 8, 10, 8)
        us_layout.setSpacing(8)

        avatar = QLabel("👤")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background-color: {PALETTE['accent_bg']}; border-radius: 15px; font-size: 14px;"
        )

        self.user_info = QWidget()
        info_col = QVBoxLayout(self.user_info)
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(0)
        name_lbl = QLabel("Mi Cuenta")
        name_lbl.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 11px; font-weight: 600;")
        status_lbl = QLabel("● Conectado")
        status_lbl.setStyleSheet(f"color: {PALETTE['positive']}; font-size: 10px;")
        info_col.addWidget(name_lbl)
        info_col.addWidget(status_lbl)

        us_layout.addWidget(avatar)
        us_layout.addWidget(self.user_info)
        layout.addWidget(self.user_strip)

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool):
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.setFixedWidth(COLLAPSED_WIDTH if collapsed else EXPANDED_WIDTH)
        self.toggle_btn.setText("»" if collapsed else "«")
        self.logo.set_collapsed(collapsed)
        for btn in self._buttons.values():
            btn.set_collapsed(collapsed)
        for lbl in self._collapsible_labels:
            lbl.setVisible(not collapsed)
        self.help_card.setVisible(not collapsed)
        self.user_info.setVisible(not collapsed)
        self.collapsed_changed.emit(collapsed)

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
