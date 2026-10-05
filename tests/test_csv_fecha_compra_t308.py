"""Tarea 308 — el importador de CSV lee la fecha de compra en vez de tirarla.

El defecto (``docs/auditoria_tanda_2026-10-05.md`` [I-1]): ninguna columna de fecha se leía, la
transacción quedaba con la hora de la importación, y las seis posiciones importadas de «Mis
Acciones» figuraban compradas el 2026-04-14 03:19 a precios que ese día no existieron. Los
dividendos cobrados se contaban desde ahí.

Los casos están elegidos para que la versión vieja y la nueva **difieran**: el CSV de Yahoo trae
`Date` (la cotización, hoy) y `Trade Date` (la compra, 2024) distintas, y el ex-date de los
dividendos cae entre la compra real y la importación.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from data.csv_importer import parse_csv, parse_trade_date

HOY = date(2026, 10, 5)

_YAHOO = (
    "Symbol,Current Price,Date,Time,Change,Open,High,Low,Volume,Trade Date,Purchase Price,Quantity,"
    "Commission,High Limit,Low Limit,Comment\n"
    "INTC,36.10,2026/10/03,16:00 EDT,0.1,36,36.5,35.8,1000,20240115,30.62,9.5692,0,,,\n"
    "AAPL,258.37,2026/10/03,16:00 EDT,1.2,257,259,256,1000,,203.30,6,0,,,\n"
)


# ── El parser ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("20240115", date(2024, 1, 15)),
        ("2024-01-15", date(2024, 1, 15)),
        ("15/01/2024", date(2024, 1, 15)),
        ("01/15/2024", date(2024, 1, 15)),  # el mes no puede ser 15: es mes/día
        ("05/05/2024", date(2024, 5, 5)),  # día == mes: no hay ambigüedad
    ],
)
def test_formatos_de_fecha(texto, esperado):
    assert parse_trade_date(texto, hoy=HOY) == (esperado, None)


@pytest.mark.parametrize(
    "texto,motivo",
    [("03/04/2026", "ambigua"), ("2099-01-01", "futura"), ("abc", "no reconocido"), ("20241340", "inválida")],
)
def test_lo_que_no_se_adivina_queda_sin_fecha_y_se_dice(texto, motivo):
    fecha, por_que = parse_trade_date(texto, hoy=HOY)
    assert fecha is None and motivo in por_que


def test_yahoo_toma_TRADE_DATE_y_no_la_fecha_de_la_cotizacion():
    res = parse_csv(_YAHOO)
    intc, aapl = res.rows
    assert intc.trade_date == date(2024, 1, 15)
    assert aapl.trade_date is None
    assert any("1 posición/es sin fecha de compra" in w for w in res.warnings)


def test_en_yahoo_la_columna_DATE_sola_no_es_la_fecha_de_compra():
    """Sin `Trade Date`, el export de Yahoo sólo trae la fecha de la cotización: no sirve."""
    csv = "Symbol,Date,Purchase Price,Quantity\nINTC,2026-10-03,30.62,10\n"
    res = parse_csv(csv)
    assert res.rows[0].trade_date is None
    assert any("ninguna columna de fecha de compra" in w for w in res.warnings)


def test_en_un_csv_generico_FECHA_si_es_la_de_compra():
    res = parse_csv("ticker,cantidad,precio,fecha\nINTC,10,30.62,15/01/2024\n")
    assert res.rows[0].trade_date == date(2024, 1, 15) and res.warnings == []


# ── La importación ───────────────────────────────────────────────────────────


def _importar(test_db, filas):
    from database.models import Portfolio, Transaction, session_scope
    from ui.import_dialog import ImportDialog

    with session_scope() as s:
        pf = Portfolio(name="Mis Acciones")
        s.add(pf)
        s.flush()
        pid = pf.id
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
        }
        for r in filas
    ]
    with session_scope() as s:
        ImportDialog._persist_rows(SimpleNamespace(portfolio_id=pid), s, items)
    with session_scope() as s:
        return {t.position.ticker: (t.date, t.position.purchase_date) for t in s.query(Transaction).all()}


def test_la_transaccion_y_la_posicion_quedan_con_la_fecha_del_csv(test_db):
    fechas = _importar(test_db, parse_csv(_YAHOO).rows)
    assert fechas["INTC"] == (datetime(2024, 1, 15), datetime(2024, 1, 15))
    # Sin fecha en el CSV: la de hoy, como antes (y el parser lo avisa).
    assert fechas["AAPL"][0].date() >= date(2026, 10, 5)


def test_los_dividendos_cobrados_cuentan_desde_la_compra_REAL(test_db):
    """Un ex-date entre la compra (2024-01-15) y la importación (hoy) se cobra; antes daba cero."""
    from database.cartera_real import dividendos_cobrados
    from paper_trading.dividends import dia

    fechas = _importar(test_db, parse_csv(_YAHOO).rows[:1])
    eventos = [(dia(fechas["INTC"][0]), 9.5692)]
    assert dividendos_cobrados(eventos, [("2024-05-06", 0.125)]) == pytest.approx(9.5692 * 0.125)
