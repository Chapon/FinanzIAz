"""
Home dashboard tab — Fuse-style analytics layout.

Top hero equity area-chart, a row of KPI tiles, then a bottom row with the
welcome/health card, a portfolio-allocation donut, and quick settings.
All metrics come from the active paper-trading account (real data).
"""

from __future__ import annotations

import contextlib
from collections import Counter

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from data.yahoo_finance import is_market_open
from ui.dashboard_charts import AreaChartHero, DonutChart, KpiCard
from ui.styles import PALETTE
from ui.widgets import (
    FeatureCard,
    HSeparator,
    SettingsRow,
    StatusRow,
)


def _abbrev(n: float) -> str:
    """Compact number formatting: 1234 → 1.2k, 2_500_000 → 2.5M."""
    n = float(n)
    for div, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if abs(n) >= div:
            return f"{n / div:.1f}{suffix}".replace(".0", "")
    return f"{int(n)}"


def _resolve_account_id() -> int | None:
    """Active paper account id — prefers id=1 ("Sim Principal"), else first active."""
    try:
        from paper_trading.account import get_account, list_accounts

        if get_account(1) is not None:
            return 1
        accounts = list_accounts(active_only=True) or list_accounts()
        return accounts[0].id if accounts else None
    except Exception:
        return None


class WelcomeCard(QFrame):
    """Left welcome card with portfolio health status rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(4)

        greeting = QLabel("Bienvenido de vuelta,")
        greeting.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 12px;")
        layout.addWidget(greeting)

        self.name_label = QLabel("Chapa")
        self.name_label.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 26px; font-weight: 800;")
        layout.addWidget(self.name_label)
        layout.addSpacing(16)

        # Status rows
        self.status_rows: dict[str, StatusRow] = {}
        _market_open, _market_label = is_market_open()
        rows_data = [
            ("portfolio", "📊", "Portafolio", "Cargando..."),
            ("perf", "📈", "Rendimiento", "Cargando..."),
            ("alerts", "🔔", "Alertas", "Sin disparar"),
            ("market", "🌐", "Mercado", _market_label),
        ]
        for key, icon, label, status in rows_data:
            row = StatusRow(icon, label, status)
            self.status_rows[key] = row
            layout.addWidget(row)
            if key != "market":
                layout.addWidget(StatusRow.separator())

        layout.addStretch()

        # Navigate link
        self.portfolio_btn = QPushButton("Ver Paper Trading  →")
        self.portfolio_btn.setStyleSheet(
            f"background-color: {PALETTE['accent_bg']}; "
            f"color: {PALETTE['accent']}; "
            f"border: 1px solid {PALETTE['border_lt']}; border-radius: 8px; "
            f"padding: 8px 14px; font-weight: 700; font-size: 12px;"
        )
        layout.addWidget(self.portfolio_btn)

    def update_status(self, n_positions: int, pl_pct: float, n_alerts: int) -> None:
        with contextlib.suppress(Exception):
            self.status_rows["portfolio"].set_status(f"{n_positions} posiciones")
            sign = "+" if pl_pct >= 0 else ""
            ok = pl_pct >= 0
            self.status_rows["perf"].set_status(
                f"{sign}{pl_pct:.2f}%",
                color=PALETTE["positive"] if ok else PALETTE["red"],
            )
            self.status_rows["alerts"].set_status("Sin disparar" if n_alerts == 0 else f"{n_alerts} activas")


class PlatformSettingsCard(QFrame):
    """Quick-settings card (mirrors the old IQON Platform Settings panel)."""

    settings_changed = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(0)

        title = QLabel("Configuración Rápida")
        title.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 15px; font-weight: 700;")
        layout.addWidget(title)
        layout.addSpacing(14)

        gen_lbl = QLabel("PREFERENCIAS GENERALES")
        gen_lbl.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        )
        layout.addWidget(gen_lbl)
        layout.addSpacing(8)

        self._rows: dict[str, SettingsRow] = {}
        general_settings = [
            ("notif", "Notificaciones de alertas", True),
            ("auto_refresh", "Actualización automática", True),
            ("default_home", "Abrir en Home al iniciar", True),
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
            ("realtime", "Precios en tiempo real", False),
            ("perf_log", "Guardar historial P&L", True),
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
        # Initial load from the DB; guarded so an empty/fresh DB can't crash the UI.
        with contextlib.suppress(Exception):
            self.load_paper_data()

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

        # ── Hero: equity area chart ─────────────────────────────────────────
        hero_card = QFrame()
        hero_card.setObjectName("card")
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(20, 16, 20, 16)
        hero_layout.setSpacing(6)

        hero_title = QLabel("Curva de Equity")
        hero_title.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 16px; font-weight: 700;")
        hero_sub = QLabel("Evolución del capital de la cuenta de paper trading")
        hero_sub.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 12px;")
        hero_layout.addWidget(hero_title)
        hero_layout.addWidget(hero_sub)

        self.hero_chart = AreaChartHero()
        self.hero_chart.setMinimumHeight(240)
        hero_layout.addWidget(self.hero_chart)
        root.addWidget(hero_card)

        # ── KPI row ─────────────────────────────────────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(16)

        self.kpi_pl = KpiCard("P/L TOTAL", kind="area", color=PALETTE["accent"])
        self.kpi_trades = KpiCard("OPERACIONES", kind="bar", color=PALETTE["orange"])
        self.kpi_positions = KpiCard("POSICIONES ABIERTAS", kind="spike", color=PALETTE["purple"])

        for card in (self.kpi_pl, self.kpi_trades, self.kpi_positions):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            kpi_row.addWidget(card)
        root.addLayout(kpi_row)

        # ── Bottom row: welcome + donut + quick settings ────────────────────
        bottom = QHBoxLayout()
        bottom.setSpacing(16)

        self.welcome_card = WelcomeCard()
        self.welcome_card.portfolio_btn.clicked.connect(lambda: self.navigate.emit("paper"))
        bottom.addWidget(self.welcome_card)

        self.donut = DonutChart("Distribución de cartera")
        self.donut.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bottom.addWidget(self.donut, stretch=1)

        self.platform_card = PlatformSettingsCard()
        bottom.addWidget(self.platform_card)
        root.addLayout(bottom)

        # ── Quick-access feature cards ──────────────────────────────────────
        row2_label = QLabel("Acceso Rápido")
        row2_label.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 11px; font-weight: 700; "
            f"text-transform: uppercase; letter-spacing: 1px;"
        )
        root.addWidget(row2_label)

        row2 = QHBoxLayout()
        row2.setSpacing(14)
        features = [
            ("📈  Análisis Técnico", "Motor RSI, MACD, Bollinger", "Listo", True, "Analizar  →", "analysis"),
            ("🔔  Alertas de Precio", "Monitoreo en tiempo real", "Activo", True, "Ver alertas →", "alerts"),
            ("📄  Reportes", "PDF y Excel", "Disponible", True, "Exportar  →", "reports"),
            ("📥  Importar CSV", "Yahoo Finance / genérico", "Disponible", True, "Importar  →", "portfolio"),
        ]
        for title, sub, status, ok, action, page in features:
            card = FeatureCard(title, sub, status, ok, action)
            card.clicked.connect(lambda p=page: self.navigate.emit(p))
            row2.addWidget(card)
        root.addLayout(row2)
        root.addStretch()

    # ── Data loading ────────────────────────────────────────────────────────
    def load_paper_data(self) -> None:
        """Populate hero chart, KPI tiles, and donut from the active paper account."""
        from paper_trading.account import (
            count_orders,
            get_account,
            get_equity_curve,
            get_orders,
            get_positions,
        )

        acct_id = _resolve_account_id()
        if acct_id is None:
            return
        acct = get_account(acct_id)

        # Equity curve → hero + P/L KPI
        curve = get_equity_curve(acct_id)
        self.hero_chart.set_data(curve)

        initial = float(getattr(acct, "initial_capital", 0.0) or 0.0)
        if curve:
            last_eq = float(curve[-1].total_equity)
            pl = last_eq - initial if initial else 0.0
            pl_pct = (pl / initial * 100.0) if initial else 0.0
            self.kpi_pl.set_value(
                f"${last_eq:,.0f}",
                delta=f"{'+' if pl >= 0 else ''}${pl:,.0f}  ({pl_pct:+.2f}%)",
                delta_positive=(pl >= 0),
            )
            self.kpi_pl.set_series([float(s.total_equity) for s in curve[-40:]])
        else:
            self.kpi_pl.set_value(f"${initial:,.0f}", delta="Sin movimientos", delta_positive=None)
            pl_pct = 0.0

        # Orders → trades KPI (filled), with a daily bar sparkline
        n_filled = count_orders(acct_id, status="filled")
        self.kpi_trades.set_value(_abbrev(n_filled), delta="órdenes ejecutadas", delta_positive=None)
        recent = get_orders(acct_id, status="filled", limit=500)
        by_day: Counter = Counter()
        for o in recent:
            ts = getattr(o, "filled_at", None) or getattr(o, "created_at", None)
            if ts is not None:
                by_day[ts.date()] += 1
        if by_day:
            days = sorted(by_day)[-14:]
            self.kpi_trades.set_series([by_day[d] for d in days])

        # Positions → positions KPI + donut
        positions = get_positions(acct_id)
        self.kpi_positions.set_value(str(len(positions)), delta="en cartera", delta_positive=None)
        cost_bases = [float(p.shares) * float(p.avg_cost) for p in positions]
        if cost_bases:
            self.kpi_positions.set_series(sorted(cost_bases, reverse=True))
        self.donut.set_data([(p.ticker, float(p.shares) * float(p.avg_cost)) for p in positions])

        # Welcome card health rows
        self.welcome_card.update_status(len(positions), pl_pct, 0)

    def refresh(self, portfolio_tab=None) -> None:
        """Called by the main window on data refresh. Reloads paper-account data."""
        with contextlib.suppress(Exception):
            self.load_paper_data()
