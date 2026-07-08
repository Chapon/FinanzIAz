"""
Paper-trading tab — IQON-style layout to manage simulated accounts.

Features
--------
* Account selector + CRUD (create / edit / delete).
* Live KPIs: equity, cash, positions value, P&L %.
* Config panel (read-only summary; edit via dialog).
* Watchlist management (add / remove tickers).
* Open positions table (mark-to-market).
* Pending orders table with Approve / Reject buttons.
* Recent filled/rejected orders history.
* Equity curve line chart (matplotlib).
* Manual "Escanear ahora" button that goes through the shared scheduler.

The tab is *signal-driven*: it emits ``scan_requested(account_id)`` and
receives completion notifications via ``on_scan_completed(result)`` from
``MainWindow`` (which owns the ``PaperScheduler``).
"""

from __future__ import annotations

import contextlib

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.logging_config import get_logger
from ui.styles import PALETTE
from ui.ticker_tooltip import apply_ticker_tooltip, install_ticker_tooltips
from ui.time_utils import fmt_local as _fmt_local
from ui.widgets import HSeparator, MetricCard

log = get_logger(__name__)

# Sub-components extracted from this file in the refactor pass. Importing
# them here keeps every external ``from ui.paper_tab import …`` call-site
# working unchanged (they re-export below).
# Real-portfolio integration: tras aprobar una orden de paper, ofrecemos
# registrar la operación correspondiente en el Portafolio real del usuario.
# NOTE: Portfolio / Position / session_scope used to be imported here for the
# real-portfolio crossover helpers; those moved to ui.paper.real_portfolio.
from paper_trading.account import (
    add_watchlist_tickers,
    compute_equity,
    count_orders,
    delete_account,
    get_account,
    get_equity_curve,
    get_orders,
    get_pending_orders,
    get_position_entry_prices,
    get_positions,
    get_watchlist,
    list_accounts,
    remove_watchlist_ticker,
    update_account_config,
)
from paper_trading.costs import get_active_commission_model
from paper_trading.engine import approve_order, reject_order
from paper_trading.presets import WATCHLIST_PRESETS
from ui.dialogs import AddPositionDialog, SellPositionDialog
from ui.paper.account_dialog import PaperAccountDialog
from ui.paper.equity_chart import EquityCurveChart
from ui.paper.real_portfolio import find_real_position, pick_real_portfolio
from ui.paper.workers import PricesWorker

# Backwards-compatible aliases for the previous private names. External code
# that referenced ``ui.paper_tab._PricesWorker`` / ``_EquityCurveChart``
# keeps working. New code should import from ``ui.paper`` directly.
_PricesWorker = PricesWorker
_EquityCurveChart = EquityCurveChart


def needs_pause_confirmation(positions, pending) -> bool:
    """Whether pausing an account should ask the user to confirm first.

    Pausing has two non-obvious consequences — open positions stop getting
    stops/risk-exits and pending orders never fill — so we only confirm when
    there is actually something at stake. Pure function so the decision is
    testable without a Qt event loop.
    """
    return bool(positions) or bool(pending)


# ── Main paper-trading tab ────────────────────────────────────────────────────


class PaperTradingTab(QWidget):
    """IQON-style paper-trading dashboard."""

    scan_requested = pyqtSignal(int)  # account_id (or 0 = all)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accounts: list = []
        self._current_account_id: int | None = None
        self._prices: dict[str, float] = {}
        self._pending_orders: list = []
        self._orders_history: list = []
        self._positions: list = []
        self._entry_prices: dict[str, float] = {}
        self._watchlist: list[str] = []
        self._price_worker: _PricesWorker | None = None

        self._build_ui()
        self._load_accounts()

        # Auto-refresh prices every 60 s when visible.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(60_000)
        self._refresh_timer.timeout.connect(self._fetch_prices)
        self._refresh_timer.start()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # Top: account selector + actions
        top = QHBoxLayout()
        top.setSpacing(10)

        top.addWidget(QLabel("Cuenta:"))
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(260)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        top.addWidget(self.account_combo)

        # Inline styles guarantee these critical buttons render correctly
        # even if the global `#primary` QSS selector gets out-prioritized.
        _PRIMARY_BTN_QSS = (
            f"QPushButton {{"
            f"  background-color: {PALETTE['accent']};"
            f"  color: #000000;"
            f"  border: none;"
            f"  border-radius: 8px;"
            f"  padding: 8px 18px;"
            f"  font-size: 13px; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background-color: #6ee7a0; }}"
            f"QPushButton:disabled {{ background-color: {PALETTE['border_lt']}; color: {PALETTE['text3']}; }}"
        )
        _SECONDARY_BTN_QSS = (
            f"QPushButton {{"
            f"  background-color: {PALETTE['elevated']};"
            f"  color: {PALETTE['text1']};"
            f"  border: 1px solid {PALETTE['border_lt']};"
            f"  border-radius: 8px;"
            f"  padding: 8px 16px;"
            f"  font-size: 13px; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background-color: {PALETTE['border_lt']}; }}"
            f"QPushButton:disabled {{ color: {PALETTE['text3']}; }}"
        )
        _DANGER_BTN_QSS = (
            f"QPushButton {{"
            f"  background-color: #3d1515;"
            f"  color: {PALETTE['red']};"
            f"  border: 1px solid #5a2020;"
            f"  border-radius: 8px;"
            f"  padding: 8px 16px;"
            f"  font-size: 13px; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background-color: #5a1f1f; }}"
            f"QPushButton:disabled {{ color: {PALETTE['text3']}; }}"
        )

        # Stashed so the pause/resume toggle can be restyled from
        # ``_refresh_account_action_buttons`` (out of this local scope).
        self._primary_btn_qss = _PRIMARY_BTN_QSS
        self._secondary_btn_qss = _SECONDARY_BTN_QSS

        self.new_btn = QPushButton("+ Nueva")
        self.new_btn.setMinimumHeight(36)
        self.new_btn.setStyleSheet(_PRIMARY_BTN_QSS)
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.clicked.connect(self._new_account)
        top.addWidget(self.new_btn)

        self.edit_btn = QPushButton("Editar")
        self.edit_btn.setMinimumHeight(36)
        self.edit_btn.setStyleSheet(_SECONDARY_BTN_QSS)
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_btn.clicked.connect(self._edit_account)
        top.addWidget(self.edit_btn)

        # One-click pause/resume of the selected account (toggle: label + style
        # reflect current state). Backend is ``is_active`` on the account.
        self.toggle_active_btn = QPushButton("⏸ Pausar")
        self.toggle_active_btn.setMinimumHeight(36)
        self.toggle_active_btn.setStyleSheet(_SECONDARY_BTN_QSS)
        self.toggle_active_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_active_btn.clicked.connect(self._toggle_account_active)
        top.addWidget(self.toggle_active_btn)

        self.delete_btn = QPushButton("Eliminar")
        self.delete_btn.setMinimumHeight(36)
        self.delete_btn.setStyleSheet(_DANGER_BTN_QSS)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.clicked.connect(self._delete_account)
        top.addWidget(self.delete_btn)

        top.addStretch()

        self.scan_btn = QPushButton("⚡ Escanear ahora")
        self.scan_btn.setMinimumHeight(36)
        self.scan_btn.setStyleSheet(_PRIMARY_BTN_QSS)
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_btn.clicked.connect(self._scan_now)
        top.addWidget(self.scan_btn)

        self.refresh_btn = QPushButton("↻ Refrescar")
        self.refresh_btn.setMinimumHeight(36)
        self.refresh_btn.setStyleSheet(_SECONDARY_BTN_QSS)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._refresh_all)
        top.addWidget(self.refresh_btn)

        root.addLayout(top)
        root.addWidget(HSeparator())

        # KPI cards row
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self.kpi_equity = MetricCard("Equity total")
        self.kpi_cash = MetricCard("Cash disponible")
        self.kpi_posvalue = MetricCard("Valor posiciones")
        self.kpi_pnl = MetricCard("P&L absoluto")
        self.kpi_pnl_pct = MetricCard("P&L %")
        self.kpi_positions = MetricCard("Posiciones abiertas")
        for w in (
            self.kpi_equity,
            self.kpi_cash,
            self.kpi_posvalue,
            self.kpi_pnl,
            self.kpi_pnl_pct,
            self.kpi_positions,
        ):
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            kpi_row.addWidget(w)
        root.addLayout(kpi_row)

        # Config strip (read-only summary)
        self.config_label = QLabel("—")
        self.config_label.setObjectName("muted")
        self.config_label.setWordWrap(True)
        root.addWidget(self.config_label)

        # Splitter: left (watchlist) | right (positions + orders + chart)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ─ Left column: watchlist ─────────────────────────────────────────────
        left = QFrame()
        left.setObjectName("card")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(8)

        wl_header = QLabel("Watchlist")
        wl_header.setObjectName("h2")
        left_layout.addWidget(wl_header)

        add_row = QHBoxLayout()
        self.ticker_input = QLineEdit()
        self.ticker_input.setPlaceholderText("Ej: AAPL, MSFT")
        self.ticker_input.returnPressed.connect(self._add_ticker)
        add_row.addWidget(self.ticker_input)

        self.add_ticker_btn = QPushButton("Agregar")
        self.add_ticker_btn.clicked.connect(self._add_ticker)
        add_row.addWidget(self.add_ticker_btn)
        left_layout.addLayout(add_row)

        # Bulk-add via curated sector presets (paper_trading/presets.py).
        self.preset_btn = QPushButton("+ Preset por sector  ▾")
        self.preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preset_btn.setToolTip(
            "Cargar una lista de tickers curada por sector (tecnología, energía, salud, etc.)"
        )
        self.preset_btn.clicked.connect(self._show_preset_menu)
        left_layout.addWidget(self.preset_btn)

        self.watchlist_table = QTableWidget(0, 3)
        self.watchlist_table.setHorizontalHeaderLabels(["Ticker", "Precio", ""])
        self.watchlist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.watchlist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.watchlist_table.verticalHeader().setVisible(False)
        self.watchlist_table.verticalHeader().setDefaultSectionSize(40)
        self.watchlist_table.horizontalHeader().setStretchLastSection(False)
        self.watchlist_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.watchlist_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.watchlist_table.setColumnWidth(2, 44)
        # Tooltip on hover over Ticker column (col 0)
        install_ticker_tooltips(self.watchlist_table, 0)
        left_layout.addWidget(self.watchlist_table, stretch=1)

        splitter.addWidget(left)

        # ─ Right column: positions + pending orders + history + chart ───────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # ── Three-column row: Posiciones | Pendientes | Historial ────────────
        # Side-by-side layout so all three tables are visible at once without
        # the user having to scroll past one to reach the next.
        tables_row = QHBoxLayout()
        tables_row.setSpacing(10)

        # Each table gets a generous minimum height so several rows fit
        # before any internal scroll kicks in.
        _TABLE_MIN_H = 280

        # Positions (col 1)
        pos_card = QFrame()
        pos_card.setObjectName("card")
        pos_l = QVBoxLayout(pos_card)
        pos_l.setContentsMargins(14, 12, 14, 12)
        pos_l.setSpacing(8)
        pos_l.addWidget(self._header_with_count("Posiciones abiertas", attr="_positions_header"))
        self.positions_table = QTableWidget(0, 10)
        self.positions_table.setHorizontalHeaderLabels(
            [
                "Ticker",
                "Shares",
                "Precio compra",
                "Avg Cost",
                "Precio",
                "Market Value",
                "Peso %",
                "P&L $",
                "P&L %",
                "Comisión est.",
            ]
        )
        self._apply_table_style(self.positions_table)
        # Tooltip on hover over Ticker column (col 0)
        install_ticker_tooltips(self.positions_table, 0)
        self.positions_table.setMinimumHeight(_TABLE_MIN_H)
        pos_l.addWidget(self.positions_table)
        tables_row.addWidget(pos_card, 1)

        # Pending orders (col 2)
        pen_card = QFrame()
        pen_card.setObjectName("card")
        pen_l = QVBoxLayout(pen_card)
        pen_l.setContentsMargins(14, 12, 14, 12)
        pen_l.setSpacing(8)
        pen_l.addWidget(self._header_with_count("Órdenes pendientes", attr="_pending_header"))
        self.pending_table = QTableWidget(0, 9)
        self.pending_table.setHorizontalHeaderLabels(
            ["Fecha", "Side", "Ticker", "Shares", "Target $", "Comisión est.", "Motivo",
             "R:R / niveles", "Acciones"]
        )
        self._apply_table_style(self.pending_table, row_height=52)
        # "Acciones" is the stretch-last column, so it soaks up the leftover
        # width for both buttons. Keep the global minimum section small so the
        # other columns can collapse to their (now word-wrapped) headers
        # instead of all being forced to a wide floor.
        self.pending_table.horizontalHeader().setMinimumSectionSize(46)
        self.pending_table.setColumnWidth(7, 150)   # R:R / niveles (V2)
        self.pending_table.setColumnWidth(8, 240)   # Acciones
        # Tooltip on hover over Ticker column (col 2)
        install_ticker_tooltips(self.pending_table, 2)
        self.pending_table.setMinimumHeight(_TABLE_MIN_H)
        pen_l.addWidget(self.pending_table)
        tables_row.addWidget(pen_card, 1)

        # Filled / history (col 3)
        hist_card = QFrame()
        hist_card.setObjectName("card")
        hist_l = QVBoxLayout(hist_card)
        hist_l.setContentsMargins(14, 12, 14, 12)
        hist_l.setSpacing(8)
        hist_l.addWidget(self._header_with_count("Historial reciente", attr="_history_header"))
        self.history_table = QTableWidget(0, 8)
        self.history_table.setHorizontalHeaderLabels(
            ["Fecha", "Side", "Ticker", "Shares", "Precio", "Total", "Comisión", "Estado"]
        )
        self._apply_table_style(self.history_table)
        # Tooltip on hover over Ticker column (col 2)
        install_ticker_tooltips(self.history_table, 2)
        self.history_table.setMinimumHeight(_TABLE_MIN_H)
        hist_l.addWidget(self.history_table)
        tables_row.addWidget(hist_card, 1)

        right_layout.addLayout(tables_row)

        # Equity curve
        chart_card = QFrame()
        chart_card.setObjectName("card")
        chart_l = QVBoxLayout(chart_card)
        chart_l.setContentsMargins(14, 12, 14, 12)
        chart_l.setSpacing(8)
        chart_title = QLabel("Curva de Equity")
        chart_title.setObjectName("h2")
        chart_l.addWidget(chart_title)
        self.equity_chart = _EquityCurveChart()
        self.equity_chart.setMinimumHeight(220)
        chart_l.addWidget(self.equity_chart)
        right_layout.addWidget(chart_card)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        # Wrap in a scroll area so it works on smaller screens
        scroll = QScrollArea()
        scroll.setWidget(splitter)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, stretch=1)

    def _apply_table_style(self, table: QTableWidget, row_height: int = 44):
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        vh = table.verticalHeader()
        vh.setVisible(False)
        # Fixed mode: rows keep the height we set and don't auto-shrink to
        # text content (which clips embedded button widgets).
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(row_height)
        vh.setMinimumSectionSize(row_height)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        header = table.horizontalHeader()
        for i in range(table.columnCount() - 1):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        # Wrap multi-word headers so each column is only as wide as its widest
        # word — keeps all columns visible without horizontal scroll.
        self._wrap_header_labels(table)

    def _wrap_header_labels(self, table: QTableWidget) -> None:
        """Stack each header label one word per line.

        ``"Precio compra"`` → ``"Precio\\ncompra"``. With ResizeToContents the
        section width then collapses to the longest single word, minimising
        column width. The header is given enough height to show every line.
        """
        header = table.horizontalHeader()
        max_lines = 1
        for col in range(table.columnCount()):
            item = table.horizontalHeaderItem(col)
            if item is None:
                continue
            words = item.text().split()
            if len(words) > 1:
                item.setText("\n".join(words))
                item.setToolTip(" ".join(words))
            max_lines = max(max_lines, len(words) or 1)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
        )
        line_h = header.fontMetrics().height()
        # Add the QSS section vertical padding (~10px top + 10px bottom) plus a
        # small margin so no line gets clipped.
        header.setFixedHeight(max_lines * line_h + 24)

    def _header_with_count(self, title: str, attr: str) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(title)
        lbl.setObjectName("h2")
        layout.addWidget(lbl)
        count = QLabel("")
        count.setObjectName("muted")
        layout.addWidget(count)
        layout.addStretch()
        setattr(self, attr, count)
        return w

    # ── Account list ──────────────────────────────────────────────────────────

    def _load_accounts(self):
        self._accounts = list_accounts()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        if not self._accounts:
            self.account_combo.addItem("— No hay cuentas —", userData=None)
            self._current_account_id = None
        else:
            for a in self._accounts:
                label = f"{a.name}   ·   {a.strategy}/{a.mode}"
                if not a.is_active:
                    label += "  (inactiva)"
                self.account_combo.addItem(label, userData=int(a.id))
            # Restore previous selection if still present
            target_idx = 0
            if self._current_account_id is not None:
                for i, a in enumerate(self._accounts):
                    if int(a.id) == self._current_account_id:
                        target_idx = i
                        break
            self.account_combo.setCurrentIndex(target_idx)
            self._current_account_id = self.account_combo.itemData(target_idx)
        self.account_combo.blockSignals(False)
        self._refresh_all()

    def _on_account_changed(self, _idx: int):
        data = self.account_combo.currentData()
        self._current_account_id = int(data) if data is not None else None
        self._refresh_all()

    # ── Account actions ───────────────────────────────────────────────────────

    def _new_account(self):
        dlg = PaperAccountDialog(account=None, parent=self)
        if dlg.exec():
            self._load_accounts()

    def _edit_account(self):
        if self._current_account_id is None:
            return
        acct = get_account(self._current_account_id)
        if acct is None:
            QMessageBox.warning(self, "Error", "La cuenta ya no existe.")
            self._load_accounts()
            return
        dlg = PaperAccountDialog(account=acct, parent=self)
        if dlg.exec():
            self._load_accounts()

    def _selected_account(self):
        """Return the selected ``PaperAccount`` from the cached list (no DB hit)."""
        if self._current_account_id is None:
            return None
        for a in self._accounts:
            if int(a.id) == self._current_account_id:
                return a
        return None

    def _refresh_account_action_buttons(self):
        """Sync the pause/resume toggle and the scan button to the selected account.

        Called from ``_load_accounts`` and ``_on_account_changed`` — the two
        points where the selected account (and its ``is_active``) can change.
        """
        acct = self._selected_account()
        if acct is None:
            self.toggle_active_btn.setEnabled(False)
            self.toggle_active_btn.setText("⏸ Pausar")
            self.toggle_active_btn.setStyleSheet(self._secondary_btn_qss)
            self.scan_btn.setEnabled(False)
            return
        self.toggle_active_btn.setEnabled(True)
        if acct.is_active:
            self.toggle_active_btn.setText("⏸ Pausar")
            self.toggle_active_btn.setStyleSheet(self._secondary_btn_qss)
        else:
            self.toggle_active_btn.setText("▶ Activar")
            self.toggle_active_btn.setStyleSheet(self._primary_btn_qss)
        # An inactive account is a no-op in ``run_scan`` (engine.py) — don't let
        # the scan button pretend a manual scan would do anything.
        self.scan_btn.setEnabled(bool(acct.is_active))

    def _toggle_account_active(self):
        """Pause (deactivate) or resume (activate) the selected account in one click."""
        if self._current_account_id is None:
            return
        acct = get_account(self._current_account_id)
        if acct is None:
            QMessageBox.warning(self, "Error", "La cuenta ya no existe.")
            self._load_accounts()
            return

        new_state = not acct.is_active
        if not new_state:
            # Pausing has two non-obvious consequences (no stops on open
            # positions + pending orders never fill). Confirm explicitly when
            # the account actually has something at stake.
            positions = get_positions(self._current_account_id)
            pending = get_pending_orders(self._current_account_id)
            if needs_pause_confirmation(positions, pending):
                body = (
                    "Al pausar esta cuenta el scan automático y el manual la van "
                    "a saltear:<br><br>"
                    "<ul>"
                    "<li>NO se van a generar nuevas órdenes.</li>"
                    "<li>Las órdenes pendientes NO se van a llenar.</li>"
                    "<li>A las posiciones abiertas NO se les van a correr "
                    "stops/risk-exits mientras esté pausada.</li>"
                    "</ul>"
                    "La historia y las posiciones se conservan.<br><br>"
                    "¿Pausar igual?"
                )
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("Pausar cuenta")
                box.setTextFormat(Qt.TextFormat.RichText)
                box.setText(body)
                box.setStandardButtons(
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                box.setDefaultButton(QMessageBox.StandardButton.No)  # safer default
                if box.exec() != QMessageBox.StandardButton.Yes:
                    return

        updated = update_account_config(self._current_account_id, is_active=new_state)
        if updated is None:
            QMessageBox.warning(self, "Error", "La cuenta ya no existe.")
            self._load_accounts()
            return

        # Refreshes the combo "(inactiva)" suffix, KPIs and the toggle itself.
        self._load_accounts()
        verb = "activada" if new_state else "pausada"
        with contextlib.suppress(Exception):
            self.window().statusBar().showMessage(f"Cuenta {verb}.", 4000)

    def _delete_account(self):
        if self._current_account_id is None:
            return
        acct = get_account(self._current_account_id)
        if acct is None:
            return

        # Show how much will cascade so the user knows what they're losing.
        n_pos = len(get_positions(self._current_account_id))
        n_ord = count_orders(self._current_account_id)
        body = (
            f"¿Eliminar la cuenta <b>'{acct.name}'</b>?<br><br>"
            f"Se borrarán también:<ul>"
            f"<li>{n_pos} posición/es abiertas</li>"
            f"<li>{n_ord} orden/es históricas</li>"
            f"<li>la curva de equity completa</li>"
            f"</ul>"
            f"<span style='color:#f87171'>Esta acción no se puede deshacer.</span><br>"
            f"<i style='color:#8b949e'>Tip: la app hace un backup diario en "
            f"<code>~/.finanzias/backups/</code>.</i>"
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Eliminar cuenta")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)  # safer default
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        # Take a "pre-destructive-op" snapshot for paranoid recovery.
        try:
            from database.backup import backup_database

            backup_database(reason="pre-delete-account")
        except Exception:
            pass  # backup is best-effort; the daily snapshot is still there.

        if delete_account(self._current_account_id):
            self._current_account_id = None
            self._load_accounts()

    def _scan_now(self):
        if self._current_account_id is None:
            QMessageBox.information(self, "Sin cuenta", "Creá una cuenta primero.")
            return
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("⌛ Escaneando…")
        self.scan_requested.emit(int(self._current_account_id))
        # Re-enable after a short timeout as a safety net — MainWindow will
        # also call on_scan_completed which properly restores the state.
        QTimer.singleShot(15_000, self._reset_scan_button)

    def _reset_scan_button(self):
        self.scan_btn.setText("⚡ Escanear ahora")
        # Re-enable only if the selected account is active (inactive = no-op scan).
        self._refresh_account_action_buttons()

    # ── Watchlist ─────────────────────────────────────────────────────────────

    def _add_ticker(self):
        if self._current_account_id is None:
            QMessageBox.information(self, "Sin cuenta", "Creá una cuenta primero.")
            return
        raw = self.ticker_input.text().strip()
        if not raw:
            return
        tickers = [t.strip().upper() for t in raw.replace(";", ",").split(",") if t.strip()]
        if not tickers:
            return
        added = add_watchlist_tickers(self._current_account_id, tickers)
        self.ticker_input.clear()
        if added == 0:
            QMessageBox.information(self, "Watchlist", "Ningún ticker nuevo agregado.")
        self._refresh_watchlist()

    def _remove_ticker(self, ticker: str):
        if self._current_account_id is None:
            return
        if remove_watchlist_ticker(self._current_account_id, ticker):
            self._refresh_watchlist()

    # ── Preset (sector) menu ──────────────────────────────────────────────────

    def _show_preset_menu(self):
        """Pop a menu listing every sector preset; clicking adds in bulk."""
        if self._current_account_id is None:
            QMessageBox.information(self, "Sin cuenta", "Creá una cuenta primero.")
            return
        if not WATCHLIST_PRESETS:
            return

        menu = QMenu(self)
        # Match the dark IQON look so the menu doesn't render as system-default.
        menu.setStyleSheet(
            f"QMenu {{"
            f"  background-color: {PALETTE['elevated']};"
            f"  color: {PALETTE['text1']};"
            f"  border: 1px solid {PALETTE['border_lt']};"
            f"  padding: 4px;"
            f"}}"
            f"QMenu::item {{"
            f"  padding: 6px 18px; border-radius: 4px;"
            f"}}"
            f"QMenu::item:selected {{"
            f"  background-color: {PALETTE['accent']}; color: #000;"
            f"}}"
        )

        for name, tickers in WATCHLIST_PRESETS.items():
            label = f"{name}   ({len(tickers)} tickers)"
            act = menu.addAction(label)
            # Bind the loop variables explicitly with default args.
            act.triggered.connect(lambda _checked=False, n=name, t=list(tickers): self._add_preset(n, t))

        # Show under the button.
        anchor = self.preset_btn.mapToGlobal(self.preset_btn.rect().bottomLeft())
        menu.exec(anchor)

    def _add_preset(self, name: str, tickers: list[str]):
        if self._current_account_id is None:
            return
        try:
            added = add_watchlist_tickers(self._current_account_id, tickers)
        except Exception as e:
            QMessageBox.critical(self, "Preset", f"No se pudo agregar el preset:\n{e}")
            return
        skipped = len(tickers) - added
        msg_parts = [f"Preset «{name}» aplicado.", f"Tickers nuevos agregados: {added}."]
        if skipped > 0:
            msg_parts.append(f"Ya estaban en la watchlist: {skipped}.")
        QMessageBox.information(self, "Preset agregado", "\n".join(msg_parts))
        self._refresh_watchlist()
        # New tickers need prices fetched for the watchlist column to fill.
        self._fetch_prices()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh_all(self):
        has_account = self._current_account_id is not None
        for btn in (
            self.edit_btn,
            self.delete_btn,
            self.refresh_btn,
            self.add_ticker_btn,
            self.preset_btn,
        ):
            btn.setEnabled(has_account)
        self.ticker_input.setEnabled(has_account)
        # scan + pause/resume buttons are account-active-aware, not just
        # account-present — the helper is the single source of truth.
        self._refresh_account_action_buttons()

        if not has_account:
            self.config_label.setText("Seleccioná o creá una cuenta para empezar.")
            self._clear_all_data()
            return

        self._refresh_config_strip()
        self._refresh_watchlist()
        self._refresh_orders()
        self._refresh_equity_curve()
        # Positions + KPIs come after prices are fetched.
        self._fetch_prices()

    def _clear_all_data(self):
        for card in (
            self.kpi_equity,
            self.kpi_cash,
            self.kpi_posvalue,
            self.kpi_pnl,
            self.kpi_pnl_pct,
            self.kpi_positions,
        ):
            card.set_value("—")
        self.watchlist_table.setRowCount(0)
        self.positions_table.setRowCount(0)
        self.pending_table.setRowCount(0)
        self.history_table.setRowCount(0)
        self.equity_chart.set_data([])
        self._entry_prices = {}
        if hasattr(self, "_positions_header"):
            self._positions_header.setText("")
        if hasattr(self, "_pending_header"):
            self._pending_header.setText("")
        if hasattr(self, "_history_header"):
            self._history_header.setText("")

    def _refresh_config_strip(self):
        acct = get_account(self._current_account_id)
        if acct is None:
            self.config_label.setText("—")
            return
        parts = [
            f"Estrategia: <b>{acct.strategy}</b>",
            f"Modo: <b>{acct.mode}</b>",
            f"Asignación: <b>{acct.allocation_mode}</b>",
            f"Máx. posiciones: <b>{acct.max_positions}</b>",
            f"Capital inicial: <b>${acct.initial_capital:,.2f}</b>",
            f"Commission: <b>{acct.commission * 100:.2f}%</b>",
            f"Slippage: <b>{acct.slippage * 100:.2f}%</b>",
            f"Drift: <b>{acct.drift_threshold * 100:.0f}%</b>",
        ]
        self.config_label.setText("   ·   ".join(parts))

    def _refresh_watchlist(self):
        if self._current_account_id is None:
            self.watchlist_table.setRowCount(0)
            return
        self._watchlist = get_watchlist(self._current_account_id)
        self.watchlist_table.setRowCount(0)
        for t in self._watchlist:
            row = self.watchlist_table.rowCount()
            self.watchlist_table.insertRow(row)
            wl_ticker_item = QTableWidgetItem(t)
            apply_ticker_tooltip(wl_ticker_item, t)
            self.watchlist_table.setItem(row, 0, wl_ticker_item)
            px = self._prices.get(t)
            self.watchlist_table.setItem(
                row,
                1,
                QTableWidgetItem(f"${px:,.2f}" if px is not None else "—"),
            )
            # Wrap the button in a centered container so it inherits the cell
            # height and doesn't get clipped by the row.
            rm_container = QWidget()
            rm_lay = QHBoxLayout(rm_container)
            rm_lay.setContentsMargins(2, 4, 2, 4)
            rm_lay.setSpacing(0)
            remove_btn = QPushButton("✕")
            remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            remove_btn.setToolTip(f"Quitar {t} de la watchlist")
            remove_btn.setFixedSize(28, 28)
            remove_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {PALETTE['elevated']};"
                f"  color: {PALETTE['text2']};"
                f"  border: 1px solid {PALETTE['border_lt']};"
                f"  border-radius: 6px;"
                f"  padding: 0px;"
                f"  font-size: 13px; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: {PALETTE['red']}; color: #000; border-color: {PALETTE['red']};"
                f"}}"
            )
            remove_btn.clicked.connect(lambda _c=False, tk=t: self._remove_ticker(tk))
            rm_lay.addWidget(remove_btn, alignment=Qt.AlignmentFlag.AlignCenter)
            self.watchlist_table.setCellWidget(row, 2, rm_container)

    def _refresh_orders(self):
        if self._current_account_id is None:
            return
        self._pending_orders = get_pending_orders(self._current_account_id)
        self._orders_history = get_orders(self._current_account_id, limit=50)
        history = [o for o in self._orders_history if o.status != "pending"]

        # Pending
        self.pending_table.setRowCount(0)
        for o in self._pending_orders:
            row = self.pending_table.rowCount()
            self.pending_table.insertRow(row)
            self._set_order_row(self.pending_table, row, o, pending=True)
        self._pending_header.setText(f"· {len(self._pending_orders)}")

        # History
        self.history_table.setRowCount(0)
        for o in history:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self._set_history_row(self.history_table, row, o)
        self._history_header.setText(f"· {len(history)}")

    def _set_order_row(self, table: QTableWidget, row: int, o, pending: bool):
        created = _fmt_local(o.created_at)
        table.setItem(row, 0, QTableWidgetItem(created))
        side_item = QTableWidgetItem(o.side)
        side_item.setForeground(QColor(PALETTE["positive"] if o.side == "BUY" else PALETTE["red"]))
        table.setItem(row, 1, side_item)
        order_ticker_item = QTableWidgetItem(o.ticker)
        apply_ticker_tooltip(order_ticker_item, o.ticker)
        table.setItem(row, 2, order_ticker_item)
        shares_txt = self._format_shares(o.target_shares)
        table.setItem(row, 3, QTableWidgetItem(shares_txt))
        dollars_txt = f"${o.target_dollars:,.2f}" if o.target_dollars is not None else "—"
        table.setItem(row, 4, QTableWidgetItem(dollars_txt))

        # Comisión estimada (col 5) — usa el precio cacheado del ticker para
        # estimar shares (en BUYs sin target_shares) y luego corre el modelo
        # IBKR activo. En "legacy" muestra "—" para no confundir.
        table.setItem(row, 5, QTableWidgetItem(self._estimate_pending_commission(o)))
        table.setItem(row, 6, QTableWidgetItem(o.reason or ""))

        # R:R / niveles (V2): la nota display-only que el engine estampó al crear
        # el BUY (stop/TP + R:R). Los SELL / órdenes sin nota muestran "—".
        rr_txt = o.notes if (o.side == "BUY" and o.notes) else "—"
        rr_item = QTableWidgetItem(rr_txt)
        if o.notes:
            rr_item.setToolTip(o.notes)
        table.setItem(row, 7, rr_item)

        if pending:
            actions = QWidget()
            alay = QHBoxLayout(actions)
            alay.setContentsMargins(6, 8, 6, 8)
            alay.setSpacing(4)

            approve = QPushButton("✓ Sim")
            approve.setCursor(Qt.CursorShape.PointingHandCursor)
            approve.setFixedHeight(32)
            approve.setMinimumWidth(60)
            approve.setToolTip("Aprobar la orden solo en la simulación de Paper Trading.")
            approve.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {PALETTE['accent']};"
                f"  color: #000000;"
                f"  border: none;"
                f"  border-radius: 6px;"
                f"  padding: 0 8px;"
                f"  font-size: 12px; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background-color: #6ee7a0; }}"
            )
            approve.clicked.connect(lambda _=False, oid=int(o.id): self._approve_order(oid))

            approve_real = QPushButton("✓ + Portafolio")
            approve_real.setCursor(Qt.CursorShape.PointingHandCursor)
            approve_real.setFixedHeight(32)
            approve_real.setMinimumWidth(112)
            approve_real.setToolTip(
                "Aprobar la orden en la simulación Y abrir el diálogo para "
                "registrar la operación correspondiente en tu Portafolio real."
            )
            approve_real.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {PALETTE['blue']};"
                f"  color: #000000;"
                f"  border: none;"
                f"  border-radius: 6px;"
                f"  padding: 0 8px;"
                f"  font-size: 12px; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background-color: #66c2ff; }}"
            )
            approve_real.clicked.connect(lambda _=False, oid=int(o.id): self._approve_and_register(oid))

            reject = QPushButton("✕")
            reject.setCursor(Qt.CursorShape.PointingHandCursor)
            reject.setFixedHeight(32)
            reject.setFixedWidth(36)
            reject.setToolTip("Rechazar la sugerencia")
            reject.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: #3d1515;"
                f"  color: {PALETTE['red']};"
                f"  border: 1px solid #5a2020;"
                f"  border-radius: 6px;"
                f"  padding: 0;"
                f"  font-size: 13px; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background-color: {PALETTE['red']}; color: #000; }}"
            )
            reject.clicked.connect(lambda _=False, oid=int(o.id): self._reject_order(oid))

            alay.addWidget(approve)
            alay.addWidget(approve_real)
            alay.addWidget(reject)
            alay.addStretch()
            table.setCellWidget(row, 8, actions)
            # Force the row height after placing the cell widget so
            # Qt allocates enough vertical space for the buttons.
            table.setRowHeight(row, 52)

    def _estimate_pending_commission(self, o) -> str:
        """
        Render the commission a pending order would incur if it filled at the
        current cached price. Returns "—" when we can't price it or when the
        user is on the legacy flat-% model (mixing both in one cell would
        misrepresent the cost).
        """
        try:
            from config.settings_manager import settings as _settings

            plan = str(_settings.get("ibkr_commission_plan", "tiered")).lower()
        except Exception:
            plan = "tiered"
        if plan not in ("tiered", "fixed"):
            return "—"

        px = self._prices.get(o.ticker) if hasattr(self, "_prices") else None
        if px is None or px <= 0:
            return "—"

        # Estimate shares: for SELLs use target_shares; for BUYs derive from
        # target_dollars (floor to integer since the engine fills whole shares).
        if o.side == "SELL" and o.target_shares:
            shares = float(o.target_shares)
        elif o.side == "BUY" and o.target_dollars and o.target_dollars > 0:
            shares = float(int(float(o.target_dollars) / float(px)))
        else:
            return "—"
        if shares < 1:
            return "—"

        try:
            model = get_active_commission_model()
            est = model.cost(side=o.side, shares=shares, price=float(px))
            return f"≈${est:,.2f}"
        except Exception:
            return "—"

    @staticmethod
    def _format_shares(value) -> str:
        """Render share counts compactly: '12' if integer, '12.3456' otherwise."""
        if value is None:
            return "—"
        try:
            f = float(value)
        except (TypeError, ValueError):
            return "—"
        if abs(f - round(f)) < 1e-6:
            return f"{round(f)}"
        return f"{f:.4f}"

    def _set_history_row(self, table: QTableWidget, row: int, o):
        ts = o.filled_at or o.decided_at or o.created_at
        ts_txt = _fmt_local(ts)
        table.setItem(row, 0, QTableWidgetItem(ts_txt))
        side_item = QTableWidgetItem(o.side)
        side_item.setForeground(QColor(PALETTE["positive"] if o.side == "BUY" else PALETTE["red"]))
        table.setItem(row, 1, side_item)
        hist_ticker_item = QTableWidgetItem(o.ticker)
        apply_ticker_tooltip(hist_ticker_item, o.ticker)
        table.setItem(row, 2, hist_ticker_item)
        shares_txt = self._format_shares(o.fill_shares)
        table.setItem(row, 3, QTableWidgetItem(shares_txt))
        price_txt = f"${o.fill_price:,.2f}" if o.fill_price is not None else "—"
        table.setItem(row, 4, QTableWidgetItem(price_txt))
        total_txt = (
            f"${o.fill_value:,.2f}" if (o.fill_price is not None and o.fill_shares is not None) else "—"
        )
        table.setItem(row, 5, QTableWidgetItem(total_txt))

        # Comisión real pagada (col 6) — stored on the order at fill time.
        # Pre-IBKR-model fills will still show the legacy %-of-notional value
        # they were stamped with; we keep them as-is per the user's
        # "dejar como están" decision for historical orders.
        comm = getattr(o, "commission_paid", None)
        comm_txt = f"${comm:,.2f}" if comm is not None else "—"
        table.setItem(row, 6, QTableWidgetItem(comm_txt))

        status_item = QTableWidgetItem(o.status)
        colors = {
            "filled": PALETTE["positive"],
            "rejected": PALETTE["red"],
            "cancelled": PALETTE["text3"],
            "expired": PALETTE["yellow"],
            "approved": PALETTE["blue"],
        }
        status_item.setForeground(QColor(colors.get(o.status, PALETTE["text2"])))
        table.setItem(row, 7, status_item)

    def _approve_order(self, order_id: int):
        try:
            ok = approve_order(order_id)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo aprobar la orden:\n{e}")
            return
        if not ok:
            QMessageBox.warning(self, "Aprobar", "La orden ya no está pendiente.")
        elif ok.status == "pending":
            # T7.2: bloqueada por re-gate (market hours / earnings blackout).
            if self._offer_gate_override(ok):
                try:
                    approve_order(order_id, override_gates=True)
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"No se pudo aprobar la orden:\n{e}")
                    return
        self._refresh_orders()
        self._fetch_prices()  # positions may have changed

    def _offer_gate_override(self, order) -> bool:
        """T7.2: la aprobación fue bloqueada por un re-gate. Mostrar el motivo
        y preguntar si se aprueba igual (override explícito). Returns True si
        el usuario confirma."""
        reason = ""
        if order.notes:
            lines = [ln for ln in order.notes.strip().splitlines() if ln.strip()]
            if lines:
                reason = lines[-1].replace("[approve] bloqueada por re-gate:", "").strip()
        resp = QMessageBox.question(
            self,
            "Bloqueada por guardrails",
            f"La aprobación de {order.ticker} {order.side} fue bloqueada:\n\n"
            f"{reason}\n\n¿Aprobar igual (override explícito)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return resp == QMessageBox.StandardButton.Yes

    def _reject_order(self, order_id: int):
        try:
            ok = reject_order(order_id, note="Rechazada desde la UI")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo rechazar la orden:\n{e}")
            return
        if not ok:
            QMessageBox.warning(self, "Rechazar", "La orden ya no está pendiente.")
        self._refresh_orders()

    # ── Approve + register in real Portfolio ───────────────────────────────────

    def _approve_and_register(self, order_id: int):
        """
        Aprobar la orden de paper trading Y abrir el diálogo del Portafolio
        real para que el usuario registre la operación con su precio efectivo
        de broker.

        Flujo:
          1. ``approve_order`` ejecuta el fill en la simulación.
          2. Si fue BUY → AddPositionDialog (eligiendo portafolio si hay >1).
          3. Si fue SELL → busca la Position real correspondiente al ticker;
             si existe, abre SellPositionDialog; si no, avisa al usuario.
        """
        # 1. Aprobar en paper trading.
        try:
            filled = approve_order(order_id)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo aprobar la orden:\n{e}")
            return
        if filled is None:
            QMessageBox.warning(self, "Aprobar", "La orden ya no está pendiente.")
            return
        if filled.status == "pending":
            # T7.2: bloqueada por re-gate. Ofrecer override explícito.
            if not self._offer_gate_override(filled):
                self._refresh_orders()
                return
            try:
                filled = approve_order(order_id, override_gates=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo aprobar la orden:\n{e}")
                return
            if filled is None or filled.status == "pending":
                QMessageBox.warning(self, "Aprobar", "No se pudo completar la aprobación.")
                self._refresh_orders()
                return

        side = filled.side
        ticker = filled.ticker
        fill_qty = float(filled.fill_shares or 0.0)
        fill_price = float(filled.fill_price or 0.0)

        # Refrescar paper view ahora — pase lo que pase en el diálogo, el sim
        # ya está actualizado.
        self._refresh_orders()
        self._fetch_prices()

        if fill_qty <= 0 or fill_price <= 0:
            QMessageBox.information(
                self,
                "Aprobada",
                "Orden aprobada en simulación, pero no se pudo calcular shares/precio "
                "para pre-llenar el Portafolio. Cargá la operación manualmente.",
            )
            return

        # 2. BUY → AddPositionDialog
        if side == "BUY":
            portfolio_id = pick_real_portfolio(self)
            if portfolio_id is None:
                return
            dlg = AddPositionDialog(
                portfolio_id,
                parent=self,
                prefill_ticker=ticker,
                prefill_qty=fill_qty,
                prefill_price=fill_price,
                prefill_notes=f"Sugerencia paper: {filled.reason or ''}".strip(),
            )
            dlg.exec()
            return

        # 3. SELL → SellPositionDialog
        if side == "SELL":
            pos = find_real_position(self, ticker)
            if pos is None:
                QMessageBox.information(
                    self,
                    "Sin posición real",
                    f"No tenés <b>{ticker}</b> en ningún portafolio real, así que la "
                    "venta solo se aprobó en la simulación. Si la operás en tu broker, "
                    "registrala manualmente desde la pestaña Portafolio.",
                )
                return
            dlg = SellPositionDialog(
                pos,
                parent=self,
                prefill_qty=fill_qty,
                prefill_price=fill_price,
            )
            dlg.exec()
            return

    # NOTE: ``_pick_real_portfolio`` and ``_find_real_position`` were
    # extracted to ``ui.paper.real_portfolio`` — they have no shared state
    # with this tab. Call sites use ``pick_real_portfolio(self)`` /
    # ``find_real_position(self, ticker)``.

    # ── Equity curve ──────────────────────────────────────────────────────────

    def _refresh_equity_curve(self):
        if self._current_account_id is None:
            self.equity_chart.set_data([])
            return
        try:
            snaps = get_equity_curve(self._current_account_id, limit=500)
        except Exception as e:
            log.warning("equity refresh failed: %s", e)
            snaps = []
        self.equity_chart.set_data(snaps, benchmark=self._load_spy_overlay(snaps))

    @staticmethod
    def _load_spy_overlay(snaps: list):
        """Serie SPY normalizada para overlayar en la curva de equity (V1).

        Best-effort/read-only: lee el cache diario de SPY (poblado por el warm-up
        del scan) y lo alinea a la ventana de los snapshots. Devuelve ``None`` si
        SPY todavía no está cacheado o algo falla — la curva se dibuja igual.
        """
        if not snaps:
            return None
        try:
            import sqlite3
            from pathlib import Path

            from analysis.metrics_panel import BENCHMARK_TICKER, load_close_series
            from database.models import DB_PATH
            from ui.paper.equity_chart import build_benchmark_overlay

            con = sqlite3.connect(f"file:{Path(DB_PATH).as_posix()}?mode=ro", uri=True)
            try:
                spy = load_close_series(con, BENCHMARK_TICKER)
            finally:
                con.close()
            return build_benchmark_overlay(snaps, spy) or None
        except Exception as e:
            log.warning("SPY overlay failed: %s", e)
            return None

    # ── Prices & KPIs ────────────────────────────────────────────────────────

    def _fetch_prices(self):
        if self._current_account_id is None:
            return
        # Union of watchlist and current positions' tickers
        try:
            self._positions = get_positions(self._current_account_id)
        except Exception as e:
            log.warning("positions refresh failed: %s", e)
            self._positions = []
        # Cheap DB hit; refreshed alongside positions so the table shows the
        # original entry price next to the running VWAP.
        try:
            self._entry_prices = get_position_entry_prices(self._current_account_id)
        except Exception as e:
            log.warning("entry_prices fetch failed: %s", e)
            self._entry_prices = {}
        tickers = set(self._watchlist) | {p.ticker for p in self._positions}
        if not tickers:
            self._on_prices_ready({})
            return

        if self._price_worker is not None and self._price_worker.isRunning():
            return  # previous fetch still in flight
        self._price_worker = _PricesWorker(sorted(tickers))
        self._price_worker.prices_ready.connect(self._on_prices_ready)
        self._price_worker.start()

    def _on_prices_ready(self, prices: dict):
        self._prices = prices or {}
        # Refresh watchlist prices
        for row in range(self.watchlist_table.rowCount()):
            item = self.watchlist_table.item(row, 0)
            if item is None:
                continue
            px = self._prices.get(item.text())
            self.watchlist_table.setItem(
                row,
                1,
                QTableWidgetItem(f"${px:,.2f}" if px is not None else "—"),
            )
        self._refresh_positions_table()
        self._refresh_kpis()

    def _refresh_positions_table(self):
        self.positions_table.setRowCount(0)

        # Peso % (V2): market value de cada nombre sobre el valor total del book,
        # para que una sobre-concentración (MU 46.6%, AAPL 33.3%) salte a la vista.
        def _mv(pos) -> float:
            px_ = self._prices.get(pos.ticker)
            return float((px_ * pos.shares) if px_ is not None else pos.shares * pos.avg_cost)

        total_mv = sum(_mv(p) for p in self._positions)

        for p in self._positions:
            row = self.positions_table.rowCount()
            self.positions_table.insertRow(row)
            pos_ticker_item = QTableWidgetItem(p.ticker)
            apply_ticker_tooltip(pos_ticker_item, p.ticker)
            self.positions_table.setItem(row, 0, pos_ticker_item)
            self.positions_table.setItem(row, 1, QTableWidgetItem(self._format_shares(p.shares)))
            # Original entry price (fill_price of the first BUY that opened
            # this position). Falls back to "—" if we can't recover it.
            entry_px = self._entry_prices.get(p.ticker)
            entry_txt = f"${entry_px:,.4f}" if entry_px is not None else "—"
            self.positions_table.setItem(row, 2, QTableWidgetItem(entry_txt))
            # Running VWAP (avg_cost) — same as entry for single-fill positions.
            self.positions_table.setItem(row, 3, QTableWidgetItem(f"${p.avg_cost:,.4f}"))
            px = self._prices.get(p.ticker)
            price_txt = f"${px:,.2f}" if px is not None else "—"
            self.positions_table.setItem(row, 4, QTableWidgetItem(price_txt))
            mv = (px * p.shares) if px is not None else p.shares * p.avg_cost
            self.positions_table.setItem(row, 5, QTableWidgetItem(f"${mv:,.2f}"))
            # Peso % del nombre en el book (rojo si ≥ 30% — sobre-concentrado).
            weight = (mv / total_mv) if total_mv > 0 else 0.0
            weight_item = QTableWidgetItem(f"{weight * 100:.1f}%")
            if weight >= 0.30:
                weight_item.setForeground(QColor(PALETTE["red"]))
            self.positions_table.setItem(row, 6, weight_item)
            cost = p.shares * p.avg_cost
            pnl_usd = mv - cost
            pnl_pct = ((mv - cost) / cost * 100.0) if cost > 0 else 0.0
            color = PALETTE["positive"] if pnl_usd >= 0 else PALETTE["red"]
            pnl_usd_item = QTableWidgetItem(f"{'+' if pnl_usd >= 0 else '-'}${abs(pnl_usd):,.2f}")
            pnl_usd_item.setForeground(QColor(color))
            self.positions_table.setItem(row, 7, pnl_usd_item)
            pnl_item = QTableWidgetItem(f"{pnl_pct:+.2f}%")
            pnl_item.setForeground(QColor(color))
            self.positions_table.setItem(row, 8, pnl_item)

            # Comisión estimada de cierre — qué pagarías si cerrás ahora a
            # mercado. Usa el modelo IBKR activo (Tiered/Fixed) configurado
            # en Settings; si está en "legacy" devolvemos "—" para no
            # mezclar dos sistemas de costos en la misma celda.
            try:
                from config.settings_manager import settings as _settings

                plan = str(_settings.get("ibkr_commission_plan", "tiered")).lower()
            except Exception:
                plan = "tiered"
            if plan in ("tiered", "fixed") and px is not None and p.shares > 0:
                model = get_active_commission_model()
                est = model.cost(side="SELL", shares=float(p.shares), price=float(px))
                comm_txt = f"≈${est:,.2f}"
            else:
                comm_txt = "—"
            self.positions_table.setItem(row, 9, QTableWidgetItem(comm_txt))
        self._positions_header.setText(f"· {len(self._positions)}")

    def _refresh_kpis(self):
        if self._current_account_id is None:
            return
        try:
            eq = compute_equity(self._current_account_id, self._prices)
        except Exception as e:
            log.warning("KPI computation failed: %s", e)
            return
        acct = get_account(self._current_account_id)
        initial = float(acct.initial_capital) if acct else 0.0
        equity = float(eq.get("total_equity", 0.0))
        cash = float(eq.get("cash", 0.0))
        pv = float(eq.get("positions_value", 0.0))
        pnl = equity - initial
        pnl_pct = (pnl / initial * 100.0) if initial > 0 else 0.0
        pnl_color = PALETTE["positive"] if pnl >= 0 else PALETTE["red"]

        self.kpi_equity.set_value(f"${equity:,.2f}")
        self.kpi_cash.set_value(f"${cash:,.2f}")
        self.kpi_posvalue.set_value(f"${pv:,.2f}")
        self.kpi_pnl.set_value(f"{'+' if pnl >= 0 else ''}${pnl:,.2f}", color=pnl_color)
        self.kpi_pnl_pct.set_value(f"{pnl_pct:+.2f}%", color=pnl_color)
        self.kpi_positions.set_value(str(len(self._positions)))

    # ── Scheduler callbacks (invoked from MainWindow) ────────────────────────

    def on_scan_completed(self, result):
        """MainWindow forwards every scheduler completion here so we can refresh
        whenever OUR account has had a new scan."""
        try:
            if int(result.account_id) != int(self._current_account_id or -1):
                return
        except Exception:
            return
        self._reset_scan_button()
        self._refresh_orders()
        self._refresh_equity_curve()
        self._fetch_prices()

        # Surface a non-modal toast so the user sees the scan completed
        # without needing to read the status bar.
        try:
            from ui.feedback import Toast

            n_filled = getattr(result, "filled", 0)
            n_queued = getattr(result, "queued", 0)
            if n_filled or n_queued:
                kind, msg = "success", f"Scan OK — {n_filled} fills, {n_queued} en cola"
            else:
                kind, msg = "info", "Scan OK — sin nuevas órdenes"
            Toast.show(self, msg, kind=kind, timeout_ms=2500)
        except Exception:
            pass

    def on_scan_failed(self, account_id: int, error: str):
        if int(account_id) == int(self._current_account_id or -1):
            self._reset_scan_button()
            try:
                from ui.feedback import Toast

                Toast.show(self, f"Scan falló: {error}", kind="error", timeout_ms=4000)
            except Exception:
                pass

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        """Release matplotlib resources held by the equity chart."""
        with contextlib.suppress(Exception):
            self.equity_chart.cleanup()
        super().closeEvent(event)
