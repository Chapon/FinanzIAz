"""Tarea 354 (YF-NEWS-VACIO-EN-SILENCIO) — una fuente que contesta vacía para TODOS es una caída.

**Lo medido.** Desde el 2026-10-01 ``finance.yahoo.com/xhr/ncp`` —el endpoint de
``Ticker.news`` en yfinance 1.4.1 y en el 1.7.0— contesta ``404 {"message":"Not Found"}``,
y yfinance devuelve ``[]`` sin levantar. ``_yf_news`` lo declaraba ``ok``, la tasa de falla
quedaba en cero y el resumen del 2026-10-11 dijo ``fuentes 4/4 limpias`` a ``INFO``.

**El caso que no tiene que disparar** es un ticker sin noticias en una corrida sana: la
alarma es "cero en TODOS", no "cero en alguno". Y una corrida a mano sobre pocos tickers no
alcanza para afirmar nada (``MIN_TICKERS_PARA_FUENTE_MUDA``).
"""

from __future__ import annotations

import logging

import pytest

from data.news_sources import NewsItem, SourceOutcome, _CollectResult
from scripts.harvest_catalysts import (
    FUENTES_QUE_NO_VIENEN_VACIAS,
    MIN_TICKERS_PARA_FUENTE_MUDA,
    HarvestReport,
    harvest,
)

_FUENTES = ("yfinance_news", "yfinance_estimates", "sec", "finnhub")


def _universo(n: int) -> list[str]:
    return [f"T{i:03d}" for i in range(n)]


def _collector(vacias_en: dict[str, set[str] | None]):
    """``vacias_en[fuente]``: los tickers donde la fuente contesta ``ok`` con 0 ítems
    (``None`` = en todos). Las demás fuentes traen un ítem."""

    def _c(ticker, sources=None):
        out = []
        for f in _FUENTES:
            vacia = f in vacias_en and (vacias_en[f] is None or ticker in vacias_en[f])
            out.append(SourceOutcome(f, "ok", 0 if vacia else 1))
        r = _CollectResult(outcomes=out)
        r.news.append(
            NewsItem(ticker=ticker, title=f"n {ticker}", source="finnhub:x", published_at=None, url=None)
        )
        return r

    return _c


# ── El kill-criteria, en sus dos direcciones ─────────────────────────────────


def test_yfinance_news_en_cero_para_TODOS_sale_como_muda(test_db):
    """La forma literal del 2026-10-01 en adelante."""
    rep = harvest(_universo(30), collector=_collector({"yfinance_news": None}), budget_seconds=0)

    assert rep.sources_mudas() == ["yfinance_news"]
    s = rep.summary()
    assert "FUENTES MUDAS: yfinance_news 0/30 con items" in s, s
    assert "fuentes 3/4 limpias" in s, "una fuente muda no puede contarse como limpia"


def test_un_SOLO_ticker_vacio_no_la_declara_muda(test_db):
    rep = harvest(_universo(30), collector=_collector({"yfinance_news": {"T007"}}), budget_seconds=0)

    assert rep.sources_mudas() == []
    assert "MUDAS" not in rep.summary()
    assert "fuentes 4/4 limpias" in rep.summary()


def test_todos_vacios_menos_UNO_tampoco_es_muda(test_db):
    """El umbral es "cero en todos": con un ticker que trajo algo, la fuente responde."""
    vacios = set(_universo(30)) - {"T029"}
    rep = harvest(_universo(30), collector=_collector({"yfinance_news": vacios}), budget_seconds=0)
    assert rep.sources_mudas() == []


def test_la_muda_sale_a_WARNING_y_la_sana_a_INFO(test_db, caplog):
    with caplog.at_level(logging.INFO, logger="scripts.harvest_catalysts"):
        harvest(_universo(30), collector=_collector({"yfinance_news": None}), budget_seconds=0)
        harvest(_universo(30), collector=_collector({"yfinance_news": {"T007"}}), budget_seconds=0)

    niveles = [r.levelno for r in caplog.records if r.getMessage().startswith("Harvest:")]
    assert niveles == [logging.WARNING, logging.INFO], niveles


# ── El mínimo de tickers ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "n, muda",
    [(MIN_TICKERS_PARA_FUENTE_MUDA - 1, False), (MIN_TICKERS_PARA_FUENTE_MUDA, True)],
)
def test_debajo_del_minimo_no_se_afirma_nada(n, muda, test_db):
    rep = harvest(_universo(n), collector=_collector({"yfinance_news": None}), budget_seconds=0)
    assert bool(rep.sources_mudas()) is muda


def test_el_minimo_es_el_declarado():
    """Fija el valor: bajarlo a 1 haría que una corrida de un ticker sin noticias alarme,
    subirlo deja pasar corridas chicas. Un cambio tiene que pasar por acá."""
    assert MIN_TICKERS_PARA_FUENTE_MUDA == 10


# ── Qué fuentes entran, y cómo convive con las otras alarmas ──────────────────


def test_sec_en_cero_para_todos_NO_es_muda(test_db):
    """En 11 de 43 días de harvest no entró ningún 8-K: la ventana de EDGAR vacía es normal."""
    assert "sec" not in FUENTES_QUE_NO_VIENEN_VACIAS
    rep = harvest(_universo(30), collector=_collector({"sec": None}), budget_seconds=0)
    assert rep.sources_mudas() == []


@pytest.mark.parametrize("fuente", ["yfinance_estimates", "finnhub"])
def test_las_otras_fuentes_que_siempre_traen_tambien_se_vigilan(fuente, test_db):
    rep = harvest(_universo(30), collector=_collector({fuente: None}), budget_seconds=0)
    assert rep.sources_mudas() == [fuente]


def test_una_fuente_ya_CAIDA_no_se_repite_como_muda():
    rep = HarvestReport()
    rep.src_run["yfinance_news"] = 30
    rep.src_fail["yfinance_news"] = 30
    assert rep.sources_alarming() == ["yfinance_news"]
    assert rep.sources_mudas() == []


def test_los_fallidos_no_cuentan_para_el_minimo():
    """Once consultas, dos fallidas (18%, debajo del umbral de caída) y nueve que contestaron
    vacías: de las que contestaron no hay diez, así que no se afirma que esté muda."""
    rep = HarvestReport()
    rep.src_run["yfinance_news"] = 11
    rep.src_fail["yfinance_news"] = 2
    assert rep.sources_alarming() == []
    assert rep.sources_mudas() == []
    rep.src_run["yfinance_news"] = 12  # diez contestaron: ahora sí
    assert rep.sources_mudas() == ["yfinance_news"]
