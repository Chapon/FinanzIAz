"""Tarea 445 — el harvest cosecha también los tickers de las carteras reales.

El 2026-11-20, 14 tickers de «Mis Acciones» y «Tech» (MARA, EMBJ, AAPL, entre otros) no estaban en
el universo del harvest —la watchlist y las posiciones de la cuenta viva— y no tenían noticias.
"""

from __future__ import annotations

from datetime import datetime

from database.models import Portfolio, Position, session_scope
from scripts import harvest_catalysts as hc


def _cartera(nombre: str, *tenencias: tuple[str, float]) -> None:
    with session_scope() as s:
        p = Portfolio(name=nombre)
        s.add(p)
        s.flush()
        for ticker, cantidad in tenencias:
            s.add(Position(portfolio_id=p.id, ticker=ticker, quantity=cantidad, avg_buy_price=1.0))


def test_los_tickers_con_tenencia_de_todas_las_carteras_una_vez(test_db):
    _cartera("Mis Acciones", ("MARA", 100), ("EMBJ", 10), ("VENDIDA", 0))
    _cartera("Tech", ("mara ", 5), ("2357.TW", 1))
    assert hc.tickers_de_las_carteras() == ["2357.TW", "EMBJ", "MARA"]


def test_el_universo_suma_las_carteras_a_la_cuenta_viva_sin_duplicar(test_db, monkeypatch):
    _cartera("Mis Acciones", ("MARA", 100), ("NVDA", 3))
    monkeypatch.setattr(hc, "resolve_universe", lambda account_id=None: ["MU", "NVDA"])
    assert hc.universo_del_harvest() == ["MARA", "MU", "NVDA"]


def test_resolve_universe_sigue_siendo_de_la_cuenta(test_db):
    """La usan también el rebuild de perfiles de sorpresa y `news_feed --watchlist`."""
    from paper_trading.models import PaperAccount, PaperWatchlistItem

    with session_scope() as s:
        acct = PaperAccount(name="Sim Segundo", is_active=True)
        s.add(acct)
        s.flush()
        s.add(PaperWatchlistItem(account_id=acct.id, ticker="MU"))
    _cartera("Mis Acciones", ("MARA", 100))
    assert hc.resolve_universe() == ["MU"]
    assert hc.universo_del_harvest() == ["MARA", "MU"]


def test_el_harvest_le_pide_noticias_a_los_de_la_cartera(test_db, monkeypatch):
    from data.news_sources import _CollectResult

    _cartera("Mis Acciones", ("MARA", 100))
    monkeypatch.setattr(hc, "resolve_universe", lambda account_id=None: ["MU"])
    monkeypatch.setattr(hc, "_ultimo_consenso_por_ticker", lambda: {})
    pedidos = []

    def collector(ticker, sources=None):
        pedidos.append(ticker)
        return _CollectResult()

    rep = hc.harvest(collector=collector, now=datetime(2026, 11, 20, 15, 0), dry_run=True)
    assert sorted(pedidos) == ["MARA", "MU"] and rep.requested == 2


def test_el_universo_de_la_nube_es_el_mismo(test_db, monkeypatch, capsys):
    from scripts import universo_para_nube as un

    _cartera("Mis Acciones", ("MARA", 100))
    monkeypatch.setattr(hc, "resolve_universe", lambda account_id=None: ["MU"])
    assert un.main([]) == 0
    assert "2 tickers" in capsys.readouterr().err
