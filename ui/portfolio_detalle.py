"""El desplegable de cada ticker en Portfolio: Lotes, Transacciones y Dividendos (tarea 325).

Pedido de Chapa (2026-10-07): *«que el portfolio represente las compras y ventas en la misma
forma que lo hace Yahoo Finance, con menús desplegables por ticker»*. Las cuentas salen del
libro FIFO de ``database.lotes`` (tarea 324); acá sólo se arman las filas —con funciones puras,
para poder testearlas sin Qt— y se pintan. Es de **lectura**: editar un lote o una transacción
desde acá no está, a diferencia de Yahoo.
"""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QTabWidget

from ui.styles import PALETTE
from ui.widgets import table_header, table_vheader

# Lo que suma el estilo global de las tablas (ui/styles.py, QTableWidget::item y
# QHeaderView::section): padding 10px 14px, encabezado de 11 px en negrita, en mayúsculas y con
# 0,8 px entre letras. Más un margen, para que el texto no quede pegado al borde.
_PAD_H = 2 * 14 + 12
_PAD_V = 2 * 10 + 4
_HEADER_PX = 11
_CELDA_PX = 13  # `QWidget { font-size: 13px }` del tema; la tabla recién creada todavía no lo tiene
_FAMILIA = "Segoe UI"
_LETTER_SPACING = 1

COLS_LOTES = [
    "Fecha",
    "Acciones",
    "Costo/acción",
    "Costo total",
    "Valor",
    "Ganancia",
    "Ganancia %",
    "Anual %",
]
COLS_TX = ["Fecha", "Tipo", "Acciones", "Precio", "Comisión", "Total", "Realizada", "Realizada %", "Nota"]
COLS_DIV = ["Ex-date", "$/acción", "Acciones", "Cobrado"]


def _anual(ganancia_pct: float, desde: date, hoy: date) -> float | None:
    """La ganancia llevada a un año. ``None`` con menos de un año: anualizar 3 días inventa ±1000%."""
    dias = (hoy - desde).days
    if dias < 365:
        return None
    return ((1 + ganancia_pct / 100.0) ** (365.0 / dias) - 1) * 100.0


def filas_lotes(libro, precio: float | None, hoy: date | None = None) -> list[dict]:
    """Un dict por lote abierto. Sin precio, valor y ganancia quedan en ``None`` (no al costo)."""
    hoy = hoy or date.today()
    out = []
    for lo in libro.lotes:
        costo = lo.cantidad * lo.precio
        valor = lo.cantidad * precio if precio else None
        gan = (valor - costo) if valor is not None else None
        pct = (gan / costo * 100.0) if gan is not None and costo > 0 else None
        out.append(
            {
                "fecha": lo.fecha,
                "acciones": lo.cantidad,
                "costo_accion": lo.precio,
                "costo_total": costo,
                "valor": valor,
                "ganancia": gan,
                "ganancia_pct": pct,
                "anual_pct": _anual(pct, lo.fecha, hoy) if pct is not None else None,
            }
        )
    return out


def filas_transacciones(libro) -> list[dict]:
    """Un dict por transacción, de la más nueva a la más vieja (como Yahoo)."""
    out = []
    for f in libro.filas:
        m = f.mov
        out.append(
            {
                "fecha": m.fecha,
                "tipo": "Compra" if m.tipo == "BUY" else "Venta",
                "acciones": m.cantidad,
                "precio": m.precio,
                "comision": m.comision,
                "total": m.cantidad * m.precio,
                "realizada": f.realizado,
                "realizada_pct": f.realizado_pct,
                "nota": m.nota,
            }
        )
    return sorted(out, key=lambda r: r["fecha"], reverse=True)


# ── Pintado ──────────────────────────────────────────────────────────────────


def _dinero(x: float | None, signo: bool = False) -> str:
    if x is None:
        return "—"
    return f"{'+' if signo and x >= 0 else ''}${x:,.2f}"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:+.2f}%"


def _tabla(columnas: list[str], filas: list[list], colores: list[list] | None = None) -> QTableWidget:
    t = QTableWidget(len(filas), len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    t.setShowGrid(False)
    table_vheader(t).setVisible(False)
    for r, fila in enumerate(filas):
        for c, texto in enumerate(fila):
            it = QTableWidgetItem(str(texto))
            izq = c == 0 or columnas[c] in ("Tipo", "Nota")
            it.setTextAlignment(
                (Qt.AlignmentFlag.AlignLeft if izq else Qt.AlignmentFlag.AlignRight)
                | Qt.AlignmentFlag.AlignVCenter
            )
            color = colores[r][c] if colores else None
            if color:
                it.setForeground(QColor(color))
            t.setItem(r, c, it)
    # Anchos y altos a mano, con el padding del estilo global incluido. ``resizeColumnsToContents``
    # mide acá, antes de que la tabla tome el stylesheet de la app (padding 10px 14px por celda y
    # encabezado, encabezados en mayúscula), así que dejaba cada columna 28 px corta y la tabla
    # 20 px baja por fila: no se leía nada (captura de Chapa, 2026-10-07).
    f_celda = QFont(_FAMILIA)
    f_celda.setPixelSize(_CELDA_PX)
    fm_celda = QFontMetrics(f_celda)
    f_header = QFont(_FAMILIA)
    f_header.setPixelSize(_HEADER_PX)
    f_header.setBold(True)
    fm_header = QFontMetrics(f_header)
    hdr = table_header(t)
    hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for c, nombre in enumerate(columnas):
        ancho_header = fm_header.horizontalAdvance(nombre.upper()) + _LETTER_SPACING * len(nombre)
        ancho_celdas = max((fm_celda.horizontalAdvance(str(f[c])) for f in filas), default=0)
        t.setColumnWidth(c, max(ancho_header, ancho_celdas) + _PAD_H)
    # Sólo se estira la nota: estirar un número lo manda al otro extremo de la pantalla.
    hdr.setStretchLastSection(columnas[-1] == "Nota")
    alto_fila = fm_celda.height() + _PAD_V
    alto_header = fm_header.height() + _PAD_V
    vh = table_vheader(t)
    vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    vh.setDefaultSectionSize(alto_fila)
    hdr.setFixedHeight(alto_header)
    t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    t.setFixedHeight(alto_header + alto_fila * len(filas) + 4)
    return t


def _signo(x: float | None) -> str | None:
    if x is None:
        return None
    return PALETTE["positive"] if x >= 0 else PALETTE["red"]


def _vacio(texto: str) -> QLabel:
    lb = QLabel(texto)
    lb.setStyleSheet(f"color: {PALETTE['text3']}; padding: 10px;")
    return lb


class DetallePosicion(QTabWidget):
    """Las tres pestañas de un ticker. ``dividendos`` es ``dividendos_detalle`` o ``None`` (cargando)."""

    def __init__(self, libro, precio: float | None, dividendos: list | None, parent=None):
        super().__init__(parent)
        self.setDocumentMode(True)

        lotes = filas_lotes(libro, precio)
        if lotes:
            self.addTab(
                _tabla(
                    COLS_LOTES,
                    [
                        [
                            f["fecha"].strftime("%d/%m/%Y"),
                            f"{f['acciones']:,.4g}",
                            _dinero(f["costo_accion"]),
                            _dinero(f["costo_total"]),
                            _dinero(f["valor"]),
                            _dinero(f["ganancia"], signo=True),
                            _pct(f["ganancia_pct"]),
                            _pct(f["anual_pct"]),
                        ]
                        for f in lotes
                    ],
                    [[None] * 5 + [_signo(f["ganancia"])] * 3 for f in lotes],
                ),
                "Lotes",
            )
        else:
            self.addTab(_vacio("Sin lotes abiertos: la posición está cerrada."), "Lotes")

        txs = filas_transacciones(libro)
        if txs:
            self.addTab(
                _tabla(
                    COLS_TX,
                    [
                        [
                            f["fecha"].strftime("%d/%m/%Y"),
                            f["tipo"],
                            f"{f['acciones']:,.6g}",
                            _dinero(f["precio"]),
                            _dinero(f["comision"]),
                            _dinero(f["total"]),
                            _dinero(f["realizada"], signo=True),
                            _pct(f["realizada_pct"]),
                            f["nota"] or "",
                        ]
                        for f in txs
                    ],
                    [
                        [None, PALETTE["positive"] if f["tipo"] == "Compra" else PALETTE["red"]]
                        + [None] * 4
                        + [_signo(f["realizada"])] * 2
                        + [None]
                        for f in txs
                    ],
                ),
                "Transacciones",
            )
        else:
            self.addTab(_vacio("Sin transacciones registradas."), "Transacciones")

        if dividendos is None:
            self.addTab(_vacio("Calculando dividendos…"), "Dividendos")
        elif dividendos:
            self.addTab(
                _tabla(
                    COLS_DIV,
                    [
                        [
                            date.fromisoformat(ex[:10]).strftime("%d/%m/%Y"),
                            f"${m:,.4f}",
                            f"{q:,.4g}",
                            _dinero(c),
                        ]
                        for ex, m, q, c in sorted(dividendos, reverse=True)
                    ],
                ),
                "Dividendos",
            )
        else:
            self.addTab(_vacio("No cobró dividendos mientras la tuviste."), "Dividendos")

    def alto_sugerido(self) -> int:
        """El alto de la pestaña más alta: así cambiar de pestaña no tiene que re-medir la fila."""
        altos = [
            max(self.widget(i).minimumHeight(), self.widget(i).sizeHint().height())
            for i in range(self.count())
        ]
        return self.tabBar().sizeHint().height() + max(altos or [60]) + 12
