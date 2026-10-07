"""
Home dashboard tab — Fuse-style analytics layout.

Top hero area-chart, a row of KPI tiles, then a bottom row with the
welcome/health card, a portfolio-allocation donut, and quick settings.

**Todo sale de la cartera REAL «Mis Acciones»** (tarea 264, decisión de Chapa: *«home debería
mostrar el portfolio, no las cuentas de sim de paper trading»*). Antes salía de una cuenta de
paper trading —y encima de la 1, cerrada, elegida por id fijo—. El paper trading tiene su lugar
en Paper y Métricas. Los números se arman en ``database.cartera_real.resumen_home``.
"""

from __future__ import annotations

import contextlib
from collections import Counter
from types import SimpleNamespace

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

from config.logging_config import get_logger
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


log = get_logger(__name__)


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
        self.portfolio_btn = QPushButton("Ver Portafolio  →")
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
            self.status_rows["alerts"].set_status(
                "Sin disparar" if n_alerts == 0 else f"{n_alerts} disparada(s)"
            )


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
        self._r: dict | None = None  # el último resumen_home: el botón re-pinta sin recalcular
        self._build_ui()
        self.load_data()

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

        self.hero_title = QLabel("Mis Acciones")
        self.hero_title.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 16px; font-weight: 700;")
        # El subtítulo lo escribe `_pintar_hero`: el fijo decía «capital invertido neto… no es valor
        # de mercado» desde la 264, y desde la 305 el gráfico ES el valor de mercado.
        self.hero_sub = QLabel("")
        self.hero_sub.setWordWrap(True)
        self.hero_sub.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 12px;")
        # Tarea 332: ocultar la plata puesta y graficar sólo la ganancia.
        self.ganancia_btn = QPushButton("Ver sólo ganancias")
        self.ganancia_btn.setCheckable(True)
        self.ganancia_btn.setMinimumHeight(36)
        self.ganancia_btn.setToolTip(
            "Saca del gráfico el costo de las acciones en cartera (la plata puesta) y muestra\n"
            "la ganancia: no realizada, realizada y dividendos cobrados."
        )
        self.ganancia_btn.toggled.connect(self._pintar_hero)
        cabecera = QHBoxLayout()
        textos = QVBoxLayout()
        textos.addWidget(self.hero_title)
        textos.addWidget(self.hero_sub)
        cabecera.addLayout(textos, stretch=1)
        cabecera.addWidget(self.ganancia_btn)
        hero_layout.addLayout(cabecera)

        self.hero_chart = AreaChartHero()
        self.hero_chart.setMinimumHeight(240)
        hero_layout.addWidget(self.hero_chart)
        root.addWidget(hero_card)

        # ── KPI row ─────────────────────────────────────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(16)

        self.kpi_pl = KpiCard("VALOR Y P/L", kind="area", color=PALETTE["accent"])
        self.kpi_trades = KpiCard("TRANSACCIONES", kind="bar", color=PALETTE["orange"])
        self.kpi_positions = KpiCard("POSICIONES ABIERTAS", kind="spike", color=PALETTE["purple"])

        for card in (self.kpi_pl, self.kpi_trades, self.kpi_positions):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            kpi_row.addWidget(card)
        root.addLayout(kpi_row)

        # ── Bottom row: welcome + donut + quick settings ────────────────────
        bottom = QHBoxLayout()
        bottom.setSpacing(16)

        self.welcome_card = WelcomeCard()
        self.welcome_card.portfolio_btn.clicked.connect(lambda: self.navigate.emit("portfolio"))
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
    def load_data(self) -> None:
        """Llena Home con la cartera real «Mis Acciones» (tarea 264).

        Si falla, lo **loguea y lo dice** en la pantalla: antes corría bajo
        ``suppress(Exception)`` y Home quedaba con los números viejos sin avisar.
        """
        from database.cartera_real import CARTERA_HOME, resumen_home
        from database.models import session_scope

        try:
            with session_scope() as session:
                r = resumen_home(session)
        except Exception:
            log.exception("Home: no se pudo cargar la cartera %s", CARTERA_HOME)
            self.kpi_pl.set_value("—", delta="error al cargar (ver el log)", delta_positive=False)
            return
        if r is None:
            # No se elige otra cartera en silencio: se dice.
            self.hero_title.setText(f"No encontré la cartera «{CARTERA_HOME}»")
            self.kpi_pl.set_value("—", delta=f"no existe «{CARTERA_HOME}»", delta_positive=None)
            self.kpi_positions.set_value("0", delta="", delta_positive=None)
            self.donut.set_data([])
            self.hero_chart.set_data([])
            self.welcome_card.update_status(0, 0.0, 0)
            return

        self._r = r
        self._pintar_hero()

        # Valor y P&L sólo sobre las posiciones CON precio; las que no tienen, se dicen.
        delta = f"{'+' if r['pl'] >= 0 else ''}${r['pl']:,.0f}  ({r['pl_pct']:+.2f}%)"
        if r["sin_precio"]:
            delta += f" · {len(r['sin_precio'])} sin precio"
        self.kpi_pl.set_value(f"${r['valor']:,.0f}", delta=delta, delta_positive=(r["pl"] >= 0))
        self.kpi_pl.set_series([v for _, v in r["invertido_neto"][-40:]])

        self.kpi_trades.set_value(_abbrev(r["transacciones"]), delta="registradas", delta_positive=None)
        por_dia = Counter(r["tx_por_dia"])
        if por_dia:
            self.kpi_trades.set_series([por_dia[d] for d in sorted(por_dia)[-14:]])

        self.kpi_positions.set_value(str(r["posiciones"]), delta="abiertas", delta_positive=None)
        if r["torta"]:
            self.kpi_positions.set_series([v for _, v in r["torta"]])
        # A valor de mercado: la torta usaba el costo y se rotulaba «distribución».
        self.donut.set_data(r["torta"])

        self.welcome_card.update_status(r["posiciones"], r["pl_pct"], r["alertas_disparadas"])

    def _pintar_hero(self, *_args) -> None:
        """El gráfico grande: valor de mercado, o —con el botón— sólo la ganancia (tarea 332)."""
        self.ganancia_btn.setText(
            "Ver valor de mercado" if self.ganancia_btn.isChecked() else "Ver sólo ganancias"
        )
        r = self._r
        if r is None:
            return
        serie = r.get("valor_diario") or []
        ganancia = r.get("ganancia_diaria") or []
        avisos = []
        if r.get("valor_diario_sin_historia"):
            avisos.append(f"sin historia: {', '.join(r['valor_diario_sin_historia'])}")
        primera_tx = min(r.get("tx_por_dia") or [None]) if r.get("tx_por_dia") else None
        if serie and primera_tx is not None and serie[0][0] > primera_tx:
            # El cache de cierres arranca después de la primera compra: lo de antes no se grafica.
            avisos.append(
                f"cierres desde el {serie[0][0]:%d/%m/%y}; la primera compra es del {primera_tx:%d/%m/%y}"
            )
        cola = f"  ·  {' · '.join(avisos)}" if avisos else ""

        if self.ganancia_btn.isChecked() and len(ganancia) >= 2:
            ult = ganancia[-1][1]
            self.hero_title.setText(
                f"{r['nombre']} — ganancia, hasta el {ganancia[-1][0]:%d/%m}: "
                f"{'+' if ult['total'] >= 0 else ''}${ult['total']:,.0f}"
            )
            sin_cal = r.get("ganancia_sin_calendario") or []
            extra = f" · sin calendario de dividendos: {', '.join(sin_cal)}" if sin_cal else ""
            self.hero_sub.setText(
                "Sin la plata puesta (el costo de lo que sigue en cartera). "
                f"No realizada ${ult['no_realizado']:,.0f} · realizada ${ult['realizado']:,.0f} · "
                f"dividendos ${ult['dividendos']:,.0f}{extra}{cola}"
            )
            xs = [d for d, _ in ganancia]
            self.hero_chart.set_lineas(
                xs,
                [
                    ("Ganancia total", [x["total"] for _, x in ganancia], PALETTE["accent"]),
                    ("No realizada", [x["no_realizado"] for _, x in ganancia], PALETTE["orange"]),
                    ("Realizada", [x["realizado"] for _, x in ganancia], PALETTE["purple"]),
                    ("Dividendos", [x["dividendos"] for _, x in ganancia], PALETTE["positive"]),
                ],
                ylabel="Ganancia ($)",
            )
        elif len(serie) >= 2:
            # Tarea 305: el valor de mercado por rueda.
            self.hero_title.setText(f"{r['nombre']} — valor de mercado, hasta el {serie[-1][0]:%d/%m}")
            self.hero_sub.setText(
                "Acciones en cartera × cierre de cada día: incluye la plata puesta. "
                f"«Ver sólo ganancias» la saca.{cola}"
            )
            self.hero_chart.set_data(
                [SimpleNamespace(snapshot_at=f, total_equity=v) for f, v in serie],
                ylabel="Valor de mercado ($)",
            )
        else:
            # El invertido neto queda de respaldo: en una cartera comprada en un solo día es UN punto.
            self.hero_title.setText(f"{r['nombre']} — capital invertido neto (sin cierres en el cache)")
            self.hero_sub.setText(
                "Compras menos ventas acumuladas, a precio de transacción (no es valor de mercado)"
            )
            self.hero_chart.set_data(
                [SimpleNamespace(snapshot_at=f, total_equity=v) for f, v in r["invertido_neto"]],
                ylabel="Invertido neto ($)",
            )
        self.ganancia_btn.setEnabled(len(ganancia) >= 2)

    def refresh(self, portfolio_tab=None) -> None:
        """Called by the main window on data refresh. Reloads the real portfolio."""
        self.load_data()
