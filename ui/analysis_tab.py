"""
Analysis tab: technical chart + signal cards for any ticker.

Layout
------
  ┌─ Splitter ──────────────────────────────────────────────────────────────┐
  │  Left: ChartWidget (price/RSI/MACD)                                     │
  │        + Static indicator legend                                         │
  │  Right: company header, overall badge, metric cards,                     │
  │         indicator signal cards (static) OR per-day hover panel          │
  └──────────────────────────────────────────────────────────────────────────┘

Hover behaviour
---------------
  When mouse is over the chart, a vertical crosshair follows the cursor.
  The right panel switches to show per-day computed signals for the hovered date.
  When mouse leaves the chart the right panel restores to the current analysis.
"""
import math
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QScrollArea, QFrame, QSizePolicy,
    QSplitter, QToolTip, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from data.yahoo_finance import get_historical_data, get_current_price, get_company_info
from analysis.technical import analyze, get_support_resistance, to_yahoo_level
from ui.chart_widget import ChartWidget
from ui.widgets import SignalBadge, MetricCard, HSeparator
from ui.styles import SIGNAL_COLORS, PALETTE
from config.settings_manager import settings


# ── Yahoo-level display helpers ────────────────────────────────────────────────
_YAHOO_COLORS = {
    "Strong Buy":   "#22c55e",
    "Buy":          "#4ade80",
    "Hold":         "#fbbf24",
    "Underperform": "#fb923c",
    "Sell":         "#f87171",
}
_YAHOO_LABELS_ES = {
    "Strong Buy":   "Compra Fuerte",
    "Buy":          "Comprar",
    "Hold":         "Mantener",
    "Underperform": "Vender",
    "Sell":         "Venta Fuerte",
}


# ── Tooltip content ────────────────────────────────────────────────────────────
TOOLTIPS = {
    "RSI": (
        "<b>RSI — Índice de Fuerza Relativa</b><br><br>"
        "Mide la velocidad y magnitud de los movimientos de precio en una escala de 0 a 100.<br><br>"
        "<b>Cómo interpretarlo:</b><br>"
        "• <span style='color:#f87171'>RSI &gt; 70</span> → Sobrecompra: el precio subió demasiado rápido, "
        "posible corrección a la baja.<br>"
        "• <span style='color:#4ade80'>RSI &lt; 30</span> → Sobreventa: el precio cayó demasiado rápido, "
        "posible rebote al alza.<br>"
        "• RSI entre 30 y 70 → Zona neutral, sin señal clara.<br><br>"
        "<b>Período estándar:</b> 14 días."
    ),
    "MACD": (
        "<b>MACD — Convergencia/Divergencia de Medias Móviles</b><br><br>"
        "Compara dos medias móviles exponenciales (EMA 12 y EMA 26) para detectar cambios de tendencia.<br><br>"
        "<b>Componentes:</b><br>"
        "• <b>Línea MACD</b>: diferencia entre EMA12 y EMA26.<br>"
        "• <b>Línea de señal</b>: EMA9 del MACD.<br>"
        "• <b>Histograma</b>: diferencia entre MACD y señal.<br><br>"
        "<b>Cómo usarlo:</b><br>"
        "• MACD cruza <i>por encima</i> de la señal → señal de <span style='color:#4ade80'>COMPRA</span>.<br>"
        "• MACD cruza <i>por debajo</i> de la señal → señal de <span style='color:#f87171'>VENTA</span>.<br>"
        "• Histograma en verde creciente → momentum alcista."
    ),
    "Bollinger Bands": (
        "<b>Bandas de Bollinger</b><br><br>"
        "Envuelven el precio con una banda superior e inferior basadas en la desviación estándar "
        "respecto a una media móvil de 20 períodos.<br><br>"
        "<b>Cómo interpretarlas:</b><br>"
        "• Precio toca la <b>banda inferior</b> → posible <span style='color:#4ade80'>rebote alcista</span>: "
        "el precio está estadísticamente barato.<br>"
        "• Precio toca la <b>banda superior</b> → posible <span style='color:#f87171'>retroceso bajista</span>: "
        "el precio está estadísticamente caro.<br>"
        "• Bandas muy juntas (<i>squeeze</i>) → se viene un movimiento fuerte, pero la dirección es incierta.<br><br>"
        "<b>La línea del medio</b> es la SMA20 y actúa como imán de precio."
    ),
    "Golden/Death Cross": (
        "<b>Golden Cross / Death Cross</b><br><br>"
        "Compara la media móvil simple de 50 días (SMA50) con la de 200 días (SMA200) "
        "para detectar cambios de tendencia de largo plazo.<br><br>"
        "<b>Señales:</b><br>"
        "• <span style='color:#4ade80'><b>Golden Cross</b></span>: SMA50 cruza <i>por encima</i> de SMA200 "
        "→ inicio de tendencia alcista de largo plazo. Señal muy confiable.<br>"
        "• <span style='color:#f87171'><b>Death Cross</b></span>: SMA50 cruza <i>por debajo</i> de SMA200 "
        "→ inicio de tendencia bajista de largo plazo. Señal de precaución.<br><br>"
        "<b>Limitación:</b> es un indicador rezagado — confirma tendencias ya en curso, "
        "no las predice con anticipación."
    ),
    "señal_general": (
        "<b>Señal General</b><br><br>"
        "Resumen ponderado de todos los indicadores técnicos, usando el sistema de "
        "5 niveles de Yahoo Finance.<br><br>"
        "• <span style='color:#22c55e'><b>● Compra Fuerte</b></span>: consenso alcista fuerte.<br>"
        "• <span style='color:#4ade80'><b>● Comprar</b></span>: mayoría alcista moderada.<br>"
        "• <span style='color:#fbbf24'><b>● Mantener</b></span>: señales mixtas o neutrales.<br>"
        "• <span style='color:#fb923c'><b>● Vender</b></span>: mayoría bajista moderada.<br>"
        "• <span style='color:#f87171'><b>● Venta Fuerte</b></span>: consenso bajista fuerte.<br><br>"
        "<i>No es asesoramiento financiero. Siempre considerá el contexto del mercado.</i>"
    ),
    "soporte": (
        "<b>Soporte</b><br><br>"
        "Nivel de precio donde históricamente el activo encontró demanda suficiente para "
        "detener su caída y rebotar.<br><br>"
        "Calculado como el mínimo de las últimas 60 velas."
    ),
    "resistencia": (
        "<b>Resistencia</b><br><br>"
        "Nivel de precio donde históricamente el activo encontró oferta suficiente para "
        "frenar su subida y retroceder.<br><br>"
        "Calculado como el máximo de las últimas 60 velas."
    ),
    "precio_actual": (
        "<b>Precio Actual</b><br><br>"
        "Último precio operado en el mercado para este ticker.<br>"
        "Se actualiza con caché de 5 minutos desde Yahoo Finance."
    ),
    "cambio_hoy": (
        "<b>Variación del Día</b><br><br>"
        "Cambio porcentual del precio respecto al cierre del día anterior.<br><br>"
        "• <span style='color:#4ade80'>Verde</span>: el precio subió hoy.<br>"
        "• <span style='color:#f87171'>Rojo</span>: el precio bajó hoy."
    ),
    "XGBoost ML": (
        "<b>XGBoost — Modelo de Machine Learning</b><br><br>"
        "Clasificador entrenado en cada análisis con los datos históricos del propio ticker.<br><br>"
        "<b>Features:</b> retornos (1/3/5/10/20 días), RSI y su tendencia de 5 días, "
        "histograma MACD y su aceleración, posición en Bandas de Bollinger, "
        "ancho del squeeze, ratio de volumen, volatilidad realizada, y ratios precio/SMA.<br><br>"
        "<b>Target:</b> ¿sube el precio en los próximos 5 días?<br><br>"
        "<b>Interpretación:</b><br>"
        "• &gt;75%: <span style='color:#22c55e'>Compra Fuerte</span> — patrones alcistas sólidos.<br>"
        "• 65-75%: <span style='color:#4ade80'>Comprar</span><br>"
        "• 35-65%: <span style='color:#fbbf24'>Neutral</span><br>"
        "• 25-35%: <span style='color:#fb923c'>Vender</span><br>"
        "• &lt;25%: <span style='color:#f87171'>Venta Fuerte</span> — patrones bajistas sólidos.<br><br>"
        "<b>Split de entrenamiento:</b> 80% histórico (entrenamiento) / 20% más reciente (validación).<br>"
        "<i>Requiere <code>pip install xgboost</code>.</i>"
    ),
    "Volumen": (
        "<b>Volumen — Acumulación / Distribución</b><br><br>"
        "Compara el volumen promedio en días alcistas vs bajistas "
        "en las últimas 10 sesiones.<br><br>"
        "<b>Señales:</b><br>"
        "• Vol. en días alcistas &gt; 1.5× días bajistas → "
        "<span style='color:#4ade80'>acumulación</span> (compradores institucionales).<br>"
        "• Vol. en días bajistas &gt; 1.5× días alcistas → "
        "<span style='color:#f87171'>distribución</span> (presión vendedora).<br>"
        "• Diferencia &lt; 1.5× → neutral.<br><br>"
        "<i>El volumen confirma (o contradice) los movimientos de precio.</i>"
    ),
    "regimen": (
        "<b>Régimen de Mercado</b><br><br>"
        "Clasifica el contexto actual del activo basándose en momentum de precio "
        "y posición respecto a medias móviles de largo plazo.<br><br>"
        "<b>Algoritmo:</b> scoring ponderado sobre retornos de 5, 20 y 60 días, "
        "más la posición del precio respecto a SMA50 y SMA200.<br><br>"
        "• <span style='color:#22c55e'><b>Alcista</b></span>: tendencia de fondo positiva — "
        "señales de compra son más confiables.<br>"
        "• <span style='color:#f87171'><b>Bajista</b></span>: tendencia de fondo negativa — "
        "señales de compra van contra la corriente; mayor riesgo.<br>"
        "• <span style='color:#fbbf24'><b>Lateral</b></span>: sin tendencia clara — "
        "señales técnicas son menos confiables.<br><br>"
        "El régimen <b>ajusta la probabilidad</b> del panel inferior."
    ),
}


def _tt(key: str) -> str:
    return TOOLTIPS.get(key, "")


PERIODS = {
    "1 mes":   "1mo",
    "3 meses": "3mo",
    "6 meses": "6mo",
    "1 año":   "1y",
    "2 años":  "2y",
    "5 años":  "5y",
}


# ── Background worker ──────────────────────────────────────────────────────────

class AnalysisWorker(QThread):
    done = pyqtSignal(object, object, object, object)  # df, result, price_data, company_info

    def __init__(self, ticker: str, period: str):
        super().__init__()
        self.ticker = ticker
        self.period = period

    def run(self):
        df = get_historical_data(self.ticker, period=self.period)
        result = (
            analyze(self.ticker, df,
                    enable_sma_cross=settings.get("sma_cross"),
                    enable_xgboost=True)
            if df is not None else None
        )
        price_data = get_current_price(self.ticker)
        company = get_company_info(self.ticker)
        self.done.emit(df, result, price_data, company)


# ── Signal card ────────────────────────────────────────────────────────────────

class SignalCard(QFrame):
    """Displays a single TechnicalSignal using Yahoo Finance's 5-level system."""
    def __init__(self, signal, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        tt = _tt(signal.indicator)
        if tt:
            self.setToolTip(tt)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        ind_label = QLabel(signal.indicator)
        ind_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        top.addWidget(ind_label)
        top.addStretch()
        yahoo_level = to_yahoo_level(signal.signal, signal.strength)
        badge = SignalBadge(yahoo_level)
        top.addWidget(badge)
        layout.addLayout(top)

        desc = QLabel(signal.description)
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 12px;")
        layout.addWidget(desc)


# ── Main tab ───────────────────────────────────────────────────────────────────

class AnalysisTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._current_result = None   # last AnalysisResult, used to restore on hover-leave
        self._current_tooltip = ""    # tooltip HTML for overall badge
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # ── Search bar ───────────────────────────────────────────────────────
        search_row = QHBoxLayout()
        self.ticker_edit = QLineEdit()
        self.ticker_edit.setPlaceholderText("Ingresá un ticker para analizar (ej: AAPL, MSFT, GGAL.BA)")
        self.ticker_edit.setMinimumWidth(280)
        self.ticker_edit.setFixedHeight(40)
        self.ticker_edit.setToolTip(
            "<b>Búsqueda de ticker</b><br><br>"
            "Ingresá el símbolo bursátil del activo que querés analizar.<br><br>"
            "Ejemplos: <b>AAPL</b> (Apple), <b>MSFT</b> (Microsoft), "
            "<b>GGAL.BA</b> (Grupo Financiero Galicia — Buenos Aires).<br><br>"
            "Presioná Enter o el botón <i>Analizar</i> para comenzar."
        )
        self.ticker_edit.returnPressed.connect(self._run_analysis)
        search_row.addWidget(self.ticker_edit)

        self.period_combo = QComboBox()
        for label in PERIODS:
            self.period_combo.addItem(label)
        self.period_combo.setCurrentText("1 año")
        self.period_combo.setFixedHeight(40)
        self.period_combo.setMinimumWidth(110)
        self.period_combo.setToolTip(
            "<b>Período de análisis</b><br><br>"
            "Cantidad de datos históricos a descargar para calcular los indicadores.<br><br>"
            "• Períodos cortos (1-3 meses): más sensibles a movimientos recientes.<br>"
            "• Períodos largos (1-5 años): mejores para detectar tendencias de fondo "
            "y calcular Golden/Death Cross (requiere al menos 1 año)."
        )
        search_row.addWidget(self.period_combo)

        self.analyze_btn = QPushButton("Analizar")
        self.analyze_btn.setFixedHeight(40)
        self.analyze_btn.setMinimumWidth(120)
        self.analyze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.analyze_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #4ade80;"
            "  color: #000000;"
            "  border: none;"
            "  border-radius: 20px;"
            "  padding: 0px 24px;"
            "  font-weight: 700;"
            "  font-size: 14px;"
            "  letter-spacing: 0.3px;"
            "}"
            "QPushButton:hover { background-color: #6ee7a0; }"
            "QPushButton:pressed { background-color: #22c55e; }"
            "QPushButton:disabled {"
            "  background-color: #1a3d28;"
            "  color: #4b5563;"
            "}"
        )
        self.analyze_btn.clicked.connect(self._run_analysis)
        search_row.addWidget(self.analyze_btn)
        root.addLayout(search_row)

        root.addWidget(HSeparator())

        # ── Splitter: left = chart+legend, right = signals ───────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left widget: chart on top, static indicator legend below
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.chart = ChartWidget()
        self.chart.setMinimumWidth(500)
        # Connect hover signal → slot in this tab
        self.chart.hover_data.connect(self._on_chart_hover)
        left_layout.addWidget(self.chart, stretch=1)

        left_layout.addWidget(self._build_legend())
        splitter.addWidget(left_widget)

        # ── Right panel ──────────────────────────────────────────────────────
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.setSpacing(6)

        # Company header
        self.company_label = QLabel("—")
        self.company_label.setObjectName("subtitle")
        self.company_label.setWordWrap(True)
        right_layout.addWidget(self.company_label)

        # Overall signal badge
        overall_row = QHBoxLayout()
        lbl_general = QLabel("Señal general:")
        lbl_general.setToolTip(_tt("señal_general"))
        overall_row.addWidget(lbl_general)
        self.overall_badge = SignalBadge("Hold")
        self.overall_badge.setFixedHeight(32)
        self.overall_badge.setMinimumWidth(140)
        self.overall_badge.setToolTip(_tt("señal_general"))
        overall_row.addWidget(self.overall_badge)
        overall_row.addStretch()
        right_layout.addLayout(overall_row)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("muted")
        self.summary_label.setWordWrap(True)
        self.summary_label.setToolTip(_tt("señal_general"))
        right_layout.addWidget(self.summary_label)

        # ── ML Context frame (regime + risk + probability bar) ────────────────
        self.context_frame = QFrame()
        self.context_frame.setObjectName("card")
        self.context_frame.setVisible(False)   # shown after first analysis
        ctx_layout = QVBoxLayout(self.context_frame)
        ctx_layout.setContentsMargins(10, 8, 10, 8)
        ctx_layout.setSpacing(6)

        # Row 1: regime badge + volatility + risk
        regime_row = QHBoxLayout()
        regime_row.setSpacing(8)

        regime_title = QLabel("Régimen:")
        regime_title.setStyleSheet("font-size: 11px; color: #6e7681;")
        regime_row.addWidget(regime_title)

        self.regime_lbl = QLabel("—")
        self.regime_lbl.setStyleSheet(
            "font-size: 12px; font-weight: 700; color: #fbbf24;"
        )
        self.regime_lbl.setToolTip(_tt("regimen"))
        regime_row.addWidget(self.regime_lbl)

        regime_row.addStretch()

        self.vol_lbl = QLabel("")
        self.vol_lbl.setStyleSheet("font-size: 11px; color: #6e7681;")
        regime_row.addWidget(self.vol_lbl)

        regime_row.addSpacing(6)

        risk_title = QLabel("Riesgo:")
        risk_title.setStyleSheet("font-size: 11px; color: #6e7681;")
        regime_row.addWidget(risk_title)

        self.risk_lbl = QLabel("—")
        self.risk_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #fbbf24;")
        regime_row.addWidget(self.risk_lbl)

        ctx_layout.addLayout(regime_row)

        # Row 2: probability bar
        self.prob_bar = QProgressBar()
        self.prob_bar.setRange(0, 100)
        self.prob_bar.setValue(50)
        self.prob_bar.setFixedHeight(22)
        self.prob_bar.setTextVisible(True)
        self.prob_bar.setToolTip(
            "<b>Probabilidad cuantitativa de compra</b><br><br>"
            "Combina el consenso de todos los indicadores (incluyendo XGBoost si está disponible) "
            "ajustado por el régimen de mercado y la volatilidad actual.<br><br>"
            "• &gt;65%: zona de compra probable<br>"
            "• 35-65%: neutral / mantener<br>"
            "• &lt;35%: zona de venta probable"
        )
        self._update_prob_bar(0.50)   # neutral default
        ctx_layout.addWidget(self.prob_bar)

        right_layout.addWidget(self.context_frame)
        # ─────────────────────────────────────────────────────────────────────

        # Metric cards
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(6)
        self.card_price = MetricCard("Precio", compact=True)
        self.card_price.setToolTip(_tt("precio_actual"))
        self.card_change = MetricCard("Cambio hoy", compact=True)
        self.card_change.setToolTip(_tt("cambio_hoy"))
        metrics_row.addWidget(self.card_price)
        metrics_row.addWidget(self.card_change)
        right_layout.addLayout(metrics_row)

        metrics_row2 = QHBoxLayout()
        metrics_row2.setSpacing(6)
        self.card_support = MetricCard("Soporte", compact=True)
        self.card_support.setToolTip(_tt("soporte"))
        self.card_resist = MetricCard("Resistencia", compact=True)
        self.card_resist.setToolTip(_tt("resistencia"))
        metrics_row2.addWidget(self.card_support)
        metrics_row2.addWidget(self.card_resist)
        right_layout.addLayout(metrics_row2)

        right_layout.addWidget(HSeparator())

        # Section title (toggles between "Indicadores técnicos" and hover label)
        self.signals_title = QLabel("Indicadores técnicos")
        self.signals_title.setObjectName("subtitle")
        self.signals_title.setToolTip(
            "<b>Indicadores Técnicos</b><br><br>"
            "Cada tarjeta muestra la señal del indicador usando el sistema de 5 niveles.<br><br>"
            "• <span style='color:#22c55e'><b>● Compra Fuerte</b></span>: señal alcista intensa.<br>"
            "• <span style='color:#4ade80'><b>● Comprar</b></span>: señal alcista moderada/débil.<br>"
            "• <span style='color:#fbbf24'><b>● Mantener</b></span>: neutral.<br>"
            "• <span style='color:#fb923c'><b>● Vender</b></span>: señal bajista moderada/débil.<br>"
            "• <span style='color:#f87171'><b>● Venta Fuerte</b></span>: señal bajista intensa.<br><br>"
            "<i>Pasá el mouse sobre el gráfico para ver el análisis de cada día histórico.</i>"
        )
        right_layout.addWidget(self.signals_title)

        # Static signal cards (scroll area)
        self.signals_scroll = QScrollArea()
        self.signals_scroll.setWidgetResizable(True)
        self.signals_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.signals_container = QWidget()
        self.signals_layout = QVBoxLayout(self.signals_container)
        self.signals_layout.setSpacing(8)
        self.signals_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.signals_scroll.setWidget(self.signals_container)
        right_layout.addWidget(self.signals_scroll, stretch=1)

        # ── Hover panel (hidden until mouse enters chart) ─────────────────────
        self.hover_panel = QFrame()
        self.hover_panel.setObjectName("card")
        self.hover_panel.setVisible(False)
        hp_layout = QVBoxLayout(self.hover_panel)
        hp_layout.setContentsMargins(12, 10, 12, 10)
        hp_layout.setSpacing(6)

        self.hover_date_lbl = QLabel("—")
        self.hover_date_lbl.setStyleSheet(
            "font-weight: 700; font-size: 12px; color: #8b949e;"
        )
        hp_layout.addWidget(self.hover_date_lbl)

        hp_layout.addWidget(HSeparator())

        # Per-indicator rows
        self._hover_ind_widgets: dict[str, tuple[QLabel, QLabel]] = {}
        _IND_DISPLAY = [
            ("RSI",               "● RSI",       "#a371f7"),
            ("MACD",              "● MACD",      "#58a6ff"),
            ("Bollinger Bands",   "● Bollinger", "#58a6ff"),
            ("Golden/Death Cross","● SMA Cross", "#d29922"),
        ]
        for ind_key, display_name, color in _IND_DISPLAY:
            row = QHBoxLayout()
            row.setSpacing(6)

            name_lbl = QLabel(display_name)
            name_lbl.setStyleSheet(
                f"color: {color}; font-size: 11px; font-weight: 600; min-width: 80px;"
            )
            row.addWidget(name_lbl)

            val_lbl = QLabel("—")
            val_lbl.setObjectName("muted")
            val_lbl.setStyleSheet("font-size: 10px; color: #6e7681;")
            row.addWidget(val_lbl, stretch=1)

            sig_lbl = QLabel("● —")
            sig_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            sig_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #fbbf24; min-width: 100px;")
            row.addWidget(sig_lbl)

            hp_layout.addLayout(row)
            self._hover_ind_widgets[ind_key] = (val_lbl, sig_lbl)

        hp_layout.addWidget(HSeparator())

        # Overall signal for the hovered day
        hover_overall_row = QHBoxLayout()
        hover_day_lbl = QLabel("Señal del día:")
        hover_day_lbl.setStyleSheet("font-size: 12px; font-weight: 600;")
        hover_overall_row.addWidget(hover_day_lbl)
        self.hover_overall_sig_lbl = QLabel("● Mantener")
        self.hover_overall_sig_lbl.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #fbbf24;"
        )
        hover_overall_row.addWidget(self.hover_overall_sig_lbl)
        hover_overall_row.addStretch()
        hp_layout.addLayout(hover_overall_row)

        note_lbl = QLabel("Análisis histórico — no predictivo")
        note_lbl.setStyleSheet("font-size: 10px; color: #4b5563; font-style: italic;")
        hp_layout.addWidget(note_lbl)

        right_layout.addWidget(self.hover_panel, stretch=1)
        # ─────────────────────────────────────────────────────────────────────

        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        right_layout.addWidget(self.status_label)

        right_panel.setMinimumWidth(300)
        right_panel.setMaximumWidth(460)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, stretch=1)

    # ── Static indicator legend ────────────────────────────────────────────────

    # ── Probability bar ────────────────────────────────────────────────────────

    def _update_prob_bar(self, prob: float):
        """
        Update the probability bar value, label and colour.

        prob 0-1:
          <0.35 → red   (venta)
          0.35-0.45 → orange
          0.45-0.55 → yellow (neutral)
          0.55-0.65 → light green
          >0.65 → green (compra)
        """
        val = int(round(prob * 100))
        self.prob_bar.setValue(val)

        if prob >= 0.65:
            color  = "#22c55e"
            label  = f"▲ Compra  {val}%"
        elif prob >= 0.55:
            color  = "#4ade80"
            label  = f"▲ Compra  {val}%"
        elif prob >= 0.45:
            color  = "#fbbf24"
            label  = f"⟶ Neutral  {val}%"
        elif prob >= 0.35:
            color  = "#fb923c"
            label  = f"▼ Venta  {100 - val}%"
        else:
            color  = "#f87171"
            label  = f"▼ Venta  {100 - val}%"

        self.prob_bar.setFormat(label)
        self.prob_bar.setStyleSheet(f"""
            QProgressBar {{
                background: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                height: 22px;
                text-align: center;
                color: #e6edf3;
                font-size: 11px;
                font-weight: 600;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 5px;
            }}
        """)

    def _build_legend(self) -> QFrame:
        """Build a compact static legend explaining all 3 chart panels."""
        frame = QFrame()
        frame.setObjectName("card")
        frame.setMaximumHeight(118)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(2)

        title = QLabel("Guía de indicadores")
        title.setStyleSheet(
            "font-weight: 700; font-size: 10px; color: #6e7681;"
            "text-transform: uppercase; letter-spacing: 0.5px;"
        )
        layout.addWidget(title)

        legend_html = (
            "<table cellspacing='1' style='font-size: 10px;'>"
            "<tr>"
            "  <td style='padding-right:6px'><span style='color:#a371f7'>● RSI</span></td>"
            "  <td style='color:#6e7681'>"
            "    &lt;30 Sobreventa <span style='color:#4ade80'>(Compra)</span>"
            "    &nbsp;·&nbsp; &gt;70 Sobrecompra <span style='color:#f87171'>(Venta)</span>"
            "    &nbsp;·&nbsp; 30-70 Neutral"
            "  </td>"
            "</tr>"
            "<tr>"
            "  <td style='padding-right:6px'><span style='color:#58a6ff'>● MACD</span></td>"
            "  <td style='color:#6e7681'>"
            "    Cruce MACD&uarr;señal = <span style='color:#4ade80'>Compra</span>"
            "    &nbsp;·&nbsp; Cruce MACD&darr;señal = <span style='color:#f87171'>Venta</span>"
            "    &nbsp;·&nbsp; Histograma = momentum"
            "  </td>"
            "</tr>"
            "<tr>"
            "  <td style='padding-right:6px'><span style='color:#58a6ff'>● BB</span></td>"
            "  <td style='color:#6e7681'>"
            "    Precio &lt; Banda inferior = <span style='color:#4ade80'>Compra</span>"
            "    &nbsp;·&nbsp; Precio &gt; Banda superior = <span style='color:#f87171'>Venta</span>"
            "    &nbsp;·&nbsp; Línea media = SMA20"
            "  </td>"
            "</tr>"
            "<tr>"
            "  <td style='padding-right:6px'><span style='color:#d29922'>● SMA</span></td>"
            "  <td style='color:#6e7681'>"
            "    Golden Cross (SMA20&uarr;SMA50) = <span style='color:#4ade80'>Alcista</span>"
            "    &nbsp;·&nbsp; Death Cross = <span style='color:#f87171'>Bajista</span>"
            "    &nbsp;·&nbsp; Tendencia de largo plazo"
            "  </td>"
            "</tr>"
            "</table>"
        )

        lbl = QLabel(legend_html)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setWordWrap(False)
        layout.addWidget(lbl)

        return frame

    # ── Public API ─────────────────────────────────────────────────────────────

    def analyze_ticker(self, ticker: str, period: str = "1y"):
        """Called from outside to trigger analysis for a specific ticker."""
        self.ticker_edit.setText(ticker)
        idx = list(PERIODS.values()).index(period) if period in PERIODS.values() else 3
        self.period_combo.setCurrentIndex(idx)
        self._run_analysis()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _run_analysis(self):
        ticker = self.ticker_edit.text().strip().upper()
        if not ticker:
            return
        period = PERIODS[self.period_combo.currentText()]
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("Analizando…")
        self.status_label.setText(f"Descargando datos para {ticker}...")
        self._clear_signals()
        self._current_result = None

        if self._worker and self._worker.isRunning():
            self._worker.quit()

        self._worker = AnalysisWorker(ticker, period)
        self._worker.done.connect(self._on_analysis_done)
        self._worker.start()

    def _on_analysis_done(self, df, result, price_data, company):
        ticker = self.ticker_edit.text().strip().upper()
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText("Analizar")

        if df is None or df.empty:
            self.status_label.setText("❌ No se encontraron datos para este ticker.")
            return

        # Company header
        name = company.get("name", ticker) if company else ticker
        sector = company.get("sector", "") if company else ""
        self.company_label.setText(f"{name}  ·  {sector}")

        # Price cards
        if price_data:
            self.card_price.set_value(f"${price_data['price']:,.4f}")
            chg = price_data.get("change_pct")
            if chg is not None:
                self.card_change.set_value(
                    f"{chg:+.2f}%",
                    color="#3fb950" if chg >= 0 else "#f85149"
                )

        # Support / resistance
        sr = get_support_resistance(df)
        if sr:
            self.card_support.set_value(f"${sr['support']:,.4f}")
            self.card_resist.set_value(f"${sr['resistance']:,.4f}")

        # Chart
        self.chart.plot_price_with_indicators(ticker, df, show_bb=settings.get("bb"))

        # Signals
        self._clear_signals()
        if result:
            self._current_result = result
            dynamic_tt = self._make_signal_tooltip(result)
            self._current_tooltip = dynamic_tt
            self.overall_badge.set_signal(result.yahoo_level)
            self.overall_badge.setToolTip(dynamic_tt)
            self.summary_label.setToolTip(dynamic_tt)
            self.summary_label.setText(result.summary)
            for sig in result.signals:
                card = SignalCard(sig, self.signals_container)
                self.signals_layout.addWidget(card)
        else:
            self.summary_label.setText("Datos insuficientes para análisis técnico.")

        # ── ML context frame ─────────────────────────────────────────────────
        if result and result.market_context:
            ctx = result.market_context
            self.regime_lbl.setText(f"{ctx.regime_icon} {ctx.regime_es}")
            self.regime_lbl.setStyleSheet(
                f"font-size: 12px; font-weight: 700; color: {ctx.regime_color};"
            )
            self.vol_lbl.setText(f"Vol. {ctx.annual_volatility:.1f}%")
            self.risk_lbl.setText(ctx.risk_es)
            self.risk_lbl.setStyleSheet(
                f"font-size: 12px; font-weight: 600; color: {ctx.risk_color};"
            )
            if result.ml_probability is not None:
                self._update_prob_bar(result.ml_probability)
            self.context_frame.setVisible(True)
        else:
            self.context_frame.setVisible(False)

        # Ensure normal view is shown
        self.signals_title.setText("Indicadores técnicos")
        self.signals_scroll.setVisible(True)
        self.hover_panel.setVisible(False)

        self.status_label.setText(
            "Análisis completado · "
            "pasá el mouse sobre el gráfico para el análisis histórico diario"
        )

    def _clear_signals(self):
        while self.signals_layout.count():
            item = self.signals_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── Chart hover ────────────────────────────────────────────────────────────

    def _on_chart_hover(self, data):
        """
        Slot connected to ChartWidget.hover_data.
        data=None → restore normal analysis view.
        data=dict → show per-day indicator signals for that date.
        """
        if data is None:
            # Restore normal view
            self.signals_title.setText("Indicadores técnicos")
            self.signals_scroll.setVisible(True)
            self.hover_panel.setVisible(False)
            if self._current_result:
                self.overall_badge.set_signal(self._current_result.yahoo_level)
                if self._current_tooltip:
                    self.overall_badge.setToolTip(self._current_tooltip)
                self.summary_label.setText(self._current_result.summary)
            return

        # Switch to hover panel
        self.signals_scroll.setVisible(False)
        self.hover_panel.setVisible(True)

        # Date header
        date = data.get('date')
        if date is not None:
            try:
                date_str = pd.Timestamp(date).strftime('%d %b %Y')
            except Exception:
                date_str = str(date)
            self.signals_title.setText(f"Análisis del {date_str}")
            self.hover_date_lbl.setText(f"📅 {date_str}")

        # Compute per-day signals
        day_sigs = self._compute_day_signals(data)

        # Update indicator rows
        for ind_key, (val_lbl, sig_lbl) in self._hover_ind_widgets.items():
            match = next((s for s in day_sigs if s[0] == ind_key), None)
            if match:
                _, raw_sig, raw_str, desc = match
                yahoo = to_yahoo_level(raw_sig, raw_str)
                color = _YAHOO_COLORS.get(yahoo, "#fbbf24")
                label = _YAHOO_LABELS_ES.get(yahoo, yahoo)
                sig_lbl.setText(f"● {label}")
                sig_lbl.setStyleSheet(
                    f"font-size: 11px; font-weight: 700; color: {color}; min-width: 100px;"
                )
                val_lbl.setText(desc[:38] + "…" if len(desc) > 38 else desc)
            else:
                sig_lbl.setText("● —")
                sig_lbl.setStyleSheet(
                    "font-size: 11px; font-weight: 700; color: #4b5563; min-width: 100px;"
                )
                val_lbl.setText("Sin datos")

        # Compute overall signal for this day
        if day_sigs:
            WEIGHTS = {"STRONG": 3, "MODERATE": 2, "WEAK": 1}
            buy_score  = sum(WEIGHTS.get(s[2], 1) for s in day_sigs if s[1] == "BUY")
            sell_score = sum(WEIGHTS.get(s[2], 1) for s in day_sigs if s[1] == "SELL")
            hold_score = sum(WEIGHTS.get(s[2], 1) for s in day_sigs if s[1] == "HOLD")
            total = buy_score + sell_score + hold_score

            if buy_score == sell_score:
                day_overall, day_str = "HOLD", "WEAK"
            else:
                dominant = max(buy_score, sell_score)
                day_overall = "BUY" if buy_score > sell_score else "SELL"
                frac = dominant / total if total > 0 else 0
                day_str = "STRONG" if frac >= 0.60 else "MODERATE" if frac >= 0.40 else "WEAK"

            day_yahoo = to_yahoo_level(day_overall, day_str)
            day_color = _YAHOO_COLORS.get(day_yahoo, "#fbbf24")
            day_label = _YAHOO_LABELS_ES.get(day_yahoo, day_yahoo)
            self.hover_overall_sig_lbl.setText(f"● {day_label}")
            self.hover_overall_sig_lbl.setStyleSheet(
                f"font-size: 13px; font-weight: 700; color: {day_color};"
            )
            # Also update the main overall badge to reflect hovered day
            self.overall_badge.set_signal(day_yahoo)
        else:
            self.hover_overall_sig_lbl.setText("● —")

    def _compute_day_signals(self, data: dict) -> list[tuple]:
        """
        Compute buy/sell/hold signals for a single day based on indicator values.
        Returns list of (indicator_name, signal, strength, description) tuples.
        """
        signals = []
        close = data.get('close')

        # ── RSI ──────────────────────────────────────────────────────────────
        rsi = data.get('rsi')
        if rsi is not None:
            if rsi < 30:
                signals.append(("RSI", "BUY",  "STRONG", f"RSI {rsi:.1f} — Sobreventa"))
            elif rsi < 40:
                signals.append(("RSI", "BUY",  "WEAK",   f"RSI {rsi:.1f} — Cerca de sobreventa"))
            elif rsi > 70:
                signals.append(("RSI", "SELL", "STRONG", f"RSI {rsi:.1f} — Sobrecompra"))
            elif rsi > 60:
                signals.append(("RSI", "SELL", "WEAK",   f"RSI {rsi:.1f} — Cerca de sobrecompra"))
            else:
                signals.append(("RSI", "HOLD", "WEAK",   f"RSI {rsi:.1f} — Neutral (30-70)"))

        # ── MACD ─────────────────────────────────────────────────────────────
        macd     = data.get('macd_line')
        sig_line = data.get('signal_line')
        hist     = data.get('histogram')
        if macd is not None and sig_line is not None:
            if macd > sig_line:
                strength = "STRONG" if (hist is not None and hist > 0) else "MODERATE"
                signals.append(("MACD", "BUY",  strength,
                                 f"MACD {macd:.3f} > señal {sig_line:.3f}"))
            elif macd < sig_line:
                strength = "STRONG" if (hist is not None and hist < 0) else "MODERATE"
                signals.append(("MACD", "SELL", strength,
                                 f"MACD {macd:.3f} < señal {sig_line:.3f}"))
            else:
                signals.append(("MACD", "HOLD", "WEAK",
                                 f"MACD en cruce ({macd:.3f})"))

        # ── Bollinger Bands ───────────────────────────────────────────────────
        upper  = data.get('upper')
        lower  = data.get('lower')
        middle = data.get('middle')
        if upper is not None and lower is not None and close is not None:
            if close < lower:
                signals.append(("Bollinger Bands", "BUY",  "STRONG",
                                 f"${close:.2f} < BB inf ${lower:.2f}"))
            elif close < middle:
                signals.append(("Bollinger Bands", "BUY",  "WEAK",
                                 f"${close:.2f} entre inf-media"))
            elif close > upper:
                signals.append(("Bollinger Bands", "SELL", "STRONG",
                                 f"${close:.2f} > BB sup ${upper:.2f}"))
            elif close > middle:
                signals.append(("Bollinger Bands", "SELL", "WEAK",
                                 f"${close:.2f} entre media-sup"))
            else:
                signals.append(("Bollinger Bands", "HOLD", "WEAK",
                                 f"${close:.2f} en banda media"))

        # ── SMA Cross ─────────────────────────────────────────────────────────
        sma20 = data.get('sma20')
        sma50 = data.get('sma50')
        if sma20 is not None and sma50 is not None:
            if sma20 > sma50:
                strength = "STRONG" if (close is not None and close > sma20) else "MODERATE"
                signals.append(("Golden/Death Cross", "BUY", strength,
                                 f"Golden: SMA20 {sma20:.2f} > SMA50 {sma50:.2f}"))
            else:
                strength = "STRONG" if (close is not None and close < sma20) else "MODERATE"
                signals.append(("Golden/Death Cross", "SELL", strength,
                                 f"Death: SMA20 {sma20:.2f} < SMA50 {sma50:.2f}"))

        return signals

    # ── Dynamic signal tooltip ─────────────────────────────────────────────────

    def _make_signal_tooltip(self, result) -> str:
        """Build an HTML tooltip explaining why the overall rating was assigned."""
        _LABELS = {
            "Strong Buy": "Compra Fuerte", "Buy": "Comprar",
            "Hold": "Mantener",
            "Underperform": "Vender", "Sell": "Venta Fuerte",
        }
        _SIG_COLOR = {
            "Strong Buy": "#22c55e", "Buy": "#4ade80",
            "Hold": "#fbbf24",
            "Underperform": "#fb923c", "Sell": "#f87171",
        }
        _DIR_COLOR  = {"BUY": "#4ade80", "SELL": "#f87171", "HOLD": "#fbbf24"}
        _DIR_ARROW  = {"BUY": "↑",       "SELL": "↓",       "HOLD": "→"}
        _DIR_LABEL  = {"BUY": "Alcista",  "SELL": "Bajista", "HOLD": "Neutral"}

        yahoo = result.yahoo_level
        color = _SIG_COLOR.get(yahoo, "#fbbf24")
        label = _LABELS.get(yahoo, yahoo)

        html = f"<b style='color:{color}; font-size:13px;'>● {label}</b><br><br>"

        html += "<b>Indicadores:</b><br>"
        for sig in result.signals:
            dc    = _DIR_COLOR.get(sig.signal, "#fbbf24")
            arrow = _DIR_ARROW.get(sig.signal, "→")
            dlbl  = _DIR_LABEL.get(sig.signal, sig.signal)
            str_txt = {"STRONG": "fuerte", "MODERATE": "moderada", "WEAK": "débil"}.get(
                sig.strength, ""
            )
            html += (
                f"&nbsp;• <b>{sig.indicator}</b> — "
                f"<span style='color:{dc}'><b>{arrow} {dlbl}</b> {str_txt}</span><br>"
                f"&nbsp;&nbsp;&nbsp;<i style='color:#8b949e'>{sig.description}</i><br>"
            )

        buy_sigs  = [s for s in result.signals if s.signal == "BUY"]
        sell_sigs = [s for s in result.signals if s.signal == "SELL"]
        hold_sigs = [s for s in result.signals if s.signal == "HOLD"]

        html += "<br><b>¿Por qué esta calificación?</b><br>"
        if buy_sigs and not sell_sigs:
            html += (
                f"<span style='color:#4ade80'>"
                f"{len(buy_sigs)} indicador{'es' if len(buy_sigs)>1 else ''} "
                f"alcista{'s' if len(buy_sigs)>1 else ''}"
                f"</span> sin señales bajistas."
            )
        elif sell_sigs and not buy_sigs:
            html += (
                f"<span style='color:#f87171'>"
                f"{len(sell_sigs)} indicador{'es' if len(sell_sigs)>1 else ''} "
                f"bajista{'s' if len(sell_sigs)>1 else ''}"
                f"</span> sin señales alcistas."
            )
        elif buy_sigs and sell_sigs:
            WEIGHTS = {"STRONG": 3, "MODERATE": 2, "WEAK": 1}
            bs = sum(WEIGHTS[s.strength] for s in buy_sigs)
            ss = sum(WEIGHTS[s.strength] for s in sell_sigs)
            if bs > ss:
                html += (
                    f"<span style='color:#4ade80'>Score alcista ({bs})</span> supera al "
                    f"<span style='color:#f87171'>bajista ({ss})</span>."
                )
            elif ss > bs:
                html += (
                    f"<span style='color:#f87171'>Score bajista ({ss})</span> supera al "
                    f"<span style='color:#4ade80'>alcista ({bs})</span>."
                )
            else:
                html += "Empate entre señales alcistas y bajistas → Mantener."
        else:
            html += "Todos los indicadores en zona neutral."

        if hold_sigs:
            html += (
                f" {len(hold_sigs)} neutral{'es' if len(hold_sigs)>1 else ''} "
                f"({'<i>' + ', '.join(s.indicator for s in hold_sigs) + '</i>'})"
                f" no suman al score."
            )

        html += (
            f"<br><br>"
            f"<span style='color:#8b949e'>Confianza: <b>{result.confidence_score:.0f}%</b> "
            f"· {len(result.signals)} indicadores analizados</span><br>"
            f"<i style='color:#4b5563'>No es asesoramiento financiero.</i>"
        )
        return html
