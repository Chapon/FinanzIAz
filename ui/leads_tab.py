"""
Leads tab — escanea el universo (S&P 500 por default) y rankea tickers con
mayoría de recomendaciones Strong Buy / Buy del mes más reciente.

Layout
------
  ┌─ Header ──────────────────────────────────────────────────────────────┐
  │  Filtros: score mínimo · # analistas mínimo · Escanear · Progress     │
  ├─ Tabla ───────────────────────────────────────────────────────────────┤
  │  Ticker · Veredicto · Score · # · %SB · %B · %H · %S · %SS · Precio │
  │         · Target medio · Upside %                                     │
  └────────────────────────────────────────────────────────────────────────┘

Doble click en una fila → navega a la pestaña de Análisis con ese ticker.

Refresh: manual con botón "Escanear". El cache de 6h en
``data.yahoo_finance.get_analyst_data`` hace que re-escaneos del mismo
universo dentro de la ventana sean casi instantáneos.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analysis.leads import LeadRow, filter_leads
from data.ticker_universe import get_sp500_tickers
from ui.leads.worker import LeadsScanWorker
from ui.widgets import table_header, table_vheader

# Color del veredicto por bucket — alineado al RecommendationsCard
VERDICT_COLORS = {
    "Compra fuerte": "#0b5d2a",
    "Compra": "#7cd992",
    "Mantener": "#fbbc04",
    "Venta": "#ff7043",
    "Venta fuerte": "#ea4335",
}

# Columnas en orden visual: (header visible, tooltip explicativo)
# El ancho se calcula dinámicamente por contenido — no se hardcodea.
COLUMNS: list[tuple[str, str]] = [
    ("Ticker", "Símbolo bursátil (ej. AAPL, MSFT)."),
    (
        "Veredicto",
        "Etiqueta agregada derivada del score:\n"
        "  ≥ +1.5 → Compra fuerte\n"
        "  ≥ +0.5 → Compra\n"
        "  ≥ −0.5 → Mantener\n"
        "  ≥ −1.5 → Venta\n"
        "  <  −1.5 → Venta fuerte",
    ),
    (
        "Score",
        "Promedio ponderado del consensus del mes actual:\n"
        "  Strong Buy = +2 · Buy = +1 · Hold = 0 · Sell = −1 · Strong Sell = −2.\n"
        "Rango teórico [−2, +2]. Cuanto más alto, mayor convicción alcista.",
    ),
    (
        "# Analistas",
        "Cantidad total de analistas que cubrieron el ticker en el mes actual.\n"
        "Cobertura baja (< 5) suele ser ruidosa — usá el filtro de mínimo.",
    ),
    ("% Compra fuerte", "Porcentaje de analistas con recomendación Strong Buy en el mes actual."),
    ("% Compra", "Porcentaje de analistas con recomendación Buy en el mes actual."),
    ("% Mantener", "Porcentaje de analistas con recomendación Hold en el mes actual."),
    ("% Venta", "Porcentaje de analistas con recomendación Sell en el mes actual."),
    ("% Venta fuerte", "Porcentaje de analistas con recomendación Strong Sell en el mes actual."),
    ("Precio actual", "Último precio reportado por Yahoo (puede tener delay de hasta 15 min)."),
    (
        "Target medio",
        "Promedio de los price targets publicados por los analistas.\n"
        "Yahoo expone también low/high/median — acá usamos solo el mean.",
    ),
    (
        "Upside %",
        "Variación implícita: (Target medio / Precio actual − 1) × 100.\n"
        "Verde si el target está por encima del precio, rojo si está por debajo.",
    ),
]


class LeadsTab(QWidget):
    """Scanner de leads basado en consensus de analistas."""

    # Emitido al hacer doble click — el main_window lo enruta al AnalysisTab
    ticker_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: LeadsScanWorker | None = None
        self._raw_rows: list[LeadRow] = []  # último resultado sin filtrar
        self._build_ui()

    # ── UI build ──────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # Header: explicación + filtros + botón
        header = QHBoxLayout()
        header.setSpacing(10)

        title = QLabel("Leads — consensus de analistas")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #e2e8f0;")
        header.addWidget(title)
        header.addStretch()

        score_lbl = QLabel("Score mín:")
        score_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header.addWidget(score_lbl)
        self.score_input = QDoubleSpinBox()
        self.score_input.setRange(-2.0, 2.0)
        self.score_input.setSingleStep(0.1)
        self.score_input.setDecimals(2)
        self.score_input.setValue(1.0)
        self.score_input.setToolTip(
            "Promedio ponderado de los buckets del mes actual. "
            "+2 = todos Strong Buy, +1 = todos Buy, 0 = todos Hold."
        )
        self.score_input.valueChanged.connect(self._apply_filters)
        header.addWidget(self.score_input)

        an_lbl = QLabel("# analistas mín:")
        an_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header.addWidget(an_lbl)
        self.analysts_input = QSpinBox()
        self.analysts_input.setRange(1, 50)
        self.analysts_input.setValue(5)
        self.analysts_input.setToolTip(
            "Mínimo de analistas que cubren el ticker (filtra small caps con poca cobertura)."
        )
        self.analysts_input.valueChanged.connect(self._apply_filters)
        header.addWidget(self.analysts_input)

        self.scan_btn = QPushButton("Escanear S&P 500")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.setMinimumHeight(36)
        self.scan_btn.clicked.connect(self._start_scan)
        header.addWidget(self.scan_btn)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.clicked.connect(self._cancel_scan)
        header.addWidget(self.cancel_btn)

        root.addLayout(header)

        # Subtítulo / estado
        self.status_lbl = QLabel(
            "Apretá «Escanear» para barrer el S&P 500 y rankear por score (sBuy=+2, buy=+1, ...). "
            "Cache 6h: scans repetidos son casi instantáneos."
        )
        self.status_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        # Progress bar (oculta hasta que arranca un scan)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)

        # Tabla de resultados
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        table_vheader(self.table).setVisible(False)
        self.table.doubleClicked.connect(self._on_row_double_clicked)

        # Headers con tooltips explicativos. Usamos QTableWidgetItem en vez de
        # setHorizontalHeaderLabels para poder asociar tooltip por columna.
        for i, (label, tooltip) in enumerate(COLUMNS):
            header_item = QTableWidgetItem(label)
            header_item.setToolTip(tooltip)
            self.table.setHorizontalHeaderItem(i, header_item)

        # Anchos: el header arranca en modo Interactive (usuario puede arrastrar)
        # y nosotros auto-ajustamos después de cargar cada batch de filas (ver
        # ``_auto_fit_columns``). Así el título nunca queda cortado pero el
        # usuario puede agrandar columnas si quiere.
        header_widget = table_header(self.table)
        header_widget.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header_widget.setStretchLastSection(False)
        header_widget.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header_widget.setMinimumSectionSize(60)

        root.addWidget(self.table, stretch=1)

        # Auto-fit inicial diferido: si lo llamamos ahora, ``fontMetrics()``
        # devuelve el font default (no el bold real del header) porque el
        # widget todavía no fue mostrado. ``QTimer.singleShot(0, ...)`` lo
        # encola para después de que el event loop renderice una vez,
        # cuando la font real ya está aplicada.
        QTimer.singleShot(0, self._auto_fit_columns)

    # ── Scan lifecycle ────────────────────────────────────────────────────
    def _start_scan(self):
        # Si ya hay uno corriendo, no arrancar otro
        if self._worker and self._worker.isRunning():
            return

        tickers = get_sp500_tickers()
        if not tickers:
            self.status_lbl.setText("❌ No se pudo cargar el universo de tickers.")
            return

        self.status_lbl.setText(f"Escaneando {len(tickers)} tickers… (cache de 6h activo)")
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.scan_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.table.setRowCount(0)

        self._worker = LeadsScanWorker(tickers, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_scan_done)
        self._worker.error.connect(self._on_scan_error)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.start()

    def _cancel_scan(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.status_lbl.setText("Cancelando…")

    def _on_progress(self, pct: int, msg: str):
        self.progress.setValue(pct)
        self.status_lbl.setText(f"Escaneando… {msg}")

    def _on_scan_done(self, rows: list[LeadRow]):
        self._raw_rows = rows
        self._apply_filters()

    def _on_scan_error(self, exc: Exception):
        self.status_lbl.setText(f"❌ Error durante el scan: {exc}")

    def _on_scan_finished(self):
        # Se llama después de done/error sí o sí
        self.progress.setVisible(False)
        self.scan_btn.setVisible(True)
        self.cancel_btn.setVisible(False)

    # ── Filter + render ───────────────────────────────────────────────────
    def _apply_filters(self):
        if not self._raw_rows:
            return
        filtered = filter_leads(
            self._raw_rows,
            min_score=self.score_input.value(),
            min_analysts=self.analysts_input.value(),
        )
        self._populate_table(filtered)
        self.status_lbl.setText(
            f"{len(filtered)} leads (de {len(self._raw_rows)} con datos) · "
            f"filtros: score ≥ {self.score_input.value():.2f} · "
            f"≥ {self.analysts_input.value()} analistas · doble click para analizar"
        )

    def _populate_table(self, rows: list[LeadRow]):
        # Hay que desactivar sorting mientras se cargan filas para no
        # corromper el orden con cada insert.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for r_idx, row in enumerate(rows):
            cells = [
                (row.ticker, None),
                (row.verdict, VERDICT_COLORS.get(row.verdict)),
                (f"{row.score:+.2f}", None),
                (str(row.total_analysts), None),
                (f"{row.pct_strong_buy:.0f}%", None),
                (f"{row.pct_buy:.0f}%", None),
                (f"{row.pct_hold:.0f}%", None),
                (f"{row.pct_sell:.0f}%", None),
                (f"{row.pct_strong_sell:.0f}%", None),
                (f"${row.price:,.2f}" if row.price is not None else "—", None),
                (f"${row.mean_target:,.2f}" if row.mean_target is not None else "—", None),
                (
                    f"{row.upside_pct:+.1f}%" if row.upside_pct is not None else "—",
                    "#4ade80" if (row.upside_pct or 0) >= 0 else "#fb7185",
                ),
            ]

            for c_idx, (text, color) in enumerate(cells):
                item = QTableWidgetItem()
                # Para que el sort funcione numéricamente en columnas numéricas
                # le seteamos Qt.UserRole con el valor crudo.
                raw = self._raw_for_col(row, c_idx)
                if raw is not None:
                    item.setData(Qt.ItemDataRole.UserRole, raw)
                item.setText(text)
                if color:
                    item.setForeground(QColor(color))
                # Alinear numéricas a la derecha
                if c_idx >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r_idx, c_idx, item)

        self.table.setSortingEnabled(True)
        # Sort default por Score descendente
        self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        # Re-ajustar anchos al contenido nuevo
        self._auto_fit_columns()

    def _auto_fit_columns(self):
        """Ajusta cada columna al max(ancho del header, ancho del contenido) + pad.

        ``resizeColumnsToContents`` solo mira las celdas, no el header. Para
        evitar que el título se corte:
          - Medimos con una copia **bold** del font del header (los headers
            de Qt render en bold, así que el font normal subestima el ancho).
          - Padding de 44px: ~16 padding interno del header + 16 para la
            flecha de sort + 12 de respiro. Generoso a propósito — mejor
            sobrar 10px que cortar la última letra.
        """
        self.table.resizeColumnsToContents()

        header = table_header(self.table)
        bold_font = header.font()
        bold_font.setBold(True)
        fm = QFontMetrics(bold_font)
        header_pad = 44
        cell_pad = 16

        for i, (label, _tooltip) in enumerate(COLUMNS):
            header_min = fm.horizontalAdvance(label) + header_pad
            current = self.table.columnWidth(i)
            new_width = max(current + cell_pad, header_min)
            self.table.setColumnWidth(i, new_width)

    @staticmethod
    def _raw_for_col(row: LeadRow, col_idx: int):
        """Valor numérico crudo para que el sort de la columna funcione bien."""
        mapping = {
            2: row.score,
            3: row.total_analysts,
            4: row.pct_strong_buy,
            5: row.pct_buy,
            6: row.pct_hold,
            7: row.pct_sell,
            8: row.pct_strong_sell,
            9: row.price if row.price is not None else -1,
            10: row.mean_target if row.mean_target is not None else -1,
            11: row.upside_pct if row.upside_pct is not None else -999,
        }
        return mapping.get(col_idx)

    def _on_row_double_clicked(self, index):
        ticker_item = self.table.item(index.row(), 0)
        if ticker_item:
            self.ticker_selected.emit(ticker_item.text())
