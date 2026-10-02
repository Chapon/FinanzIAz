"""Tarea 264 — Home muestra la cartera real «Mis Acciones», no una cuenta de paper trading.

El defecto (``docs/auditoria_pantalla_2026-10-02.md`` [F-1]): Home elegía la cuenta paper **1**
—cerrada desde julio— por id fijo, y pintaba su equity, su P&L en rojo y sus 5 posiciones como
si fueran lo vivo. Chapa definió el remedio: Home es el resumen de **su cartera real**, y de las
dos, sólo «Mis Acciones». Además: la fila de alertas pasaba un ``0`` fijo, la torta usaba el
costo, y la carga corría bajo ``suppress(Exception)``.

El caso que separa las versiones: «Tech» se crea **antes** que «Mis Acciones», así que un
resolver por id (o por «la primera») agarra la cartera equivocada; y hay una cuenta paper
activa con posiciones, que no tiene que aparecer en ningún número.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from database.cartera_real import resumen_home
from database.models import Alert, Portfolio, Position, PriceCache, Transaction, session_scope, utcnow_naive


def _cartera(nombre: str, posiciones: list[tuple[str, float, float]]) -> int:
    with session_scope() as s:
        pf = Portfolio(name=nombre)
        s.add(pf)
        s.flush()
        for ticker, qty, avg in posiciones:
            pos = Position(portfolio_id=pf.id, ticker=ticker, quantity=qty, avg_buy_price=avg)
            s.add(pos)
            s.flush()
            if qty > 0:
                s.add(
                    Transaction(
                        position_id=pos.id,
                        transaction_type="BUY",
                        quantity=qty,
                        price=avg,
                        date=datetime(2026, 9, 1),
                    )
                )
        return pf.id


def _precio(ticker: str, px: float) -> None:
    with session_scope() as s:
        s.add(PriceCache(ticker=ticker, price=px, fetched_at=utcnow_naive()))


def _alerta(pf_id: int, disparada: bool) -> None:
    with session_scope() as s:
        s.add(
            Alert(
                portfolio_id=pf_id,
                ticker="AAA",
                alert_type="ABOVE",
                target_value=1.0,
                is_active=not disparada,
                triggered_at=utcnow_naive() if disparada else None,
            )
        )


@pytest.fixture
def escenario(test_db):
    from paper_trading.account import create_account
    from paper_trading.models import PaperPosition

    tech = _cartera("Tech", [("ZZZ", 100.0, 10.0)])  # se crea PRIMERO: id menor
    mis = _cartera("Mis Acciones", [("AAA", 10.0, 100.0), ("BBB", 5.0, 50.0), ("CCC", 0.0, 70.0)])
    acct = create_account(name="Sim Viva", initial_capital=50_000.0)
    with session_scope() as s:
        s.add(PaperPosition(account_id=acct.id, ticker="PPP", shares=99.0, avg_cost=1.0))
    _precio("AAA", 120.0)
    _precio("BBB", 40.0)
    _precio("ZZZ", 999.0)
    _precio("PPP", 999.0)
    return tech, mis


def _resumen():
    with session_scope() as s:
        return resumen_home(s)


def test_muestra_SOLO_mis_acciones_y_nada_de_paper(escenario):
    _, mis = escenario
    r = _resumen()
    assert r["portfolio_id"] == mis and r["nombre"] == "Mis Acciones"
    assert r["posiciones"] == 2, "la cerrada (CCC, cantidad 0) no cuenta y las de Tech/paper tampoco"
    assert {t for t, _ in r["torta"]} == {"AAA", "BBB"}


def test_valor_y_PL_a_precio_de_mercado(escenario):
    r = _resumen()
    assert r["valor"] == pytest.approx(10 * 120 + 5 * 40)
    assert r["pl"] == pytest.approx((10 * 120 + 5 * 40) - (10 * 100 + 5 * 50))


def test_la_torta_es_a_VALOR_DE_MERCADO_no_al_costo(escenario):
    r = _resumen()
    assert dict(r["torta"]) == {"AAA": pytest.approx(1200.0), "BBB": pytest.approx(200.0)}


def test_un_precio_faltante_se_DICE_y_no_se_valua_al_costo(escenario):
    _, mis = escenario
    with session_scope() as s:
        pos = Position(portfolio_id=mis, ticker="DDD", quantity=3.0, avg_buy_price=10.0)
        s.add(pos)
    r = _resumen()
    assert r["sin_precio"] == ["DDD"]
    assert r["valor"] == pytest.approx(1400.0), "DDD no puede entrar al valor (ni al costo)"
    assert r["posiciones"] == 3


def test_las_alertas_son_las_DISPARADAS_de_esta_cartera(escenario):
    tech, mis = escenario
    _alerta(mis, disparada=True)
    _alerta(mis, disparada=False)
    _alerta(tech, disparada=True)
    assert _resumen()["alertas_disparadas"] == 1


def test_sin_la_cartera_devuelve_None(test_db):
    _cartera("Tech", [("ZZZ", 1.0, 1.0)])
    assert _resumen() is None


def test_el_capital_invertido_neto_es_compras_menos_ventas(escenario):
    _, mis = escenario
    with session_scope() as s:
        aaa = s.query(Position).filter(Position.portfolio_id == mis, Position.ticker == "AAA").one()
        s.add(
            Transaction(
                position_id=aaa.id,
                transaction_type="SELL",
                quantity=2.0,
                price=120.0,
                date=datetime(2026, 9, 5),
            )
        )
    serie = _resumen()["invertido_neto"]
    assert serie[-1][1] == pytest.approx(10 * 100 + 5 * 50 - 2 * 120)


# ── La pantalla ──────────────────────────────────────────────────────────────


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_home_PINTA_mis_acciones_y_las_alertas_reales(escenario, qapp):
    from ui.home_tab import HomeTab

    _, mis = escenario
    _alerta(mis, disparada=True)
    home = HomeTab()
    try:
        assert home.kpi_pl.value_lbl.text() == "$1,400"
        assert home.kpi_positions.value_lbl.text() == "2"
        assert "Mis Acciones" in home.hero_title.text()
        assert home.welcome_card.status_rows["alerts"].stat_lbl.text() == "1 disparada(s)"
    finally:
        home.hero_chart.cleanup()


def test_home_sin_la_cartera_LO_DICE(test_db, qapp):
    from ui.home_tab import HomeTab

    home = HomeTab()
    try:
        assert "No encontré" in home.hero_title.text()
    finally:
        home.hero_chart.cleanup()


def test_home_no_traga_errores_en_silencio():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "ui" / "home_tab.py").read_text(encoding="utf-8")
    assert "suppress(Exception):\n            self.load" not in src
    assert "paper_trading.account" not in src, "Home no debe leer cuentas de paper trading"
