"""Tarea 414 — el harvest no le pide a Yahoo el consenso de un ticker que ya tiene la foto del día.

``_insert_estimate_if_new_today`` guarda la primera foto del día y descarta las demás; el horario la
pedía en cada corrida para tirarla: del 07/09 al 09/11, 104.895 filas recibidas y 29 nuevas.
"""

from __future__ import annotations

from datetime import datetime

from data.news_sources import EstimateSnapshot, _CollectResult
from database.models import AnalystEstimateSnapshot, session_scope
from scripts import harvest_catalysts as hc

_AHORA = datetime(2026, 11, 20, 15, 0)
_HOY = datetime(2026, 11, 20)


def _foto(ticker: str, dia: datetime) -> None:
    with session_scope() as s:
        s.add(
            AnalystEstimateSnapshot(
                ticker=ticker,
                metric="eps",
                period_label="0q",
                consensus_value=1.0,
                num_analysts=10,
                snapshot_date=dia,
                fetched_at=dia,
            )
        )


def _correr(monkeypatch, universo, sources={"yfinance", "finnhub"}):  # noqa: B006
    monkeypatch.setattr(hc, "universo_del_harvest", lambda account_id=None: list(universo))
    pedidos: dict[str, set] = {}

    def collector(ticker, fuentes=None):
        pedidos[ticker] = set(fuentes) if fuentes else None
        est = []
        if fuentes is None or "yfinance" in fuentes:
            est = [
                EstimateSnapshot(
                    ticker=ticker, metric="eps", period_label="0q", consensus_value=2.0, num_analysts=9
                )
            ]
        return _CollectResult(estimates=est)

    rep = hc.harvest(sources=sources, collector=collector, now=_AHORA)
    return pedidos, rep


def test_con_la_foto_de_hoy_no_se_pide_el_consenso(test_db, monkeypatch):
    _foto("MU", _HOY)
    pedidos, _ = _correr(monkeypatch, ["MU"])
    assert pedidos["MU"] == {"yfinance_news", "finnhub"}


def test_sin_foto_o_con_la_de_ayer_se_pide(test_db, monkeypatch):
    _foto("NVDA", datetime(2026, 11, 19))
    pedidos, rep = _correr(monkeypatch, ["NVDA", "AAPL"])
    assert pedidos["NVDA"] == {"yfinance", "finnhub"} and pedidos["AAPL"] == {"yfinance", "finnhub"}
    assert rep.est_new == 2  # la foto de hoy se toma como siempre


def test_la_foto_que_queda_es_la_primera_del_dia(test_db, monkeypatch):
    """Lo que se guarda no cambia: la primera foto del día, como antes de la 414."""
    _foto("MU", _HOY)
    _correr(monkeypatch, ["MU"])
    with session_scope() as s:
        fotos = s.query(AnalystEstimateSnapshot).filter(AnalystEstimateSnapshot.ticker == "MU").all()
    assert [f.consensus_value for f in fotos] == [1.0]


def test_las_fuentes_por_ticker():
    con = {"MU"}
    assert hc.fuentes_del_ticker({"yfinance", "sec"}, "MU", con) == {"yfinance_news", "sec"}
    assert hc.fuentes_del_ticker(None, "MU", con) == {"yfinance_news"}  # None es {"yfinance"}
    assert hc.fuentes_del_ticker({"yfinance_news", "sec"}, "MU", con) == {"yfinance_news", "sec"}
    assert hc.fuentes_del_ticker({"yfinance"}, "NVDA", con) == {"yfinance"}


def test_con_foto_de_hoy_compara_contra_la_medianoche():
    ultimos = {"MU": _HOY, "NVDA": datetime(2026, 11, 19, 23, 59), "AAPL": None}
    assert hc.con_foto_de_hoy(ultimos, _HOY) == {"MU"}
