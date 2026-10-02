"""Tarea 277 — vender entera una posición real no borra su historial.

El defecto (``docs/auditoria_cuentas_real_2026-10-02.md`` [R-1]): ``SellPositionDialog`` hacía
``session.delete(pos)`` en la venta total; con ``cascade="all, delete-orphan"`` y la sesión de
la app (``autoflush=False`` — la de ``test_db``, verificado contra ``tests/conftest.py``) la
compra se borraba y la venta quedaba huérfana. Estos tests corren con esa misma sesión: el
``verificador`` mostró que con ``autoflush=True`` el resultado es otro.
"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

from database.cartera_real import esta_abierta, reabrir_si_cerrada, registrar_venta
from database.models import Portfolio, Position, Transaction, session_scope

_REPO = Path(__file__).resolve().parent.parent


def _posicion(qty: float = 10.0, precio: float = 100.0) -> int:
    with session_scope() as s:
        pf = Portfolio(name="Mis Acciones")
        s.add(pf)
        s.flush()
        pos = Position(
            portfolio_id=pf.id,
            ticker="AAA",
            quantity=qty,
            avg_buy_price=precio,
            purchase_date=datetime(2026, 5, 1),
        )
        s.add(pos)
        s.flush()
        s.add(Transaction(position_id=pos.id, transaction_type="BUY", quantity=qty, price=precio))
        return pos.id


def _vender(pid: int, qty: float, precio: float = 120.0) -> None:
    with session_scope() as s:
        pos = s.query(Position).filter(Position.id == pid).one()
        registrar_venta(s, pos, qty, precio, 1.0)


def test_la_venta_TOTAL_conserva_la_compra_y_la_venta_ligadas_a_la_posicion(test_db):
    pid = _posicion()
    _vender(pid, 10.0)
    with session_scope() as s:
        pos = s.query(Position).filter(Position.id == pid).one_or_none()
        assert pos is not None, "la venta total borró la posición (y con ella la compra)"
        assert pos.quantity == 0.0 and pos.avg_buy_price == 100.0 and pos.ticker == "AAA"
        txs = s.query(Transaction).filter(Transaction.position_id == pid).order_by(Transaction.id).all()
        assert [(t.transaction_type, t.quantity, t.price) for t in txs] == [
            ("BUY", 10.0, 100.0),
            ("SELL", 10.0, 120.0),
        ]
        huerfanas = s.query(Transaction).filter(~Transaction.position_id.in_(s.query(Position.id))).count()
        assert huerfanas == 0


def test_la_venta_PARCIAL_descuenta_y_sigue_abierta(test_db):
    pid = _posicion()
    _vender(pid, 4.0)
    with session_scope() as s:
        pos = s.query(Position).filter(Position.id == pid).one()
        assert pos.quantity == 6.0 and esta_abierta(pos)


def test_un_residuo_de_float_cuenta_como_cerrada(test_db):
    pid = _posicion(qty=0.3)
    _vender(pid, 0.1)
    _vender(pid, 0.2)  # 0.3 - 0.1 - 0.2 = 5.5e-17 en float
    with session_scope() as s:
        assert s.query(Position).filter(Position.id == pid).one().quantity == 0.0


def test_reabrir_una_cerrada_REINICIA_la_fecha_y_una_abierta_no(test_db):
    pid = _posicion()
    nueva = datetime(2026, 10, 1)
    with session_scope() as s:
        pos = s.query(Position).filter(Position.id == pid).one()
        reabrir_si_cerrada(pos, nueva)
        assert pos.purchase_date == datetime(2026, 5, 1), "una abierta conserva su fecha"
    _vender(pid, 10.0)
    with session_scope() as s:
        pos = s.query(Position).filter(Position.id == pid).one()
        reabrir_si_cerrada(pos, nueva)
        assert pos.purchase_date == nueva, "un lote nuevo contaría dividendos desde la compra vieja"


# ── Los cables ───────────────────────────────────────────────────────────────


def _src(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8")


def test_el_dialogo_de_venta_usa_registrar_venta_y_no_borra():
    src = _src("ui/dialogs.py")
    clase = next(
        n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ClassDef) and n.name == "SellPositionDialog"
    )
    cuerpo = ast.get_source_segment(src, clase)
    assert "registrar_venta(" in cuerpo
    assert "session.delete(" not in cuerpo


def test_las_vistas_de_tenencias_filtran_las_cerradas():
    for rel in ("ui/portfolio_tab.py", "ui/rsi_scanner.py"):
        assert "Position.quantity > 0" in _src(rel), f"{rel} mostraría posiciones vendidas en cero"


def test_los_reportes_muestran_abiertas_y_el_historial_de_TODAS(test_db, tmp_path):
    """La tabla de tenencias sin la cerrada, y su compra y su venta en el historial."""
    from reports.excel_report import generate_portfolio_excel

    pid = _posicion()
    _vender(pid, 10.0)
    with session_scope() as s:
        pf_id = s.query(Position).filter(Position.id == pid).one().portfolio_id
        bbb = Position(portfolio_id=pf_id, ticker="BBB", quantity=5.0, avg_buy_price=50.0)
        s.add(bbb)
        s.flush()
        # BBB con su compra: así la segunda hoja de transacciones existe en las dos versiones
        # (sin esto, con el historial restringido a las abiertas la hoja no se creaba y el
        # test no tenía nada que revisar — un caso degenerado).
        s.add(Transaction(position_id=bbb.id, transaction_type="BUY", quantity=5.0, price=50.0))
    with session_scope() as s:
        positions = s.query(Position).all()
        s.expunge_all()

    from openpyxl import load_workbook

    out = tmp_path / "r.xlsx"
    generate_portfolio_excel(str(out), "Mis Acciones", positions, {}, "USD", include_tx=True)
    wb = load_workbook(out)
    try:
        hojas = {
            ws.title: [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
            for ws in wb.worksheets
        }
    finally:
        wb.close()
    texto = " ".join(v for vs in hojas.values() for v in vs)
    assert "BBB" in texto
    primera = next(iter(hojas.values()))  # la hoja de tenencias
    assert "AAA" not in primera, "la posición vendida entera aparece como tenencia"
    # El Excel arma DOS hojas de transacciones (`:194` y `:271`): las dos tienen que verla,
    # o una mutación en cualquiera queda tapada por la otra (pasó: buscar en todo el libro
    # dejaba verde la mutación de la segunda).
    tx = {t: v for t, v in hojas.items() if t.startswith("Transacciones")}
    assert len(tx) >= 1
    for titulo, valores in tx.items():
        assert "SELL" in valores, f"la venta de la posición cerrada no aparece en {titulo!r}"


def test_el_pdf_se_genera_con_una_posicion_cerrada(test_db, tmp_path):
    """Humo: el PDF tiene el mismo filtro que el Excel y no se cae con una posición en cero."""
    from reports.pdf_report import generate_portfolio_pdf

    pid = _posicion()
    _vender(pid, 10.0)
    with session_scope() as s:
        positions = s.query(Position).all()
        s.expunge_all()
    out = tmp_path / "r.pdf"
    generate_portfolio_pdf(str(out), "Mis Acciones", positions, {}, "USD", include_tx=True, dark_mode=False)
    assert out.exists() and out.stat().st_size > 0
