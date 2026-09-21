"""Tarea 207 (HARVEST-DICE-FAILED-0-CON-TODO-CAIDO) — el reporte puede acusar.

**Lo medido, y es literal.** Las dos corridas catastróficas del 2026-08-14 —95,0 y 81,8
min con las tres fuentes timeouteando— cerraron con
``Harvest: 52 tickers | news +1 (dup 33) | estimates +0 (dup 261) | failed 0``. **Cero
tickers fallidos**, y a nivel ``INFO``, igual que cualquier día sano.

**La causa.** ``collect_all`` corre cada fuente adentro de su propio ``try`` —*«Each
source is independently guarded — one failing source never sinks the others»*, que es
correcto y deliberado— así que **nunca levanta**. ``report.failed`` sólo cuenta los
tickers cuyo *collector* tira, y eso en producción no pasa casi nunca: el campo existe y
mide algo que no ocurre.

**El umbral está calibrado, no elegido.** Contando las líneas de fallo de cada collector
entre cada *«harvest starting»* y su *«done»* sobre los cinco logs (77 corridas con
reporte): **normales (n=72, sin el 2026-08-14) máx 0,019**; **el desastre 0,98-1,00**.
Las dos poblaciones están separadas ~50× y `SOURCE_FAILURE_ALARM_RATE = 0.20` cae en el
medio. El día malo se excluyó de la calibración **antes** de medir, no después de ver el
resultado — es la diferencia con [[guard-no-puede-usar-de-verdad-lo-que-chequea]].

**Lo que NO es la alarma, a propósito:** ``cero_resultados``. El dedup hace que la
mayoría de los tickers devuelva cero filas nuevas en una corrida sana (los reportes
reales dicen ``news +1 (dup 33)``), y esa tasa normal **no se puede medir con los logs de
hoy**, que no son por ticker. Se reporta como contexto; no es gate.
"""

from __future__ import annotations

import logging

import pytest

from data.news_sources import EstimateSnapshot, NewsItem, SourceOutcome, _CollectResult
from scripts.harvest_catalysts import (
    SOURCE_FAILURE_ALARM_RATE,
    HarvestReport,
    harvest,
)

_FUENTES = ("yfinance_news", "yfinance_estimates", "sec", "finnhub")


def _universo(n: int) -> list[str]:
    return [f"T{i:03d}" for i in range(n)]


def _res(ticker: str, *, fallan: tuple[str, ...] = (), saltean: tuple[str, ...] = (), items: bool = True):
    """Un `_CollectResult` con el veredicto de cada fuente puesto a mano."""
    out = []
    for f in _FUENTES:
        if f in saltean:
            out.append(SourceOutcome(f, "skipped", 0, "de test"))
        elif f in fallan:
            out.append(SourceOutcome(f, "failed", 0, "boom"))
        else:
            out.append(SourceOutcome(f, "ok", 1 if items else 0))
    r = _CollectResult(outcomes=out)
    if items:
        r.news.append(
            NewsItem(ticker=ticker, title=f"n {ticker}", source="yfinance", published_at=None, url=None)
        )
        r.estimates.append(EstimateSnapshot(ticker, "eps", "0q", 1.0, 3))
    return r


def _collector(**kw):
    return lambda ticker, sources=None: _res(ticker, **kw)


# ── El kill-criteria, en sus DOS direcciones ─────────────────────────────────


def test_con_todas_las_fuentes_caidas_el_reporte_LO_DICE(test_db):
    """**La dirección que faltaba el 2026-08-14.** Tres fuentes timeouteando para todos
    los tickers tiene que ser visible en el reporte, no sólo en el traceback."""
    rep = harvest(_universo(20), collector=_collector(fallan=_FUENTES, items=False), budget_seconds=0)

    assert rep.degraded, "con las cuatro fuentes caídas la corrida es degradada"
    assert sorted(rep.sources_alarming()) == sorted(_FUENTES)
    assert rep.source_failure_rates() == {f: 1.0 for f in _FUENTES}
    s = rep.summary()
    assert "FUENTES CAIDAS" in s, s
    assert "20/20" in s, s  # y no dejó de correr sobre nadie: no es un corte


def test_una_corrida_SANA_no_dispara_la_alarma(test_db):
    """**La otra dirección, y es la que hace que la alarma sirva.** Un guard que acusa
    siempre es tan inútil como uno que no acusa nunca."""
    rep = harvest(_universo(20), collector=_collector(), budget_seconds=0)

    assert not rep.degraded
    assert rep.sources_alarming() == []
    assert rep.source_failure_rates() == {f: 0.0 for f in _FUENTES}
    s = rep.summary()
    assert "FUENTES CAIDAS" not in s, s
    assert "fuentes 4/4 limpias" in s, s


def test_el_peor_caso_NORMAL_medido_no_dispara(test_db):
    """La corrida más sucia de las 72 normales: **una** falla de Finnhub en 52 tickers
    (tasa 0,019). Si el umbral acusara eso, acusaría 1 de cada 72 días sanos."""

    def _collect(ticker, sources=None):
        return _res(ticker, fallan=("finnhub",) if ticker == "T000" else ())

    rep = harvest(_universo(52), collector=_collect, budget_seconds=0)
    assert rep.source_failure_rates()["finnhub"] == pytest.approx(1 / 52, abs=1e-6)
    assert not rep.degraded, "0,019 es el peor caso normal medido y NO puede alarmar"


def test_una_fuente_caida_de_cuatro_alarma_solo_por_esa(test_db):
    """El caso que de verdad va a pasar: una fuente se cae y las otras siguen."""
    rep = harvest(_universo(20), collector=_collector(fallan=("finnhub",)), budget_seconds=0)

    assert rep.sources_alarming() == ["finnhub"]
    assert rep.source_failure_rates()["finnhub"] == 1.0
    assert rep.source_failure_rates()["sec"] == 0.0
    assert "finnhub 20/20" in rep.summary()


# ── El umbral, y de qué lado cae cada cosa ───────────────────────────────────


@pytest.mark.parametrize(
    ("caidos", "total", "alarma"),
    [
        (1, 52, False),  # 0,019 — el peor caso normal medido
        (3, 20, False),  # 0,15 — abajo del umbral
        (4, 20, True),  # 0,20 — el umbral es inclusivo
        (20, 20, True),  # 1,00 — el desastre
    ],
)
def test_el_umbral_separa_las_dos_poblaciones(caidos, total, alarma, test_db):
    def _collect(ticker, sources=None):
        idx = int(ticker[1:])
        return _res(ticker, fallan=("finnhub",) if idx < caidos else ())

    rep = harvest(_universo(total), collector=_collect, budget_seconds=0)
    assert rep.degraded is alarma, f"{caidos}/{total} = {caidos / total:.3f}"


def test_el_umbral_esta_en_el_hueco_medido():
    """El número no se puede mover a cualquier lado sin romper una de las dos
    direcciones: arriba de 0,019 (peor normal) y abajo de 0,98 (el desastre)."""
    assert 0.019 < SOURCE_FAILURE_ALARM_RATE < 0.98


# ── `skipped` no es `failed`, y no puede diluir la tasa ──────────────────────


def test_una_fuente_SALTEADA_no_entra_en_el_denominador(test_db):
    """Un ADR sin CIK en EDGAR no dice nada sobre la salud de la fuente: meterlo en el
    denominador diluiría la tasa justo cuando hay que verla.

    El otro ejemplo que decía acá —Finnhub sin key— **ya no es éste**: desde la tarea
    217 es ``unavailable``, porque el motivo es el mismo para los 127 tickers. Sigue
    fuera del denominador, pero ahora además se reporta."""
    rep = harvest(_universo(20), collector=_collector(saltean=("finnhub",)), budget_seconds=0)

    assert "finnhub" not in rep.source_failure_rates(), "una fuente salteada no se mide"
    assert rep.src_run["finnhub"] == 0
    assert not rep.degraded


def test_salteada_en_la_mitad_no_afloja_la_tasa_de_la_otra_mitad(test_db):
    """El caso mixto: la fuente falla en 10 y se saltea en 10. La tasa es 10/10 = 1,0,
    **no** 10/20 = 0,5, porque los salteados no se consultaron."""

    def _collect(ticker, sources=None):
        idx = int(ticker[1:])
        return _res(ticker, fallan=("finnhub",) if idx < 10 else (), saltean=() if idx < 10 else ("finnhub",))

    rep = harvest(_universo(20), collector=_collect, budget_seconds=0)
    assert rep.src_run["finnhub"] == 10
    assert rep.source_failure_rates()["finnhub"] == 1.0
    assert rep.degraded


# ── El nivel del log, que es la otra mitad de "poder acusar" ─────────────────


def test_la_corrida_degradada_sale_a_WARNING(test_db, caplog):
    """El 2026-08-14 el resumen salió a INFO como cualquier día. Para quien lee tres
    meses de log filtrando por nivel, eso es idéntico a que no hubiera pasado nada."""
    with caplog.at_level(logging.INFO, logger="scripts.harvest_catalysts"):
        harvest(_universo(20), collector=_collector(fallan=_FUENTES, items=False), budget_seconds=0)

    resumenes = [r for r in caplog.records if r.getMessage().startswith("Harvest:")]
    assert resumenes, "no salió ningún resumen"
    assert all(r.levelno == logging.WARNING for r in resumenes), [r.levelname for r in resumenes]


def test_la_corrida_sana_sigue_saliendo_a_INFO(test_db, caplog):
    """La contraprueba: si todo saliera a WARNING, el nivel dejaría de informar."""
    with caplog.at_level(logging.INFO, logger="scripts.harvest_catalysts"):
        harvest(_universo(5), collector=_collector(), budget_seconds=0)

    resumenes = [r for r in caplog.records if r.getMessage().startswith("Harvest:")]
    assert resumenes and all(r.levelno == logging.INFO for r in resumenes)


# ── Tickers sin datos: se reporta, no alarma ────────────────────────────────


def test_los_tickers_sin_NADA_se_cuentan_pero_no_alarman(test_db):
    """Con dedup, cero filas nuevas es lo normal — por eso se reporta y no es gate."""
    rep = harvest(_universo(20), collector=_collector(items=False), budget_seconds=0)

    assert len(rep.cero_resultados) == 20
    assert not rep.degraded, "cero filas con todas las fuentes OK es una corrida sana"
    assert "sin datos 20" in rep.summary()


def test_un_ticker_con_datos_no_cuenta_como_sin_datos(test_db):
    def _collect(ticker, sources=None):
        return _res(ticker, items=(ticker == "T000"))

    rep = harvest(_universo(5), collector=_collect, budget_seconds=0)
    assert rep.cero_resultados == ["T001", "T002", "T003", "T004"]


# ── Interacción con el techo de la 204 ──────────────────────────────────────


def test_un_ticker_SALTEADO_por_presupuesto_no_cuenta_en_ninguna_tasa(test_db):
    """Los que el techo dejó sin correr no son ni fallas ni ceros: no se consultaron."""
    import time

    def _collect(ticker, sources=None):
        time.sleep(0.05)
        return _res(ticker, fallan=("finnhub",))

    rep = harvest(_universo(40), collector=_collect, budget_seconds=0.2)
    assert rep.stopped_early
    assert rep.src_run["finnhub"] == rep.tickers, "sólo los que corrieron entran"
    assert len(rep.cero_resultados) == 0
    # Y las dos señales conviven en el resumen.
    s = rep.summary()
    assert "CORTADO por presupuesto" in s and "FUENTES CAIDAS" in s, s


# ── Tolerancia con un collector viejo ───────────────────────────────────────


def test_un_collector_sin_outcomes_no_inventa_salud(test_db):
    """Un collector inyectado que no declara nada deja las tasas vacías — que es honesto.
    Lo contrario (asumir 'ok') fabricaría una corrida sana de la nada."""

    def _collect(ticker, sources=None):
        return _CollectResult(
            news=[NewsItem(ticker=ticker, title="t", source="x", published_at=None, url=None)]
        )

    rep = harvest(_universo(5), collector=_collect, budget_seconds=0)
    assert rep.source_failure_rates() == {}
    assert not rep.degraded
    assert "fuentes" not in rep.summary()


def test_el_reporte_vacio_no_se_declara_degradado():
    assert not HarvestReport().degraded
    assert HarvestReport().source_failure_rates() == {}


# ── El otro extremo: que los collectors REALES digan la verdad ──────────────
#
# Sin esto, todo lo de arriba prueba mi fake. Es el eslabón que hace que la cadena
# signifique algo: si `_finnhub_news` declarara "ok" cuando el request revienta, el
# reporte seguiría diciendo que el día salió bien, con más campos.


class _RespOK:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _SessQueRevienta:
    def get(self, *a, **kw):
        raise ConnectionError("connect timeout")


def test_finnhub_sin_key_es_UNAVAILABLE_no_skipped(monkeypatch):
    """Era ``skipped`` hasta la **tarea 217**, y por eso desaparecía del reporte.

    Sin key la fuente no corre para **ningún** ticker, ni hoy ni nunca — el motivo es
    estructural, no del ticker. Como ``skipped`` quedaba fuera del denominador (bien) y
    también fuera del resumen (mal), así que el 56,6% del volumen de ``news_events`` se
    podía ir a INFO sin que nadie se enterara. Ver ``test_skipped_estructural_t217.py``.
    """
    from data.news_sources import _finnhub_news

    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_TOKEN", raising=False)
    items, o = _finnhub_news("NVDA")
    assert items == [] and o.status == "unavailable" and o.source == "finnhub"
    assert o.unavailable and not o.skipped


def test_finnhub_que_revienta_es_FAILED_con_el_motivo():
    from data.news_sources import _finnhub_news

    items, o = _finnhub_news("NVDA", session=_SessQueRevienta(), api_key="k")
    assert items == [] and o.failed
    assert "ConnectionError" in o.detail, o.detail


def test_finnhub_que_responde_es_OK_con_la_cuenta():
    from data.news_sources import _finnhub_news
    from tests.test_news_sources_t_cat_1 import FINNHUB_PAYLOAD

    class _S:
        def get(self, *a, **kw):
            return _RespOK(FINNHUB_PAYLOAD)

    items, o = _finnhub_news("nvda", session=_S(), api_key="k")
    assert o.status == "ok" and o.items == len(items) == 2


def test_sec_sin_CIK_es_SKIPPED_no_failed():
    """Un ADR o un ETF no cotizan en EDGAR. Contarlo como falla haría que cualquier
    universo con uno pareciera roto todos los días."""
    from data.news_sources import _sec_8k

    items, o = _sec_8k("NOEXISTE", mapping={})
    assert items == [] and o.status == "skipped" and "CIK" in o.detail


def test_sec_que_revienta_es_FAILED():
    from data.news_sources import _sec_8k

    items, o = _sec_8k("NVDA", session=_SessQueRevienta(), mapping={"NVDA": 1045810})
    assert items == [] and o.failed and "ConnectionError" in o.detail


def test_yfinance_news_que_revienta_es_FAILED(monkeypatch):
    import data.yahoo_finance as yh
    from data.news_sources import _yf_news

    def _boom(sym):
        raise TimeoutError("curl 28")

    monkeypatch.setattr(yh, "_ticker", _boom)
    items, o = _yf_news("NVDA")
    assert items == [] and o.failed and o.source == "yfinance_news"


def test_yfinance_news_vacio_pero_sano_es_OK(monkeypatch):
    """La distinción entera de la tarea: `[]` que respondió no es `[]` que se cayó."""
    import data.yahoo_finance as yh
    from data.news_sources import _yf_news

    class _T:
        news = []

    monkeypatch.setattr(yh, "_ticker", lambda s: _T())
    items, o = _yf_news("NVDA")
    assert items == [] and o.status == "ok"


def test_estimates_con_la_fuente_ENTERA_caida_es_failed(monkeypatch):
    """Lo que el ``try`` de afuera sí alcanza: que ``_ticker()`` no resuelva."""
    import data.yahoo_finance as yh
    from data.news_sources import _yf_estimates

    def _boom(sym):
        raise TimeoutError("curl 28")

    monkeypatch.setattr(yh, "_ticker", _boom)
    items, o = _yf_estimates("NVDA")
    assert items == [] and o.failed and o.source == "yfinance_estimates"


def test_una_propiedad_caida_deja_la_fuente_DEGRADED_y_la_NOMBRA(monkeypatch):
    """**Cerrado por la tarea 210 — este test fijaba la limitación y ahora fija el arreglo.**

    Antes decía: *«acá una propiedad revienta y la fuente igual se declara ``ok``»*, y
    era cierto — ``_getattr`` envuelve cada sub-fetch en su propio ``try`` **a propósito**
    (yfinance fetchea de verdad al acceder a la propiedad, y una caída no debe hundir a
    las otras), pero el veredicto no las veía. Eso explica el log del 2026-08-14, donde
    ``yfinance_news`` registró 52 fallas de 52 y ``yfinance_estimates`` **ninguna**.

    Ahora tolerar y **ocultar** dejaron de ser la misma cosa: el ``try`` sigue igual, y
    lo que cambió es que anota. El veredicto es ``degraded`` —no ``failed``, porque la
    fuente contestó— y el ``detail`` **nombra** cuál se cayó, que es lo que convierte
    *«algo anda mal»* en algo accionable.
    """
    import data.yahoo_finance as yh
    from data.news_sources import _yf_estimates

    class _T:
        @property
        def earnings_estimate(self):
            import pandas as pd

            return pd.DataFrame({"avg": [1.0], "numberOfAnalysts": [3]}, index=["0q"])

        @property
        def revenue_estimate(self):
            return None

        @property
        def analyst_price_targets(self):
            raise RuntimeError("boom en UNA propiedad")

        @property
        def info(self):
            return {}

    monkeypatch.setattr(yh, "_ticker", lambda s: _T())
    items, o = _yf_estimates("NVDA")
    assert len(items) > 0, "las propiedades que sí contestaron tienen que entrar"
    assert o.status == "degraded", (
        f"una propiedad caída de cuatro no es la fuente caída, pero tampoco es 'ok': {o}"
    )
    assert "analyst_price_targets" in o.detail, (
        "el veredicto tiene que NOMBRAR la propiedad que se cayó — sin eso, 'degraded' "
        f"es igual de mudo que el 'ok' de antes: {o.detail!r}"
    )
    assert "boom en UNA propiedad" in o.detail, "y el motivo, no sólo el nombre"
    assert "1/4" in o.detail, "cuántas de cuántas, que es lo que dice si es un hipo o un outage"


def test_los_accesores_publicos_devuelven_LO_MISMO_que_la_implementacion(monkeypatch):
    """Los ``collect_*`` son una línea sobre la implementación, así que no pueden
    divergir. Este test es lo que lo fija si alguien los reescribe."""
    import data.yahoo_finance as yh
    from data.news_sources import _yf_news, collect_yfinance_news

    class _T:
        news = []

    monkeypatch.setattr(yh, "_ticker", lambda s: _T())
    assert collect_yfinance_news("NVDA") == _yf_news("NVDA")[0]
