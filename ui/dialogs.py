"""
Modal dialogs for FinanzIAs: add position, add portfolio, add alert.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QDoubleSpinBox, QComboBox, QTextEdit,
    QPushButton, QLabel, QMessageBox, QDialogButtonBox,
    QSpinBox, QDateEdit
)
from PyQt6.QtCore import Qt, QDate
from database.models import get_session, Portfolio, Position, Transaction
from data.yahoo_finance import validate_ticker, get_company_info
from alerts.alert_manager import AlertManager
from config.settings_manager import settings
from datetime import datetime


class AddPortfolioDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuevo Portafolio")
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ej: Largo Plazo")
        form.addRow("Nombre *", self.name_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Descripción opcional...")
        self.desc_edit.setMaximumHeight(80)
        form.addRow("Descripción", self.desc_edit)

        self.currency_combo = QComboBox()
        self.currency_combo.addItems(["USD", "ARS", "EUR", "BRL", "GBP"])
        form.addRow("Moneda", self.currency_combo)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "El nombre es requerido.")
            return

        session = get_session()
        try:
            existing = session.query(Portfolio).filter(Portfolio.name == name).first()
            if existing:
                QMessageBox.warning(self, "Error", f"Ya existe un portafolio llamado '{name}'.")
                return
            p = Portfolio(
                name=name,
                description=self.desc_edit.toPlainText().strip() or None,
                currency=self.currency_combo.currentText(),
            )
            session.add(p)
            session.commit()
            self.accept()
        finally:
            session.close()


class RenamePortfolioDialog(QDialog):
    """Simple dialog to rename an existing portfolio."""

    def __init__(self, portfolio_id: int, current_name: str, parent=None):
        super().__init__(parent)
        self._portfolio_id = portfolio_id
        self.setWindowTitle("Renombrar Portafolio")
        self.setMinimumWidth(380)
        self._build_ui(current_name)

    def _build_ui(self, current_name: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl = QLabel("Nuevo nombre del portafolio:")
        lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(lbl)

        self.name_edit = QLineEdit(current_name)
        self.name_edit.setPlaceholderText("Nombre del portafolio")
        self.name_edit.selectAll()
        self.name_edit.returnPressed.connect(self._accept)
        layout.addWidget(self.name_edit)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "El nombre no puede estar vacío.")
            return
        session = get_session()
        try:
            conflict = (
                session.query(Portfolio)
                .filter(Portfolio.name == name, Portfolio.id != self._portfolio_id)
                .first()
            )
            if conflict:
                QMessageBox.warning(self, "Nombre en uso",
                                    f"Ya existe un portafolio llamado '{name}'.")
                return
            p = session.query(Portfolio).filter(Portfolio.id == self._portfolio_id).first()
            if p:
                p.name = name
                session.commit()
            self.accept()
        finally:
            session.close()


class AddPositionDialog(QDialog):
    def __init__(
        self,
        portfolio_id: int,
        parent=None,
        *,
        prefill_ticker: str = "",
        prefill_qty: float | None = None,
        prefill_price: float | None = None,
        prefill_notes: str = "",
    ):
        super().__init__(parent)
        self.portfolio_id = portfolio_id
        self.setWindowTitle("Agregar Acción")
        self.setMinimumWidth(460)
        self._build_ui()

        # Aplicar pre-fill después de construir el form. Sirve para los flows
        # tipo "Aprobar y registrar en Portafolio" desde Paper Trading, donde
        # ya conocemos ticker/cantidad/precio sugerido y solo queremos que el
        # usuario ajuste el precio real y las fees del broker.
        if prefill_ticker:
            self.ticker_edit.setText(prefill_ticker.upper())
        if prefill_qty is not None and prefill_qty > 0:
            self.qty_spin.setValue(float(prefill_qty))
        if prefill_price is not None and prefill_price > 0:
            self.price_spin.setValue(float(prefill_price))
        if prefill_notes:
            self.notes_edit.setText(prefill_notes)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(10)

        self.ticker_edit = QLineEdit()
        self.ticker_edit.setPlaceholderText("Ej: AAPL, MSFT, GGAL.BA")
        self.ticker_edit.textChanged.connect(self._on_ticker_changed)
        form.addRow("Símbolo (ticker) *", self.ticker_edit)

        self.name_label = QLabel("—")
        self.name_label.setObjectName("muted")
        form.addRow("Empresa", self.name_label)

        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0.0001, 1_000_000)
        self.qty_spin.setDecimals(4)
        self.qty_spin.setValue(1)
        form.addRow("Cantidad *", self.qty_spin)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0.0001, 10_000_000)
        self.price_spin.setDecimals(4)
        self.price_spin.setPrefix("$ ")
        self.price_spin.setValue(0)
        form.addRow("Precio de compra *", self.price_spin)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setMaximumDate(QDate.currentDate())
        form.addRow("Fecha de compra *", self.date_edit)

        self.fees_spin = QDoubleSpinBox()
        self.fees_spin.setRange(0, 100_000)
        self.fees_spin.setDecimals(2)
        self.fees_spin.setPrefix("$ ")
        form.addRow("Comisiones", self.fees_spin)

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Notas opcionales...")
        form.addRow("Notas", self.notes_edit)

        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setText("Agregar")
        self.ok_btn.setObjectName("primary")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_ticker_changed(self, text: str):
        if len(text) >= 2:
            self.status_label.setText("Verificando ticker...")
        else:
            self.name_label.setText("—")
            self.status_label.setText("")

    def _accept(self):
        ticker = self.ticker_edit.text().strip().upper()
        if not ticker:
            QMessageBox.warning(self, "Error", "Ingresá un ticker.")
            return

        self.status_label.setText("Validando ticker en Yahoo Finance...")
        if not validate_ticker(ticker):
            QMessageBox.warning(self, "Ticker inválido", f"'{ticker}' no se encontró en Yahoo Finance.")
            self.status_label.setText("")
            return

        qty = self.qty_spin.value()
        price = self.price_spin.value()

        if qty <= 0 or price <= 0:
            QMessageBox.warning(self, "Error", "Cantidad y precio deben ser mayores a 0.")
            return

        # Convert QDate → Python datetime
        qd = self.date_edit.date()
        purchase_dt = datetime(qd.year(), qd.month(), qd.day())

        company_info = get_company_info(ticker)

        session = get_session()
        try:
            # Check if position already exists and merge
            existing = (
                session.query(Position)
                .filter(Position.portfolio_id == self.portfolio_id)
                .filter(Position.ticker == ticker)
                .first()
            )

            if existing:
                # Update average price; keep the earliest purchase_date
                total_qty = existing.quantity + qty
                avg = ((existing.avg_buy_price * existing.quantity) + (price * qty)) / total_qty
                existing.quantity = total_qty
                existing.avg_buy_price = avg
                existing.updated_at = datetime.utcnow()
                # Keep earliest date for dividend calculation
                if existing.purchase_date is None or purchase_dt < existing.purchase_date:
                    existing.purchase_date = purchase_dt
                pos = existing
            else:
                pos = Position(
                    portfolio_id=self.portfolio_id,
                    ticker=ticker,
                    company_name=company_info.get("name", ticker),
                    quantity=qty,
                    avg_buy_price=price,
                    sector=company_info.get("sector"),
                    notes=self.notes_edit.text().strip() or None,
                    purchase_date=purchase_dt,
                )
                session.add(pos)

            session.flush()

            tx = Transaction(
                position_id=pos.id,
                transaction_type="BUY",
                quantity=qty,
                price=price,
                fees=self.fees_spin.value(),
            )
            session.add(tx)
            session.commit()
            self.accept()
        finally:
            session.close()


class AddAlertDialog(QDialog):
    def __init__(self, portfolio_id: int, parent=None):
        super().__init__(parent)
        self.portfolio_id = portfolio_id
        self.setWindowTitle("Nueva Alerta de Precio")
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(10)

        self.ticker_edit = QLineEdit()
        self.ticker_edit.setPlaceholderText("Ej: AAPL")
        form.addRow("Ticker *", self.ticker_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["ABOVE — Precio supera", "BELOW — Precio cae bajo"])
        form.addRow("Tipo de alerta", self.type_combo)

        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0.0001, 10_000_000)
        self.target_spin.setDecimals(4)
        self.target_spin.setPrefix("$ ")
        form.addRow("Precio objetivo *", self.target_spin)

        self.msg_edit = QLineEdit()
        self.msg_edit.setPlaceholderText("Mensaje opcional para la notificación...")
        form.addRow("Mensaje", self.msg_edit)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Crear Alerta")
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _accept(self):
        ticker = self.ticker_edit.text().strip().upper()
        if not ticker:
            QMessageBox.warning(self, "Error", "Ingresá un ticker.")
            return

        alert_type = "ABOVE" if "ABOVE" in self.type_combo.currentText() else "BELOW"
        target = self.target_spin.value()

        if target <= 0:
            QMessageBox.warning(self, "Error", "El precio objetivo debe ser mayor a 0.")
            return

        AlertManager.create_alert(
            portfolio_id=self.portfolio_id,
            ticker=ticker,
            alert_type=alert_type,
            target_value=target,
            message=self.msg_edit.text().strip(),
        )
        self.accept()


class SellPositionDialog(QDialog):
    def __init__(
        self,
        position,
        parent=None,
        *,
        prefill_qty: float | None = None,
        prefill_price: float | None = None,
    ):
        super().__init__(parent)
        self.position = position
        self.setWindowTitle(f"Vender {position.ticker}")
        self.setMinimumWidth(380)
        self._build_ui()

        # Pre-fill desde Paper Trading: sugerencia de cantidad a vender y/o
        # precio aproximado. Cap por seguridad a position.quantity (no podés
        # vender más de lo que tenés en el portafolio real).
        if prefill_qty is not None and prefill_qty > 0:
            self.qty_spin.setValue(min(float(prefill_qty), float(position.quantity)))
        if prefill_price is not None and prefill_price > 0:
            self.price_spin.setValue(float(prefill_price))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        info = QLabel(
            f"<b>{self.position.ticker}</b> — {self.position.company_name or ''}<br>"
            f"Tenés <b>{self.position.quantity:.4f} acciones</b>"
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)

        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0.0001, self.position.quantity)
        self.qty_spin.setDecimals(4)
        self.qty_spin.setValue(self.position.quantity)
        form.addRow("Cantidad a vender *", self.qty_spin)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0.0001, 10_000_000)
        self.price_spin.setDecimals(4)
        self.price_spin.setPrefix("$ ")
        form.addRow("Precio de venta *", self.price_spin)

        self.fees_spin = QDoubleSpinBox()
        self.fees_spin.setRange(0, 100_000)
        self.fees_spin.setDecimals(2)
        self.fees_spin.setPrefix("$ ")
        form.addRow("Comisiones", self.fees_spin)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Confirmar Venta")
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("danger")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _accept(self):
        qty = self.qty_spin.value()
        price = self.price_spin.value()

        if qty <= 0 or price <= 0:
            QMessageBox.warning(self, "Error", "Cantidad y precio deben ser mayores a 0.")
            return

        # Extra confirmation step (gated by setting)
        if settings.get("confirm_sell"):
            total = qty * price - self.fees_spin.value()
            reply = QMessageBox.question(
                self,
                "Confirmar venta",
                f"¿Confirmar venta de <b>{qty:.4f}</b> acciones de <b>{self.position.ticker}</b> "
                f"a <b>${price:.4f}</b>?<br><br>"
                f"Comisiones: ${self.fees_spin.value():.2f}<br>"
                f"<b>Total neto: ${total:,.2f}</b>",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        session = get_session()
        try:
            pos = session.query(Position).filter(Position.id == self.position.id).first()
            if pos is None:
                return

            tx = Transaction(
                position_id=pos.id,
                transaction_type="SELL",
                quantity=qty,
                price=price,
                fees=self.fees_spin.value(),
            )
            session.add(tx)

            if abs(pos.quantity - qty) < 1e-8:
                session.delete(pos)
            else:
                pos.quantity -= qty
                pos.updated_at = datetime.utcnow()

            session.commit()
            self.accept()
        finally:
            session.close()
