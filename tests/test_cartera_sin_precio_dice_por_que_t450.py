"""Tarea 450 — una tenencia sin precio dice por qué en la Cartera, en vez de un «—» mudo.

EA está en la cartera «Tech» y dejó de cotizar en agosto de 2026: la 369 la marcó
``serie_congelada``, ``get_bulk_prices`` la saltea y la fila mostraba «—».
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from data.failed_tickers import OP_SERIE_CONGELADA, FailedTickerRow
from ui import portfolio_tab as pt

_MOTIVO = "La serie diaria (2y) termina el 2026-08-04, hace 78 ruedas: Yahoo dejó de cotizarlo"


def _fila(op: str, error: str | None = _MOTIVO) -> FailedTickerRow:
    t = datetime(2026, 11, 20, 19, 13)
    return FailedTickerRow("EA", error, op, 1, t, t, "failing")


def test_una_serie_congelada_dice_no_cotiza_con_el_motivo():
    assert pt.motivo_sin_precio("ea", {"EA": _fila(OP_SERIE_CONGELADA)}) == ("no cotiza", _MOTIVO)


def test_otra_falla_dice_sin_precio():
    texto, tooltip = pt.motivo_sin_precio("EA", {"EA": _fila("price", "Sin precio")})
    assert (texto, tooltip) == ("sin precio", "Sin precio")
    assert pt.motivo_sin_precio("EA", {"EA": _fila("price", None)})[1] == "Yahoo no devolvió precio"


def test_sin_registro_no_inventa_nada():
    assert pt.motivo_sin_precio("MSFT", {"EA": _fila(OP_SERIE_CONGELADA)}) is None


def _tab(fallidos, precios):
    tab = MagicMock()
    tab._cell = pt.PortfolioTab._cell
    tab._color = pt.PortfolioTab._color
    tab._prices = precios
    tab._fallidos = fallidos
    tab._dividends = {}
    tab._show_dividends = False
    tab._signals = {}
    return tab


def _celda_de_precio(tab):
    return next(c.args[2] for c in tab.table.setItem.call_args_list if c.args[1] == 6)


def test_la_fila_de_la_cartera(qapp):
    pos = SimpleNamespace(ticker="EA", quantity=10.0, avg_buy_price=150.0)
    tab = _tab({"EA": _fila(OP_SERIE_CONGELADA)}, {"EA": None})
    pt.PortfolioTab._render_abierta(tab, 0, pos)
    celda = _celda_de_precio(tab)
    assert celda.text() == "no cotiza" and "2026-08-04" in celda.toolTip()


def test_con_precio_la_fila_es_como_antes(qapp):
    """Aunque haya un registro viejo: si llegó precio, se muestra el precio."""
    pos = SimpleNamespace(ticker="EA", quantity=10.0, avg_buy_price=150.0)
    tab = _tab({"EA": _fila(OP_SERIE_CONGELADA)}, {"EA": {"price": 190.5, "change_pct": 0.1}})
    pt.PortfolioTab._render_abierta(tab, 0, pos)
    assert _celda_de_precio(tab).text() == "$190.50"


def test_al_llegar_los_precios_se_leen_los_motivos(monkeypatch):
    fallidos = {"EA": _fila(OP_SERIE_CONGELADA)}
    monkeypatch.setattr(pt, "fallidos_por_ticker", lambda: fallidos)
    tab = MagicMock()
    pt.PortfolioTab._on_prices_ready(tab, {"EA": None})
    assert tab._fallidos is fallidos
