"""Tarea 204 (HARVEST-SIN-TECHO) — el harvest tiene techo de wall-clock y lo reporta.

**Lo medido** (pares *«hourly catalyst harvest starting»*/*«done»* de los cinco logs,
re-medido al abrir la tarea): con los 127 tickers vivos **n=26, mediana 4,7 min, máx
5,8**. El **2026-08-14**, con las tres fuentes timeouteando, dos corridas tardaron
**95,0 y 81,8 min** — y eran los **52** tickers de la cuenta vieja, o sea ~110 s por
ticker. El camino lento **no es el del éxito, es el de la falla**: el harvest tarda más
justo cuando no está trayendo nada.

**Y las dos reportaron `Harvest: 52 tickers | ... | failed 0`**, idéntico a una corrida
sana. El reporte no tenía **ningún** campo que distinguiera un desastre de 95 minutos de
una corrida de 5. Por eso la tarea no es sólo el techo: es el techo **y** que el reporte
diga sobre cuántos tickers corrió de verdad.

**El corte va por ticker** (ver ``_collect_fase1``), así que el sobrepaso es lo que tarde
el último ticker. Estos tests lo fijan con un collector que duerme.

**Lo que NO cubre, y va dicho:** la fase 2 (persistir) queda **fuera** del presupuesto a
propósito — matar la corrida sin escribir lo ya recolectado es el modo de falla que esto
evita, no el que introduce. Es local y corta, pero no está acotada por este número.
"""

from __future__ import annotations

import time

import pytest

from data.news_sources import EstimateSnapshot, NewsItem, _CollectResult
from scripts.harvest_catalysts import (
    HarvestReport,
    harvest,
    resolve_budget_seconds,
)

# Cuánto duerme el collector fake por ticker. Es el análogo del ticker lento real
# (~110 s el 2026-08-14); acá en segundos de test.
_SLEEP = 0.05


def _collector_lento(sleep_s: float = _SLEEP, *, vistos: list[str] | None = None):
    """Collector que duerme por ticker — el instrumento del kill-criteria."""

    def _collect(ticker, sources=None):
        if vistos is not None:
            vistos.append(ticker)
        time.sleep(sleep_s)
        return _CollectResult(
            news=[
                NewsItem(ticker=ticker, title=f"n {ticker}", source="yfinance", published_at=None, url=None)
            ],
            estimates=[],
        )

    return _collect


def _universo(n: int) -> list[str]:
    return [f"T{i:03d}" for i in range(n)]


# ── El kill-criteria ─────────────────────────────────────────────────────────


def test_con_presupuesto_N_vuelve_en_N_mas_un_ticker(test_db):
    """**El kill-criteria.** Con presupuesto de N segundos, ``harvest()`` vuelve en
    ≤ N + el delta declarado (lo que tarde el último ticker) y no en N × tickers.

    Sin el presupuesto este universo tarda ``40 × _SLEEP`` = 2,0 s; con techo de 0,2 s
    tiene que volver en ~0,25.
    """
    universo = _universo(40)
    presupuesto = 0.2
    t0 = time.monotonic()
    rep = harvest(universo, collector=_collector_lento(), budget_seconds=presupuesto)
    elapsed = time.monotonic() - t0

    sin_techo = len(universo) * _SLEEP
    # El delta declarado: un ticker (el que ya estaba corriendo) + holgura de scheduling
    # del runner de CI, que no es tiempo nuestro.
    delta = _SLEEP + 0.35
    assert elapsed <= presupuesto + delta, (
        f"volvió en {elapsed:.2f}s con presupuesto {presupuesto}s "
        f"(techo declarado {presupuesto + delta:.2f}s)"
    )
    assert elapsed < sin_techo, f"{elapsed:.2f}s no es menos que los {sin_techo:.2f}s sin techo"
    # Y volvió temprano por el PRESUPUESTO, no porque el collector se haya salteado
    # trabajo: la única forma de terminar antes es dejar tickers sin correr.
    assert rep.stopped_early and rep.tickers < len(universo)


def test_reporta_los_tickers_que_ALCANZO_no_los_que_se_pidieron(test_db):
    """**La segunda mitad del kill-criteria.** El reporte tiene que decir sobre cuántos
    corrió de verdad. Es lo que faltaba el 2026-08-14: *«52 tickers»* en las dos
    corridas de 95 y 82 minutos, igual que en una sana."""
    universo = _universo(40)
    vistos: list[str] = []
    rep = harvest(universo, collector=_collector_lento(vistos=vistos), budget_seconds=0.2)

    assert rep.requested == 40
    assert rep.stopped_early, "con 40 tickers de 0,05 s y presupuesto 0,2 s tenía que cortar"
    assert rep.tickers == len(vistos), (
        f"el reporte dice {rep.tickers} y el collector se invocó {len(vistos)} veces"
    )
    assert rep.tickers < 40, "no puede haber corrido sobre los 40"
    assert len(rep.skipped) == 40 - rep.tickers
    # Los que no corrieron son el SUFIJO del universo, en orden.
    assert rep.skipped == universo[rep.tickers :]
    assert rep.elapsed_s > 0


def test_el_summary_DICE_que_cortó(test_db):
    """Un corte que no se ve en el log es un corte que nadie va a investigar."""
    rep = harvest(_universo(40), collector=_collector_lento(), budget_seconds=0.2)
    s = rep.summary()
    assert "CORTADO por presupuesto" in s, s
    assert f"/{rep.requested} tickers" in s, s
    assert f"{rep.tickers}/" in s, s


def test_lo_recolectado_ANTES_del_corte_se_persiste(test_db):
    """El modo de falla que esto evita es morir **después** de trabajar, así que la
    fase 2 corre sobre lo que alcanzó a recolectar."""
    from database.models import NewsEvent, session_scope

    universo = _universo(40)
    rep = harvest(universo, collector=_collector_lento(), budget_seconds=0.2)
    assert rep.stopped_early
    assert rep.news_new == rep.tickers, f"{rep.news_new} filas nuevas para {rep.tickers} tickers"

    with session_scope() as s:
        guardados = {r.ticker for r in s.query(NewsEvent).all()}
    assert guardados == set(universo[: rep.tickers])


def test_sin_corte_el_reporte_dice_el_universo_entero(test_db):
    """El camino feliz no cambia: presupuesto holgado ⇒ corre sobre todos y no acusa."""
    rep = harvest(_universo(5), collector=_collector_lento(), budget_seconds=30)
    assert rep.tickers == rep.requested == 5
    assert rep.skipped == []
    assert not rep.stopped_early
    assert "CORTADO" not in rep.summary()


def test_el_dry_run_tambien_tiene_techo(test_db):
    """El dry-run recolecta por la misma red: sin techo tiene el mismo problema."""
    universo = _universo(40)
    t0 = time.monotonic()
    rep = harvest(universo, collector=_collector_lento(), budget_seconds=0.2, dry_run=True)
    elapsed = time.monotonic() - t0
    assert elapsed <= 0.2 + _SLEEP + 0.35, f"{elapsed:.2f}s"
    assert rep.stopped_early
    assert rep.tickers < 40
    assert rep.news_new == rep.tickers


# ── La semántica del 0, fijada por un test y no sólo por el doc ──────────────


@pytest.mark.parametrize("apagado", [0, 0.0, -1, None])
def test_cero_es_SIN_TECHO_no_cortar_ya(apagado, monkeypatch):
    """``0`` es la forma de apagar el mecanismo. La lectura opuesta —«presupuesto cero
    ⇒ no corras nada»— es la trampa de ``paper_whipsaw_min_loss_pct``, donde el valor
    que parece no-op es el más estricto. Acá queda fijado por un test.

    ``None`` cae a settings; se lo mockea para no depender del ``settings.json`` vivo.
    """
    if apagado is None:
        from config.settings_manager import settings

        monkeypatch.setattr(
            settings, "get", lambda k, d=None: 0 if k == "catalyst_harvest_budget_seconds" else d
        )
    assert resolve_budget_seconds(apagado) is None


def test_sin_techo_corre_sobre_TODOS_aunque_tarde(test_db):
    """La contraprueba de arriba de punta a punta: con 0, ningún ticker se saltea."""
    universo = _universo(12)
    rep = harvest(universo, collector=_collector_lento(0.01), budget_seconds=0)
    assert rep.tickers == rep.requested == 12
    assert rep.skipped == []


def test_el_presupuesto_default_sale_de_settings(monkeypatch):
    """Sin argumento, el número sale del flag declarado — no de un literal al lado del
    call site (el defecto de la tarea 154)."""
    from config.settings_manager import settings

    monkeypatch.setattr(
        settings, "get", lambda k, d=None: 777 if k == "catalyst_harvest_budget_seconds" else d
    )
    assert resolve_budget_seconds(None) == 777.0


def test_el_default_declarado_no_muerde_una_corrida_sana():
    """El default tiene que estar holgadamente arriba del camino feliz medido.

    Máximo observado con los 127 tickers vivos: **5,8 min** (n=26). Si el default cayera
    por debajo de ~2× eso, el techo pasaría a cortar corridas sanas — y la cobertura de
    consenso que se pierde **no tiene catch-up** (hallazgo de la 196).
    """
    from config.settings_manager import DEFAULTS

    MAX_CAMINO_FELIZ_S = 5.8 * 60
    assert DEFAULTS["catalyst_harvest_budget_seconds"] >= 2 * MAX_CAMINO_FELIZ_S


def test_un_valor_basura_no_rompe_el_harvest():
    """El presupuesto es un guardrail de ops: si el valor es ilegible, la política
    correcta es correr sin techo (lo de antes), no reventar la corrida."""
    assert resolve_budget_seconds("no-es-un-numero") is None


# ── Contraprueba del instrumento ─────────────────────────────────────────────


def test_el_collector_lento_de_verdad_es_lento(test_db):
    """Si el fake no durmiera, todos los tests de arriba pasarían sin medir nada — el
    defecto de instrumento de la 133 y la 141."""
    t0 = time.monotonic()
    harvest(_universo(6), collector=_collector_lento(), budget_seconds=0)
    assert time.monotonic() - t0 >= 6 * _SLEEP * 0.8


def test_el_reporte_vacio_no_miente():
    """``HarvestReport()`` pelado no puede declarar que corrió sobre nada pedido."""
    r = HarvestReport()
    assert r.tickers == 0 and r.requested == 0 and not r.stopped_early


def test_un_collector_que_revienta_cuenta_como_CORRIDO_no_como_salteado(test_db):
    """``failed`` y ``skipped`` son cosas distintas: uno corrió y falló, el otro nunca
    corrió. Mezclarlos volvería a hacer ilegible el reporte."""

    def _revienta(ticker, sources=None):
        if ticker == "T001":
            raise RuntimeError("boom")
        return _CollectResult(news=[], estimates=[])

    rep = harvest(_universo(3), collector=_revienta, budget_seconds=0)
    assert rep.failed == ["T001"]
    assert rep.skipped == []
    assert rep.tickers == 3


def test_las_estimates_tambien_se_persisten_hasta_el_corte(test_db):
    """El corte no puede dejar a medias el par news/estimates de un ticker recolectado."""
    from database.models import AnalystEstimateSnapshot, session_scope

    def _collect(ticker, sources=None):
        time.sleep(_SLEEP)
        return _CollectResult(
            news=[],
            estimates=[EstimateSnapshot(ticker, "eps", "0q", 1.23, 4)],
        )

    universo = _universo(40)
    rep = harvest(universo, collector=_collect, budget_seconds=0.2)
    assert rep.stopped_early
    with session_scope() as s:
        filas = {r.ticker for r in s.query(AnalystEstimateSnapshot).all()}
    assert filas == set(universo[: rep.tickers])
