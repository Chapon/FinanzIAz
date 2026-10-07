"""Tarea 329 — las posiciones de la cartera real toman el nombre de empresa del cache, sin red.

Después del reemplazo de la 324, KO, MARA, MO y MSFT quedaron sin nombre y EMBJ seguía como
«ERJ» (su símbolo viejo). Un nombre escrito a mano no se pisa: ése es el caso que distingue un
completado de un pisado.
"""

from __future__ import annotations

from database.cartera_real import _parece_ticker, completar_nombres
from database.models import CompanyInfoCache, Portfolio, Position, session_scope


def _cartera():
    with session_scope() as s:
        pf = Portfolio(name="Mis Acciones")
        s.add(pf)
        s.flush()
        for t, nombre in (("KO", None), ("EMBJ", "ERJ"), ("MSFT", "Mi Microsoft"), ("ZZZ", None)):
            s.add(
                Position(portfolio_id=pf.id, ticker=t, quantity=1.0, avg_buy_price=1.0, company_name=nombre)
            )
        for t, nombre, sector in (
            ("KO", "The Coca-Cola Company", "Consumer Defensive"),
            ("EMBJ", "Embraer S.A.", "Industrials"),
            ("MSFT", "Microsoft Corporation", "Technology"),
        ):
            s.add(CompanyInfoCache(ticker=t, name=nombre, sector=sector))
        return pf.id


def test_completa_los_vacios_y_los_simbolos_y_NO_pisa_un_nombre_propio(test_db):
    pid = _cartera()
    with session_scope() as s:
        cambios = completar_nombres(s, pid)
    assert cambios == [("EMBJ", "ERJ", "Embraer S.A."), ("KO", None, "The Coca-Cola Company")]
    with session_scope() as s:
        por = {p.ticker: (p.company_name, p.sector) for p in s.query(Position)}
    assert por["MSFT"] == ("Mi Microsoft", None)  # escrito a mano: queda
    assert por["KO"] == ("The Coca-Cola Company", "Consumer Defensive")
    assert por["ZZZ"] == (None, None)  # sin cache: no se inventa


def test_que_es_un_simbolo():
    assert _parece_ticker("ERJ") and _parece_ticker("BRK.B")
    assert not _parece_ticker("Embraer S.A.") and not _parece_ticker("NVIDIA Corporation")
    assert not _parece_ticker(None) and not _parece_ticker("")
