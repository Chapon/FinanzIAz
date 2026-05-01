"""
Alerts tab: manage price alerts and view history.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QAbstractItemView, QHeaderView, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from database.models import get_session, Alert
from alerts.alert_manager import AlertManager
from ui.dialogs import AddAlertDialog
from ui.widgets import SectionHeader, HSeparator
from ui.ticker_tooltip import apply_ticker_tooltip, install_ticker_tooltips


class AlertsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._portfolio_id = None
        self._alerts = []
        self._alert_manager = AlertManager(on_triggered=self._on_alert_triggered)
        self._build_ui()

        # Check alerts every 2 minutes
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check_alerts)
        self._check_timer.start(120_000)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        header = SectionHeader("Alertas de Precio", "+ Nueva Alerta")
        if header.action_btn:
            header.action_btn.clicked.connect(self._add_alert)
        root.addWidget(header)
        root.addWidget(HSeparator())

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Ticker", "Tipo", "Precio Objetivo", "Estado", "Creada", "Disparada", "Mensaje"
        ])
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        # Tooltip on hover over the Ticker column (col 0)
        install_ticker_tooltips(self.table, 0)
        root.addWidget(self.table)

        bottom = QHBoxLayout()
        self.delete_btn = QPushButton("Eliminar seleccionada")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_alert)
        bottom.addWidget(self.delete_btn)
        bottom.addStretch()

        self.check_btn = QPushButton("Verificar ahora")
        self.check_btn.clicked.connect(self._check_alerts)
        bottom.addWidget(self.check_btn)

        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        bottom.addWidget(self.status_label)
        root.addLayout(bottom)

        self.table.itemSelectionChanged.connect(
            lambda: self.delete_btn.setEnabled(self.table.currentRow() >= 0)
        )

    def set_portfolio_id(self, portfolio_id: int):
        self._portfolio_id = portfolio_id
        self._load_alerts()

    def _load_alerts(self):
        self._alerts = AlertManager.get_alerts(portfolio_id=self._portfolio_id)
        self._render_table()

    def _render_table(self):
        self.table.setRowCount(0)
        for alert in self._alerts:
            row = self.table.rowCount()
            self.table.insertRow(row)

            def cell(text, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align)
                return item

            ticker_item = cell(alert.ticker)
            apply_ticker_tooltip(ticker_item, alert.ticker)
            self.table.setItem(row, 0, ticker_item)

            type_text = "⬆ Por encima" if alert.alert_type == "ABOVE" else "⬇ Por debajo"
            self.table.setItem(row, 1, cell(type_text))
            self.table.setItem(row, 2, cell(f"${alert.target_value:,.4f}",
                                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))

            status = "Activa" if alert.is_active else "Disparada"
            status_item = cell(status)
            status_item.setForeground(QColor("#3fb950" if alert.is_active else "#d29922"))
            self.table.setItem(row, 3, status_item)

            created = alert.created_at.strftime("%d/%m/%Y %H:%M") if alert.created_at else "—"
            self.table.setItem(row, 4, cell(created))

            triggered = alert.triggered_at.strftime("%d/%m/%Y %H:%M") if alert.triggered_at else "—"
            self.table.setItem(row, 5, cell(triggered))

            self.table.setItem(row, 6, cell(alert.message or "—"))

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

    def _add_alert(self):
        if self._portfolio_id is None:
            QMessageBox.warning(self, "Sin portafolio", "Seleccioná un portafolio primero.")
            return
        dlg = AddAlertDialog(self._portfolio_id, self)
        if dlg.exec():
            self._load_alerts()

    def _delete_alert(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._alerts):
            return
        alert = self._alerts[row]
        reply = QMessageBox.question(
            self, "Confirmar", f"¿Eliminar alerta para {alert.ticker}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            AlertManager.delete_alert(alert.id)
            self._load_alerts()

    def _check_alerts(self):
        self.check_btn.setEnabled(False)
        self.status_label.setText("Verificando alertas...")
        triggered = self._alert_manager.check_alerts(self._portfolio_id)
        self._load_alerts()
        if triggered:
            self.status_label.setText(f"⚡ {len(triggered)} alerta(s) disparada(s).")
        else:
            self.status_label.setText("Sin alertas disparadas.")
        self.check_btn.setEnabled(True)

    def _on_alert_triggered(self, alert: Alert, price: float):
        QMessageBox.information(
            self,
            "🔔 Alerta Disparada",
            f"<b>{alert.ticker}</b> alcanzó ${price:,.4f}<br>"
            f"Objetivo: {alert.alert_type} ${alert.target_value:,.4f}<br>"
            f"{alert.message or ''}",
        )
