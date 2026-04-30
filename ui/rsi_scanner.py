"""
RSI Scanner dialog — triggered when the 'rsi_alerts' setting is turned ON.
Fetches RSI for every position in the portfolio and shows extremes.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from database.models import get_session, Position
from data.yahoo_finance import get_historical_data
from analysis.technical import compute_rsi
from alerts.alert_manager import AlertManager


class RsiScanWorker(QThread):
    """Fetches 30 days of data and computes latest RSI for each position."""
    row_done  = pyqtSignal(str, float)    # ticker, rsi_value
    all_done  = pyqtSignal()
    error_row = pyqtSignal(str, str)      # ticker, error_msg

    def __init__(self, tickers: list[str]):
        super().__init__()
        self.tickers = tickers

    def run(self):
        for ticker in self.tickers:
            try:
                df = get_historical_data(ticker, period="3mo")
                if df is None or len(df) < 15:
                    self.error_row.emit(ticker, "Datos insuficientes")
                    continue
                rsi_series = compute_rsi(df)
                rsi_val = float(rsi_series.dropna().iloc[-1])
                self.row_done.emit(ticker, round(rsi_val, 1))
            except Exception as e:
                self.error_row.emit(ticker, str(e))
        self.all_done.emit()


class RsiScanDialog(QDialog):
    def __init__(self, portfolio_id: int, parent=None):
        super().__init__(parent)
        self.portfolio_id = portfolio_id
        self.setWindowTitle("Escaneo RSI — Portafolio")
        self.setMinimumSize(500, 420)
        self.resize(560, 480)
        self._tickers: list[str] = []
        self._rsi_results: dict[str, float] = {}
        self._worker: RsiScanWorker | None = None
        self._build_ui()
        self._start_scan()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)

        title = QLabel("Escaneo de RSI Extremo")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        root.addWidget(title)

        desc = QLabel(
            "Valores RSI <b>&lt; 30</b> indican sobreventa (posible rebote). "
            "Valores <b>&gt; 70</b> indican sobrecompra (posible corrección)."
        )
        desc.setObjectName("muted")
        desc.setTextFormat(Qt.TextFormat.RichText)
        desc.setWordWrap(True)
        root.addWidget(desc)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("Escaneando… %p%")
        root.addWidget(self.progress)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Ticker", "RSI", "Estado"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, stretch=1)

        self.status_lbl = QLabel("Iniciando escaneo…")
        self.status_lbl.setObjectName("muted")
        root.addWidget(self.status_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.alert_btn = QPushButton("Crear alertas para extremos")
        self.alert_btn.setEnabled(False)
        self.alert_btn.setStyleSheet(
            "background-color: #4ade80; color: #000; border: none; "
            "border-radius: 20px; padding: 8px 20px; font-weight: 700;"
        )
        self.alert_btn.clicked.connect(self._create_alerts)
        btn_row.addWidget(self.alert_btn)

        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _start_scan(self):
        session = get_session()
        try:
            positions = session.query(Position).filter(
                Position.portfolio_id == self.portfolio_id
            ).all()
            self._tickers = [p.ticker for p in positions]
        finally:
            session.close()

        if not self._tickers:
            self.status_lbl.setText("Sin posiciones en el portafolio.")
            return

        self.progress.setMaximum(len(self._tickers))
        self.progress.setValue(0)
        self.table.setRowCount(len(self._tickers))

        for i, ticker in enumerate(self._tickers):
            self.table.setItem(i, 0, QTableWidgetItem(ticker))
            pending = QTableWidgetItem("—")
            pending.setForeground(QColor("#4b5563"))
            self.table.setItem(i, 1, pending)
            self.table.setItem(i, 2, QTableWidgetItem("Calculando…"))

        self._worker = RsiScanWorker(self._tickers)
        self._worker.row_done.connect(self._on_row_done)
        self._worker.error_row.connect(self._on_row_error)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _on_row_done(self, ticker: str, rsi: float):
        self._rsi_results[ticker] = rsi
        idx = self._tickers.index(ticker)

        rsi_item = QTableWidgetItem(f"{rsi:.1f}")
        rsi_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

        if rsi < 30:
            status = "⬇ Sobreventa — posible COMPRA"
            color = "#4ade80"
            rsi_item.setForeground(QColor("#4ade80"))
        elif rsi > 70:
            status = "⬆ Sobrecompra — posible VENTA"
            color = "#f87171"
            rsi_item.setForeground(QColor("#f87171"))
        else:
            status = "Zona neutral"
            color = "#94a3b8"
            rsi_item.setForeground(QColor("#94a3b8"))

        self.table.setItem(idx, 1, rsi_item)
        status_item = QTableWidgetItem(status)
        status_item.setForeground(QColor(color))
        self.table.setItem(idx, 2, status_item)
        self.progress.setValue(self.progress.value() + 1)

    def _on_row_error(self, ticker: str, msg: str):
        idx = self._tickers.index(ticker)
        self.table.setItem(idx, 1, QTableWidgetItem("Error"))
        err_item = QTableWidgetItem(msg)
        err_item.setForeground(QColor("#f87171"))
        self.table.setItem(idx, 2, err_item)
        self.progress.setValue(self.progress.value() + 1)

    def _on_all_done(self):
        self.progress.setVisible(False)
        extremes = [(t, r) for t, r in self._rsi_results.items() if r < 30 or r > 70]
        if extremes:
            self.status_lbl.setText(
                f"⚠  {len(extremes)} posición/es con RSI extremo detectadas."
            )
            self.alert_btn.setEnabled(True)
        else:
            self.status_lbl.setText("✅ Todas las posiciones tienen RSI en zona neutral.")

    def _create_alerts(self):
        """Create price alerts for positions with extreme RSI."""
        created = 0
        for ticker, rsi in self._rsi_results.items():
            if rsi < 30:
                # Alert when price rises 5% (potential exit from oversold)
                from data.yahoo_finance import get_current_price
                price_data = get_current_price(ticker)
                if price_data:
                    target = round(price_data["price"] * 1.05, 4)
                    AlertManager.create_alert(
                        portfolio_id=self.portfolio_id,
                        ticker=ticker,
                        alert_type="ABOVE",
                        target_value=target,
                        message=f"RSI estaba en sobreventa ({rsi:.1f}). Rebote +5%.",
                    )
                    created += 1
            elif rsi > 70:
                # Alert when price drops 5% (potential exit from overbought)
                from data.yahoo_finance import get_current_price
                price_data = get_current_price(ticker)
                if price_data:
                    target = round(price_data["price"] * 0.95, 4)
                    AlertManager.create_alert(
                        portfolio_id=self.portfolio_id,
                        ticker=ticker,
                        alert_type="BELOW",
                        target_value=target,
                        message=f"RSI estaba en sobrecompra ({rsi:.1f}). Caída -5%.",
                    )
                    created += 1

        QMessageBox.information(
            self, "Alertas creadas",
            f"Se crearon {created} alerta/s automáticas en la pestaña Alertas.\n\n"
            "• Sobreventa (RSI < 30): alerta cuando el precio sube 5%.\n"
            "• Sobrecompra (RSI > 70): alerta cuando el precio cae 5%."
        )
        self.accept()
