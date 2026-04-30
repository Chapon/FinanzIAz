"""
PDF report generator for FinanzIAs portfolio summaries.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib import colors
from datetime import datetime
from typing import Optional

# ── Dark palette ─────────────────────────────────────────────────────────────
C_BG_DARK    = HexColor("#0d1117")
C_CARD_DARK  = HexColor("#161b22")
C_MUTED_DARK = HexColor("#8b949e")
C_TEXT_DARK  = HexColor("#e6edf3")
C_BORDER_DARK= HexColor("#21262d")

# ── Light palette ─────────────────────────────────────────────────────────────
C_BG_LIGHT    = HexColor("#ffffff")
C_CARD_LIGHT  = HexColor("#f6f8fa")
C_MUTED_LIGHT = HexColor("#57606a")
C_TEXT_LIGHT  = HexColor("#1f2328")
C_BORDER_LIGHT= HexColor("#d0d7de")

# ── Shared accent colors ──────────────────────────────────────────────────────
C_BLUE   = HexColor("#58a6ff")
C_GREEN  = HexColor("#3fb950")
C_RED    = HexColor("#f85149")
C_YELLOW = HexColor("#d29922")


def generate_portfolio_pdf(
    output_path: str,
    portfolio_name: str,
    positions: list,
    prices: dict,
    currency: str = "USD",
    include_tx: bool = True,
    dark_mode: bool = True,
) -> str:
    """
    Generate a PDF portfolio report.
    positions: list of Position ORM objects
    prices: dict ticker -> {price, change_pct, ...}
    Returns the output_path on success.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    # ── Pick palette based on dark_mode setting ───────────────────────────────
    C_BG   = C_BG_DARK   if dark_mode else C_BG_LIGHT
    C_CARD = C_CARD_DARK if dark_mode else C_CARD_LIGHT
    C_MUTED = C_MUTED_DARK if dark_mode else C_MUTED_LIGHT
    C_TEXT  = C_TEXT_DARK  if dark_mode else C_TEXT_LIGHT
    C_BORDER= C_BORDER_DARK if dark_mode else C_BORDER_LIGHT

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", fontSize=22, fontName="Helvetica-Bold",
        textColor=C_TEXT, spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        "subtitle", fontSize=13, fontName="Helvetica",
        textColor=C_MUTED, spaceAfter=12
    )
    section_style = ParagraphStyle(
        "section", fontSize=13, fontName="Helvetica-Bold",
        textColor=C_BLUE, spaceBefore=16, spaceAfter=8
    )
    body_style = ParagraphStyle(
        "body", fontSize=10, fontName="Helvetica",
        textColor=C_TEXT, leading=14
    )

    story = []
    now = datetime.now().strftime("%d de %B de %Y, %H:%M")

    # ── Header ──────────────────────────────────────────────────────────────
    story.append(Paragraph(f"FinanzIAs — Reporte de Portafolio", title_style))
    story.append(Paragraph(f"{portfolio_name}  ·  {now}", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_BORDER, spaceAfter=16))

    # ── Summary metrics ──────────────────────────────────────────────────────
    total_invested = sum(p.quantity * p.avg_buy_price for p in positions)
    total_value = 0.0
    for p in positions:
        d = prices.get(p.ticker)
        total_value += (p.quantity * d["price"]) if d else (p.quantity * p.avg_buy_price)

    pl = total_value - total_invested
    pl_pct = (pl / total_invested * 100) if total_invested > 0 else 0.0
    pl_color = C_GREEN if pl >= 0 else C_RED

    summary_data = [
        ["Métrica", "Valor"],
        ["Valor total del portafolio", f"{currency} {total_value:,.2f}"],
        ["Total invertido", f"{currency} {total_invested:,.2f}"],
        ["P&L total", f"{'+'if pl>=0 else ''}{currency} {pl:,.2f}"],
        ["Rendimiento", f"{pl_pct:+.2f}%"],
        ["Número de posiciones", str(len(positions))],
    ]

    summary_table = Table(summary_data, colWidths=[9 * cm, 7 * cm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_CARD),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_MUTED),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_BG, C_CARD]),
        ("TEXTCOLOR", (0, 1), (-1, -1), C_TEXT),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 1), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        # Color P&L row
        ("TEXTCOLOR", (1, 3), (1, 3), pl_color),
        ("TEXTCOLOR", (1, 4), (1, 4), pl_color),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 16))

    # ── Positions table ──────────────────────────────────────────────────────
    story.append(Paragraph("Detalle de Posiciones", section_style))

    headers = ["Ticker", "Empresa", "Cant.", "P. Compra", "P. Actual", "P&L", "P&L %"]
    rows = [headers]
    for p in sorted(positions, key=lambda x: x.ticker):
        d = prices.get(p.ticker)
        current = d["price"] if d else None
        invested_pos = p.quantity * p.avg_buy_price
        current_val = (p.quantity * current) if current else None
        pos_pl = (current_val - invested_pos) if current_val else None
        pos_pl_pct = ((pos_pl / invested_pos) * 100) if (pos_pl is not None and invested_pos > 0) else None

        rows.append([
            p.ticker,
            (p.company_name or p.ticker)[:30],
            f"{p.quantity:.4f}",
            f"${p.avg_buy_price:,.4f}",
            f"${current:,.4f}" if current else "—",
            f"{'+'if pos_pl>=0 else ''}${pos_pl:,.2f}" if pos_pl is not None else "—",
            f"{pos_pl_pct:+.2f}%" if pos_pl_pct is not None else "—",
        ])

    col_widths = [2 * cm, 5.5 * cm, 2 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2 * cm]
    pos_table = Table(rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_CARD),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_MUTED),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_BG, C_CARD]),
        ("TEXTCOLOR", (0, 1), (-1, -1), C_TEXT),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    # Color P&L cells
    for i, p in enumerate(positions, 1):
        d = prices.get(p.ticker)
        current = d["price"] if d else None
        if current:
            pos_pl = (p.quantity * current) - (p.quantity * p.avg_buy_price)
            col = C_GREEN if pos_pl >= 0 else C_RED
            style.append(("TEXTCOLOR", (5, i), (6, i), col))

    pos_table.setStyle(TableStyle(style))
    story.append(pos_table)

    # ── Transaction history (optional) ───────────────────────────────────────
    if include_tx:
        try:
            from database.models import get_session, Transaction, Position as Pos
            session = get_session()
            pos_ids = [p.id for p in positions if hasattr(p, "id")]
            txs = (
                session.query(Transaction)
                .filter(Transaction.position_id.in_(pos_ids))
                .order_by(Transaction.date.desc())
                .limit(100)
                .all()
            )
            # Build ticker lookup
            pos_map = {p.id: p.ticker for p in positions if hasattr(p, "id")}
            session.expunge_all()
            session.close()

            if txs:
                story.append(Paragraph("Historial de Transacciones (últimas 100)", section_style))
                tx_headers = ["Fecha", "Ticker", "Tipo", "Cantidad", "Precio", "Comisión"]
                tx_rows = [tx_headers]
                for tx in txs:
                    tx_rows.append([
                        tx.date.strftime("%d/%m/%Y") if tx.date else "—",
                        pos_map.get(tx.position_id, "?"),
                        tx.transaction_type,
                        f"{tx.quantity:.4f}",
                        f"${tx.price:,.4f}",
                        f"${tx.fees:,.2f}" if tx.fees else "$0.00",
                    ])
                tx_col_w = [2.5*cm, 2*cm, 2*cm, 2.5*cm, 3*cm, 2.5*cm]
                tx_table = Table(tx_rows, colWidths=tx_col_w, repeatRows=1)
                tx_style = [
                    ("BACKGROUND", (0, 0), (-1, 0), C_CARD),
                    ("TEXTCOLOR", (0, 0), (-1, 0), C_MUTED),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_BG, C_CARD]),
                    ("TEXTCOLOR", (0, 1), (-1, -1), C_TEXT),
                    ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
                for i, tx in enumerate(txs, 1):
                    color = C_GREEN if tx.transaction_type == "BUY" else C_RED
                    tx_style.append(("TEXTCOLOR", (2, i), (2, i), color))
                tx_table.setStyle(TableStyle(tx_style))
                story.append(tx_table)
        except Exception as e:
            print(f"[PDF] Transaction history error: {e}")

    # ── Footer ───────────────────────────────────────────────────────────────
    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=1, color=C_BORDER))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Generado por FinanzIAs · Datos obtenidos de Yahoo Finance · "
        "Este reporte es únicamente informativo y no constituye asesoramiento financiero.",
        ParagraphStyle("footer", fontSize=8, fontName="Helvetica", textColor=C_MUTED)
    ))

    doc.build(story)
    return output_path
