"""
Portfolio tab — IQON-style card layout with live P&L metrics.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QComboBox, QHeaderView, QAbstractItemView,
    QFrame, QMessageBox, QSizePolicy, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont
from database.models import get_session, Portfolio, Position
from data.yahoo_finance import get_bulk_prices, get_bulk_dividends
from ui.widgets import MetricCard, MiniProgressBar, SectionHeader, HSeparator, StatusDot
from ui.dialogs import AddPositionDialog, SellPositionDialog, AddPortfolioDialog, RenamePortfolioDialog
from ui.import_dialog import ImportDialog
from ui.styles import PALETTE, SIGNAL_COLORS
from ui.ticker_tooltip import apply_ticker_tooltip, install_ticker_tooltips
from config.settings_manager import settings

# Spanish labels for Yahoo Finance 5-level system (mirrors SignalBadge._LABELS)
_SIGNAL_LABELS = {
    "Strong Buy":   "Compra Fuerte",
    "Buy":          "Comprar",
    "Hold":         "Mantener",
    "Underperform": "Vender",
    "Sell":         "Venta Fuerte",
}


class PriceWorker(QThread):
    prices_ready = pyqtSignal(dict)

    def __init__(self, tickers: list):
        super().__init__()
        self.tickers = tickers

    def run(self):
        self.prices_ready.emit(get_bulk_prices(self.tickers))


class DividendWorker(QThread):
    """Background thread to fetch cumulative dividends per position."""
    dividends_ready = pyqtSignal(dict)   # {ticker: total_div_per_share}

    def __init__(self, tickers_since: dict):
        super().__init__()
        self.tickers_since = tickers_since  # {ticker: purchase_date}

    def run(self):
        self.dividends_ready.emit(get_bulk_dividends(self.tickers_since))


class SignalWorker(QThread):
    """
    Background worker: fetches 1 year of historical data for each ticker
    and returns the Yahoo Finance 5-level signal for every one.
    Tickers are analyzed in parallel (up to 4 threads).
    """
    signals_ready = pyqtSignal(dict)   # {ticker: yahoo_level_str}

    def __init__(self, tickers: list):
        super().__init__()
        self.tickers = tickers

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from data.yahoo_finance import get_historical_data
        from analysis.technical import analyze
        from config.settings_manager import settings as _settings

        sma_cross = _settings.get("sma_cross")

        def _analyze_one(ticker: str) -> tuple[str, str]:
            try:
                df = get_historical_data(ticker, period="1y")
                if df is None or len(df) < 50:
                    print(f"[SignalWorker] {ticker}: datos insuficientes "
                          f"({len(df) if df is not None else 0} filas)")
                    return ticker, "Hold"
                result = analyze(
                    ticker, df,
                    enable_sma_cross=sma_cross,
                    enable_xgboost=False,   # skip ML in batch scan to stay fast
                )
                if result:
                    print(f"[SignalWorker] {ticker}: {result.yahoo_level} "
                          f"(buy={result.overall_signal}, strength={result.overall_strength}, "
                          f"conf={result.confidence_score}%)")
                    return ticker, result.yahoo_level
                return ticker, "Hold"
            except Exception as e:
                print(f"[SignalWorker] {ticker}: error — {e}")
                return ticker, "Hold"

        results = {}
        max_workers = min(4, len(self.tickers))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_analyze_one, t): t for t in self.tickers}
            for future in as_completed(futures):
                ticker, signal = future.result()
                results[ticker] = signal

        self.signals_ready.emit(results)


class PortfolioTab(QWidget):
    position_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._portfolios = []
        self._current_portfolio_id = None
        self._positions = []
        self._prices = {}
        self._dividends = {}          # {ticker: total_div_per_share}
        self._signals = {}            # {ticker: yahoo_level_str}
        self._show_dividends = True   # toggle
        self._price_worker = None
        self._div_worker = None
        self._signal_worker = None
        self._build_ui()
        self._load_portfolios()
        self._refresh_positions()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._fetch_prices)
        if settings.get("auto_refresh"):
            self._timer.start(60_000)

    def set_auto_refresh(self, enabled: bool):
        """Called by MainWindow when the auto_refresh setting changes."""
        if enabled:
            if not self._timer.isActive():
                self._timer.start(60_000)
        else:
            self._timer.stop()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        container.setStyleSheet(f"background-color: {PALETTE['bg']};")
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root = QVBoxLayout(container)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(18)

        # ── Top bar ────────────────────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(10)

        portfolio_lbl = QLabel("Portafolio:")
        portfolio_lbl.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 12px;")
        top.addWidget(portfolio_lbl)

        self.portfolio_combo = QComboBox()
        self.portfolio_combo.setMinimumWidth(200)
        self.portfolio_combo.setFixedHeight(36)
        self.portfolio_combo.currentIndexChanged.connect(self._on_portfolio_changed)
        top.addWidget(self.portfolio_combo)

        self.new_portfolio_btn = QPushButton("+ Portafolio")
        self.new_portfolio_btn.setFixedHeight(36)
        self.new_portfolio_btn.clicked.connect(self._add_portfolio)
        top.addWidget(self.new_portfolio_btn)

        self.rename_portfolio_btn = QPushButton("✏️  Renombrar")
        self.rename_portfolio_btn.setFixedHeight(36)
        self.rename_portfolio_btn.setToolTip("Cambiar el nombre del portafolio seleccionado")
        self.rename_portfolio_btn.clicked.connect(self._rename_portfolio)
        top.addWidget(self.rename_portfolio_btn)

        self.import_btn_top = QPushButton("📥  Importar CSV")
        self.import_btn_top.setFixedHeight(36)
        self.import_btn_top.clicked.connect(self._import_csv)
        top.addWidget(self.import_btn_top)

        self.watchlist_btn = QPushButton("📋  Watchlist desde CSV")
        self.watchlist_btn.setFixedHeight(36)
        self.watchlist_btn.setToolTip(
            "Creá un nuevo portafolio de seguimiento importando un CSV de Yahoo Finance watchlist"
        )
        self.watchlist_btn.setStyleSheet(
            f"background-color: #1e3a5f; color: #60a5fa; "
            f"border: 1px solid #1d4ed8; border-radius: 8px; "
            f"padding: 0 14px; font-weight: 600; font-size: 12px;"
        )
        self.watchlist_btn.clicked.connect(self._import_watchlist)
        top.addWidget(self.watchlist_btn)

        top.addStretch()

        self.refresh_btn = QPushButton("↻  Actualizar")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.clicked.connect(self._fetch_prices)
        top.addWidget(self.refresh_btn)

        self.div_btn = QPushButton("💰  Dividendos: ON")
        self.div_btn.setFixedHeight(36)
        self.div_btn.setToolTip("Incluir dividendos cobrados en el P&L total")
        self.div_btn.setStyleSheet(
            f"background-color: {PALETTE['accent_bg']}; color: {PALETTE['accent']}; "
            f"border: 1px solid #1a4a2a; border-radius: 8px; "
            f"padding: 0 14px; font-weight: 600; font-size: 12px;"
        )
        self.div_btn.clicked.connect(self._toggle_dividends)
        top.addWidget(self.div_btn)

        self.last_update_label = QLabel("—")
        self.last_update_label.setStyleSheet(
            f"color: {PALETTE['text3']}; font-size: 11px;"
        )
        top.addWidget(self.last_update_label)

        root.addLayout(top)

        # ── Metric cards ────────────────────────────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        self.card_total     = MetricCard("Valor Total")
        self.card_invested  = MetricCard("Invertido")
        self.card_pl        = MetricCard("Ganancia de Precio")
        self.card_divs      = MetricCard("Dividendos Cobrados")
        self.card_pl_total  = MetricCard("Ganancia Total")
        self.card_pl_pct    = MetricCard("Rendimiento Total")
        self.card_positions = MetricCard("Posiciones")

        for card in [self.card_total, self.card_invested, self.card_pl,
                     self.card_divs, self.card_pl_total, self.card_pl_pct, self.card_positions]:
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card.setFixedHeight(100)
            cards_row.addWidget(card)

        root.addLayout(cards_row)

        # ── Positions table ────────────────────────────────────────────────
        header = SectionHeader("Mis Posiciones", "+ Agregar Acción")
        if header.action_btn:
            header.action_btn.clicked.connect(self._add_position)
        root.addWidget(header)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(14)
        self.table.setHorizontalHeaderLabels([
            "Ticker", "Empresa", "Cant.", "P. Compra", "P. Actual",
            "Var. Hoy", "Invertido", "Valor", "Ganancia Precio", "Dividendos",
            "Ganancia Total", "G/P %", "Rend. Total", "Señal Técnica",
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        # Tooltip on hover over the Ticker column (col 0)
        install_ticker_tooltips(self.table, 0)
        root.addWidget(self.table, stretch=1)

        # ── Bottom bar ─────────────────────────────────────────────────────
        bottom = QHBoxLayout()
        self.sell_btn = QPushButton("💰  Vender seleccionada")
        self.sell_btn.setObjectName("danger")
        self.sell_btn.setFixedHeight(36)
        self.sell_btn.setEnabled(False)
        self.sell_btn.clicked.connect(self._sell_position)
        bottom.addWidget(self.sell_btn)

        self.analyze_btn = QPushButton("📈  Analizar seleccionada")
        self.analyze_btn.setFixedHeight(36)
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.clicked.connect(self._analyze_selected)
        bottom.addWidget(self.analyze_btn)

        bottom.addStretch()
        root.addLayout(bottom)

    # ── Data ───────────────────────────────────────────────────────────────

    def _load_portfolios(self):
        session = get_session()
        try:
            self._portfolios = session.query(Portfolio).order_by(Portfolio.name).all()
            session.expunge_all()
        finally:
            session.close()

        self.portfolio_combo.blockSignals(True)
        self.portfolio_combo.clear()
        for p in self._portfolios:
            self.portfolio_combo.addItem(p.name, userData=p.id)
        self.portfolio_combo.blockSignals(False)

        if self._portfolios:
            self._current_portfolio_id = self._portfolios[0].id

    def _on_portfolio_changed(self, idx: int):
        if 0 <= idx < len(self._portfolios):
            self._current_portfolio_id = self._portfolios[idx].id
            self._refresh_positions()

    def _refresh_positions(self):
        if self._current_portfolio_id is None:
            return
        session = get_session()
        try:
            self._positions = (
                session.query(Position)
                .filter(Position.portfolio_id == self._current_portfolio_id)
                .order_by(Position.ticker)
                .all()
            )
            session.expunge_all()
        finally:
            session.close()

        self._signals = {}
        self._render_table()
        if self._positions:
            self._fetch_prices()
            self._fetch_dividends()
            self._fetch_signals()

    def _fetch_prices(self):
        tickers = [p.ticker for p in self._positions]
        if not tickers:
            return
        if self._price_worker and self._price_worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Actualizando...")
        self._price_worker = PriceWorker(tickers)
        self._price_worker.prices_ready.connect(self._on_prices_ready)
        self._price_worker.start()

    def _fetch_dividends(self):
        """Fetch dividends in background — uses purchase date per position."""
        if not self._positions:
            return
        if self._div_worker and self._div_worker.isRunning():
            return
        tickers_since = {
            p.ticker: (p.purchase_date or p.created_at) for p in self._positions
        }
        self._div_worker = DividendWorker(tickers_since)
        self._div_worker.dividends_ready.connect(self._on_dividends_ready)
        self._div_worker.start()

    def _fetch_signals(self):
        """Fetch technical signals for all positions in background."""
        tickers = [p.ticker for p in self._positions]
        if not tickers:
            return
        if self._signal_worker and self._signal_worker.isRunning():
            return
        self._signal_worker = SignalWorker(tickers)
        self._signal_worker.signals_ready.connect(self._on_signals_ready)
        self._signal_worker.start()

    def _on_signals_ready(self, signals: dict):
        self._signals = signals
        self._render_table()

    def _on_dividends_ready(self, dividends: dict):
        self._dividends = dividends
        self._render_table()
        self._update_cards()

    def _on_prices_ready(self, prices: dict):
        self._prices = prices
        self._render_table()
        self._update_cards()
        from datetime import datetime
        self.last_update_label.setText(f"Actualizado: {datetime.now().strftime('%H:%M:%S')}")
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("↻  Actualizar")

    # ── Render ─────────────────────────────────────────────────────────────

    def _render_table(self):
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._positions))

        for row, pos in enumerate(self._positions):
            d             = self._prices.get(pos.ticker)
            current_price = d["price"] if d else None
            change_pct    = d.get("change_pct") if d else None

            invested      = pos.quantity * pos.avg_buy_price
            current_val   = (pos.quantity * current_price) if current_price else None
            pl_price      = (current_val - invested) if current_val is not None else None

            # Dividends
            div_per_share   = self._dividends.get(pos.ticker, 0.0) if self._show_dividends else 0.0
            div_total       = div_per_share * pos.quantity if div_per_share else 0.0

            # Total P&L = price gain + dividends
            pl_total  = ((pl_price or 0.0) + div_total) if pl_price is not None else None
            pl_pct    = ((pl_price / invested) * 100) if (pl_price is not None and invested > 0) else None
            pl_pct_div = (((pl_price or 0) + div_total) / invested * 100) if invested > 0 and pl_price is not None else None

            def cell(text, right=False, bold=False):
                item = QTableWidgetItem(str(text))
                align = Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                if bold:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                return item

            ticker_item = cell(pos.ticker, bold=True)
            apply_ticker_tooltip(ticker_item, pos.ticker)
            self.table.setItem(row, 0, ticker_item)
            self.table.setItem(row, 1, cell(pos.company_name or pos.ticker))
            self.table.setItem(row, 2, cell(f"{pos.quantity:.1f}", right=True))
            self.table.setItem(row, 3, cell(f"${pos.avg_buy_price:,.1f}", right=True))
            self.table.setItem(row, 4, cell(f"${current_price:,.1f}" if current_price else "—", right=True))

            # Daily change
            chg_item = cell(f"{change_pct:+.2f}%" if change_pct is not None else "—", right=True)
            if change_pct is not None:
                chg_item.setForeground(QColor(PALETTE["accent"] if change_pct >= 0 else PALETTE["red"]))
            self.table.setItem(row, 5, chg_item)

            self.table.setItem(row, 6, cell(f"${invested:,.2f}", right=True))
            self.table.setItem(row, 7, cell(f"${current_val:,.2f}" if current_val else "—", right=True))

            # P&L Precio
            pl_p_item = cell(f"${pl_price:,.2f}" if pl_price is not None else "—", right=True, bold=True)
            if pl_price is not None:
                pl_p_item.setForeground(QColor(PALETTE["accent"] if pl_price >= 0 else PALETTE["red"]))
            self.table.setItem(row, 8, pl_p_item)

            # Dividendos cobrados
            div_item = cell(f"${div_total:,.2f}" if div_total else "—", right=True)
            if div_total:
                div_item.setForeground(QColor(PALETTE["blue"]))
            self.table.setItem(row, 9, div_item)

            # P&L Total (precio + dividendos)
            pl_t_item = cell(f"${pl_total:,.2f}" if pl_total is not None else "—", right=True, bold=True)
            if pl_total is not None:
                pl_t_item.setForeground(QColor(PALETTE["accent"] if pl_total >= 0 else PALETTE["red"]))
            self.table.setItem(row, 10, pl_t_item)

            # P&L % (solo precio)
            pct_item = cell(f"{pl_pct:+.2f}%" if pl_pct is not None else "—", right=True)
            if pl_pct is not None:
                pct_item.setForeground(QColor(PALETTE["accent"] if pl_pct >= 0 else PALETTE["red"]))
            self.table.setItem(row, 11, pct_item)

            # Rendimiento total c/dividendos
            pct_div_item = cell(f"{pl_pct_div:+.2f}%" if pl_pct_div is not None else "—", right=True, bold=True)
            if pl_pct_div is not None:
                pct_div_item.setForeground(QColor(PALETTE["accent"] if pl_pct_div >= 0 else PALETTE["red"]))
            self.table.setItem(row, 12, pct_div_item)

            # Señal técnica — colored badge cell
            yahoo_level = self._signals.get(pos.ticker)
            sig_widget = QLabel()
            sig_widget.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            if yahoo_level:
                color = SIGNAL_COLORS.get(yahoo_level, PALETTE["text3"])
                label = _SIGNAL_LABELS.get(yahoo_level, yahoo_level)
                sig_widget.setText(f"● {label}")
                sig_widget.setStyleSheet(
                    f"color: {color}; font-weight: 700; font-size: 11px; "
                    f"background-color: {color}18; border-radius: 5px; "
                    f"padding: 2px 8px;"
                )
                sig_widget.setToolTip(
                    f"<b>Señal Técnica: {label}</b><br>"
                    "Basada en RSI, MACD, Bandas de Bollinger y SMA50/200.<br>"
                    "Hacé doble clic para ver el análisis completo."
                )
            else:
                sig_widget.setText("Calculando…")
                sig_widget.setStyleSheet(
                    f"color: {PALETTE['text3']}; font-size: 11px;"
                )
            self.table.setCellWidget(row, 13, sig_widget)

            self.table.setRowHeight(row, 48)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def _update_cards(self):
        total_invested = sum(p.quantity * p.avg_buy_price for p in self._positions)
        total_value = sum(
            p.quantity * (self._prices[p.ticker]["price"] if p.ticker in self._prices and self._prices[p.ticker] else p.avg_buy_price)
            for p in self._positions
        )
        pl_price = total_value - total_invested

        # Dividends
        total_divs = sum(
            (self._dividends.get(p.ticker, 0.0) * p.quantity)
            for p in self._positions
        ) if self._show_dividends else 0.0

        pl_total  = pl_price + total_divs
        pl_pct    = (pl_price  / total_invested * 100) if total_invested > 0 else 0
        pl_pct_div = (pl_total / total_invested * 100) if total_invested > 0 else 0

        self.card_total.set_value(f"${total_value:,.2f}")
        self.card_invested.set_value(f"${total_invested:,.2f}")
        self.card_pl.set_value(
            f"{'+'if pl_price>=0 else ''}${pl_price:,.2f}",
            color=PALETTE["accent"] if pl_price >= 0 else PALETTE["red"]
        )
        self.card_divs.set_value(
            f"+${total_divs:,.2f}" if total_divs > 0 else "—",
            color=PALETTE["blue"] if total_divs > 0 else PALETTE["text3"]
        )
        self.card_pl_total.set_value(
            f"{'+'if pl_total>=0 else ''}${pl_total:,.2f}",
            color=PALETTE["accent"] if pl_total >= 0 else PALETTE["red"]
        )
        self.card_pl_pct.set_value(
            f"{pl_pct_div:+.2f}%",
            color=PALETTE["accent"] if pl_pct_div >= 0 else PALETTE["red"]
        )
        self.card_positions.set_value(str(len(self._positions)))

    # ── Actions ────────────────────────────────────────────────────────────

    def _toggle_dividends(self):
        self._show_dividends = not self._show_dividends
        if self._show_dividends:
            self.div_btn.setText("💰  Dividendos: ON")
            self.div_btn.setStyleSheet(
                f"background-color: {PALETTE['accent_bg']}; color: {PALETTE['accent']}; "
                f"border: 1px solid #1a4a2a; border-radius: 8px; "
                f"padding: 0 14px; font-weight: 600; font-size: 12px;"
            )
            self._fetch_dividends()
        else:
            self.div_btn.setText("💰  Dividendos: OFF")
            self.div_btn.setStyleSheet(
                f"background-color: {PALETTE['elevated']}; color: {PALETTE['text3']}; "
                f"border: 1px solid {PALETTE['border_lt']}; border-radius: 8px; "
                f"padding: 0 14px; font-weight: 600; font-size: 12px;"
            )
            self._render_table()
            self._update_cards()

    def _add_portfolio(self):
        if AddPortfolioDialog(self).exec():
            self._load_portfolios()

    def _rename_portfolio(self):
        if self._current_portfolio_id is None:
            QMessageBox.warning(self, "Sin portafolio", "Seleccioná un portafolio primero.")
            return
        current_name = self.portfolio_combo.currentText()
        if RenamePortfolioDialog(self._current_portfolio_id, current_name, self).exec():
            self._load_portfolios()

    def _add_position(self):
        if self._current_portfolio_id is None:
            QMessageBox.warning(self, "Sin portafolio", "Primero creá un portafolio.")
            return
        if AddPositionDialog(self._current_portfolio_id, self).exec():
            self._refresh_positions()

    def _import_csv(self):
        if self._current_portfolio_id is None:
            QMessageBox.warning(self, "Sin portafolio", "Seleccioná un portafolio primero.")
            return
        if ImportDialog(self._current_portfolio_id, self).exec():
            self._refresh_positions()

    def _import_watchlist(self):
        """Create a new portfolio and open the import dialog in one step."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Nueva Watchlist",
            "Nombre del portafolio watchlist:",
            text="Watchlist"
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        # Create the portfolio
        session = get_session()
        try:
            from database.models import Portfolio as PortfolioModel
            conflict = session.query(PortfolioModel).filter(PortfolioModel.name == name).first()
            if conflict:
                QMessageBox.warning(self, "Nombre en uso",
                                    f"Ya existe un portafolio llamado '{name}'.\n"
                                    f"Elegí otro nombre o importá directamente desde '📥 Importar CSV'.")
                return
            p = PortfolioModel(name=name, description="Watchlist de seguimiento", currency="USD")
            session.add(p)
            session.commit()
            new_id = p.id
        finally:
            session.close()

        # Reload combo and select the new portfolio
        self._load_portfolios()
        for i in range(self.portfolio_combo.count()):
            if self.portfolio_combo.itemData(i) == new_id:
                self.portfolio_combo.setCurrentIndex(i)
                break

        # Open import dialog for the new portfolio
        if ImportDialog(new_id, self).exec():
            self._refresh_positions()
        else:
            # If import was cancelled, remove the empty portfolio
            session = get_session()
            try:
                from database.models import Portfolio as PortfolioModel
                p = session.query(PortfolioModel).filter(PortfolioModel.id == new_id).first()
                if p:
                    session.delete(p)
                    session.commit()
            finally:
                session.close()
            self._load_portfolios()

    def _sell_position(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._positions):
            if SellPositionDialog(self._positions[row], self).exec():
                self._refresh_positions()

    def _analyze_selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._positions):
            self.position_selected.emit(self._positions[row])

    def _on_row_selected(self):
        row = self.table.currentRow()
        has = 0 <= row < len(self._positions)
        self.sell_btn.setEnabled(has)
        self.analyze_btn.setEnabled(has)

    def _on_row_double_clicked(self, index):
        row = index.row()
        if 0 <= row < len(self._positions):
            self.position_selected.emit(self._positions[row])

    def _show_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu, QWidgetAction
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._positions):
            return
        position = self._positions[row]

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {PALETTE['card']}; border: 1px solid {PALETTE['border_lt']}; "
            f"border-radius: 8px; padding: 4px; }}"
            f"QMenu::item {{ padding: 8px 20px; color: {PALETTE['text1']}; border-radius: 5px; }}"
            f"QMenu::item:selected {{ background: {PALETTE['nav_active']}; color: {PALETTE['accent']}; }}"
            f"QMenu::separator {{ height: 1px; background: {PALETTE['border']}; margin: 3px 8px; }}"
        )

        menu.addAction("📈  Analizar",  lambda: self.position_selected.emit(position))
        menu.addAction("💰  Vender",    lambda: self._sell_pos_at_row(row))
        menu.addSeparator()

        delete_action = menu.addAction(f"🗑  Eliminar {position.ticker}")
        delete_action.setToolTip("Elimina la posición y todo su historial de transacciones")
        # Style the delete action in red
        delete_action.triggered.connect(lambda: self._delete_pos_at_row(row))

        # Override color for delete item via stylesheet hack
        menu.setStyleSheet(
            menu.styleSheet() +
            f"QMenu::item[text*='Eliminar'] {{ color: {PALETTE['red']}; }}"
        )

        menu.exec(self.table.mapToGlobal(pos))

    def _sell_pos_at_row(self, row: int):
        if SellPositionDialog(self._positions[row], self).exec():
            self._refresh_positions()

    def _delete_pos_at_row(self, row: int):
        if row < 0 or row >= len(self._positions):
            return
        pos = self._positions[row]
        reply = QMessageBox.question(
            self,
            "Eliminar posición",
            f"¿Eliminar <b>{pos.ticker}</b> ({pos.company_name or pos.ticker}) "
            f"y todo su historial de transacciones?<br><br>"
            f"<span style='color:#f87171'>Esta acción no se puede deshacer.</span>",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = get_session()
        try:
            db_pos = session.query(Position).filter(Position.id == pos.id).first()
            if db_pos:
                session.delete(db_pos)   # cascades to transactions via relationship
                session.commit()
        finally:
            session.close()

        self._refresh_positions()

    def get_current_portfolio_id(self) -> int:
        return self._current_portfolio_id
