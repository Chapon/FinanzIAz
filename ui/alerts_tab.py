"""
Alerts tab: manage price alerts and view history.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from alerts.alert_manager import AlertManager, alert_row_actions, alert_status
from database.models import Alert
from integrations.slack import AlertNotice
from ui.dialogs import AddAlertDialog
from ui.ticker_tooltip import apply_ticker_tooltip, install_ticker_tooltips
from ui.time_utils import fmt_local
from ui.widgets import HSeparator, SectionHeader, table_header, table_vheader
from ui.workers import BaseWorker


class AlertCheckWorker(BaseWorker):
    """Corre ``check_alerts`` fuera del hilo de la GUI (tarea 80).

    Adentro, ``AlertManager.check_alerts`` pide precio **por ticker en serie**, y
    con ``PRICE_CACHE_TTL_MINUTES = 5`` contra un timer de 120 s alrededor de un
    tercio de las corridas encuentra el cache vencido y **sale a la red** — que
    con el breaker de throttle haciendo backoff son decenas de segundos, no
    décimas. Antes eso pasaba con la UI congelada.

    Emite **valores planos**, no objetos ORM: ``check_alerts`` devuelve
    ``Alert``es que quedan detachados al cerrar la sesión, y mandarlos por una
    señal entre hilos es pedir un ``DetachedInstanceError`` el día que alguien
    toque un atributo que no estaba cargado. ``AlertNotice`` ya existe para
    exactamente esto (lo usa el aviso de Slack) y tiene todo lo que muestra el
    popup.
    """

    result_ready = pyqtSignal(list)  # list[AlertNotice]

    def __init__(self, portfolio_id=None, parent=None):
        super().__init__(parent)
        self._portfolio_id = portfolio_id
        self._notices: list[AlertNotice] = []

    def _collect(self, alert: Alert, price: float) -> None:
        """Callback de ``on_triggered``: corre en el hilo del worker.

        Copia a valores planos **mientras el ORM sigue attachado** y no toca la
        UI — el popup lo abre el slot, ya en el hilo de la GUI.
        """
        self._notices.append(
            AlertNotice(
                ticker=alert.ticker,
                alert_type=alert.alert_type,
                target_value=alert.target_value,
                current_price=price,
                message=alert.message or "",
            )
        )

    def do_work(self) -> list[AlertNotice]:
        # Manager propio, con el callback que sólo acumula: el de la pestaña
        # abre un QMessageBox y desde acá sería una llamada a la UI desde otro
        # hilo.
        AlertManager(on_triggered=self._collect).check_alerts(self._portfolio_id)
        return self._notices

    def on_success(self, result: list[AlertNotice]) -> None:
        self.result_ready.emit(result)


class AlertsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._portfolio_id = None
        self._alerts = []
        self._check_worker = None
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
        self.table.setHorizontalHeaderLabels(
            ["Ticker", "Tipo", "Precio Objetivo", "Estado", "Creada", "Disparada", "Mensaje"]
        )
        table_header(self.table).setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        table_vheader(self.table).setVisible(False)
        # Tooltip on hover over the Ticker column (col 0)
        install_ticker_tooltips(self.table, 0)
        # ALRT1: menú contextual (Editar / Pausar / Eliminar) + doble-click = Editar.
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.cellDoubleClicked.connect(self._on_double_click)
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
            self.table.setItem(
                row,
                2,
                cell(
                    f"${alert.target_value:,.4f}", Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                ),
            )

            # ALRT1: tres estados. Activa (verde) / Pausada (gris) / Disparada (naranja).
            status = alert_status(alert)
            status_label = {"activa": "Activa", "pausada": "Pausada", "disparada": "Disparada"}[status]
            status_color = {"activa": "#3fb950", "pausada": "#8b949e", "disparada": "#d29922"}[status]
            status_item = cell(status_label)
            status_item.setForeground(QColor(status_color))
            self.table.setItem(row, 3, status_item)

            created = fmt_local(alert.created_at, "%d/%m/%Y %H:%M")
            self.table.setItem(row, 4, cell(created))

            triggered = fmt_local(alert.triggered_at, "%d/%m/%Y %H:%M")
            self.table.setItem(row, 5, cell(triggered))

            self.table.setItem(row, 6, cell(alert.message or "—"))

        self.table.resizeColumnsToContents()
        table_header(self.table).setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

    def _add_alert(self):
        if self._portfolio_id is None:
            QMessageBox.warning(self, "Sin portafolio", "Seleccioná un portafolio primero.")
            return
        dlg = AddAlertDialog(self._portfolio_id, self)
        if dlg.exec():
            self._load_alerts()

    def _delete_alert(self):
        """Handler del botón "Eliminar seleccionada" (usa la fila seleccionada)."""
        row = self.table.currentRow()
        if row < 0 or row >= len(self._alerts):
            return
        self._confirm_delete(self._alerts[row])

    def _confirm_delete(self, alert: Alert):
        reply = QMessageBox.question(
            self,
            "Confirmar",
            f"¿Eliminar alerta para {alert.ticker}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            AlertManager.delete_alert(alert.id)
            self._load_alerts()

    def _show_context_menu(self, pos):
        """Menú contextual sobre la fila bajo el cursor (ALRT1)."""
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._alerts):
            return
        self.table.selectRow(row)
        alert = self._alerts[row]
        actions = alert_row_actions(alert)

        menu = QMenu(self)
        edit_act = menu.addAction("Editar")
        pause_act = menu.addAction(actions["pausar_label"]) if actions["pausar_visible"] else None
        delete_act = menu.addAction("Eliminar")

        chosen = menu.exec(self.table.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == edit_act:
            self._edit_alert(alert)
        elif pause_act is not None and chosen == pause_act:
            self._toggle_pause(alert)
        elif chosen == delete_act:
            self._confirm_delete(alert)

    def _on_double_click(self, row: int, _col: int):
        """Doble-click en una fila = Editar (atajo del menú contextual)."""
        if 0 <= row < len(self._alerts):
            self._edit_alert(self._alerts[row])

    def _edit_alert(self, alert: Alert):
        dlg = AddAlertDialog(self._portfolio_id, self, alert=alert)
        if dlg.exec():
            self._load_alerts()

    def _toggle_pause(self, alert: Alert):
        AlertManager.set_paused(alert.id, not bool(alert.is_paused))
        self._load_alerts()

    def _check_alerts(self):
        """Lanza el chequeo en un worker. **No bloquea el hilo de la GUI** (tarea 80)."""
        if self._check_worker is not None and self._check_worker.isRunning():
            # El timer es de 120 s y una corrida con la red lenta puede pasarse:
            # sin esto se apilarían workers pidiendo los mismos precios.
            return
        self.check_btn.setEnabled(False)
        self.status_label.setText("Verificando alertas...")
        self._check_worker = AlertCheckWorker(self._portfolio_id, self)
        self._check_worker.result_ready.connect(self._on_check_done)
        self._check_worker.error.connect(self._on_check_error)
        self._check_worker.start()

    def _on_check_done(self, notices: list):
        """Slot: corre en el hilo de la GUI, que es donde se puede abrir el popup."""
        self._load_alerts()
        if notices:
            self.status_label.setText(f"⚡ {len(notices)} alerta(s) disparada(s).")
        else:
            self.status_label.setText("Sin alertas disparadas.")
        self.check_btn.setEnabled(True)
        for notice in notices:
            self._on_alert_triggered(notice)

    def _on_check_error(self, exc: Exception):
        """Fail-open, como el resto de los workers: se avisa y se sigue."""
        self.status_label.setText(f"Error al verificar alertas: {exc}")
        self.check_btn.setEnabled(True)

    def _on_alert_triggered(self, notice: AlertNotice):
        QMessageBox.information(
            self,
            "🔔 Alerta Disparada",
            f"<b>{notice.ticker}</b> alcanzó ${notice.current_price:,.4f}<br>"
            f"Objetivo: {notice.alert_type} ${notice.target_value:,.4f}<br>"
            f"{notice.message or ''}",
        )
