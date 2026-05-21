"""
Pestaña: Tickers fallidos.

Muestra los símbolos que Yahoo Finance no pudo resolver (deslistados, mal
escritos, sin datos) con su último error, contador de fallos y fechas.

Acciones disponibles:
- Reintentar el seleccionado → marca status=retry y el próximo fetch lo prueba
- Ignorar el seleccionado    → status=ignored (sigue oculto)
- Eliminar del registro       → borra la fila (próximo fetch volverá a probar)
- Vaciar todo                 → limpia toda la tabla
- Refrescar                   → recarga la lista desde la DB
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from data import failed_tickers as registry
from ui.styles import PALETTE
from ui.time_utils import fmt_local
from ui.widgets import HSeparator, SectionHeader

_STATUS_LABELS = {
    registry.STATUS_FAILING: ("Fallando", PALETTE["red"]),
    registry.STATUS_RETRY: ("Reintentar", PALETTE.get("yellow", "#d29922")),
    registry.STATUS_IGNORED: ("Ignorado", PALETTE["text3"]),
}


class FailedTickersTab(QWidget):
    """Lista de tickers que fallaron al consultar Yahoo Finance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[registry.FailedTickerRow] = []
        self._build_ui()
        self.refresh()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        header = SectionHeader("Tickers fallidos", "↻ Refrescar")
        if header.action_btn:
            header.action_btn.clicked.connect(self.refresh)
        root.addWidget(header)

        hint = QLabel(
            "Símbolos que Yahoo Finance no pudo resolver. "
            "Se omiten automáticamente en las próximas consultas para reducir el ruido en los logs. "
            "Usá <b>Reintentar</b> si creés que el símbolo ya está disponible de nuevo."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 12px;")
        root.addWidget(hint)
        root.addWidget(HSeparator())

        # Tabla
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Ticker", "Estado", "Operación", "Fallos", "Último error", "Última falla"]
        )
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table)

        # Botonera inferior
        bottom = QHBoxLayout()
        self.retry_btn = QPushButton("↻ Reintentar")
        self.retry_btn.clicked.connect(self._retry_selected)
        bottom.addWidget(self.retry_btn)

        self.ignore_btn = QPushButton("🚫 Ignorar")
        self.ignore_btn.clicked.connect(self._ignore_selected)
        bottom.addWidget(self.ignore_btn)

        self.delete_btn = QPushButton("🗑  Eliminar")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.clicked.connect(self._delete_selected)
        bottom.addWidget(self.delete_btn)

        bottom.addStretch()

        self.clear_btn = QPushButton("Vaciar todo")
        self.clear_btn.setObjectName("danger")
        self.clear_btn.clicked.connect(self._clear_all)
        bottom.addWidget(self.clear_btn)

        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        bottom.addWidget(self.status_label)

        root.addLayout(bottom)

        # Habilitar/deshabilitar botones según selección
        self.table.itemSelectionChanged.connect(self._update_button_state)
        self._update_button_state()

    def _update_button_state(self):
        has_selection = self.table.currentRow() >= 0
        self.retry_btn.setEnabled(has_selection)
        self.ignore_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        self.clear_btn.setEnabled(self.table.rowCount() > 0)

    # ── Data ──────────────────────────────────────────────────────────────────

    def refresh(self):
        """Recarga la tabla desde la DB."""
        self._rows = registry.get_all()
        self._render_table()
        if not self._rows:
            self.status_label.setText("✓ No hay tickers fallidos registrados.")
        else:
            self.status_label.setText(f"{len(self._rows)} ticker(s) con fallos.")
        self._update_button_state()

    def _render_table(self):
        self.table.setRowCount(0)
        for row_data in self._rows:
            row = self.table.rowCount()
            self.table.insertRow(row)

            def cell(text, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align)
                return item

            # Ticker
            ticker_item = cell(row_data.ticker)
            f = ticker_item.font()
            f.setBold(True)
            ticker_item.setFont(f)
            self.table.setItem(row, 0, ticker_item)

            # Estado coloreado
            label, color = _STATUS_LABELS.get(row_data.status, (row_data.status, PALETTE["text3"]))
            status_item = cell(label)
            status_item.setForeground(QColor(color))
            self.table.setItem(row, 1, status_item)

            # Operación
            self.table.setItem(row, 2, cell(row_data.last_operation or "—"))

            # Fallos (alineado a la derecha)
            self.table.setItem(
                row,
                3,
                cell(
                    row_data.fail_count,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
            )

            # Último error
            err = row_data.last_error or "—"
            err_item = cell(err)
            err_item.setToolTip(err)
            self.table.setItem(row, 4, err_item)

            # Última falla
            last = fmt_local(row_data.last_failed_at, "%d/%m/%Y %H:%M")
            self.table.setItem(row, 5, cell(last))

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _selected_ticker(self) -> str | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row].ticker

    def _retry_selected(self):
        ticker = self._selected_ticker()
        if not ticker:
            return
        registry.mark_for_retry(ticker)
        self.status_label.setText(f"{ticker} marcado para reintento en la próxima consulta.")
        self.refresh()

    def _ignore_selected(self):
        ticker = self._selected_ticker()
        if not ticker:
            return
        registry.mark_ignored(ticker)
        self.status_label.setText(f"{ticker} marcado como ignorado permanentemente.")
        self.refresh()

    def _delete_selected(self):
        ticker = self._selected_ticker()
        if not ticker:
            return
        reply = QMessageBox.question(
            self,
            "Confirmar",
            f"¿Eliminar el registro de fallo para <b>{ticker}</b>?<br><br>"
            "Se borra solo el historial — la próxima consulta volverá a intentarlo.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            registry.delete(ticker)
            self.status_label.setText(f"{ticker} eliminado del registro.")
            self.refresh()

    def _clear_all(self):
        if self.table.rowCount() == 0:
            return
        reply = QMessageBox.question(
            self,
            "Confirmar",
            f"¿Vaciar la lista completa de tickers fallidos? "
            f"Se borrarán {self.table.rowCount()} registro(s).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            count = registry.clear_all()
            self.status_label.setText(f"Se eliminaron {count} registro(s).")
            self.refresh()
