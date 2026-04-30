"""
Main application window — IQON-style layout with sidebar + content stack.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QLabel, QStatusBar, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from ui.sidebar import Sidebar
from ui.styles import DARK_THEME, PALETTE
from data.yahoo_finance import is_market_open
from config.settings_manager import settings
from ui.home_tab import HomeTab
from ui.portfolio_tab import PortfolioTab
from ui.analysis_tab import AnalysisTab
from ui.alerts_tab import AlertsTab
from ui.reports_tab import ReportsTab
from ui.settings_tab import SettingsTab
from ui.paper_tab import PaperTradingTab
from paper_trading.scheduler import PaperScheduler


class TopBar(QWidget):
    """Header bar: page title on the left, status info on the right."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setStyleSheet(
            f"background-color: {PALETTE['bg']}; "
            f"border-bottom: 1px solid {PALETTE['border']};"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 0)

        # Left: page label
        left = QVBoxLayout()
        left.setSpacing(0)
        self.page_label = QLabel("FinanzIAs")
        self.page_label.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 11px; font-weight: 600; "
            f"text-transform: uppercase; letter-spacing: 0.8px;"
        )
        self.title_label = QLabel("Home")
        self.title_label.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 22px; font-weight: 800;"
        )
        left.addWidget(self.page_label)
        left.addWidget(self.title_label)

        layout.addLayout(left)
        layout.addStretch()

        # Right: tooltip mode toggle + user chip
        right = QHBoxLayout()
        right.setSpacing(16)

        self.market_label = QLabel()
        self._refresh_market_label()
        right.addWidget(self.market_label)

        # Refresh market status every 60 seconds
        self._market_timer = QTimer(self)
        self._market_timer.setInterval(60_000)
        self._market_timer.timeout.connect(self._refresh_market_label)
        self._market_timer.start()

        vline = QFrame()
        vline.setObjectName("vline")
        vline.setFrameShape(QFrame.Shape.VLine)
        vline.setFixedHeight(24)
        right.addWidget(vline)

        user_chip = QFrame()
        user_chip.setStyleSheet(
            f"background-color: {PALETTE['elevated']}; "
            f"border: 1px solid {PALETTE['border_lt']}; border-radius: 20px;"
        )
        uc_layout = QHBoxLayout(user_chip)
        uc_layout.setContentsMargins(10, 4, 14, 4)
        uc_layout.setSpacing(8)
        avatar = QLabel("👤")
        avatar.setStyleSheet("font-size: 14px; background: transparent;")
        name = QLabel("Mi Cuenta")
        name.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        uc_layout.addWidget(avatar)
        uc_layout.addWidget(name)
        right.addWidget(user_chip)

        layout.addLayout(right)

    def set_title(self, title: str, subtitle: str = "FinanzIAs"):
        self.title_label.setText(title)
        self.page_label.setText(subtitle)

    def _refresh_market_label(self):
        open_, label = is_market_open()
        dot_color = PALETTE["accent"] if open_ else PALETTE["red"]
        self.market_label.setText(f"●  {label}")
        self.market_label.setStyleSheet(
            f"color: {dot_color}; font-size: 12px; font-weight: 600;"
        )


class MainWindow(QMainWindow):
    PAGE_TITLES = {
        "home":      ("Home",           "FinanzIAs"),
        "portfolio": ("Portafolio",     "Mis Inversiones"),
        "analysis":  ("Análisis",       "Técnico"),
        "alerts":    ("Alertas",        "Precios"),
        "paper":     ("Paper Trading",  "Simulación en vivo"),
        "reports":   ("Reportes",       "Exportar"),
        "settings":  ("Ajustes",        "Configuración"),
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FinanzIAs — Seguimiento de Inversiones")
        self.setMinimumSize(1300, 900)
        self.setStyleSheet(DARK_THEME)
        self._build_ui()
        self._connect_signals()
        # Center and resize to fit content on most screens
        self.resize(1980, 1140)

        # Paper-trading background scheduler (interval + daily cron + startup)
        self.paper_scheduler = PaperScheduler(self)
        self.paper_scheduler.scan_started.connect(self._on_paper_scan_started)
        self.paper_scheduler.scan_completed.connect(self._on_paper_scan_completed)
        self.paper_scheduler.scan_failed.connect(self._on_paper_scan_failed)
        self.paper_scheduler.start()

    def _build_ui(self):
        # Root horizontal: sidebar | content
        root_widget = QWidget()
        self.setCentralWidget(root_widget)
        root_layout = QHBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar()
        root_layout.addWidget(self.sidebar)

        # Right side: topbar + page stack
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.topbar = TopBar()
        right_layout.addWidget(self.topbar)

        # Page stack
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background-color: {PALETTE['bg']};")

        self.home_tab      = HomeTab()
        self.portfolio_tab = PortfolioTab()
        self.analysis_tab  = AnalysisTab()
        self.alerts_tab    = AlertsTab()
        self.paper_tab     = PaperTradingTab()
        self.reports_tab   = ReportsTab()
        self.settings_tab  = SettingsTab()

        self.stack.addWidget(self.home_tab)       # 0
        self.stack.addWidget(self.portfolio_tab)  # 1
        self.stack.addWidget(self.analysis_tab)   # 2
        self.stack.addWidget(self.alerts_tab)     # 3
        self.stack.addWidget(self.paper_tab)      # 4
        self.stack.addWidget(self.reports_tab)    # 5
        self.stack.addWidget(self.settings_tab)   # 6

        right_layout.addWidget(self.stack, stretch=1)
        root_layout.addWidget(right, stretch=1)

        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("FinanzIAs listo.")
        self.setStatusBar(self.status_bar)

    _PAGE_IDX = {
        "home": 0, "portfolio": 1, "analysis": 2,
        "alerts": 3, "paper": 4, "reports": 5, "settings": 6,
    }

    def _connect_signals(self):
        self.sidebar.navigate.connect(self._navigate)
        self.portfolio_tab.position_selected.connect(self._on_position_selected)
        self.home_tab.navigate.connect(self._navigate)
        self.settings_tab.setting_changed.connect(self._on_setting_changed)
        self.settings_tab.rsi_scan_requested.connect(self._run_rsi_scan)

        # Paper-trading tab <-> scheduler wiring
        self.paper_tab.scan_requested.connect(self._on_paper_tab_scan_request)

        # Open on the configured default tab
        if not settings.get("default_home"):
            self._navigate("portfolio")

    def _navigate(self, key: str):
        idx = self._PAGE_IDX.get(key, 0)
        self.stack.setCurrentIndex(idx)
        title, subtitle = self.PAGE_TITLES.get(key, ("", ""))
        self.topbar.set_title(title, subtitle)
        self.sidebar.set_active(key)

        # Side effects
        pid = self.portfolio_tab.get_current_portfolio_id()
        if key == "alerts" and pid:
            self.alerts_tab.set_portfolio_id(pid)
        elif key == "reports" and pid:
            self.reports_tab.set_portfolio_id(pid, self.portfolio_tab._prices)
        elif key == "home":
            self.home_tab.refresh(self.portfolio_tab)
        elif key == "paper":
            # Refresh paper data each time the tab is shown.
            try:
                self.paper_tab._refresh_all()
            except Exception as e:
                print(f"[MainWindow] paper refresh failed: {e}")

    def _on_position_selected(self, position):
        self._navigate("analysis")
        self.analysis_tab.analyze_ticker(position.ticker)

    def _on_setting_changed(self, key: str, value: bool):
        """React immediately to settings that require live side-effects."""
        if key == "auto_refresh":
            self.portfolio_tab.set_auto_refresh(value)

    def _run_rsi_scan(self):
        """Triggered when rsi_alerts is turned ON. Scan portfolio RSI in background."""
        pid = self.portfolio_tab.get_current_portfolio_id()
        if pid is None:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "RSI Scan",
                "Seleccioná un portafolio primero para escanear el RSI."
            )
            return
        from ui.rsi_scanner import RsiScanDialog
        dlg = RsiScanDialog(pid, parent=self)
        dlg.exec()

    # ── Paper-trading scheduler callbacks ─────────────────────────────────────

    def _on_paper_scan_started(self, account_id: int):
        self.status_bar.showMessage(f"Paper trading: escaneando cuenta #{account_id}…", 3_000)

    def _on_paper_scan_completed(self, result):
        parts = [f"cuenta #{result.account_id}", result.strategy, result.mode]
        if result.filled:
            parts.append(f"{result.filled} ejecutadas")
        if result.queued:
            parts.append(f"{result.queued} pendientes")
        if result.skipped:
            parts.append(f"{result.skipped} omitidas")
        if not (result.filled or result.queued or result.skipped):
            parts.append("sin acción")
        self.status_bar.showMessage(f"Paper scan · {' · '.join(parts)}", 8_000)
        # Let the paper tab refresh if the scanned account is the one shown.
        try:
            self.paper_tab.on_scan_completed(result)
        except Exception as e:
            print(f"[MainWindow] paper_tab.on_scan_completed: {e}")

    def _on_paper_scan_failed(self, account_id: int, error: str):
        self.status_bar.showMessage(
            f"Paper scan falló (#{account_id}): {error}", 10_000
        )
        try:
            self.paper_tab.on_scan_failed(account_id, error)
        except Exception as e:
            print(f"[MainWindow] paper_tab.on_scan_failed: {e}")

    def _on_paper_tab_scan_request(self, account_id: int):
        """Manual "Escanear ahora" button in PaperTradingTab."""
        try:
            self.paper_scheduler.scan_now(int(account_id))
        except Exception as e:
            self.status_bar.showMessage(f"No se pudo iniciar el escaneo: {e}", 6_000)

    # ── Qt lifecycle ──────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Shut down background workers cleanly before the app exits."""
        try:
            if hasattr(self, "paper_scheduler") and self.paper_scheduler is not None:
                self.paper_scheduler.stop()
        except Exception as e:
            print(f"[MainWindow.closeEvent] scheduler stop failed: {e}")
        super().closeEvent(event)
