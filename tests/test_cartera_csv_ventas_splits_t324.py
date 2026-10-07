"""Tarea 324 — el CSV de Yahoo con compras, ventas y el split de NVDA.

El defecto: el importador ignoraba ``Transaction Type``, y **cada venta del CSV entraba como una
compra**; una fila sin lotes (TSLA) entraba como una compra inventada de 1 acción al precio del
día. El par «Stock Split» con el que Yahoo carga el split de NVDA, tomado literal, inventa una
ganancia realizada de +$3.438,16 y deja el costo en $120.

Los casos están elegidos para que la versión literal y la correcta **difieran**: INTC tiene dos
compras a precios muy distintos (FIFO deja el lote de $103,53; el promedio daría ~$52), y el split
de NVDA cambia a la vez el costo (89,85 contra 120) y la realizada (0 contra 3.438,16).
"""

from __future__ import annotations

from datetime import date

import pytest

from data.csv_importer import parse_csv
from database.lotes import Movimiento, armar_posiciones, detectar_splits, libro_fifo

_CAB = (
    "Symbol,Current Price,Date,Time,Change,Open,High,Low,Volume,Trade Date,Purchase Price,Quantity,"
    "Commission,High Limit,Low Limit,Comment,Transaction Type\n"
)
_CSV = _CAB + (
    "NVDA,237.15,2026/10/07,12:51 EDT,-2,237,239,236,1,20240610,120.0,120.0,0.0,,,Stock Split,BUY\n"
    "NVDA,237.15,2026/10/07,12:51 EDT,-2,237,239,236,1,20240607,1200.0,12.0,0.0,,,Stock Split,SELL\n"
    "NVDA,237.15,2026/10/07,12:51 EDT,-2,237,239,236,1,20240606,1202.66,5.0,100.0,,,,BUY\n"
    "NVDA,237.15,2026/10/07,12:51 EDT,-2,237,239,236,1,20240221,681.22,7.0,80.0,,,,BUY\n"
    "AAPL,336.2,2026/10/07,12:51 EDT,2,337,338,332,1,20260923,341.32,6.0,19.94,,,,SELL\n"
    "AAPL,336.2,2026/10/07,12:51 EDT,2,337,338,332,1,20240611,203.3,6.0,26.01,,,,BUY\n"
    "INTC,113.1,2026/10/07,12:51 EDT,0.6,111,115,111,1,20260923,121.72,9.569235,11.36,,,,SELL\n"
    "INTC,113.1,2026/10/07,12:51 EDT,0.6,111,115,111,1,20260721,103.53,4.0,0.35,,,,BUY\n"
    "INTC,113.1,2026/10/07,12:51 EDT,0.6,111,115,111,1,20240610,30.6212,9.569235,6.98,,,,BUY\n"
    "TSLA,376.1,2026/10/07,12:51 EDT,-4.5,378,382,374,1,,,,,,,,\n"
)


def _movs(rows):
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r.ticker, []).append(
            Movimiento(r.trade_date, r.tipo, r.quantity, r.buy_price, r.commission, r.notes)
        )
    return out


def _armadas():
    return {a.ticker: a for a in armar_posiciones(_movs(parse_csv(_CSV).rows))}


# ── El parser ────────────────────────────────────────────────────────────────


def test_las_ventas_entran_como_VENTAS():
    tipos = {(r.ticker, r.trade_date): r.tipo for r in parse_csv(_CSV).rows}
    assert tipos[("AAPL", date(2026, 9, 23))] == "SELL"
    assert tipos[("AAPL", date(2024, 6, 11))] == "BUY"


def test_un_ticker_SIN_LOTES_se_omite_y_no_se_inventa_una_compra():
    res = parse_csv(_CSV)
    assert "TSLA" not in {r.ticker for r in res.rows}
    assert any("TSLA sin lotes" in s["reason"] for s in res.skipped)


def test_una_watchlist_con_la_columna_de_tipo_VACIA_sigue_siendo_watchlist():
    """Si la regla nueva mirara sólo la columna, una watchlist de Yahoo dejaría de importarse."""
    res = parse_csv(_CAB + "TSLA,376.1,2026/10/07,12:51 EDT,-4.5,378,382,374,1,,,,,,,,\n")
    (tsla,) = res.rows
    assert tsla.is_watchlist and tsla.quantity == 1.0 and tsla.buy_price == pytest.approx(376.1)


# ── El split ─────────────────────────────────────────────────────────────────


def test_el_split_de_NVDA_es_un_split_y_no_una_venta():
    nvda = _armadas()["NVDA"]
    assert [(s.fecha, s.ratio) for s in nvda.splits] == [(date(2024, 6, 10), 10.0)]
    lb = nvda.libro
    assert lb.cantidad == pytest.approx(120.0)
    assert lb.costo_promedio == pytest.approx((7 * 681.22 + 5 * 1202.66) / 120)  # 89,85, no 120
    assert lb.realizado == 0.0  # literal daba +3.438,16
    assert [f.mov.tipo for f in lb.filas] == ["BUY", "BUY"]
    # Quedan las fechas REALES de compra, con la cantidad llevada a acciones de hoy.
    assert [(lo.fecha, lo.cantidad) for lo in lb.lotes] == [
        (date(2024, 2, 21), 70.0),
        (date(2024, 6, 6), 50.0),
    ]
    assert "original: 7 a $681.22" in lb.filas[0].mov.nota


def test_un_par_que_NO_cierra_queda_literal_y_se_avisa():
    """La venta «split» no es toda la tenencia: adivinar un split es peor que mostrar el archivo."""
    movs = [
        Movimiento(date(2024, 2, 21), "BUY", 7, 681.22),
        Movimiento(date(2024, 6, 6), "BUY", 5, 1202.66),
        Movimiento(date(2024, 6, 7), "SELL", 10, 1200.0, nota="Stock Split"),
        Movimiento(date(2024, 6, 10), "BUY", 100, 120.0, nota="Stock Split"),
    ]
    resto, splits, avisos = detectar_splits(movs)
    assert splits == [] and len(resto) == 4
    assert any("no es la tenencia" in a for a in avisos)


# ── FIFO ─────────────────────────────────────────────────────────────────────


def test_FIFO_vende_el_lote_mas_viejo_primero():
    lb = _armadas()["INTC"].libro
    assert [(lo.fecha, lo.cantidad, lo.precio) for lo in lb.lotes] == [(date(2026, 7, 21), 4.0, 103.53)]
    assert lb.costo_promedio == pytest.approx(103.53)  # el promedio ponderado daría ~52


def test_la_realizada_descuenta_las_DOS_comisiones():
    lb = _armadas()["AAPL"].libro
    assert not lb.abierta
    esperado = 6 * 341.32 - 19.94 - (6 * 203.3 + 26.01)
    assert lb.realizado == pytest.approx(esperado)  # 782,17
    compra, venta = lb.filas
    assert compra.realizado == pytest.approx(esperado) and venta.realizado == pytest.approx(esperado)


def test_la_realizada_de_cada_COMPRA_es_la_de_su_lote():
    """Las dos columnas de Yahoo: el lote de 7 NVDA a $681,22 vendido a $1200 da +3.551,46."""
    lb = libro_fifo(
        [
            Movimiento(date(2024, 2, 21), "BUY", 7, 681.22, 80),
            Movimiento(date(2024, 6, 6), "BUY", 5, 1202.66, 100),
            Movimiento(date(2024, 6, 7), "SELL", 12, 1200.0, 0),
        ]
    )
    c7, c5, venta = lb.filas
    assert c7.realizado == pytest.approx(3551.46)
    assert c5.realizado == pytest.approx(-113.30)
    assert venta.realizado == pytest.approx(3438.16)
    # Los % de la captura de Yahoo de Chapa (2026-10-07).
    assert c7.realizado_pct == pytest.approx(74.48, abs=0.01)
    assert c5.realizado_pct == pytest.approx(-1.88, abs=0.01)
    assert venta.realizado_pct == pytest.approx(31.36, abs=0.01)


def test_vender_mas_de_lo_que_hay_es_un_error():
    lb = libro_fifo(
        [Movimiento(date(2024, 1, 2), "BUY", 5, 10.0), Movimiento(date(2024, 2, 1), "SELL", 6, 12.0)]
    )
    assert lb.error and "6" in lb.error


# ── La importación y el reemplazo ────────────────────────────────────────────


def _cartera(nombre="Mis Acciones"):
    from database.models import Portfolio, session_scope

    with session_scope() as s:
        pf = Portfolio(name=nombre)
        s.add(pf)
        s.flush()
        return pf.id


def _estado(pid):
    from database.models import Position, session_scope

    with session_scope() as s:
        return {
            p.ticker: (round(p.quantity, 6), round(p.avg_buy_price, 4), p.company_name, len(p.transactions))
            for p in s.query(Position).filter(Position.portfolio_id == pid)
        }


def test_el_dialogo_guarda_las_ventas_como_ventas(test_db):
    from types import SimpleNamespace

    from database.models import session_scope
    from ui.import_dialog import ImportDialog

    pid = _cartera()
    items = [
        {
            "ticker": r.ticker,
            "quantity": r.quantity,
            "price": r.buy_price,
            "fee": r.commission,
            "company_name": r.ticker,
            "sector": "",
            "is_watchlist": r.is_watchlist,
            "trade_date": r.trade_date,
            "tipo": r.tipo,
            "notes": r.notes,
        }
        for r in parse_csv(_CSV).rows
    ]
    with session_scope() as s:
        ImportDialog._persist_rows(SimpleNamespace(portfolio_id=pid), s, items)
    est = _estado(pid)
    assert est["AAPL"][0] == 0.0  # antes: 12 acciones compradas
    assert est["INTC"][:2] == (4.0, 103.53)
    assert est["NVDA"][:2] == (120.0, 89.8487)
    assert set(est) == {"AAPL", "INTC", "NVDA"}


def test_reemplazar_borra_lo_viejo_y_conserva_la_empresa(test_db):
    from database.cartera_real import reemplazar_cartera
    from database.models import Position, Transaction, session_scope

    pid = _cartera()
    with session_scope() as s:
        for t, q in (("AAPL", 6.0), ("ZZZ", 3.0)):
            p = Position(portfolio_id=pid, ticker=t, quantity=q, avg_buy_price=1.0, company_name=f"{t} Inc")
            s.add(p)
            s.flush()
            s.add(Transaction(position_id=p.id, transaction_type="BUY", quantity=q, price=1.0))
    with session_scope() as s:
        out = reemplazar_cartera(s, pid, list(_armadas().values()))
    assert out["borradas"] == 2 and out["errores"] == {}
    est = _estado(pid)
    assert "ZZZ" not in est
    assert est["AAPL"] == (0.0, 203.3, "AAPL Inc", 2)  # la compra y la venta del CSV, no la vieja


def test_reemplazar_NO_toca_nada_si_un_ticker_no_cierra(test_db):
    from database.cartera_real import reemplazar_cartera
    from database.models import Position, session_scope

    pid = _cartera()
    with session_scope() as s:
        s.add(Position(portfolio_id=pid, ticker="AAPL", quantity=6.0, avg_buy_price=1.0))
    malas = armar_posiciones(
        {"XXX": [Movimiento(date(2024, 1, 2), "BUY", 1, 1.0), Movimiento(date(2024, 1, 3), "SELL", 2, 1.0)]}
    )
    with session_scope() as s:
        out = reemplazar_cartera(s, pid, malas)
    assert "XXX" in out["errores"]
    assert set(_estado(pid)) == {"AAPL"}
