"""
Pestaña "Métricas" — efectividad real del engine de paper-trading.

Muestra, sin tocar el hot-path de trading (solo lectura):
  * KPI cards: P/L realizado, win rate, profit factor, expectancy, compras
    buenas/malas, y % de timing bueno (forward return > 0).
  * Gráfico de efectividad en el tiempo: P/L realizado acumulado + win-rate
    móvil, con líneas verticales en las fechas de los commits que cambian la
    lógica del engine (para ver si el modelo mejora con cada cambio).
  * Tablas: round-trips realizados, timing por compra, mix de salidas, churn.

El cálculo vive en ``analysis.metrics_panel`` (módulo puro); acá solo se arma la
UI y se corre el cálculo en un worker para no bloquear el hilo de Qt.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("QtAgg")
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analysis.metrics_panel import build_metrics, commit_markers
from config.logging_config import get_logger
from database.models import DB_PATH
from paper_trading.account import list_accounts
from ui.dashboard_charts import KpiCard, _apply_chart_rcparams
from ui.styles import CHART_STYLE, PALETTE
from ui.workers import BaseWorker

log = get_logger(__name__)

# Edad (segundos) tras la cual maybe_refresh() vuelve a calcular.
_STALE_SECONDS = 120
_REPO_DIR = Path(__file__).resolve().parents[1]
# Altura fija de las 4 tablas inferiores (alineadas en una fila a lo ancho).
_TABLE_HEIGHT = 460


def pick_initial_account_index(account_ids: list[int], preferred_id: int | None) -> int:
    """Índice de ``preferred_id`` en ``account_ids``; si no está (o es None), 0.

    Función pura para testear la selección inicial del combo sin un event loop Qt.
    """
    if preferred_id is not None:
        for i, aid in enumerate(account_ids):
            if aid == preferred_id:
                return i
    return 0


class MetricsWorker(BaseWorker):
    """Calcula el payload de métricas + marcadores de commits fuera del hilo UI."""

    result_ready = pyqtSignal(dict)

    def __init__(self, account_id: int = 1, parent=None):
        super().__init__(parent)
        self.account_id = account_id

    def do_work(self) -> dict:
        con = sqlite3.connect(f"file:{Path(DB_PATH).as_posix()}?mode=ro", uri=True)
        try:
            payload = build_metrics(con, self.account_id)
        finally:
            con.close()
        try:
            payload["commit_markers"] = commit_markers(_REPO_DIR)
        except Exception:  # nunca romper por git
            payload["commit_markers"] = []
        return payload

    def on_success(self, result: dict) -> None:
        self.result_ready.emit(result)


def _money(x: float | None) -> str:
    if x is None:
        return "—"
    return f"${x:,.0f}" if abs(x) >= 100 else f"${x:,.2f}"


def _pct(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "—"
    return (f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%")


class EffectivenessChart(QFrame):
    """P/L realizado acumulado + win-rate móvil, con marcadores de commits."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(340)
        _apply_chart_rcparams()
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(8)
        title = QLabel("Evolución del P/L acumulado (win-rate de contexto, no es el veredicto)")
        title.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 15px; font-weight: 700;")
        root.addWidget(title)
        sub = QLabel("Líneas punteadas = commits que cambian la lógica del engine")
        sub.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px;")
        root.addWidget(sub)
        self.figure = Figure(figsize=(7.4, 3.0), tight_layout=True)
        self.figure.patch.set_facecolor(CHART_STYLE["figure.facecolor"])
        self.canvas = FigureCanvas(self.figure)
        root.addWidget(self.canvas, stretch=1)

    def update_chart(self, timeline: list[dict], markers: list[dict]) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_facecolor(CHART_STYLE["axes.facecolor"])
        if not timeline:
            ax.text(0.5, 0.5, "Sin round-trips cerrados todavía",
                    ha="center", va="center", color=PALETTE["text3"], transform=ax.transAxes)
            self.canvas.draw()
            return
        days = [mdates.datestr2num(p["day"]) for p in timeline if p["day"]]
        cum = [p["cum_pnl"] for p in timeline if p["day"]]
        wr = [p["rolling_win_rate"] * 100 for p in timeline if p["day"]]
        if not days:
            self.canvas.draw()
            return
        line_color = PALETTE.get("accent", "#5B8DEF")
        ax.plot(days, cum, color=line_color, lw=2.0, label="P/L acumulado ($)")
        ax.axhline(0, color=PALETTE["text3"], lw=0.8, alpha=0.5)
        ax.fill_between(days, 0, cum, color=line_color, alpha=0.12)
        ax.set_ylabel("P/L acumulado ($)", color=line_color, fontsize=9)
        ax.tick_params(axis="y", labelcolor=line_color, labelsize=8)
        ax.tick_params(axis="x", labelsize=8)

        ax2 = ax.twinx()
        wr_color = PALETTE.get("positive", "#3FB68B")
        ax2.plot(days, wr, color=wr_color, lw=1.3, ls="--", alpha=0.85, label="Win-rate (%)")
        ax2.set_ylabel("Win-rate (%)", color=wr_color, fontsize=9)
        ax2.set_ylim(0, 100)
        ax2.tick_params(axis="y", labelcolor=wr_color, labelsize=8)

        # Marcadores de commits dentro del rango temporal de los trades.
        lo, hi = min(days), max(days)
        plotted = set()
        for mk in markers:
            day = mk.get("day")
            if not day:
                continue
            try:
                x = mdates.datestr2num(day)
            except (ValueError, TypeError):
                continue
            if x < lo or x > hi or day in plotted:
                continue
            plotted.add(day)
            ax.axvline(x, color=PALETTE.get("text2", "#9AA4B2"), lw=0.7, ls=":", alpha=0.55)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(0)
        self.figure.autofmt_xdate(rotation=0)
        self.canvas.draw()


class MetricsTab(QWidget):
    """Pestaña de métricas de funcionamiento del modelo."""

    def __init__(self, account_id: int = 1, parent=None):
        super().__init__(parent)
        self.account_id = account_id
        self._worker: MetricsWorker | None = None
        self._loaded_at: float | None = None
        self._build_ui()
        self._load_accounts()  # puebla el combo y fija la selección inicial

    # ── construcción ──────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        container = QWidget()
        scroll.setWidget(container)
        self.root = QVBoxLayout(container)
        self.root.setContentsMargins(24, 20, 24, 24)
        self.root.setSpacing(16)

        # ── selector de cuenta (paper sim) ──
        # Elige qué cuenta alimenta TODO el panel (KPIs, gráfico y tablas).
        # Independiente del combo del paper_tab (no se sincronizan).
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(QLabel("Cuenta:"))
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(260)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        header.addWidget(self.account_combo)
        header.addStretch()
        self.root.addLayout(header)

        self.status_lbl = QLabel("Cargando métricas…")
        self.status_lbl.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 12px;")
        self.root.addWidget(self.status_lbl)

        # ── KPI cards (2 filas de 4) ──
        self.cards: dict[str, KpiCard] = {}
        grid = QGridLayout()
        grid.setSpacing(14)
        defs = [
            ("pnl", "P/L REALIZADO", "spike",
             "Ganancia/pérdida total ya realizada de los round-trips cerrados "
             "(compras emparejadas con sus ventas por FIFO), neta de comisión y "
             "slippage. No incluye las posiciones todavía abiertas.\n"
             "'Sin peor nombre' = el mismo total excluyendo el ticker que más perdió, "
             "para ver cuánto pesa un solo nombre tóxico."),
            ("winrate", "WIN RATE", "area",
             "Porcentaje de round-trips cerrados con ganancia (P/L > 0). "
             "NO es el veredicto de efectividad: para un sistema asimétrico un "
             "win-rate < 50% es viable si el payoff ratio > 1. Mirá payoff, "
             "expectancy y profit factor para juzgar el sistema."),
            ("pf", "PROFIT FACTOR", "bar",
             "Ganancia bruta de los trades ganadores dividida por la pérdida bruta de "
             "los perdedores. Mayor a 1 significa que el sistema gana plata; 2 = ganás "
             "el doble de lo que perdés."),
            ("expectancy", "EXPECTANCY / TRADE", "area",
             "Ganancia promedio esperable por cada round-trip cerrado "
             "(P/L total ÷ cantidad de trades)."),
            ("payoff", "PAYOFF RATIO", "bar",
             "Ganancia media de los ganadores ÷ |pérdida media| de los perdedores "
             "(avg_win / |avg_loss|). Para un sistema asimétrico es el verdadero "
             "veredicto: con payoff > 1 un win-rate < 50% igual puede ser rentable."),
            ("exworst", "P/L SIN PEOR NOMBRE", "spike",
             "P/L realizado total excluyendo el ticker que más perdió. Muestra "
             "cuánto pesa un solo nombre tóxico sobre el resultado."),
            ("goodbad", "COMPRAS BUENAS / MALAS", "bar",
             "Cantidad de compras buenas (round-trip cerrado con P/L > 0) frente a las "
             "malas (P/L ≤ 0)."),
            ("sellquality", "VENTAS BUENAS / MALAS", "bar",
             "Calidad de la SALIDA por forward-return: venta BUENA = el precio NO "
             "subió en los 5 días hábiles siguientes (evitó una caída / preservó "
             "ganancia, fwd5 ≤ 0); venta MALA = siguió subiendo (vendiste temprano, "
             "'regret', fwd5 > 0). Convención INVERTIDA respecto de las compras."),
            ("timing", "TIMING BUENO (fwd5>0)", "area",
             "Porcentaje de compras cuyo precio SUBIÓ en los 5 días hábiles siguientes "
             "al BUY (forward return a 5 días > 0). Mide la calidad de la ENTRADA, "
             "aunque la posición siga abierta y todavía no se haya vendido."),
            ("costs", "COSTOS TOTALES", "bar",
             "Suma de comisión + slippage pagados en todos los round-trips cerrados."),
            ("expired", "BUYS NO LLENADOS", "spike",
             "Órdenes de compra que expiraron sin llegar a ejecutarse "
             "(la cuenta opera en modo manual)."),
        ]
        for i, (key, title, kind, tip) in enumerate(defs):
            card = KpiCard(title, "—", "", kind=kind)
            card.setToolTip(tip)
            self.cards[key] = card
            grid.addWidget(card, i // 4, i % 4)
        self.root.addLayout(grid)

        # ── gráfico de efectividad ──
        self.chart = EffectivenessChart()
        self.chart.setToolTip(
            "P/L realizado ACUMULADO (línea sólida, eje izquierdo) y win-rate MÓVIL "
            "(línea verde punteada, eje derecho) ordenados por fecha de venta.\n"
            "Las líneas verticales punteadas marcan los commits que cambian la lógica "
            "del engine (gates, stops, hysteresis, etc.), para ver si el modelo mejora "
            "después de cada cambio."
        )
        self.root.addWidget(self.chart)

        # ── tablas (4 columnas a lo ancho, misma altura) ──
        row = QHBoxLayout()
        row.setSpacing(14)
        self.exit_table = self._make_table(
            "Mix de salidas (P/L por tipo)",
            ["Tipo", "n", "P/L total", "P/L prom."],
            section_tip="Cómo rinde cada tipo de salida. signal_sell = el modelo decidió "
                        "vender; atr_stop = stop de pérdida por ATR; atr_trail = trailing "
                        "stop que sigue al máximo; atr_tp = take-profit.",
            col_tips=["Tipo de salida que cerró el trade", "Cantidad de round-trips",
                      "P/L total realizado de ese tipo", "P/L promedio por trade de ese tipo"],
            fixed_height=_TABLE_HEIGHT)
        self.ticker_table = self._make_table(
            "P/L por ticker (peores primero)",
            ["Ticker", "n", "P/L"],
            section_tip="P/L realizado acumulado por nombre, peores arriba. Sirve para "
                        "detectar si un solo ticker domina las pérdidas.",
            col_tips=["Símbolo", "Cantidad de round-trips cerrados", "P/L realizado acumulado"],
            fixed_height=_TABLE_HEIGHT)
        self.rt_table = self._make_table(
            "Round-trips realizados (compra buena = P/L > 0)",
            ["Ticker", "Compra", "Venta", "Hold", "Salida", "P/L", "P/L %"],
            section_tip="Cada operación cerrada (BUY emparejado con su SELL por FIFO), "
                        "de la más reciente a la más vieja.",
            col_tips=["Símbolo", "Fecha de compra", "Fecha de venta",
                      "Días de tenencia entre compra y venta",
                      "Tipo de salida que cerró el trade",
                      "Ganancia/pérdida neta de costos", "Ganancia/pérdida en porcentaje"],
            fixed_height=_TABLE_HEIGHT)
        self.timing_table = self._make_table(
            "Timing de compras (forward return tras el BUY)",
            ["Ticker", "Fecha", "Score", "fwd5", "fwd20"],
            section_tip="Calidad de la ENTRADA de cada compra: cuánto se movió el precio "
                        "después del BUY. Comparar Score con fwd5 muestra si la señal "
                        "predice el movimiento de corto plazo.",
            col_tips=["Símbolo", "Fecha de la compra",
                      "Signal score del modelo al comprar (0-1, mayor = más convicción)",
                      "Retorno del precio 5 días hábiles después del BUY",
                      "Retorno del precio 20 días hábiles después del BUY"],
            fixed_height=_TABLE_HEIGHT)
        for t in (self.exit_table, self.ticker_table, self.rt_table, self.timing_table):
            row.addWidget(t["frame"], 1)
        self.root.addLayout(row)

        # ── 2ª fila de tablas: timing de ventas (calidad de la SALIDA, MET2) ──
        self.sell_timing_table = self._make_table(
            "Timing de ventas (forward return tras el SELL)",
            ["Ticker", "Fecha", "Score", "Salida", "fwd5", "fwd20"],
            section_tip="Calidad de la SALIDA: cuánto se movió el precio DESPUÉS del "
                        "SELL. Venta buena = el precio no subió (fwd5 ≤ 0, verde); mala = "
                        "siguió subiendo (fwd5 > 0, rojo, 'regret'). Color INVERTIDO "
                        "respecto de las compras. Un atr_stop con regret igual hizo su "
                        "trabajo (protección de capital), no es señal para apagar stops.",
            col_tips=["Símbolo", "Fecha de la venta",
                      "Signal score del modelo al vender",
                      "Tipo de salida (signal_sell / atr_stop / atr_trail / atr_tp)",
                      "Retorno del precio 5 días hábiles tras el SELL (negativo = venta buena)",
                      "Retorno del precio 20 días hábiles tras el SELL"],
            fixed_height=_TABLE_HEIGHT)
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        row2.addWidget(self.sell_timing_table["frame"], 1)
        self.root.addLayout(row2)

    def _make_table(self, title: str, headers: list[str], *,
                    section_tip: str | None = None,
                    col_tips: list[str] | None = None,
                    fixed_height: int | None = None) -> dict:
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        lbl = QLabel(title)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {PALETTE['text1']}; font-size: 13px; font-weight: 700;")
        if section_tip:
            lbl.setToolTip(section_tip)
        lay.addWidget(lbl)
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        if fixed_height is not None:
            table.setProperty("_fixed_height", True)
            table.setMinimumHeight(fixed_height)
            table.setMaximumHeight(fixed_height)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            table.horizontalHeader().setStretchLastSection(False)
        if col_tips:
            for c, tip in enumerate(col_tips):
                item = table.horizontalHeaderItem(c)
                if item is not None:
                    item.setToolTip(tip)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.horizontalHeader().setStretchLastSection(fixed_height is None)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if section_tip:
            frame.setToolTip(section_tip)
        lay.addWidget(table)
        return {"frame": frame, "table": table}

    # ── selector de cuenta ────────────────────────────────────────────────────
    def _load_accounts(self):
        """Puebla el combo con TODAS las cuentas y fija la selección inicial.

        Replica el patrón del paper_tab pero sin disparar refresh acá: el
        primer cálculo lo hace ``maybe_refresh()`` al mostrarse la pestaña.
        """
        accounts = list_accounts()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        if not accounts:
            self.account_combo.addItem("— No hay cuentas —", userData=None)
        else:
            for a in accounts:
                label = f"{a.name}   ·   {a.strategy}/{a.mode}"
                if not a.is_active:
                    label += "  (inactiva)"
                self.account_combo.addItem(label, userData=int(a.id))
            idx = pick_initial_account_index([int(a.id) for a in accounts], self.account_id)
            self.account_combo.setCurrentIndex(idx)
            data = self.account_combo.itemData(idx)
            if data is not None:
                self.account_id = int(data)
        self.account_combo.blockSignals(False)

    def _on_account_changed(self, _idx: int):
        data = self.account_combo.currentData()
        if data is None:
            return
        self.account_id = int(data)
        # Recalcular YA para esta cuenta, sin esperar el stale de 120s.
        self.invalidate()
        self.refresh()

    # ── refresh lifecycle (patrón NewsTab) ────────────────────────────────────
    def maybe_refresh(self):
        import time
        if self._loaded_at is None or (time.time() - self._loaded_at) > _STALE_SECONDS:
            self.refresh()

    def invalidate(self):
        self._loaded_at = None

    def refresh(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.status_lbl.setText("Calculando métricas…")
        self._worker = MetricsWorker(self.account_id, self)
        self._worker.result_ready.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ── slots ──────────────────────────────────────────────────────────────────
    def _on_error(self, exc: Exception):
        log.warning("metrics refresh failed: %s", exc)
        self.status_lbl.setText(f"Error al calcular métricas: {exc}")

    def _on_result(self, m: dict):
        import time
        self._loaded_at = time.time()
        r = m["realized"]
        t = m["timing"]
        self.status_lbl.setText(
            f"{r['n_round_trips']} round-trips cerrados · "
            f"{len(m['open_positions'])} posiciones abiertas · "
            f"generado {m['generated_at'][:19].replace('T', ' ')}"
        )
        # KPI cards
        self.cards["pnl"].set_value(_money(r["total_pnl"]),
                                    f"sin peor nombre: {_money(r['pnl_ex_worst'])}",
                                    r["total_pnl"] > 0)
        # Win-rate reencuadrado: NO es el veredicto de efectividad (color neutro),
        # el titular real es el payoff ratio (sistema asimétrico).
        self.cards["winrate"].set_value(_pct(r["win_rate"]),
                                        "no es el veredicto — mirá payoff", None)
        pf = r["profit_factor"]
        self.cards["pf"].set_value(f"{pf:.2f}" if pf else "—",
                                   "ganancia/pérdida bruta", (pf or 0) >= 1.0)
        self.cards["expectancy"].set_value(_money(r["expectancy"]),
                                           f"avg win {_money(r['avg_win'])}", r["expectancy"] > 0)
        payoff = r["payoff_ratio"]
        self.cards["payoff"].set_value(f"{payoff:.2f}×" if payoff else "—",
                                       "avg win / |avg loss|", (payoff or 0) >= 1.0)
        self.cards["exworst"].set_value(
            _money(r["pnl_ex_worst"]),
            f"peor: {r['worst_ticker']['ticker']}" if r["worst_ticker"] else "",
            r["pnl_ex_worst"] > 0)
        self.cards["goodbad"].set_value(f"{r['n_wins']} / {r['n_losses']}",
                                        "buenas / malas", r["n_wins"] >= r["n_losses"])
        st = m["sell_timing"]
        self.cards["sellquality"].set_value(
            f"{st['good5']} / {st['n5'] - st['good5']}",
            f"mean fwd5 {_pct(st['mean5'], signed=True)} (regret)",
            st["good5_pct"] >= 0.5)
        self.cards["timing"].set_value(_pct(t["good5_pct"]),
                                       f"mean fwd5 {_pct(t['mean5'], signed=True)}",
                                       t["good5_pct"] >= 0.5)
        self.cards["costs"].set_value(_money(r["total_costs"]), "comisión + slippage", False)
        self.cards["expired"].set_value(str(m["expired_buys"]["n"]),
                                        "órdenes expiradas", m["expired_buys"]["n"] == 0)
        # ── sparklines ──
        # Cada card lleva un mini-gráfico abajo. Le damos serie a las que tienen
        # una secuencia con sentido y ocultamos el recuadro en las que son un
        # número suelto (profit factor, costos, expirados) para que no quede vacío.
        timeline = m["timeline"]
        cum = [p["cum_pnl"] for p in timeline]
        wr_series = [p["rolling_win_rate"] * 100 for p in timeline]
        # P/L por trade en orden cronológico de venta (para goodbad: +/- por trade).
        rts_ordered = sorted(r["round_trips"], key=lambda x: (x["sell_day"] or ""))
        pnl_seq = [x["pnl"] for x in rts_ordered]
        # fwd5 por compra (timing), en orden y salteando los None.
        fwd5_seq = [b["fwd5"] * 100 for b in sorted(t["per_buy"], key=lambda x: (x["day"] or ""))
                    if b["fwd5"] is not None]
        sell_fwd5_seq = [s["fwd5"] * 100 for s in sorted(st["per_sell"], key=lambda x: (x["day"] or ""))
                         if s["fwd5"] is not None]

        def _spark(key: str, series: list[float]):
            card = self.cards[key]
            if series:
                card.set_series(series)
            else:
                card.spark.hide()

        _spark("pnl", cum)
        _spark("winrate", wr_series)
        _spark("expectancy", pnl_seq)
        _spark("goodbad", pnl_seq)
        _spark("timing", fwd5_seq)
        _spark("sellquality", sell_fwd5_seq)
        # Estas son métricas escalares: ocultamos el sparkline vacío.
        for key in ("pf", "payoff", "exworst", "costs", "expired"):
            self.cards[key].spark.hide()

        # chart
        self.chart.update_chart(m["timeline"], m.get("commit_markers", []))

        # tablas
        self._fill_exit_table(r["by_exit_kind"])
        self._fill_ticker_table(r["per_ticker"])
        self._fill_rt_table(r["round_trips"])
        self._fill_timing_table(t["per_buy"])
        self._fill_sell_timing_table(st["per_sell"])

    # ── llenado de tablas ──────────────────────────────────────────────────────
    @staticmethod
    def _autosize(table: QTableWidget, max_rows: int = 16) -> None:
        """Ajusta la altura de la tabla a su contenido (hasta ``max_rows`` filas).

        Sin esto la tabla queda con la altura mínima de Qt y solo se ve el header.
        Si hay más de ``max_rows`` filas, deja scroll interno.

        Las tablas con altura fija (``_fixed_height``) no se tocan: solo se ajustan
        los anchos de columna al contenido y se deja scroll interno.
        """
        if table.property("_fixed_height"):
            table.resizeColumnsToContents()
            return
        table.resizeRowsToContents()
        rows = table.rowCount()
        header_h = table.horizontalHeader().height()
        row_h = table.verticalHeader().defaultSectionSize() if rows else 0
        visible = min(rows, max_rows) if rows else 0
        height = header_h + visible * row_h + 4
        table.setMinimumHeight(max(height, header_h + 8))
        table.setMaximumHeight(height if rows <= max_rows else 16777215)

    @staticmethod
    def _cell(text: str, positive: bool | None = None, align_right: bool = False):
        it = QTableWidgetItem(text)
        if align_right:
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if positive is True:
            it.setForeground(Qt.GlobalColor.green)
        elif positive is False:
            it.setForeground(Qt.GlobalColor.red)
        return it

    def _fill_exit_table(self, by_kind: dict):
        tbl = self.exit_table["table"]
        rows = sorted(by_kind.items(), key=lambda kv: kv[1]["pnl"], reverse=True)
        tbl.setRowCount(len(rows))
        for i, (kind, v) in enumerate(rows):
            tbl.setItem(i, 0, self._cell(kind))
            tbl.setItem(i, 1, self._cell(str(v["n"]), align_right=True))
            tbl.setItem(i, 2, self._cell(_money(v["pnl"]), v["pnl"] > 0, True))
            tbl.setItem(i, 3, self._cell(_money(v["avg"]), v["avg"] > 0, True))
        self._autosize(tbl)

    def _fill_ticker_table(self, per_ticker: list[dict]):
        tbl = self.ticker_table["table"]
        tbl.setRowCount(len(per_ticker))
        for i, row in enumerate(per_ticker):
            tbl.setItem(i, 0, self._cell(row["ticker"]))
            tbl.setItem(i, 1, self._cell(str(row["n"]), align_right=True))
            tbl.setItem(i, 2, self._cell(_money(row["pnl"]), row["pnl"] > 0, True))
        self._autosize(tbl)

    def _fill_rt_table(self, rts: list[dict]):
        tbl = self.rt_table["table"]
        ordered = sorted(rts, key=lambda r: (r["sell_day"] or ""), reverse=True)
        tbl.setRowCount(len(ordered))
        for i, r in enumerate(ordered):
            tbl.setItem(i, 0, self._cell(r["ticker"]))
            tbl.setItem(i, 1, self._cell(r["buy_day"] or "—"))
            tbl.setItem(i, 2, self._cell(r["sell_day"] or "—"))
            tbl.setItem(i, 3, self._cell(f"{r['hold_days']}d", align_right=True))
            tbl.setItem(i, 4, self._cell(r["exit_kind"]))
            tbl.setItem(i, 5, self._cell(_money(r["pnl"]), r["pnl"] > 0, True))
            tbl.setItem(i, 6, self._cell(_pct(r["pnl_pct"], signed=True), r["pnl"] > 0, True))
        self._autosize(tbl)

    def _fill_timing_table(self, per_buy: list[dict]):
        tbl = self.timing_table["table"]
        ordered = sorted(per_buy, key=lambda r: (r["day"] or ""), reverse=True)
        tbl.setRowCount(len(ordered))
        for i, r in enumerate(ordered):
            sc = r["score"]
            tbl.setItem(i, 0, self._cell(r["ticker"]))
            tbl.setItem(i, 1, self._cell(r["day"] or "—"))
            tbl.setItem(i, 2, self._cell(f"{sc:.2f}" if sc is not None else "—", align_right=True))
            f5 = r["fwd5"]
            f20 = r["fwd20"]
            tbl.setItem(i, 3, self._cell(_pct(f5, signed=True) if f5 is not None else "—",
                                         (f5 > 0) if f5 is not None else None, True))
            tbl.setItem(i, 4, self._cell(_pct(f20, signed=True) if f20 is not None else "—",
                                         (f20 > 0) if f20 is not None else None, True))
        self._autosize(tbl)

    def _fill_sell_timing_table(self, per_sell: list[dict]):
        # Mirror de _fill_timing_table pero con la convención de color INVERTIDA:
        # verde cuando fwd5 ≤ 0 (venta buena) y rojo cuando fwd5 > 0 (regret).
        tbl = self.sell_timing_table["table"]
        ordered = sorted(per_sell, key=lambda r: (r["day"] or ""), reverse=True)
        tbl.setRowCount(len(ordered))
        for i, r in enumerate(ordered):
            sc = r["score"]
            tbl.setItem(i, 0, self._cell(r["ticker"]))
            tbl.setItem(i, 1, self._cell(r["day"] or "—"))
            tbl.setItem(i, 2, self._cell(f"{sc:.2f}" if sc is not None else "—", align_right=True))
            tbl.setItem(i, 3, self._cell(r["exit_kind"]))
            f5 = r["fwd5"]
            f20 = r["fwd20"]
            tbl.setItem(i, 4, self._cell(_pct(f5, signed=True) if f5 is not None else "—",
                                         (f5 <= 0) if f5 is not None else None, True))
            tbl.setItem(i, 5, self._cell(_pct(f20, signed=True) if f20 is not None else "—",
                                         (f20 <= 0) if f20 is not None else None, True))
        self._autosize(tbl)
