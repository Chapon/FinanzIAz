"""
Reports tab: generate PDF and Excel portfolio reports.
"""
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QGroupBox, QRadioButton,
    QButtonGroup, QSizePolicy
)
from PyQt6.QtCore import QThread, pyqtSignal
from database.models import get_session, Portfolio, Position
from ui.widgets import SectionHeader, HSeparator, MetricCard
from ui.styles import DARK_THEME
from datetime import datetime
from config.settings_manager import settings


class ReportWorker(QThread):
    done = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, report_type: str, output_path: str, portfolio_id: int, prices: dict):
        super().__init__()
        self.report_type = report_type
        self.output_path = output_path
        self.portfolio_id = portfolio_id
        self.prices = prices

    def run(self):
        try:
            session = get_session()
            portfolio = session.query(Portfolio).filter(Portfolio.id == self.portfolio_id).first()
            positions = session.query(Position).filter(Position.portfolio_id == self.portfolio_id).all()
            session.expunge_all()
            session.close()

            if self.report_type == "pdf":
                from reports.pdf_report import generate_portfolio_pdf
                generate_portfolio_pdf(
                    self.output_path,
                    portfolio.name,
                    positions,
                    self.prices,
                    portfolio.currency,
                    include_tx=settings.get("tx_history"),
                    dark_mode=settings.get("pdf_dark"),
                )
            else:
                from reports.excel_report import generate_portfolio_excel
                generate_portfolio_excel(
                    self.output_path,
                    portfolio.name,
                    positions,
                    self.prices,
                    portfolio.currency,
                    include_tx=settings.get("tx_history"),
                )
            self.done.emit(self.output_path)
        except Exception as e:
            self.error.emit(str(e))


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

    def _on_error(self, error: str):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generar y Guardar Reporte")
        self.status_label.setText(f"❌ Error: {error}")
        QMessageBox.critical(self, "Error al generar reporte", error)
