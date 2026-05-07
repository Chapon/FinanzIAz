"""
Reports tab: generate PDF and Excel portfolio reports.

The actual generation runs on a background ``BaseWorker`` so the UI stays
responsive — large portfolios with full transaction history can take 5-10 s.
"""
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QGroupBox, QRadioButton,
    QButtonGroup, QSizePolicy
)
from PyQt6.QtCore import pyqtSignal
from database.models import session_scope, Portfolio, Position
from ui.widgets import SectionHeader, HSeparator, MetricCard
from ui.styles import DARK_THEME
from ui.workers import BaseWorker
from datetime import datetime
from config.logging_config import get_logger
from config.settings_manager import settings

log = get_logger(__name__)


def _check_writable(path: str) -> None:
    """
    Pre-flight check before kicking off the background worker.

    Raises ``OSError`` (with a friendly message) if the target directory is
    missing, not writable, or the file is currently held open by another
    process (common on Windows when the user has the previous PDF open).
    """
    folder = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(folder):
        raise OSError(f"La carpeta de destino no existe: {folder}")
    if not os.access(folder, os.W_OK):
        raise OSError(f"No tenés permiso para escribir en: {folder}")
    if os.path.exists(path):
        try:
            with open(path, "ab"):
                pass
        except OSError as e:
            raise OSError(
                f"No se puede sobrescribir {os.path.basename(path)} — "
                f"¿lo tenés abierto en otra aplicación? ({e})"
            ) from e


class ReportWorker(BaseWorker):
    """
    Background worker that materialises a portfolio report (PDF or XLSX).

    Emits ``done(path)`` on success and the inherited ``error(Exception)``
    on failure. The previous string-based ``error`` channel was migrated
    to BaseWorker's exception object channel — callers should adapt by
    using ``str(exc)`` for display.
    """

    done = pyqtSignal(str)

    def __init__(self, report_type: str, output_path: str, portfolio_id: int, prices: dict):
        super().__init__()
        self.report_type = report_type
        self.output_path = output_path
        self.portfolio_id = portfolio_id
        self.prices = prices

    def do_work(self) -> str:
        # Snapshot the portfolio under a clean session, then drop the session
        # before running report generation (which is purely CPU/IO bound).
        with session_scope() as session:
            portfolio = (session.query(Portfolio)
                         .filter(Portfolio.id == self.portfolio_id).first())
            if portfolio is None:
                raise ValueError(f"Portafolio {self.portfolio_id} no encontrado")
            positions = (session.query(Position)
                         .filter(Position.portfolio_id == self.portfolio_id).all())
            session.expunge_all()
            portfolio_name     = portfolio.name
            portfolio_currency = portfolio.currency

        if self.report_type == "pdf":
            from reports.pdf_report import generate_portfolio_pdf
            generate_portfolio_pdf(
                self.output_path,
                portfolio_name,
                positions,
                self.prices,
                portfolio_currency,
                include_tx=settings.get("tx_history"),
                dark_mode=settings.get("pdf_dark"),
            )
        else:
            from reports.excel_report import generate_portfolio_excel
            generate_portfolio_excel(
                self.output_path,
                portfolio_name,
                positions,
                self.prices,
                portfolio_currency,
                include_tx=settings.get("tx_history"),
            )
        return self.output_path

    def on_success(self, result: str) -> None:
        self.done.emit(result)


class ReportsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._portfolio_id = None
        self._prices = {}
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        root.addWidget(SectionHeader("Generar Reporte"))
        root.addWidget(HSeparator())

        # Format selection
        fmt_group = QGroupBox("Formato")
        fmt_layout = QHBoxLayout(fmt_group)
        self.pdf_radio = QRadioButton("PDF")
        self.excel_radio = QRadioButton("Excel (.xlsx)")
        self.pdf_radio.setChecked(True)
        fmt_layout.addWidget(self.pdf_radio)
        fmt_layout.addWidget(self.excel_radio)
        fmt_layout.addStretch()
        root.addWidget(fmt_group)

        # Generate button
        btn_row = QHBoxLayout()
        self.generate_btn = QPushButton("Generar y Guardar Reporte")
        self.generate_btn.setObjectName("primary")
        self.generate_btn.setFixedHeight(40)
        self.generate_btn.setMinimumWidth(240)
        self.generate_btn.clicked.connect(self._generate)
        btn_row.addWidget(self.generate_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        root.addWidget(self.status_label)

        root.addStretch()

        note = QLabel(
            "Los reportes incluyen: resumen del portafolio, detalle de posiciones, "
            "P&L, precios actuales y historial de transacciones."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

    def set_portfolio_id(self, pid: int, prices: dict):
        self._portfolio_id = pid
        self._prices = prices

    def _generate(self):
        if self._portfolio_id is None:
            QMessageBox.warning(self, "Sin portafolio", "Seleccioná un portafolio primero.")
            return

        is_pdf = self.pdf_radio.isChecked()
        ext = "pdf" if is_pdf else "xlsx"
        name_filter = "PDF (*.pdf)" if is_pdf else "Excel (*.xlsx)"

        default_name = f"FinanzIAs_Reporte_{datetime.now().strftime('%Y%m%d_%H%M')}.{ext}"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar reporte", default_name, name_filter)
        if not path:
            return

        # Pre-flight: validate the destination *before* starting the worker
        # so the user gets a clear, immediate error if the folder is read-only
        # or the file is held open elsewhere.
        try:
            _check_writable(path)
        except OSError as e:
            QMessageBox.warning(self, "No se puede guardar", str(e))
            return

        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Generando...")
        self.status_label.setText("Generando reporte...")

        self._worker = ReportWorker(
            "pdf" if is_pdf else "excel",
            path,
            self._portfolio_id,
            self._prices,
        )
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self, path: str):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generar y Guardar Reporte")
        self.status_label.setText(f"✅ Reporte guardado en: {path}")
        reply = QMessageBox.question(
            self, "Reporte generado",
            f"Reporte guardado en:\n{path}\n\n¿Abrirlo ahora?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            import subprocess, sys
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])

    def _on_error(self, exc):
        # BaseWorker now emits an Exception on `error`, not a string. Coerce
        # to a friendly message but keep the type-check defensive — pre-base-
        # worker callers may still pass strings from older signal contracts.
        msg = str(exc) if exc else "Error desconocido"
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generar y Guardar Reporte")
        self.status_label.setText(f"❌ Error: {msg}")
        QMessageBox.critical(self, "Error al generar reporte", msg)
