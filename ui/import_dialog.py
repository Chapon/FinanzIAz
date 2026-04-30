"""
CSV import dialog for FinanzIAs.
Shows a preview table of parsed rows and lets the user confirm before saving.
"""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox,
    QHeaderView, QAbstractItemView, QFrame, QScrollArea,
    QWidget, QProgressBar, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QDragEnterEvent, QDropEvent
from data.csv_importer import parse_csv_file, ImportRow, ImportResult
from data.yahoo_finance import get_company_info
from database.models import get_session, Position, Transaction
from datetime import datetime


class ValidateWorker(QThread):
    """Background: fetch company names for imported tickers."""
    progress = pyqtSignal(int, str, str)   # row_idx, company_name, sector
    done = pyqtSignal()

    def __init__(self, rows: list[ImportRow]):
        super().__init__()
        self.rows = rows

    def run(self):
        for i, row in enumerate(self.rows):
            info = get_company_info(row.ticker)
            name = info.get("name", row.ticker) if info else row.ticker
            sector = info.get("sector", "N/A") if info else "N/A"
            self.progress.emit(i, name, sector)
        self.done.emit()


class ImportDialog(QDialog):
    """
    Full-featured import dialog:
    1. Drop zone / file picker
    2. Preview table (editable qty + price)
    3. Warnings panel
    4. Confirm → saves to DB
    """

    def __init__(self, portfolio_id: int, parent=None):
        super().__init__(parent)
        self.portfolio_id = portfolio_id
        self.setWindowTitle("Importar desde CSV — Yahoo Finance")
        self.setMinimumSize(860, 600)
        self.resize(960, 680)
        self._result: ImportResult | None = None
        self._company_names: dict[int, str] = {}
        self._company_sectors: dict[int, str] = {}
        self._worker: ValidateWorker | None = None
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(14)

        # Title
        title = QLabel("Importar Portafolio desde CSV")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        root.addWidget(title)

        hint = QLabel(
            "Exportá tu portafolio desde Yahoo Finance: <b>Finance → Portfolio → ⋮ → Export</b><br>"
            "También acepta watchlists de Yahoo Finance y cualquier CSV con columnas: "
            "<i>ticker, quantity, purchase_price</i>"
        )
        hint.setObjectName("muted")
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        root.addWidget(hint)

        # Watchlist mode banner (hidden until detected)
        self.watchlist_banner = QLabel(
            "📋  <b>Modo Watchlist detectado</b> — las acciones no tienen cantidad ni precio de compra. "
            "Se importarán con cantidad = 1 y precio = precio actual del CSV para poder analizarlas. "
            "El P&amp;L mostrará 0% hasta que edites el precio real de compra."
        )
        self.watchlist_banner.setTextFormat(Qt.TextFormat.RichText)
        self.watchlist_banner.setWordWrap(True)
        self.watchlist_banner.setStyleSheet(
            "background-color: #1e3a5f; color: #60a5fa; border: 1px solid #1d4ed8; "
            "border-radius: 8px; padding: 10px 14px; font-size: 12px;"
        )
        self.watchlist_banner.setVisible(False)
        root.addWidget(self.watchlist_banner)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self._load_file)
        root.addWidget(self.drop_zone)

        browse_row = QHBoxLayout()
        browse_btn = QPushButton("📂  Seleccionar archivo CSV...")
        browse_btn.setObjectName("primary")
        browse_btn.clicked.connect(self._browse_file)
        browse_row.addWidget(browse_btn)
        browse_row.addStretch()

        self.format_label = QLabel("")
        self.format_label.setObjectName("muted")
        browse_row.addWidget(self.format_label)
        root.addLayout(browse_row)

        # Warnings box
        self.warnings_frame = QFrame()
        self.warnings_frame.setObjectName("card")
        self.warnings_frame.setVisible(False)
        w_layout = QVBoxLayout(self.warnings_frame)
        w_layout.setContentsMargins(12, 10, 12, 10)
        self.warnings_label = QLabel()
        self.warnings_label.setObjectName("muted")
        self.warnings_label.setWordWrap(True)
        w_layout.addWidget(self.warnings_label)
        root.addWidget(self.warnings_frame)

        # Preview table
        preview_title = QLabel("Vista previa — editá cantidad o precio antes de importar:")
        preview_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        root.addWidget(preview_title)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Ticker", "Empresa", "Sector", "Cantidad", "Precio Compra", "Comisión"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.table.setVisible(False)
        root.addWidget(self.table, stretch=1)

        # Progress bar (shown during validation)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Validando tickers en Yahoo Finance... %p%")
        root.addWidget(self.progress_bar)

        # Bottom
        bottom = QHBoxLayout()
        self.skipped_label = QLabel("")
        self.skipped_label.setObjectName("muted")
        bottom.addWidget(self.skipped_label)
        bottom.addStretch()

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(self.cancel_btn)

        self.import_btn = QPushButton("✅  Importar al portafolio")
        self.import_btn.setObjectName("success")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._do_import)
        bottom.addWidget(self.import_btn)
        root.addLayout(bottom)

    # ── File loading ───────────────────────────────────────────────────────

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar CSV", "",
            "CSV Files (*.csv);;All Files (*)"
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str):
        self._result = parse_csv_file(path)
        self._display_result()

    def _display_result(self):
        result = self._result
        if result is None:
            return

        # Format badge
        fmt = "Yahoo Finance" if result.source_format == "yahoo_finance" else "Genérico"
        self.format_label.setText(f"Formato detectado: {fmt}")

        # Warnings
        if result.warnings:
            self.warnings_label.setText("⚠️  " + "  ·  ".join(result.warnings))
            self.warnings_frame.setVisible(True)
        else:
            self.warnings_frame.setVisible(False)

        # Skipped rows
        n_skip = len(result.skipped)
        if n_skip:
            self.skipped_label.setText(
                f"⚠️  {n_skip} fila(s) omitida(s) por datos inválidos."
            )

        # Show watchlist banner if any row is a watchlist entry
        has_watchlist = any(r.is_watchlist for r in result.rows)
        self.watchlist_banner.setVisible(has_watchlist)

        # Table
        self.table.setVisible(True)
        self.table.setRowCount(0)
        for row in result.rows:
            r = self.table.rowCount()
            self.table.insertRow(r)

            ticker_item = QTableWidgetItem(row.ticker)
            ticker_item.setFlags(ticker_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ticker_item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.table.setItem(r, 0, ticker_item)

            name_item = QTableWidgetItem("Verificando...")
            name_item.setForeground(QColor("#8b949e"))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 1, name_item)

            sector_item = QTableWidgetItem("—")
            sector_item.setForeground(QColor("#8b949e"))
            sector_item.setFlags(sector_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 2, sector_item)

            qty_item = QTableWidgetItem(f"{row.quantity:.4f}")
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if row.is_watchlist:
                qty_item.setForeground(QColor("#60a5fa"))
                qty_item.setToolTip("Cantidad watchlist — editá si ya compraste")
            self.table.setItem(r, 3, qty_item)

            price_item = QTableWidgetItem(f"{row.buy_price:.4f}" if row.buy_price else "0.0000")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if row.buy_price == 0:
                price_item.setForeground(QColor("#f85149"))
            elif row.is_watchlist:
                price_item.setForeground(QColor("#60a5fa"))
                price_item.setToolTip("Precio actual usado como referencia — editá si ya compraste")
            self.table.setItem(r, 4, price_item)

            fee_item = QTableWidgetItem(f"{row.commission:.2f}")
            fee_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 5, fee_item)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        # Start background validation
        self._start_validation()

    def _start_validation(self):
        if not self._result or not self._result.rows:
            return
        n = len(self._result.rows)
        self.progress_bar.setMaximum(n)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.import_btn.setEnabled(False)

        self._worker = ValidateWorker(self._result.rows)
        self._worker.progress.connect(self._on_ticker_validated)
        self._worker.done.connect(self._on_validation_done)
        self._worker.start()

    def _on_ticker_validated(self, row_idx: int, name: str, sector: str):
        self._company_names[row_idx] = name
        self._company_sectors[row_idx] = sector
        name_item = self.table.item(row_idx, 1)
        sector_item = self.table.item(row_idx, 2)
        if name_item:
            name_item.setText(name)
            name_item.setForeground(QColor("#e6edf3"))
        if sector_item:
            sector_item.setText(sector)
        self.progress_bar.setValue(row_idx + 1)

    def _on_validation_done(self):
        self.progress_bar.setVisible(False)
        self.import_btn.setEnabled(bool(self._result and self._result.rows))
        n = len(self._result.rows) if self._result else 0
        self.import_btn.setText(f"✅  Importar {n} posición/es al portafolio")

    # ── Import ─────────────────────────────────────────────────────────────

    def _do_import(self):
        if not self._result:
            return

        # Read possibly-edited values from table
        rows_to_import = []
        price_zero = []
        for r in range(self.table.rowCount()):
            ticker = self.table.item(r, 0).text().strip().upper()
            try:
                qty = float(self.table.item(r, 3).text().replace(",", ""))
            except (ValueError, AttributeError):
                qty = 0.0
            try:
                price = float(self.table.item(r, 4).text().replace(",", ""))
            except (ValueError, AttributeError):
                price = 0.0
            try:
                fee = float(self.table.item(r, 5).text().replace(",", ""))
            except (ValueError, AttributeError):
                fee = 0.0

            if qty <= 0:
                continue
            if price <= 0:
                price_zero.append(ticker)

            orig = self._result.rows[r] if self._result and r < len(self._result.rows) else None
            rows_to_import.append({
                "ticker": ticker,
                "quantity": qty,
                "price": price,
                "fee": fee,
                "company_name": self._company_names.get(r, ticker),
                "sector": self._company_sectors.get(r, ""),
                "is_watchlist": getattr(orig, "is_watchlist", False),
            })

        if not rows_to_import:
            QMessageBox.warning(self, "Sin datos", "No hay filas válidas para importar.")
            return

        if price_zero:
            reply = QMessageBox.question(
                self, "Precios en cero",
                f"Los siguientes tickers tienen precio de compra = 0:\n"
                f"{', '.join(price_zero)}\n\n"
                f"¿Importar de todas formas? Podés editarlos después.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Save to DB
        session = get_session()
        try:
            imported = 0
            merged = 0
            for item in rows_to_import:
                existing = (
                    session.query(Position)
                    .filter(Position.portfolio_id == self.portfolio_id)
                    .filter(Position.ticker == item["ticker"])
                    .first()
                )
                if existing:
                    # Merge: recalculate avg price
                    total_qty = existing.quantity + item["quantity"]
                    avg = (
                        (existing.avg_buy_price * existing.quantity) +
                        (item["price"] * item["quantity"])
                    ) / total_qty
                    existing.quantity = total_qty
                    existing.avg_buy_price = avg
                    existing.updated_at = datetime.utcnow()
                    pos = existing
                    merged += 1
                else:
                    note = "Watchlist — precio referencia" if item.get("is_watchlist") else "Importado desde CSV"
                    pos = Position(
                        portfolio_id=self.portfolio_id,
                        ticker=item["ticker"],
                        company_name=item["company_name"],
                        quantity=item["quantity"],
                        avg_buy_price=item["price"],
                        sector=item["sector"],
                        notes=note,
                        purchase_date=datetime.utcnow(),
                    )
                    session.add(pos)
                    imported += 1

                session.flush()

                tx = Transaction(
                    position_id=pos.id,
                    transaction_type="BUY",
                    quantity=item["quantity"],
                    price=item["price"],
                    fees=item["fee"],
                    notes="Importado desde CSV",
                )
                session.add(tx)

            session.commit()

            parts = []
            if imported:
                parts.append(f"{imported} posición/es nuevas")
            if merged:
                parts.append(f"{merged} posición/es actualizadas (ya existían)")

            QMessageBox.information(
                self, "Importación exitosa",
                f"✅ Importación completada:\n" + "\n".join(parts)
            )
            self.accept()
        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, "Error", f"Error al guardar: {e}")
        finally:
            session.close()


# ── Drag & Drop Zone ────────────────────────────────────────────────────────

class DropZone(QFrame):
    """A drag-and-drop target that accepts CSV files."""
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setAcceptDrops(True)
        self.setFixedHeight(90)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = QLabel("📂  Arrastrá tu CSV acá")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("font-size: 14px; color: #8b949e;")
        layout.addWidget(self._label)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(u.toLocalFile().lower().endswith(".csv") for u in urls):
                event.acceptProposedAction()
                self.setStyleSheet(
                    "#card { border: 2px solid #58a6ff; background-color: #1f6feb22; border-radius: 8px; }"
                )

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("")
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".csv"):
                self.file_dropped.emit(path)
                break
