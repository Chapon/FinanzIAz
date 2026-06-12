"""
Noticias tab — resumen diario de las noticias más relevantes.

Lee el output del pipeline catalyst que ya corre solo todos los días
(harvest T-CAT-1 → clasificación T-CAT-2) y lo rankea con el Impact Score
(T-CAT-4). Arriba muestra un briefing narrativo generado por qwen local
(mismo servidor Ollama del classifier); si Ollama no está corriendo cae a un
resumen determinístico. Solo lectura — nunca toca el hot-path de trading.

Layout
------
  ┌─ Header ─────────────────────────────────────────────────────────────┐
  │  Ventana (días) · Briefing IA ☑ · Actualizar · estado                │
  ├─ Briefing card ──────────────────────────────────────────────────────┤
  ├─ Tabla ──────────────────────────────────────────────────────────────┤
  │  Fecha · Ticker · Impacto · Categoría · Sentimiento · Conf · Fuente  │
  │        · Titular                                                     │
  └──────────────────────────────────────────────────────────────────────┘

Doble click en una fila → abre la noticia en el navegador (si tiene URL).
La lista aparece apenas termina el ranking; el briefing llega después sin
bloquear (dos señales del mismo worker).
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFontMetrics
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analysis.news_digest import (
    DigestItem,
    classify_missing,
    default_window,
    fallback_briefing,
    fetch_news_window,
    make_ollama_briefer,
    rank_news,
)
from config.logging_config import get_logger
from ui.styles import PALETTE
from ui.workers import BaseWorker

log = get_logger(__name__)

# Refrescar solo automáticamente si los datos tienen más de este age (min).
AUTO_REFRESH_MINUTES = 30

SENTIMENT_COLORS = {"positive": "#4ade80", "negative": "#fb7185", "neutral": "#94a3b8"}

COLUMNS: list[tuple[str, str]] = [
    ("Fecha", "Fecha que declara la fuente (— si la fuente no la trae)."),
    ("Ticker", "Símbolo al que la noticia fue asociada por el harvester."),
    ("Impacto",
     "Impact Score heurístico (T-CAT-4): dirección × magnitud × confianza.\n"
     "Signo = dirección esperada del precio; |valor| = convicción.\n"
     "Sin historial de reacción usa priors por categoría — orientativo, no señal."),
    ("Categoría", "Una de las 17 categorías de la taxonomía catalyst (T-CAT-2)."),
    ("Sentimiento", "Clasificado por qwen local o heurística, desde la óptica del ticker."),
    ("Conf", "Confianza del clasificador (0-1). 0.90 = item-code SEC estructurado."),
    ("Fuente", "sec_8k = filing EDGAR · yahoo_rss / yfinance = headlines."),
    ("Titular", "Doble click para abrir la noticia en el navegador."),
]


class _SortItem(QTableWidgetItem):
    """Item que ordena por el valor crudo (UserRole) si ambos lo tienen.

    El sort default de QTableWidgetItem compara el texto visible, lo que rompe
    columnas numéricas con signo ("-0.72" > "+0.85" lexicográficamente). Acá la
    columna Impacto ordena por |impacto| (lo material primero, sin importar signo).
    """

    def __lt__(self, other):
        a = self.data(Qt.ItemDataRole.UserRole)
        b = other.data(Qt.ItemDataRole.UserRole)
        if a is not None and b is not None:
            try:
                return float(a) < float(b)
            except (TypeError, ValueError):
                pass
        return super().__lt__(other)


class NewsDigestWorker(BaseWorker):
    """Carga la ventana, rankea, y (opcional) genera el briefing con qwen.

    Dos señales para no bloquear la UI con el LLM:
      ``rows_ready(list[DigestItem])``  — apenas está el ranking (rápido, local).
      ``briefing_ready(str)``           — cuando el briefing está listo (LLM o fallback).
    """

    rows_ready = pyqtSignal(object)   # list[DigestItem]
    briefing_ready = pyqtSignal(str)

    def __init__(self, days: int, use_llm: bool, parent=None):
        super().__init__(parent)
        self.days = days
        self.use_llm = use_llm

    def do_work(self):
        since, until = default_window(self.days)
        rows = fetch_news_window(since, until=until)
        # Filas que el classifier nocturno todavía no tocó → heurística al
        # vuelo (display-only). Sin esto, todo sale Otro/Neutral/impacto 0.
        rows = classify_missing(rows)
        items = rank_news(rows)
        self.rows_ready.emit(items)

        if self.is_cancelled():
            return items

        briefing: str | None = None
        if self.use_llm and items:
            briefing = make_ollama_briefer()(items)  # None si Ollama no responde
        if briefing is None:
            briefing = fallback_briefing(items)
        self.briefing_ready.emit(briefing)
        return items


class NewsTab(QWidget):
    """Resumen diario de noticias rankeadas por impact score + briefing IA."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: NewsDigestWorker | None = None
        self._items: list[DigestItem] = []
        self._last_loaded: datetime | None = None
        self._build_ui()

    # ── UI build ──────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        title = QLabel("Noticias — resumen diario")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #e2e8f0;")
        header.addWidget(title)
        header.addStretch()

        days_lbl = QLabel("Ventana (días):")
        days_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header.addWidget(days_lbl)
        self.days_input = QSpinBox()
        self.days_input.setRange(1, 14)
        self.days_input.setValue(1)
        self.days_input.setToolTip(
            "Cuántos días hacia atrás incluir. 1 = últimas 24 h.\n"
            "Tip: después de un finde, 3 días cubre lo acumulado."
        )
        header.addWidget(self.days_input)

        self.llm_check = QCheckBox("Briefing IA (qwen)")
        self.llm_check.setChecked(True)
        self.llm_check.setToolTip(
            "Genera un párrafo narrativo con qwen local (Ollama).\n"
            "Si Ollama no está corriendo, se muestra un resumen automático."
        )
        self.llm_check.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header.addWidget(self.llm_check)

        self.refresh_btn = QPushButton("Actualizar")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.setMinimumHeight(36)
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)

        root.addLayout(header)

        self.status_lbl = QLabel(
            "Noticias del harvest diario, rankeadas por impacto esperado (T-CAT-4). "
            "Solo lectura: nada de esto opera por sí solo."
        )
        self.status_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        # Briefing card
        self.briefing_card = QFrame()
        self.briefing_card.setStyleSheet(
            f"background-color: {PALETTE['elevated']}; "
            f"border: 1px solid {PALETTE['border_lt']}; border-radius: 10px;"
        )
        card_layout = QVBoxLayout(self.briefing_card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(6)
        brief_title = QLabel("📰 Briefing del día")
        brief_title.setStyleSheet(
            f"color: {PALETTE['text1']}; font-weight: 700; font-size: 13px; background: transparent;"
        )
        self.briefing_lbl = QLabel("Generando briefing…")
        self.briefing_lbl.setWordWrap(True)
        self.briefing_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.briefing_lbl.setStyleSheet(
            f"color: {PALETTE['text1']}; font-size: 13px; line-height: 1.5; background: transparent;"
        )
        card_layout.addWidget(brief_title)
        card_layout.addWidget(self.briefing_lbl)
        self.briefing_card.setVisible(False)
        root.addWidget(self.briefing_card)

        # Tabla
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._on_row_double_clicked)

        for i, (label, tooltip) in enumerate(COLUMNS):
            header_item = QTableWidgetItem(label)
            header_item.setToolTip(tooltip)
            self.table.setHorizontalHeaderItem(i, header_item)

        header_widget = self.table.horizontalHeader()
        header_widget.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header_widget.setStretchLastSection(True)  # Titular absorbe el resto
        header_widget.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header_widget.setMinimumSectionSize(50)

        root.addWidget(self.table, stretch=1)
        QTimer.singleShot(0, self._auto_fit_columns)

    # ── Refresh lifecycle ─────────────────────────────────────────────────
    def invalidate(self):
        """Marca los datos como viejos: la próxima navegación a la pestaña
        re-carga sí o sí (lo usa el refresh diario del scheduler)."""
        self._last_loaded = None

    def maybe_refresh(self):
        """Llamado al navegar a la pestaña: refresca si nunca cargó o está viejo."""
        if self._last_loaded is None:
            self.refresh()
            return
        age_min = (datetime.utcnow() - self._last_loaded).total_seconds() / 60.0
        if age_min >= AUTO_REFRESH_MINUTES:
            self.refresh()

    def refresh(self):
        if self._worker and self._worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.status_lbl.setText("Cargando y rankeando noticias…")
        self.briefing_card.setVisible(False)

        self._worker = NewsDigestWorker(
            days=self.days_input.value(),
            use_llm=self.llm_check.isChecked(),
            parent=self,
        )
        self._worker.rows_ready.connect(self._on_rows_ready)
        self._worker.briefing_ready.connect(self._on_briefing_ready)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_rows_ready(self, items: list):
        self._items = items
        self._last_loaded = datetime.utcnow()
        self._populate_table(items)
        if items:
            self.status_lbl.setText(
                f"{len(items)} noticias en los últimos {self.days_input.value()} día(s), "
                f"rankeadas por impacto esperado · doble click abre la noticia."
            )
            self.briefing_lbl.setText("Generando briefing…")
            self.briefing_card.setVisible(True)
        else:
            self.status_lbl.setText(
                "Sin noticias en la ventana. ¿Corrió el harvest diario? "
                "Probá ampliar la ventana de días."
            )

    def _on_briefing_ready(self, text: str):
        self.briefing_lbl.setText(text)
        self.briefing_card.setVisible(bool(self._items))

    def _on_error(self, exc: Exception):
        self.status_lbl.setText(f"❌ Error cargando noticias: {exc}")
        log.exception("NewsTab refresh failed: %s", exc)

    def _on_finished(self):
        self.refresh_btn.setEnabled(True)

    # ── Render ────────────────────────────────────────────────────────────
    def _populate_table(self, items: list):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))

        for r_idx, it in enumerate(items):
            when = it.published_at.strftime("%m-%d %H:%M") if it.published_at else "—"
            impact_color = (
                "#4ade80" if it.impact > 0 else ("#fb7185" if it.impact < 0 else None)
            )
            conf = (
                f"{it.classifier_confidence:.2f}"
                if it.classifier_confidence is not None
                else "—"
            )
            cells = [
                (when, None),
                (it.ticker, None),
                (f"{it.impact:+.2f}", impact_color),
                (it.event_label, None),
                (it.sentiment_label, SENTIMENT_COLORS.get(it.sentiment or "neutral")),
                (conf, None),
                (it.source, None),
                (it.title, None),
            ]
            for c_idx, (text, color) in enumerate(cells):
                item = _SortItem()
                raw = self._raw_for_col(it, c_idx)
                if raw is not None:
                    item.setData(Qt.ItemDataRole.UserRole, raw)
                item.setText(text)
                if color:
                    item.setForeground(QColor(color))
                if c_idx in (2, 5):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if c_idx == 7:
                    item.setToolTip(it.title + (f"\n{it.url}" if it.url else ""))
                    # guardamos la URL en la celda del titular para el doble click
                    item.setData(Qt.ItemDataRole.UserRole + 1, it.url or "")
                self.table.setItem(r_idx, c_idx, item)

        self.table.setSortingEnabled(True)
        self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        self._auto_fit_columns()

    @staticmethod
    def _raw_for_col(it: DigestItem, col_idx: int):
        if col_idx == 0:
            return it.published_at.timestamp() if it.published_at else 0.0
        if col_idx == 2:
            # orden por |impacto|: lo material primero, sin importar el signo
            return abs(it.impact)
        if col_idx == 5:
            return it.classifier_confidence if it.classifier_confidence is not None else -1.0
        return None

    def _auto_fit_columns(self):
        """Mismo approach que LeadsTab: max(header bold, contenido) + padding."""
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        bold_font = header.font()
        bold_font.setBold(True)
        fm = QFontMetrics(bold_font)
        header_pad = 44
        cell_pad = 16
        # No tocamos la última columna (Titular): stretch la absorbe.
        for i, (label, _tooltip) in enumerate(COLUMNS[:-1]):
            header_min = fm.horizontalAdvance(label) + header_pad
            current = self.table.columnWidth(i)
            self.table.setColumnWidth(i, max(current + cell_pad, header_min))

    def _on_row_double_clicked(self, index):
        title_item = self.table.item(index.row(), len(COLUMNS) - 1)
        if not title_item:
            return
        url = title_item.data(Qt.ItemDataRole.UserRole + 1) or ""
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            self.status_lbl.setText("Esa noticia no trae URL (filing/feed sin link).")
