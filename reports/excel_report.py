"""
Excel report generator for FinanzIAs.
"""

from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from config.logging_config import get_logger

log = get_logger(__name__)


# Color constants
C_BG = "FF0D1117"
C_CARD = "FF161B22"
C_HEADER = "FF21262D"
C_BLUE = "FF58A6FF"
C_GREEN = "FF3FB950"
C_RED = "FFF85149"
C_MUTED = "FF8B949E"
C_TEXT = "FFE6EDF3"
C_BORDER = "FF30363D"


def _fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)


def _font(bold=False, color=C_TEXT, size=10):
    return Font(bold=bold, color=color, name="Calibri", size=size)


def _border():
    side = Side(style="thin", color=C_BORDER)
    return Border(left=side, right=side, top=side, bottom=side)


def total_de_transaccion(tipo: str, cantidad: float, precio: float, comision: float | None) -> float:
    """El efectivo de una transacción, con el signo de la comisión según el tipo (tarea 268).

    En una compra la comisión se suma a lo que se paga; en una venta se resta de lo que entra.
    ``Transaction.total_value`` la suma siempre, y la segunda hoja que se sacó la restaba
    siempre: las dos estaban mal en una de las dos patas.
    """
    bruto = float(cantidad) * float(precio)
    fee = float(comision or 0.0)
    return bruto + fee if str(tipo).upper() == "BUY" else bruto - fee


def generate_portfolio_excel(
    output_path: str,
    portfolio_name: str,
    positions: list,
    prices: dict,
    currency: str = "USD",
    include_tx: bool = True,
) -> str:
    wb = openpyxl.Workbook()

    # ── Sheet 1: Summary ─────────────────────────────────────────────────────
    # `wb.active` está tipada Optional porque un Workbook sin hojas devuelve None;
    # uno recién construido siempre tiene la activa. Se estrecha con un error
    # explícito en vez de un `assert` (que `-O` borra): el resultado es el mismo
    # que hoy —si fuera None, la línea siguiente reventaría con AttributeError—
    # pero dicho, y le saca 21 errores a mypy de un solo punto.
    ws = wb.active
    if ws is None:  # pragma: no cover — openpyxl no llega acá con un Workbook nuevo
        raise RuntimeError("openpyxl devolvió un Workbook sin hoja activa")
    ws.title = "Portafolio"
    ws.sheet_view.showGridLines = False

    # Background for all used cells
    for row in ws.iter_rows(min_row=1, max_row=200, min_col=1, max_col=12):
        for cell in row:
            cell.fill = _fill(C_BG)

    # Title
    ws.merge_cells("A1:H1")
    ws["A1"] = f"FinanzIAs — {portfolio_name}"
    ws["A1"].font = Font(bold=True, color=C_BLUE, size=16, name="Calibri")
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 36

    ws.merge_cells("A2:H2")
    ws["A2"] = f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws["A2"].font = _font(color=C_MUTED, size=10)
    ws.row_dimensions[2].height = 20

    # ── Metrics block ────────────────────────────────────────────────────────
    # Tarea 277: las tenencias son las abiertas; el historial de transacciones usa TODAS,
    # porque una posición vendida entera queda en cantidad 0 con su compra y su venta.
    todas = list(positions)
    positions = [p for p in todas if (p.quantity or 0) > 0]
    # Tarea 268: el resumen valuaba al costo, sin decirlo, una posición sin precio (el
    # defecto de las tarjetas de la 281). Ahora: valor y P&L sólo con precio, y se nombran.
    from database.cartera_real import valor_y_pl

    _t = valor_y_pl(positions, prices)
    total_invested, total_value, pl, pl_pct = _t["invertido"], _t["valor"], _t["pl"], _t["pl_pct"]
    sin_precio_txt = (
        f" ({len(_t['sin_precio'])} sin precio: {', '.join(_t['sin_precio'])})" if _t["sin_precio"] else ""
    )

    metrics = [
        ("Valor Total", f"{currency} {total_value:,.2f}{sin_precio_txt}", C_BLUE),
        ("Invertido", f"{currency} {total_invested:,.2f}", C_MUTED),
        ("P&L", f"{'+' if pl >= 0 else ''}{currency} {pl:,.2f}", C_GREEN if pl >= 0 else C_RED),
        ("Rendimiento", f"{pl_pct:+.2f}%", C_GREEN if pl_pct >= 0 else C_RED),
    ]

    start_row = 4
    for i, (label, value, color) in enumerate(metrics):
        col = 2 + i * 2
        label_cell = ws.cell(row=start_row, column=col, value=label)
        label_cell.font = _font(color=C_MUTED, size=9)
        label_cell.alignment = Alignment(horizontal="center")
        label_cell.fill = _fill(C_CARD)

        val_cell = ws.cell(row=start_row + 1, column=col, value=value)
        val_cell.font = Font(bold=True, color=color, size=12, name="Calibri")
        val_cell.alignment = Alignment(horizontal="center")
        val_cell.fill = _fill(C_CARD)

        ws.row_dimensions[start_row].height = 20
        ws.row_dimensions[start_row + 1].height = 28

    # ── Positions table ──────────────────────────────────────────────────────
    headers = [
        "Ticker",
        "Empresa",
        "Sector",
        "Cantidad",
        "P. Compra",
        "P. Actual",
        "Var. Hoy %",
        "Invertido",
        "Valor Actual",
        "P&L",
        "P&L %",
    ]
    header_row = 8
    ws.row_dimensions[header_row].height = 22

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=header)
        cell.font = Font(bold=True, color=C_MUTED, size=9, name="Calibri")
        cell.fill = _fill(C_HEADER)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _border()

    data_row = header_row + 1
    for p in sorted(positions, key=lambda x: x.ticker):
        d = prices.get(p.ticker)
        current = d["price"] if d else None
        change_pct = d.get("change_pct") if d else None
        invested_pos = p.quantity * p.avg_buy_price
        current_val = (p.quantity * current) if current else None
        pos_pl = (current_val - invested_pos) if current_val else None
        pos_pl_pct = ((pos_pl / invested_pos) * 100) if (pos_pl is not None and invested_pos > 0) else None

        row_data = [
            p.ticker,
            p.company_name or p.ticker,
            p.sector or "—",
            p.quantity,
            p.avg_buy_price,
            current,
            change_pct,
            invested_pos,
            current_val,
            pos_pl,
            pos_pl_pct,
        ]

        bg = C_BG if data_row % 2 == 0 else C_CARD
        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=data_row, column=col_idx, value=val)
            cell.fill = _fill(bg)
            cell.border = _border()
            cell.alignment = Alignment(horizontal="right" if col_idx >= 4 else "left", vertical="center")

            if col_idx in (5, 6, 8, 9, 10) and val is not None:
                cell.number_format = f'"{currency}" #,##0.00'
            elif col_idx in (7, 11) and val is not None:
                cell.number_format = "+0.00%;-0.00%"
                cell.value = val / 100 if val is not None else None

            # Color P&L cells
            if col_idx in (10, 11) and val is not None:
                cell.font = Font(
                    bold=True, color=C_GREEN if float(val) >= 0 else C_RED, size=10, name="Calibri"
                )
            else:
                cell.font = _font(size=10)

        ws.row_dimensions[data_row].height = 20
        data_row += 1

    # Column widths
    widths = [10, 28, 18, 12, 14, 14, 12, 14, 14, 14, 10]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── Sheet 2: Transactions ─────────────────────────────────────────────────
    ws_tx = wb.create_sheet("Transacciones")
    ws_tx.sheet_view.showGridLines = False

    for row in ws_tx.iter_rows(min_row=1, max_row=500, min_col=1, max_col=8):
        for cell in row:
            cell.fill = _fill(C_BG)

    tx_headers = ["Ticker", "Tipo", "Cantidad", "Precio", "Comisiones", "Total", "Fecha", "Notas"]
    for col_idx, h in enumerate(tx_headers, 1):
        cell = ws_tx.cell(row=1, column=col_idx, value=h)
        cell.font = Font(bold=True, color=C_MUTED, size=9, name="Calibri")
        cell.fill = _fill(C_HEADER)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _border()

    tx_row = 2
    from database.models import Transaction, session_scope

    with session_scope() as session:
        pos_ids = [p.id for p in todas]
        txs = (
            session.query(Transaction)
            .filter(Transaction.position_id.in_(pos_ids))
            .order_by(Transaction.date.desc())
            .all()
        )
        pos_map = {p.id: p.ticker for p in todas}
        for tx in txs:
            ticker = pos_map.get(tx.position_id, "?")
            bg = C_BG if tx_row % 2 == 0 else C_CARD
            row_data = [
                ticker,
                tx.transaction_type,
                tx.quantity,
                tx.price,
                tx.fees,
                total_de_transaccion(tx.transaction_type, tx.quantity, tx.price, tx.fees),
                tx.date.strftime("%d/%m/%Y") if tx.date else "",
                tx.notes or "",
            ]
            for col_idx, val in enumerate(row_data, 1):
                cell = ws_tx.cell(row=tx_row, column=col_idx, value=val)
                cell.fill = _fill(bg)
                cell.font = _font(size=10)
                cell.border = _border()
                cell.alignment = Alignment(
                    horizontal="right" if col_idx in (3, 4, 5, 6) else "left", vertical="center"
                )
            # Color buy/sell
            type_cell = ws_tx.cell(row=tx_row, column=2)
            type_cell.font = Font(
                bold=True, color=C_GREEN if tx.transaction_type == "BUY" else C_RED, size=10, name="Calibri"
            )
            tx_row += 1

    tx_widths = [10, 10, 12, 14, 12, 14, 14, 30]
    for i, w in enumerate(tx_widths, 1):
        ws_tx.column_dimensions[get_column_letter(i)].width = w

    # Tarea 268: acá se armaba una SEGUNDA hoja «Transacciones» (openpyxl la renombraba
    # «Transacciones1») con lo mismo, y la primera se armaba siempre aunque `tx_history`
    # estuviera apagado. Queda una, y sólo si se pidió.
    if not include_tx:
        wb.remove(ws_tx)

    wb.save(output_path)
    return output_path
