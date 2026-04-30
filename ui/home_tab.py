"""
Home dashboard tab — IQON-inspired layout.
Shows portfolio summary, metric cards, feature shortcuts.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QGridLayout, QSizePolicy, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from ui.widgets import (
    MetricCard, GaugeCard, FeatureCard, StatusRow,
    MiniProgressBar, SettingsRow, HSeparator, ToggleSwitch
)
from ui.styles import PALETTE
from data.yahoo_finance import is_market_open
import datetime


class WelcomeCard(QFrame):
    """Left welcome card with portfolio health status rows."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(220)
        self.setMaximumWidth(300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(4)

        greeting = QLabel("Bienvenido de vuelta,")
        greeting.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 12px;"
        )
        layout.addWidget(greeting)

        self.name_label = QLabel("Chapa")
        self.name_label.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 26px; font-weight: 800;"
        )
        layout.addWidget(self.name_label)
        layout.addSpacing(16)

        # Status rows
        self.status_rows: list[StatusRow] = []
        _market_open, _market_label = is_market_open()
        rows_data = [
            ("📊", "Portafolio",  "Cargando..."),
            ("📈", "Rendimiento", "Cargando..."),
            ("🔔", "Alertas",     "Sin disparar"),
            ("🌐", "Mercado",     _market_label),
        ]
        for icon, label, status in rows_data:
            row = StatusRow(icon, label, status)
            self.status_rows.append(row)
            layout.addWidget(row)
            if icon != "🌐":
                layout.addWidget(StatusRow.separator())

        layout.addStretch()

        # Navigate link
        self.portfolio_btn = QPushButton("Ver portafolio  →")
        self.portfolio_btn.setStyleSheet(
            f"background-color: {PALETTE['accent_bg']}; "
            f"color: {PALETTE['accent']}; "
            f"border: 1px solid #1a4a2a; border-radius: 8px; "
            f"padding: 8px 14px; font-weight: 700; font-size: 12px;"
        )
        layout.addWidget(self.portfolio_btn)

    def update_status(self, n_positions: int, pl_pct: float, n_alerts: int):
        if self.status_rows:
            self.status_rows[0].findChild(QLabel).setText(
                f"📊  Portafolio"
            )


class PlatformSettingsCard(QFrame):
    """Right panel mirroring IQON's Platform Settings card."""
    settings_changed = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(0)

        title = QLabel("Configuración Rápida")
        title.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 15px; font-weight: 700;"
        )
        layout.addWidget(title)
        layout.addSpacing(14)

        # General section
        gen_lbl = QLabel("PREFERENCIAS GENERALES")
        gen_lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        )
        layout.addWidget(gen_lbl)
        layout.addSpacing(8)

        self._rows: dict[str, SettingsRow] = {}
        general_settings = [
            ("notif",        "Notificaciones de alertas", True),
            ("auto_refresh", "Actualización automática",  True),
            ("default_home", "Abrir en Home al iniciar",  True),
        ]
        for key, label, default in general_settings:
            row = SettingsRow(key, label, default)
            row.toggled.connect(self.settings_changed)
            self._rows[key] = row
            layout.addWidget(row)
            layout.addWidget(HSeparator())

        layout.addSpacing(10)

        sys_lbl = QLabel("DATOS Y MERCADO")
        sys_lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        )
        layout.addWidget(sys_lbl)
        layout.addSpacing(8)

        system_settings = [
            ("realtime",  "Precios en tiempo real",  False),
            ("perf_log",  "Guardar historial P&L",   True),
        ]
        for key, label, default in system_settings:
            row = SettingsRow(key, label, default)
            row.toggled.connect(self.settings_changed)
            self._rows[key] = row
            layout.addWidget(row)
            layout.addWidget(HSeparator())

        layout.addStretch()

        all_btn = QPushButton("Todos los ajustes  →")
        all_btn.setObjectName("ghost")
        all_btn.setFixedHeight(32)
        layout.addWidget(all_btn)


class HomeTab(QWidget):
    navigate = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        container.setStyleSheet(f"background-color: {PALETTE['bg']};")
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root = QVBoxLayout(container)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        # ── Row 1: Welcome card + Metric cards ──────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(16)

        self.welcome_card = WelcomeCard()
        self.welcome_card.portfolio_btn.clicked.connect(lambda: self.navigate.emit("portfolio"))
        row1.addWidget(self.welcome_card)

        # P&L metric cards (right of welcome)
        metrics_grid = QWidget()
        metrics_layout = QGridLayout(metrics_grid)
        metrics_layout.setSpacing(14)
        metrics_layout.setContentsMargins(0, 0, 0, 0)

        self.card_total    = MetricCard("Valor Total")
        self.card_pl       = MetricCard("Ganancia Total")
        self.card_invested = MetricCard("Invertido")
        self.card_pl_pct   = MetricCard("Rendimiento Total")

        for i, card in enumerate([self.card_total, self.card_pl, self.card_invested, self.card_pl_pct]):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            metrics_layout.addWidget(card, i // 2, i % 2)

        row1.addWidget(metrics_grid, stretch=1)

        # Platform settings (right column)
        self.platform_card = PlatformSettingsCard()
        row1.addWidget(self.platform_card)

        root.addLayout(row1)

        # ── Row 2: Feature cards ─────────────────────────────────────────────
        row2_label = QLabel("Acceso Rápido")
        row2_label.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 11px; font-weight: 700; "
            f"text-transform: uppercase; letter-spacing: 1px;"
        )
        root.addWidget(row2_label)

        row2 = QHBoxLayout()
        row2.setSpacing(14)

        features = [
            ("📈  Análisis Técnico",   "Motor RSI, MACD, Bollinger",
             "Listo",   True,  "Analizar  →",  "analysis"),
            ("🔔  Alertas de Precio",  "Monitoreo en tiempo real",
             "Activo",  True,  "Ver alertas →","alerts"),
            ("📄  Reportes",           "PDF y Excel",
             "Disponible", True, "Exportar  →", "reports"),
            ("📥  Importar CSV",       "Yahoo Finance / genérico",
             "Disponible", True, "Importar  →", "portfolio"),
        ]

        for title, sub, status, ok, action, page in features:
            card = FeatureCard(title, sub, status, ok, action)
            card.clicked.connect(lambda p=page: self.navigate.emit(p))
            row2.addWidget(card)

        root.addLayout(row2)
        root.addStretch()

    def refresh(self, portfolio_tab=None):
        """Pull metrics from the portfolio tab and update cards."""
        if portfolio_tab is None:
            return
        positions = getattr(portfolio_tab, "_positions", [])
        prices    = getattr(portfolio_tab, "_prices", {})

        total_invested = sum(p.quantity * p.avg_buy_price for p in positions)
        total_value = sum(
            p.quantity * (prices[p.ticker]["price"] if p.ticker in prices and prices[p.ticker] else p.avg_buy_price)
            for p in positions
        )
        pl     = total_value - total_invested
        pl_pct = (pl / total_invested * 100) if total_invested > 0 else 0.0

        self.card_total.set_value(f"${total_value:,.2f}")
        self.card_invested.set_value(f"${total_invested:,.2f}")
        self.card_pl.set_value(
            f"{'+'if pl>=0 else ''}${pl:,.2f}",
            color=PALETTE["accent"] if pl >= 0 else PALETTE["red"]
        )
        self.card_pl_pct.set_value(
            f"{pl_pct:+.2f}%",
            color=PALETTE["accent"] if pl_pct >= 0 else PALETTE["red"]
        )
