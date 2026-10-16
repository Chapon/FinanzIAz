"""Tarea 353 — un harvest con FUENTES CAIDAS ya no cuenta como el del día: se reintenta una vez.

El 2026-10-09 (23:30 local, 10/10 en UTC) el harvest corrió con la red recién vuelta de una
suspensión: `fuentes 0/4 limpias`, FUENTES CAIDAS, y el consenso del 10/10 quedó en 95 de
127 tickers. `refresh_due` sólo miraba si hubo filas nuevas hoy, así que no se reintentó y
los 32 que faltan no se recuperaron.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from analysis import news_digest
from data.news_sources import EstimateSnapshot, SourceOutcome, _CollectResult
from scripts import harvest_catalysts as hc

AHORA = datetime(2026, 10, 10, 2, 30)


def _reporte(*, caida: bool = False, muda: bool = False) -> hc.HarvestReport:
    r = hc.HarvestReport(tickers=127, requested=127)
    for fuente in ("yfinance_estimates", "sec", "finnhub"):
        r.src_run[fuente] = 127
        r.src_con_items[fuente] = 100
    if caida:
        r.src_fail["sec"] = 127
    if muda:
        r.src_run["yfinance_news"] = 127  # contesta ok y sin ítems en todos
    assert r.degraded is caida
    return r


def test_una_corrida_con_FUENTES_CAIDAS_pide_reintento_y_una_sana_no():
    hc.registrar_salud(_reporte(caida=True), AHORA)
    assert hc.harvest_pide_reintento(AHORA)

    hc.registrar_salud(_reporte(), AHORA + timedelta(minutes=30))
    assert not hc.harvest_pide_reintento(AHORA + timedelta(minutes=30))


def test_se_reintenta_UNA_sola_vez():
    hc.registrar_salud(_reporte(caida=True), AHORA)
    hc.registrar_salud(_reporte(caida=True), AHORA + timedelta(minutes=30))

    assert not hc.harvest_pide_reintento(AHORA + timedelta(minutes=31))
    assert hc.leer_estado_harvest()["corridas_degradadas"] == 2


def test_una_fuente_MUDA_no_pide_reintento():
    """Estructural (yfinance_news desde el 2026-10-01): reintentarla no recupera nada."""
    r = _reporte(muda=True)
    assert r.sources_mudas() == ["yfinance_news"]
    hc.registrar_salud(r, AHORA)
    assert not hc.harvest_pide_reintento(AHORA)


def test_el_estado_de_OTRO_dia_no_cuenta():
    hc.registrar_salud(_reporte(caida=True), AHORA - timedelta(days=1))
    assert not hc.harvest_pide_reintento(AHORA)


def test_el_contador_arranca_de_cero_cada_dia():
    hc.registrar_salud(_reporte(caida=True), AHORA - timedelta(days=1))
    hc.registrar_salud(_reporte(caida=True), AHORA - timedelta(days=1, minutes=-30))
    hc.registrar_salud(_reporte(caida=True), AHORA)
    assert hc.harvest_pide_reintento(AHORA)


def test_el_estado_vive_junto_al_settings_de_la_suite_no_en_el_de_la_maquina():
    from config import settings_manager

    assert hc.ruta_estado_harvest().parent == settings_manager._CONFIG_PATH.parent


# ── refresh_due y el harvest de verdad ───────────────────────────────────────


def _colector(caidas: bool):
    def _c(ticker, sources):
        res = _CollectResult()
        res.estimates.append(EstimateSnapshot(ticker, "eps", "0q", 1.0, 10))
        res.outcomes.append(SourceOutcome("yfinance_estimates", "ok", 1))
        res.outcomes.append(
            SourceOutcome("sec", "failed", 0, "OSError: red") if caidas else SourceOutcome("sec", "ok", 0)
        )
        return res

    return _c


@pytest.mark.parametrize("caidas", [True, False])
def test_refresh_due_tras_un_harvest_sintetico(test_db, monkeypatch, caidas):
    """Hubo filas hoy y no hay backlog: antes, `refresh_due` daba falso en los dos casos."""
    from database.models import NewsEvent, session_scope

    with session_scope() as s:
        s.add(
            NewsEvent(
                ticker="AAA", title="t", source="x", content_hash="h", fetched_at=AHORA, event_type="otro"
            )
        )

    hc.harvest(["AAA", "BBB", "CCC", "DDD"], collector=_colector(caidas), now=AHORA, budget_seconds=0)

    assert news_digest.refresh_due(now=AHORA) is caidas


# ── El scheduler ─────────────────────────────────────────────────────────────


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_el_scheduler_des_estampa_el_dia_y_espera_antes_de_reintentar(qapp, monkeypatch):
    from paper_trading import scheduler

    s = scheduler.PaperScheduler()
    lanzados: list[int] = []
    monkeypatch.setattr(s, "_launch_catalyst_refresh", lambda: lanzados.append(1))
    monkeypatch.setattr(news_digest, "refresh_due", lambda: True)
    reloj = {"t": datetime(2026, 10, 10, 2, 30)}
    monkeypatch.setattr(scheduler, "utcnow_naive", lambda: reloj["t"])

    hc.registrar_salud(_reporte(caida=True), reloj["t"])
    s._last_catalyst_refresh = reloj["t"].date()
    s._on_catalyst_completed({"harvest_rc": 0, "classify_rc": 0})

    assert s._last_catalyst_refresh is None
    s._maybe_refresh_catalysts()
    assert lanzados == []  # todavía no pasaron los 30 min

    reloj["t"] += timedelta(minutes=31)
    s._maybe_refresh_catalysts()
    assert lanzados == [1]


def test_un_refresh_SANO_no_programa_nada(qapp, monkeypatch):
    from paper_trading import scheduler

    s = scheduler.PaperScheduler()
    hc.registrar_salud(_reporte(), AHORA)
    s._last_catalyst_refresh = AHORA.date()
    s._on_catalyst_completed({"harvest_rc": 0, "classify_rc": 0})

    assert s._last_catalyst_refresh == AHORA.date()
    assert s._catalyst_retry_after is None
