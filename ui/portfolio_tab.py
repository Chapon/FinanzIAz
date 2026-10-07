"""
Portfolio tab — IQON-style card layout with live P&L metrics.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.logging_config import get_logger
from config.settings_manager import settings
from data.yahoo_finance import get_bulk_dividend_calendar, get_bulk_prices
from database.models import Portfolio, Position, Transaction, session_scope
from ui.dialogs import (
    AddPortfolioDialog,
    AddPositionDialog,
    EditTickerDialog,
    RenamePortfolioDialog,
    SellPositionDialog,
)
from ui.import_dialog import ImportDialog
from ui.styles import PALETTE, SIGNAL_COLORS
from ui.ticker_tooltip import apply_ticker_tooltip, install_ticker_tooltips
from ui.widgets import MetricCard, SectionHeader, table_header, table_vheader
from ui.workers import BaseWorker

log = get_logger(__name__)

# Spanish labels for Yahoo Finance 5-level system (mirrors SignalBadge._LABELS)
_SIGNAL_LABELS = {
    "Strong Buy": "Compra Fuerte",
    "Buy": "Comprar",
    "Hold": "Mantener",
    "Underperform": "Vender",
    "Sell": "Venta Fuerte",
}


# Tarea 325: la columna 0 es la flecha del desplegable; el ticker queda limpio en la 1, porque el
# tooltip lee el ticker del texto de la celda.
_COLUMNAS = [
    "",
    "Ticker",
    "Estado",
    "Empresa",
    "Cant.",
    "P. Compra",
    "P. Actual",
    "Var. Hoy",
    "Invertido",
    "Valor",
    "Ganancia Precio",
    "Dividendos",
    "Realizada",
    "Ganancia Total",
    "G/P %",
    "Rend. Total",
    "Señal Técnica",
]
_COL_TICKER = _COLUMNAS.index("Ticker")
_COL_EMPRESA = _COLUMNAS.index("Empresa")
_COL_SENAL = _COLUMNAS.index("Señal Técnica")


def totales_cartera(positions, prices: dict, dividends: dict, show_dividends: bool) -> dict:
    """Las cuentas de las tarjetas de Portfolio (tarea 281). Pura, para poder testearla.

    [P-1] Una posición **sin precio no se valúa al costo en silencio**: antes entraba al valor
    con P&L cero y la tarjeta no lo decía. Valor y ganancia se calculan sobre las que tienen
    precio, el % sobre el costo de esas mismas, y ``sin_precio`` las nombra.
    [P-2] ``dividends`` es efectivo cobrado por posición (lote por lote), no $/acción.
    """
    con_precio = [p for p in positions if prices.get(p.ticker)]
    valor = sum(p.quantity * prices[p.ticker]["price"] for p in con_precio)
    invertido_con_precio = sum(p.quantity * p.avg_buy_price for p in con_precio)
    pl_precio = valor - invertido_con_precio
    divs = sum(dividends.get(p.ticker, 0.0) for p in positions) if show_dividends else 0.0
    pl_total = pl_precio + divs
    return {
        "invertido": sum(p.quantity * p.avg_buy_price for p in positions),
        "valor": valor,
        "sin_precio": sorted(p.ticker for p in positions if not prices.get(p.ticker)),
        "pl_precio": pl_precio,
        "dividendos": divs,
        "pl_total": pl_total,
        # Sobre el costo de las que TIENEN precio: la ganancia de precio sólo las cuenta a ellas.
        "pl_pct": (pl_total / invertido_con_precio * 100) if invertido_con_precio > 0 else 0.0,
    }


class PriceWorker(BaseWorker):
    prices_ready = pyqtSignal(dict)

    def __init__(self, tickers: list):
        super().__init__()
        self.tickers = tickers

    def do_work(self) -> dict:
        return get_bulk_prices(self.tickers)

    def on_success(self, result: dict) -> None:
        self.prices_ready.emit(result)


class DividendWorker(BaseWorker):
    """Background thread to fetch cumulative dividends per position."""

    dividends_ready = pyqtSignal(dict)  # {ticker: efectivo cobrado} — tarea 281
    detalle_ready = pyqtSignal(dict)  # {ticker: dividendos_detalle} — tarea 325

    def __init__(self, lotes: dict):
        super().__init__()
        self.lotes = lotes  # {ticker: [(día, acciones con signo), ...]}

    def do_work(self) -> dict:
        """Tarea 281: efectivo cobrado lote por lote, con el calendario de ex-dates.

        Antes era el dividendo por acción desde UNA fecha por la cantidad ACTUAL, que en una
        posición comprada en tramos contaba dividendos de acciones que todavía no se tenían.
        """
        from database.cartera_real import dividendos_cobrados, dividendos_detalle

        calendario = get_bulk_dividend_calendar(sorted(self.lotes))
        return {
            "totales": {t: dividendos_cobrados(ev, calendario.get(t, [])) for t, ev in self.lotes.items()},
            "detalle": {t: dividendos_detalle(ev, calendario.get(t, [])) for t, ev in self.lotes.items()},
        }

    def on_success(self, result: dict) -> None:
        self.detalle_ready.emit(result["detalle"])
        self.dividends_ready.emit(result["totales"])


class SignalWorker(BaseWorker):
    """
    Background worker: fetches 1 year of historical data for each ticker
    and returns the Yahoo Finance 5-level signal for every one.
    Tickers are analyzed in parallel (up to 4 threads).
    """

    signals_ready = pyqtSignal(dict)  # {ticker: yahoo_level_str}

    def __init__(self, tickers: list):
        super().__init__()
        self.tickers = tickers

    def do_work(self) -> dict:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from analysis.technical import analyze
        from config.settings_manager import settings as _settings
        from data.yahoo_finance import get_historical_data_batch

        sma_cross = _settings.get("sma_cross")

        # Prefetch OHLCV en un lote (un crumb compartido por chunk → menos 401);
        # el análisis sigue paralelizado, solo la descarga se agrupa.
        prefetched = get_historical_data_batch(self.tickers, period="1y")

        def _analyze_one(ticker: str) -> tuple[str, str]:
            try:
                df = prefetched.get(ticker.upper())
                if df is None or len(df) < 50:
                    log.debug("%s: insufficient data (%s rows)", ticker, len(df) if df is not None else 0)
                    return ticker, "Hold"
                result = analyze(
                    ticker,
                    df,
                    enable_sma_cross=sma_cross,
                    enable_xgboost=False,  # skip ML in batch scan to stay fast
                )
                if result:
                    log.debug(
                        "%s: %s (buy=%s strength=%s conf=%s%%)",
                        ticker,
                        result.yahoo_level,
                        result.overall_signal,
                        result.overall_strength,
                        result.confidence_score,
                    )
                    return ticker, result.yahoo_level
                return ticker, "Hold"
            except Exception:
                log.exception("Signal calc failed for %s", ticker)
                return ticker, "Hold"

        results: dict = {}
        if not self.tickers:
            return results
        max_workers = min(4, len(self.tickers))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_analyze_one, t): t for t in self.tickers}
            for future in as_completed(futures):
                ticker, signal = future.result()
                results[ticker] = signal
        return results

    def on_success(self, result: dict) -> None:
        self.signals_ready.emit(result)


class PortfolioTab(QWidget):
    position_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._portfolios = []
        self._current_portfolio_id = None
        self._positions = []  # las ABIERTAS: las que suman las tarjetas
        self._cerradas = []  # tarea 325: vendidas enteras, rotuladas «Cerrada» y fuera de los totales
        self._libros = {}  # {ticker: LibroTicker} — el FIFO de sus transacciones (tarea 324)
        self._div_detalle = None  # {ticker: dividendos_detalle}; None mientras se calcula
        self._expandidos: set[str] = set()  # tickers con el desplegable abierto
        self._filas: list[tuple[str, object]] = []  # por fila de la tabla: ("pos"|"detalle", Position)
        self._prices = {}
        self._dividends = {}  # {ticker: efectivo cobrado} — tarea 281
        self._signals = {}  # {ticker: yahoo_level_str}
        self._show_dividends = True  # toggle
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
            "background-color: #1e3a5f; color: #60a5fa; "
            "border: 1px solid #1d4ed8; border-radius: 8px; "
            "padding: 0 14px; font-weight: 600; font-size: 12px;"
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
        self.last_update_label.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px;")
        top.addWidget(self.last_update_label)

        root.addLayout(top)

        # ── Metric cards ────────────────────────────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        self.card_total = MetricCard("Valor Total")
        self.card_invested = MetricCard("Invertido")
        self.card_pl = MetricCard("Ganancia de Precio")
        self.card_divs = MetricCard("Dividendos Cobrados")
        self.card_pl_total = MetricCard("Ganancia Total")
        self.card_pl_pct = MetricCard("Rendimiento Total")
        self.card_positions = MetricCard("Posiciones")

        for card in [
            self.card_total,
            self.card_invested,
            self.card_pl,
            self.card_divs,
            self.card_pl_total,
            self.card_pl_pct,
            self.card_positions,
        ]:
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
        self.table.setColumnCount(len(_COLUMNAS))
        self.table.setHorizontalHeaderLabels(_COLUMNAS)
        table_header(self.table).setSectionResizeMode(_COL_EMPRESA, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        table_vheader(self.table).setVisible(False)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        # Tarea 325: la flecha de la columna 0 abre y cierra el desplegable del ticker.
        self.table.cellClicked.connect(self._on_cell_clicked)
        # Tooltip on hover over the Ticker column
        install_ticker_tooltips(self.table, _COL_TICKER)
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
        with session_scope() as session:
            self._portfolios = session.query(Portfolio).order_by(Portfolio.name).all()
            session.expunge_all()

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
        with session_scope() as session:
            self._positions = (
                session.query(Position)
                .filter(Position.portfolio_id == self._current_portfolio_id)
                .filter(Position.quantity > 0)  # tarea 277: las vendidas enteras quedan en 0
                .order_by(Position.ticker)
                .all()
            )
            # Tarea 325: las cerradas se muestran aparte, rotuladas, y no suman a las tarjetas.
            self._cerradas = (
                session.query(Position)
                .filter(Position.portfolio_id == self._current_portfolio_id)
                .filter(Position.quantity <= 0)
                .order_by(Position.ticker)
                .all()
            )
            self._libros = self._armar_libros(session, self._positions + self._cerradas)
            session.expunge_all()

        self._div_detalle = None
        self._signals = {}
        self._render_table()
        if self._positions:
            self._fetch_prices()
            self._fetch_dividends()
            self._fetch_signals()

    @staticmethod
    def _armar_libros(session, posiciones) -> dict:
        """``{ticker: LibroTicker}``: el FIFO de las transacciones de cada posición (tarea 324)."""
        from database.cartera_real import movimientos_de
        from database.lotes import libro_fifo

        ids = {p.id: p.ticker for p in posiciones}
        txs: dict[int, list] = {i: [] for i in ids}
        if ids:
            for t in session.query(Transaction).filter(Transaction.position_id.in_(list(ids))).all():
                txs[t.position_id].append(t)
        return {ids[i]: libro_fifo(movimientos_de(ts)) for i, ts in txs.items()}

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
        if not self._positions and not self._cerradas:
            return
        if self._div_worker and self._div_worker.isRunning():
            return
        self._div_worker = DividendWorker(self._lotes())
        self._div_worker.detalle_ready.connect(self._on_div_detalle_ready)
        self._div_worker.dividends_ready.connect(self._on_dividends_ready)
        self._div_worker.start()

    def _lotes(self) -> dict:
        """``{ticker: [(día, acciones con signo)]}`` desde las transacciones (tarea 281)."""
        from paper_trading.dividends import dia

        por_id = {p.id: p for p in self._positions + self._cerradas}
        lotes: dict = {p.ticker: [] for p in por_id.values()}
        with session_scope() as session:
            for t in session.query(Transaction).filter(Transaction.position_id.in_(list(por_id))).all():
                pos = por_id[t.position_id]
                d = dia(t.date or pos.purchase_date or pos.created_at)
                if d is None:
                    continue
                signo = 1.0 if str(t.transaction_type).upper() == "BUY" else -1.0
                lotes[pos.ticker].append((d, signo * float(t.quantity)))
        return lotes

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

    def _on_div_detalle_ready(self, detalle: dict):
        self._div_detalle = detalle  # lo pinta el render que dispara _on_dividends_ready

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
        self.table.clearSpans()
        self.table.setRowCount(0)
        self._filas = []
        for pos in self._positions + self._cerradas:
            self._filas.append(("pos", pos))
            if pos.ticker in self._expandidos:
                self._filas.append(("detalle", pos))
        self.table.setRowCount(len(self._filas))

        for row, (tipo, pos) in enumerate(self._filas):
            if tipo == "detalle":
                self._render_detalle(row, pos)
            elif pos.quantity > 0:
                self._render_abierta(row, pos)
            else:
                self._render_cerrada(row, pos)

        self.table.resizeColumnsToContents()
        table_header(self.table).setSectionResizeMode(_COL_EMPRESA, QHeaderView.ResizeMode.Stretch)

    @staticmethod
    def _cell(text, right=False, bold=False, color=None):
        item = QTableWidgetItem(str(text))
        align = Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        if bold:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        if color:
            item.setForeground(QColor(color))
        return item

    @staticmethod
    def _color(x):
        return None if x is None else (PALETTE["positive"] if x >= 0 else PALETTE["red"])

    def _render_comunes(self, row: int, pos, estado: str, color_estado: str):
        """Flecha, ticker, estado, empresa y realizada: lo que tienen abiertas y cerradas."""
        cell = self._cell
        flecha = cell("▾" if pos.ticker in self._expandidos else "▸", color=PALETTE["text3"])
        flecha.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        flecha.setToolTip("Ver lotes, transacciones y dividendos")
        self.table.setItem(row, 0, flecha)
        ticker_item = cell(pos.ticker, bold=True)
        apply_ticker_tooltip(ticker_item, pos.ticker)
        self.table.setItem(row, _COL_TICKER, ticker_item)
        self.table.setItem(row, 2, cell(estado, color=color_estado))
        self.table.setItem(row, _COL_EMPRESA, cell(pos.company_name or pos.ticker))
        libro = self._libros.get(pos.ticker)
        realizada = libro.realizado if libro and any(f.mov.tipo == "SELL" for f in libro.filas) else None
        texto = f"{'+' if realizada >= 0 else ''}${realizada:,.2f}" if realizada is not None else "—"
        self.table.setItem(row, 12, cell(texto, right=True, color=self._color(realizada)))

    def _render_abierta(self, row: int, pos):
        cell = self._cell
        d = self._prices.get(pos.ticker)
        current_price = d["price"] if d else None
        change_pct = d.get("change_pct") if d else None

        invested = pos.quantity * pos.avg_buy_price
        current_val = (pos.quantity * current_price) if current_price else None
        pl_price = (current_val - invested) if current_val is not None else None

        # Dividends
        div_total = self._dividends.get(pos.ticker, 0.0) if self._show_dividends else 0.0

        # Total P&L = price gain + dividends
        pl_total = ((pl_price or 0.0) + div_total) if pl_price is not None else None
        pl_pct = ((pl_price / invested) * 100) if (pl_price is not None and invested > 0) else None
        pl_pct_div = (
            (((pl_price or 0) + div_total) / invested * 100)
            if invested > 0 and pl_price is not None
            else None
        )

        def dinero(x, signo=False):
            return "—" if x is None else f"{'+' if signo and x >= 0 else ''}${x:,.2f}"

        def pct(x):
            return "—" if x is None else f"{x:+.2f}%"

        self._render_comunes(row, pos, "Abierta", PALETTE["text2"])
        self.table.setItem(row, 4, cell(f"{pos.quantity:,.4g}", right=True))
        self.table.setItem(row, 5, cell(f"${pos.avg_buy_price:,.2f}", right=True))
        self.table.setItem(row, 6, cell(dinero(current_price), right=True))
        self.table.setItem(row, 7, cell(pct(change_pct), right=True, color=self._color(change_pct)))
        self.table.setItem(row, 8, cell(dinero(invested), right=True))
        self.table.setItem(row, 9, cell(dinero(current_val), right=True))
        self.table.setItem(
            row, 10, cell(dinero(pl_price), right=True, bold=True, color=self._color(pl_price))
        )
        div_color = PALETTE["positive"] if div_total else None
        self.table.setItem(
            row, 11, cell(dinero(div_total) if div_total else "—", right=True, color=div_color)
        )
        self.table.setItem(
            row, 13, cell(dinero(pl_total), right=True, bold=True, color=self._color(pl_total))
        )
        self.table.setItem(row, 14, cell(pct(pl_pct), right=True, color=self._color(pl_pct)))
        self.table.setItem(
            row, 15, cell(pct(pl_pct_div), right=True, bold=True, color=self._color(pl_pct_div))
        )

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
            sig_widget.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px;")
        self.table.setCellWidget(row, _COL_SENAL, sig_widget)

        self.table.setRowHeight(row, 48)

    def _render_cerrada(self, row: int, pos):
        """Tarea 325: vendida entera. Sin valor ni ganancia de precio; sí su realizada y dividendos."""
        cell = self._cell
        gris = PALETTE["text3"]
        self._render_comunes(row, pos, "Cerrada", gris)
        div_total = self._dividends.get(pos.ticker, 0.0) if self._show_dividends else 0.0
        self.table.setItem(row, 4, cell("0", right=True, color=gris))
        for col in (5, 6, 7, 8, 9, 10, 13, 14, 15):
            self.table.setItem(row, col, cell("—", right=True, color=gris))
        texto = f"${div_total:,.2f}" if div_total else "—"
        self.table.setItem(row, 11, cell(texto, right=True, color=PALETTE["positive"] if div_total else gris))
        self.table.setItem(row, _COL_SENAL, cell(""))
        self.table.setRowHeight(row, 40)

    def _render_detalle(self, row: int, pos):
        from database.lotes import LibroTicker
        from ui.portfolio_detalle import DetallePosicion

        d = self._prices.get(pos.ticker)
        detalle = DetallePosicion(
            self._libros.get(pos.ticker) or LibroTicker([], []),
            d["price"] if d else None,
            None if self._div_detalle is None else self._div_detalle.get(pos.ticker, []),
        )
        self.table.setSpan(row, 0, 1, self.table.columnCount())
        self.table.setCellWidget(row, 0, detalle)
        self.table.setRowHeight(row, detalle.alto_sugerido())

    def _update_cards(self):
        t = totales_cartera(self._positions, self._prices, self._dividends, self._show_dividends)
        total_invested, total_value, sin_precio = t["invertido"], t["valor"], t["sin_precio"]
        pl_price, total_divs, pl_total, pl_pct_div = (
            t["pl_precio"],
            t["dividendos"],
            t["pl_total"],
            t["pl_pct"],
        )

        faltan = f"  ({len(sin_precio)} sin precio)" if sin_precio else ""
        self.card_total.set_value(f"${total_value:,.2f}{faltan}")
        self.card_total.setToolTip(
            "Sin precio, fuera del valor y de la ganancia: " + ", ".join(sin_precio) if sin_precio else ""
        )
        self.card_invested.set_value(f"${total_invested:,.2f}")
        self.card_pl.set_value(
            f"{'+' if pl_price >= 0 else ''}${pl_price:,.2f}",
            color=PALETTE["positive"] if pl_price >= 0 else PALETTE["red"],
        )
        self.card_divs.set_value(
            f"+${total_divs:,.2f}" if total_divs > 0 else "—",
            color=PALETTE["positive"] if total_divs > 0 else PALETTE["text3"],
        )
        self.card_pl_total.set_value(
            f"{'+' if pl_total >= 0 else ''}${pl_total:,.2f}",
            color=PALETTE["positive"] if pl_total >= 0 else PALETTE["red"],
        )
        self.card_pl_pct.set_value(
            f"{pl_pct_div:+.2f}%", color=PALETTE["positive"] if pl_pct_div >= 0 else PALETTE["red"]
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
            self, "Nueva Watchlist", "Nombre del portafolio watchlist:", text="Watchlist"
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        # Create the portfolio
        from database.models import Portfolio as PortfolioModel

        with session_scope() as session:
            conflict = session.query(PortfolioModel).filter(PortfolioModel.name == name).first()
            if conflict:
                QMessageBox.warning(
                    self,
                    "Nombre en uso",
                    f"Ya existe un portafolio llamado '{name}'.\n"
                    f"Elegí otro nombre o importá directamente desde '📥 Importar CSV'.",
                )
                return
            p = PortfolioModel(name=name, description="Watchlist de seguimiento", currency="USD")
            session.add(p)
            session.flush()
            new_id = int(p.id)

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
            with session_scope() as session:
                p = session.query(PortfolioModel).filter(PortfolioModel.id == new_id).first()
                if p:
                    session.delete(p)
            self._load_portfolios()

    def _pos_en(self, row: int):
        """La posición de la fila ``row``, o ``None`` si es un desplegable o no existe (tarea 325).

        Con los desplegables y las cerradas, la fila de la tabla ya no es el índice en
        ``self._positions``: indexar así abría el análisis o la venta de otro ticker.
        """
        if 0 <= row < len(self._filas) and self._filas[row][0] == "pos":
            return self._filas[row][1]
        return None

    def _abierta_en(self, row: int):
        pos = self._pos_en(row)
        return pos if pos is not None and pos.quantity > 0 else None

    def _on_cell_clicked(self, row: int, col: int):
        pos = self._pos_en(row)
        if col == 0 and pos is not None:
            self._expandidos.symmetric_difference_update({pos.ticker})
            self._render_table()

    def _sell_position(self):
        pos = self._abierta_en(self.table.currentRow())
        if pos is not None and SellPositionDialog(pos, self).exec():
            self._refresh_positions()

    def _analyze_selected(self):
        pos = self._pos_en(self.table.currentRow())
        if pos is not None:
            self.position_selected.emit(pos)

    def _on_row_selected(self):
        row = self.table.currentRow()
        self.sell_btn.setEnabled(self._abierta_en(row) is not None)
        self.analyze_btn.setEnabled(self._pos_en(row) is not None)

    def _on_row_double_clicked(self, index):
        pos = self._pos_en(index.row())
        if pos is not None:
            self.position_selected.emit(pos)

    def _show_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu

        row = self.table.rowAt(pos.y())
        position = self._pos_en(row)
        if position is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {PALETTE['card']}; border: 1px solid {PALETTE['border_lt']}; "
            f"border-radius: 8px; padding: 4px; }}"
            f"QMenu::item {{ padding: 8px 20px; color: {PALETTE['text1']}; border-radius: 5px; }}"
            f"QMenu::item:selected {{ background: {PALETTE['nav_active']}; color: {PALETTE['accent']}; }}"
            f"QMenu::separator {{ height: 1px; background: {PALETTE['border']}; margin: 3px 8px; }}"
        )

        menu.addAction("📈  Analizar", lambda: self.position_selected.emit(position))
        abierto = position.ticker in self._expandidos
        menu.addAction(
            "▴  Ocultar lotes y transacciones" if abierto else "▾  Ver lotes y transacciones",
            lambda: self._on_cell_clicked(row, 0),
        )
        if position.quantity > 0:
            menu.addAction("💰  Vender", lambda: self._sell_pos_at_row(row))
        menu.addAction("✏️  Editar ticker…", lambda: self._edit_ticker_at_row(row))
        menu.addSeparator()

        delete_action = menu.addAction(f"🗑  Eliminar {position.ticker}")
        if delete_action is None:  # pragma: no cover — addAction con texto no devuelve None
            return
        delete_action.setToolTip("Elimina la posición y todo su historial de transacciones")
        # Style the delete action in red
        delete_action.triggered.connect(lambda: self._delete_pos_at_row(row))

        # Override color for delete item via stylesheet hack
        menu.setStyleSheet(
            menu.styleSheet() + f"QMenu::item[text*='Eliminar'] {{ color: {PALETTE['red']}; }}"
        )

        menu.exec(self.table.mapToGlobal(pos))

    def _sell_pos_at_row(self, row: int):
        pos = self._abierta_en(row)
        if pos is not None and SellPositionDialog(pos, self).exec():
            self._refresh_positions()

    def _edit_ticker_at_row(self, row: int):
        """Renombra el símbolo de una posición (manteniendo cantidad, precio y transacciones)."""
        pos = self._pos_en(row)
        if pos is not None and EditTickerDialog(pos, self).exec():
            self._refresh_positions()

    def _delete_pos_at_row(self, row: int):
        pos = self._pos_en(row)
        if pos is None:
            return

        # Count transactions to surface what cascades on delete.
        from database.models import Transaction as TxModel

        with session_scope() as session:
            n_tx = session.query(TxModel).filter(TxModel.position_id == pos.id).count()

        body = (
            f"¿Eliminar <b>{pos.ticker}</b> ({pos.company_name or pos.ticker})?<br><br>"
            f"Se borrarán también <b>{n_tx}</b> transacción/es asociadas.<br><br>"
            f"<span style='color:#f87171'>Esta acción no se puede deshacer.</span><br>"
            f"<i style='color:#8b949e'>Tip: la app hace un backup diario en "
            f"<code>~/.finanzias/backups/</code>.</i>"
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Eliminar posición")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        # Pre-destructive snapshot — best-effort; daily backup is the floor.
        try:
            from database.backup import backup_database

            backup_database(reason="pre-delete-position")
        except Exception:
            pass

        with session_scope() as session:
            db_pos = session.query(Position).filter(Position.id == pos.id).first()
            if db_pos:
                session.delete(db_pos)  # cascades to transactions via relationship

        self._refresh_positions()

    def get_current_portfolio_id(self) -> int:
        return self._current_portfolio_id
