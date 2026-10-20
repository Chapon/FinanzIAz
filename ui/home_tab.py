"""
Home dashboard tab — Fuse-style analytics layout.

Top hero area-chart, a row of KPI tiles, then a bottom row with the
welcome/health card, a portfolio-allocation donut, and quick settings.

**Todo sale de la cartera REAL «Mis Acciones»** (tarea 264, decisión de Chapa: *«home debería
mostrar el portfolio, no las cuentas de sim de paper trading»*). Antes salía de una cuenta de
paper trading —y encima de la 1, cerrada, elegida por id fijo—. El paper trading tiene su lugar
en Paper y Métricas. Los números se arman en ``database.cartera_real.resumen_home``.

Desde la tarea 359 el gráfico grande **también** puede mostrar las cuentas paper, y desde la 360
se tildan: una o varias a la vez, en el mismo eje. «Mis Acciones» arranca tildada, y las tarjetas
de abajo son siempre suyas.
"""

from __future__ import annotations

import contextlib
from collections import Counter
from types import SimpleNamespace

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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


def _pesos_con_signo(v: float) -> str:
    """``+$1,234`` / ``-$1,234``: el f-string de antes escribía ``$-1,234`` (tarea 359)."""
    return f"{'+' if v >= 0 else '-'}${abs(v):,.0f}"


log = get_logger(__name__)

# Tarea 334: las vistas del gráfico grande de Home, (texto del selector, clave).
VISTAS_HOME = (
    ("Valor de mercado", "valor"),
    ("Sólo ganancias", "ganancia"),
    ("Monto invertido", "invertido"),
)
# Tarea 359: de una cuenta paper la tercera vista no es un costo (los snapshots no lo guardan).
TEXTO_INVERTIDO_PAPER = "Efectivo y posiciones"
# Tarea 360: con varias cuentas tildadas, la tercera vista mezcla el costo de la cartera con las
# posiciones a mercado de las paper; el rótulo lo dice.
TEXTO_INVERTIDO_VARIAS = "Invertido / en posiciones"
# Un color por cuenta, en el orden de los checkboxes.
COLORES_CUENTAS = ("accent", "orange", "purple", "positive", "blue", "yellow", "red")


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
        self._r: dict | None = None  # el último resumen_home: el selector re-pinta sin recalcular
        self._paper: dict[int, list] = {}  # equity diaria por cuenta paper, leída al tildarla (tarea 359)
        self._ref: dict[int, object] = {}  # su universo sin elegir (tarea 377), calculado al tildarla
        self._cuentas_paper: dict[int, tuple[str, float]] = {}  # id → (nombre, capital inicial)
        self.cuenta_checks: dict[int | None, QCheckBox] = {}  # None = la cartera real (tarea 360)
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
        # Tarea 334: un selector de tres vistas (era el botón «Ver sólo ganancias» de la 332).
        self.vista_combo = QComboBox()
        for texto, clave in VISTAS_HOME:
            self.vista_combo.addItem(texto, clave)
        self.vista_combo.setMinimumHeight(36)
        self.vista_combo.setToolTip(
            "Valor de mercado: acciones en cartera × cierre de cada día (incluye la plata puesta).\n"
            "Sólo ganancias: sin la plata puesta — no realizada, realizada y dividendos cobrados.\n"
            "Monto invertido: lo que costaron, por FIFO, las acciones que siguen en cartera."
        )
        self.vista_combo.currentIndexChanged.connect(self._pintar_hero)
        cabecera = QHBoxLayout()
        textos = QVBoxLayout()
        textos.addWidget(self.hero_title)
        textos.addWidget(self.hero_sub)
        cabecera.addLayout(textos, stretch=1)
        cabecera.addWidget(self.vista_combo)
        hero_layout.addLayout(cabecera)
        # Tarea 360: un checkbox por cuenta (era el desplegable de la 359). Los llena `load_data`.
        self.cuentas_fila = QHBoxLayout()
        self.cuentas_fila.setSpacing(16)
        cuentas_lbl = QLabel("Cuentas:")
        cuentas_lbl.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 12px;")
        cuentas_lbl.setToolTip(
            "Qué cuentas muestra el gráfico grande, superpuestas en el mismo eje.\n"
            "Con una sola tildada se ve su detalle. Las tarjetas de abajo son siempre de «Mis Acciones»."
        )
        self.cuentas_fila.addWidget(cuentas_lbl)
        self.cuentas_fila.addStretch()
        hero_layout.addLayout(self.cuentas_fila)

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

        self._llenar_cuentas(CARTERA_HOME)
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
        delta = f"{_pesos_con_signo(r['pl'])}  ({r['pl_pct']:+.2f}%)"
        if r["sin_precio"]:
            delta += f" · {len(r['sin_precio'])} sin precio"
        self.kpi_pl.set_value(f"${r['valor']:,.0f}", delta=delta, delta_positive=(r["pl"] >= 0))

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

    def _llenar_cuentas(self, cartera: str) -> None:
        """Los checkboxes de cuentas (tarea 360): la cartera real primero, después todas las paper.

        Conservan lo tildado entre refrescos (al principio, sólo la cartera); la cerrada va
        rotulada, no escondida.
        """
        from paper_trading.account import list_accounts

        tildadas = set(self._cuentas_tildadas()) if self.cuenta_checks else {None}
        for cb in self.cuenta_checks.values():
            self.cuentas_fila.removeWidget(cb)
            cb.deleteLater()
        self.cuenta_checks = {}
        self._paper.clear()
        self._ref.clear()
        self._cuentas_paper = {}
        cuentas = [(None, cartera)]
        try:
            for a in sorted(list_accounts(), key=lambda a: a.id):
                self._cuentas_paper[a.id] = (a.name, float(a.initial_capital))
                cuentas.append((a.id, f"Paper · {a.name}{'' if a.is_active else ' (cerrada)'}"))
        except Exception:
            log.exception("Home: no se pudieron listar las cuentas paper")
        for i, (clave, texto) in enumerate(cuentas):
            cb = QCheckBox(texto)
            cb.setChecked(clave in tildadas)
            color = PALETTE[COLORES_CUENTAS[i % len(COLORES_CUENTAS)]]
            cb.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
            cb.toggled.connect(self._pintar_hero)
            self.cuentas_fila.insertWidget(self.cuentas_fila.count() - 1, cb)  # antes del stretch
            self.cuenta_checks[clave] = cb

    def _cuentas_tildadas(self) -> list[int | None]:
        return [clave for clave, cb in self.cuenta_checks.items() if cb.isChecked()]

    def _color_cuenta(self, clave: int | None) -> str:
        i = list(self.cuenta_checks).index(clave)
        return PALETTE[COLORES_CUENTAS[i % len(COLORES_CUENTAS)]]

    def _pintar_hero(self, *_args) -> None:
        """El gráfico grande: las cuentas tildadas (tarea 360) en la vista del selector (tarea 334).

        Una sola tildada muestra su detalle; varias, una línea por cuenta en el mismo eje. Re-pinta
        con el último resumen, sin recalcular. La sparkline de «VALOR Y P/L» es siempre de la
        cartera y sigue a la vista (tanda 2026-10-07 [F-2]).
        """
        vista = self.vista_combo.currentData()
        tildadas = self._cuentas_tildadas()
        if tildadas == [None]:
            texto_inv = VISTAS_HOME[2][0]
        elif len(tildadas) == 1:
            texto_inv = TEXTO_INVERTIDO_PAPER
        else:
            texto_inv = TEXTO_INVERTIDO_VARIAS
        self.vista_combo.setItemText(self.vista_combo.findData("invertido"), texto_inv)
        self._pintar_spark(vista)
        ganancia = (self._r or {}).get("ganancia_diaria") or []
        self.vista_combo.setEnabled(tildadas != [None] or len(ganancia) >= 2)
        if not tildadas:
            self.hero_title.setText("Ninguna cuenta tildada")
            self.hero_sub.setText("Tildá una o varias cuentas para graficarlas.")
            self.hero_chart.set_data([])
        elif tildadas == [None]:
            self._pintar_cartera(vista)
        elif len(tildadas) == 1:
            self._pintar_paper(tildadas[0], vista)
        else:
            self._pintar_varias(tildadas, vista)

    def _pintar_spark(self, vista: str) -> None:
        """La sparkline de «VALOR Y P/L»: la cartera, en la serie de la vista (tarea 334)."""
        r = self._r
        if r is None:
            return
        serie = r.get("valor_diario") or []
        ganancia = r.get("ganancia_diaria") or []
        if vista == "ganancia" and len(ganancia) >= 2:
            spark = [x["total"] for _, x in ganancia]
        elif vista == "invertido" and len(ganancia) >= 2:
            spark = [x["costo"] for _, x in ganancia]
        elif len(serie) >= 2:
            spark = [v for _, v in serie]
        else:
            spark = [v for _, v in r["invertido_neto"]]
        self.kpi_pl.set_series(spark[-40:])

    def _pintar_cartera(self, vista: str) -> None:
        """La cartera sola: valor de mercado, sólo la ganancia (la 332) o el monto invertido."""
        r = self._r
        if r is None:
            return
        serie = r.get("valor_diario") or []
        ganancia = r.get("ganancia_diaria") or []
        avisos = []
        if r.get("valor_diario_sin_historia"):
            avisos.append(f"sin historia: {', '.join(r['valor_diario_sin_historia'])}")
        for t, (compra, primer) in sorted((r.get("valor_diario_sin_cierre") or {}).items()):
            # Tarea 336: comprado antes de su primer cierre; esos días no suma (no hay precio).
            avisos.append(
                f"{t} suma desde el {primer:%d/%m/%y} (comprada el {compra:%d/%m/%y}, sin cierres antes)"
            )
        primera_tx = min(r.get("tx_por_dia") or [None]) if r.get("tx_por_dia") else None
        if serie and primera_tx is not None and serie[0][0] > primera_tx:
            # El cache de cierres arranca después de la primera compra: lo de antes no se grafica.
            avisos.append(
                f"cierres desde el {serie[0][0]:%d/%m/%y}; la primera compra es del {primera_tx:%d/%m/%y}"
            )
        cola = f"  ·  {' · '.join(avisos)}" if avisos else ""

        if vista == "ganancia" and len(ganancia) >= 2:
            ult = ganancia[-1][1]
            self.hero_title.setText(
                f"{r['nombre']} — ganancia, hasta el {ganancia[-1][0]:%d/%m}: "
                f"{_pesos_con_signo(ult['total'])}"
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
        elif vista == "invertido" and len(ganancia) >= 2:
            # El costo abierto FIFO, la «plata puesta» de la 332 — no compras − ventas.
            costo = [(d, x["costo"]) for d, x in ganancia]
            self.hero_title.setText(
                f"{r['nombre']} — monto invertido, hasta el {costo[-1][0]:%d/%m}: ${costo[-1][1]:,.0f}"
            )
            self.hero_sub.setText(
                "Lo que costaron, por FIFO, las acciones que siguen en cartera (sin la comisión de "
                "compra). Una venta lo baja en el costo de lo vendido, no en lo cobrado: no es "
                f"compras − ventas.{cola}"
            )
            self.hero_chart.set_data(
                [SimpleNamespace(snapshot_at=f, total_equity=v) for f, v in costo],
                ylabel="Monto invertido ($)",
            )
        elif len(serie) >= 2:
            # Tarea 305: el valor de mercado por rueda.
            self.hero_title.setText(f"{r['nombre']} — valor de mercado, hasta el {serie[-1][0]:%d/%m}")
            self.hero_sub.setText(
                "Acciones en cartera × cierre de cada día: incluye la plata puesta. "
                f"«Sólo ganancias» la saca.{cola}"
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

    def _equity_paper(self, account_id: int) -> list:
        """La equity diaria de una cuenta paper, leída una vez por carga (tarea 359)."""
        from paper_trading.account import equity_diaria

        if account_id not in self._paper:
            try:
                self._paper[account_id] = equity_diaria(account_id)
            except Exception:
                log.exception("Home: no se pudo leer la equity de la cuenta paper %s", account_id)
                self._paper[account_id] = []
        return self._paper[account_id]

    def _referencia(self, account_id: int):
        """El universo de la cuenta sin elegir (tarea 377), calculado una vez por carga."""
        from paper_trading.referencia import CurvaReferencia, referencia_de_cuenta

        if account_id not in self._ref:
            try:
                self._ref[account_id] = referencia_de_cuenta(account_id)
            except Exception:
                log.exception("Home: no se pudo calcular la referencia de la cuenta paper %s", account_id)
                self._ref[account_id] = CurvaReferencia()
        return self._ref[account_id]

    def _serie_referencia(self, account_id: int, vista: str) -> tuple[str, list, list[float]] | None:
        """La línea de la referencia en la vista: valor, o valor menos el capital. En «invertido» no va."""
        if vista == "invertido" or account_id not in self._cuentas_paper:
            return None
        ref = self._referencia(account_id)
        if len(ref.serie) < 2:
            return None
        nombre, capital = self._cuentas_paper[account_id]
        resta = capital if vista == "ganancia" else 0.0
        return (
            f"Universo de {nombre}, sin elegir",
            [d for d, _ in ref.serie],
            [v - resta for _, v in ref.serie],
        )

    def _nota_referencia(self, account_id: int) -> str:
        """Qué es la línea punteada y qué quedó afuera, para no pintar un hueco como dato."""
        ref = self._referencia(account_id)
        partes = [
            f"Punteada: los {ref.n} de la watchlist de hoy en partes iguales desde el alta, rebalanceo "
            f"mensual y los costos del motor (${ref.costos:,.0f}); no es point-in-time"
        ]
        if ref.sin_historia:
            partes.append(f"afuera, sin precio al alta: {', '.join(ref.sin_historia)}")
        if ref.quietos:
            partes.append(
                "quietos desde que dejaron de cotizar: "
                + ", ".join(f"{t} ({d:%d/%m})" for t, d in ref.quietos)
            )
        return " · ".join(partes) + "."

    def _con_referencia(self, account_id: int, vista: str, linea: tuple, ylabel: str) -> bool:
        """Dibuja la cuenta junto a su referencia (tarea 377). ``False`` si no hay referencia."""
        ref = self._serie_referencia(account_id, vista)
        if ref is None:
            return False
        rotulo, xs, ys, color = linea
        self.hero_chart.set_series(
            [(rotulo, xs, ys, color), (*ref, color, "--")], ylabel=ylabel, cero=vista == "ganancia"
        )
        self.hero_sub.setText(f"{self.hero_sub.text()} {self._nota_referencia(account_id)}")
        return True

    def _pintar_paper(self, account_id: int, vista: str) -> None:
        """Una cuenta paper sola (tarea 359): el último snapshot de cada día.

        No toca las tarjetas ni la sparkline: esas son de «Mis Acciones».
        """
        nombre = self.cuenta_checks[account_id].text()
        serie = self._equity_paper(account_id)
        if account_id not in self._cuentas_paper or len(serie) < 2:
            self.hero_title.setText(f"{nombre} — sin historia de equity para graficar")
            self.hero_sub.setText("La cuenta no tiene snapshots de equity en dos días distintos todavía.")
            self.hero_chart.set_data([])
            return
        capital = self._cuentas_paper[account_id][1]
        hasta = f"{serie[-1][0]:%d/%m}"
        cola = f"Último snapshot de cada día (hora de Nueva York). Capital inicial ${capital:,.0f}."
        xs = [d for d, *_ in serie]
        if vista == "ganancia":
            ganancia = [eq - capital for *_, eq in serie]
            self.hero_title.setText(
                f"{nombre} — ganancia, hasta el {hasta}: {_pesos_con_signo(ganancia[-1])}"
            )
            self.hero_sub.setText(
                "Equity menos el capital inicial: realizada, no realizada y dividendos juntos "
                f"(los snapshots no los separan). {cola}"
            )
            if not self._con_referencia(
                account_id, vista, (nombre, xs, ganancia, PALETTE["accent"]), "Ganancia ($)"
            ):
                self.hero_chart.set_lineas(
                    xs, [("Ganancia total", ganancia, PALETTE["accent"])], ylabel="Ganancia ($)"
                )
        elif vista == "invertido":
            self.hero_title.setText(
                f"{nombre} — efectivo y posiciones, hasta el {hasta}: "
                f"${serie[-1][2]:,.0f} en posiciones · ${serie[-1][1]:,.0f} en efectivo"
            )
            self.hero_sub.setText(
                f"Las posiciones a valor de mercado, no a costo: los snapshots no guardan lo que costaron. {cola}"
            )
            self.hero_chart.set_lineas(
                xs,
                [
                    ("En posiciones", [p for _, _, p, _ in serie], PALETTE["accent"]),
                    ("Efectivo", [c for _, c, _, _ in serie], PALETTE["orange"]),
                ],
                ylabel="Monto ($)",
            )
        else:
            self.hero_title.setText(f"{nombre} — valor de la cuenta, hasta el {hasta}: ${serie[-1][3]:,.0f}")
            self.hero_sub.setText(f"Efectivo + posiciones a valor de mercado. {cola}")
            if not self._con_referencia(
                account_id,
                vista,
                (nombre, xs, [eq for *_, eq in serie], PALETTE["accent"]),
                "Valor de la cuenta ($)",
            ):
                self.hero_chart.set_data(
                    [SimpleNamespace(snapshot_at=d, total_equity=eq) for d, *_, eq in serie],
                    ylabel="Valor de la cuenta ($)",
                )

    def _serie_de(self, clave: int | None, vista: str) -> tuple[str, list, list[float]] | None:
        """La línea de una cuenta cuando hay varias tildadas (tarea 360): (rótulo, fechas, valores)."""
        if clave is None:
            r = self._r
            if r is None:
                return None
            ganancia = r.get("ganancia_diaria") or []
            if vista == "ganancia":
                pares = [(d, x["total"]) for d, x in ganancia]
            elif vista == "invertido":
                pares = [(d, x["costo"]) for d, x in ganancia]
            else:
                pares = list(r.get("valor_diario") or [])
            rotulo = r["nombre"] + (" (costo)" if vista == "invertido" else "")
        else:
            if clave not in self._cuentas_paper:
                return None
            nombre, capital = self._cuentas_paper[clave]
            serie = self._equity_paper(clave)
            if vista == "ganancia":
                pares = [(d, eq - capital) for d, *_, eq in serie]
            elif vista == "invertido":
                pares = [(d, p) for d, _, p, _ in serie]
            else:
                pares = [(d, eq) for d, *_, eq in serie]
            rotulo = nombre + (" (posiciones a mercado)" if vista == "invertido" else "")
        if not pares:
            return None
        return rotulo, [d for d, _ in pares], [v for _, v in pares]

    def _pintar_varias(self, tildadas: list[int | None], vista: str) -> None:
        """Varias cuentas tildadas (tarea 360): una línea por cuenta, en el mismo eje y con sus fechas."""
        nombre_vista = {"ganancia": "ganancia", "invertido": "invertido / en posiciones"}.get(vista, "valor")
        series, ultimos, sin, notas_ref = [], [], [], []
        for clave in tildadas:
            s = self._serie_de(clave, vista)
            if s is None:
                sin.append(self.cuenta_checks[clave].text())
                continue
            rotulo, xs, ys = s
            series.append((rotulo, xs, ys, self._color_cuenta(clave)))
            ultimo = _pesos_con_signo(ys[-1]) if vista == "ganancia" else f"${ys[-1]:,.0f}"
            ultimos.append(f"{rotulo} {ultimo} ({xs[-1]:%d/%m})")
            ref = self._serie_referencia(clave, vista) if clave is not None else None
            if ref is not None:
                # Tarea 377: punteada, del color de su cuenta.
                r_rot, r_xs, r_ys = ref
                series.append((r_rot, r_xs, r_ys, self._color_cuenta(clave), "--"))
                r_ult = _pesos_con_signo(r_ys[-1]) if vista == "ganancia" else f"${r_ys[-1]:,.0f}"
                ultimos.append(f"{r_rot} {r_ult} ({r_xs[-1]:%d/%m})")
                notas_ref.append(self._nota_referencia(clave))
        self.hero_title.setText(f"{len(tildadas)} cuentas — {nombre_vista}")
        notas = {
            "ganancia": "La cartera: ganancia total. Las paper: equity menos el capital inicial.",
            "invertido": "La cartera: lo que costó lo que sigue en cartera. Las paper: las posiciones a "
            "valor de mercado (los snapshots no guardan el costo).",
        }.get(vista, "La cartera: valor de mercado. Las paper: efectivo + posiciones.")
        extra = f" · sin datos: {', '.join(sin)}" if sin else ""
        ref = f" {' '.join(notas_ref)}" if notas_ref else ""
        self.hero_sub.setText(f"{' · '.join(ultimos)}. {notas}{extra}{ref}")
        ylabel = {"ganancia": "Ganancia ($)", "invertido": "Monto ($)"}.get(vista, "Valor ($)")
        self.hero_chart.set_series(series, ylabel=ylabel, cero=vista == "ganancia")

    def refresh(self, portfolio_tab=None) -> None:
        """Called by the main window on data refresh. Reloads the real portfolio."""
        self.load_data()
