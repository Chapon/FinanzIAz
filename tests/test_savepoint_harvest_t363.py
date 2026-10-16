"""Tarea 363 — el consenso de un ticker se guarda entero o no se guarda.

``_insert_estimate_if_new_today`` insertaba dentro de un ``begin_nested()``. pysqlite no emite
``BEGIN`` antes de un ``SAVEPOINT``: si el primer write de la sesión era ese savepoint (un
ticker sin noticias nuevas), el ``SAVEPOINT`` abría la transacción y su ``RELEASE`` la
commiteaba, fila por fila. Un error a mitad del ticker dejaba sus primeras filas guardadas
mientras el reporte lo contaba como ``failed``.
"""

from __future__ import annotations

from datetime import datetime

from data.news_sources import EstimateSnapshot, SourceOutcome, _CollectResult
from scripts import harvest_catalysts as hc

AHORA = datetime(2026, 10, 16, 21, 0)


def _consenso():
    from database.models import AnalystEstimateSnapshot, session_scope

    with session_scope() as s:
        return sorted((r.ticker, r.metric) for r in s.query(AnalystEstimateSnapshot))


def _colector(ticker, sources):
    res = _CollectResult()
    for metrica in ("eps", "revenue", "rec_mean"):
        res.estimates.append(EstimateSnapshot(ticker, metrica, "0q", 1.0, 10))
    res.outcomes.append(SourceOutcome("yfinance_estimates", "ok", 3))
    return res  # sin noticias: el primer write de la sesión es el consenso


def test_un_error_en_la_SEGUNDA_fila_no_deja_la_primera(test_db, monkeypatch):
    real = hc._insert_estimate_if_new_today
    llamadas = {"n": 0}

    def _falla_en_la_segunda(session, snap, today, **kw):
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise RuntimeError("se cortó a mitad del ticker")
        return real(session, snap, today, **kw)

    monkeypatch.setattr(hc, "_insert_estimate_if_new_today", _falla_en_la_segunda)

    rep = hc.harvest(["AAA"], collector=_colector, now=AHORA, budget_seconds=0)

    assert rep.failed == ["AAA"]
    assert rep.est_new == 0
    assert _consenso() == []  # con el savepoint quedaba ("AAA", "eps")


def test_el_ticker_sano_guarda_todo_y_repetir_no_duplica(test_db):
    hc.harvest(["AAA"], collector=_colector, now=AHORA, budget_seconds=0)
    rep = hc.harvest(["AAA"], collector=_colector, now=AHORA.replace(hour=22), budget_seconds=0)

    assert _consenso() == [("AAA", "eps"), ("AAA", "rec_mean"), ("AAA", "revenue")]
    assert (rep.est_new, rep.est_dup) == (0, 3)


def test_una_fila_del_dia_con_OTRA_hora_la_frena_el_indice_y_cuenta_como_dup(test_db):
    """El caso que motivó el savepoint (tarea 203): la consulta previa compara el datetime
    exacto y no ve la fila; la frena el UNIQUE por día, y no aborta el resto del ticker."""
    from database.models import AnalystEstimateSnapshot, session_scope

    with session_scope() as s:
        s.add(
            AnalystEstimateSnapshot(
                ticker="AAA", metric="eps", period_label="0q", consensus_value=9.0,
                snapshot_date=datetime(2026, 10, 16, 13, 0),
            )
        )  # fmt: skip

    rep = hc.harvest(["AAA"], collector=_colector, now=AHORA, budget_seconds=0)

    assert (rep.est_new, rep.est_dup, rep.failed) == (2, 1, [])
    assert _consenso() == [("AAA", "eps"), ("AAA", "rec_mean"), ("AAA", "revenue")]
