"""Tarea 217 (SKIPPED-ESTRUCTURAL-ES-INVISIBLE) — una fuente caída de raíz se ve.

**La forma, y es la que la 212 sacó de en medio en vez de arreglar.** La **207** decidió
—bien— que ``skipped`` **no entra al denominador** de ``SOURCE_FAILURE_ALARM_RATE``: un
ADR sin CIK en EDGAR no dice nada sobre la salud de la fuente, y meterlo diluiría la tasa
justo cuando hay que verla. Pero eso vale para un skip **por ticker**. Un ``skipped`` del
**100% de los tickers, todas las corridas, para siempre** —porque falta una dependencia o
una key— es una fuente caída de raíz, y el reporte era ciego a eso **por construcción**.

En la **212** el caso se disolvió borrando la rama RSS. Acá no se puede: ``finnhub`` está
en producción —``analysis/news_digest.py`` pasa ``--sources yfinance,sec,finnhub`` en los
dos caminos— y ``_finnhub_news`` devolvía ``skipped`` sin ``FINNHUB_API_KEY``.

**Cuánto se perdería, medido.** De las 59.611 filas de ``news_events`` al 2026-09-21,
**33.741 (56,6%)** vienen de Finnhub. La key que se cae se lleva **más de la mitad** del
volumen de noticias.

**Qué decía el resumen antes, exactamente** — porque el enunciado decía *«indistinguible
de un día sano»* y eso era **sobre-afirmar**. Medido con las cuatro fuentes de producción:

    sano   …| failed 0 | sin datos 0 | fuentes 4/4 limpias
    viejo  …| failed 0 | sin datos 0 | fuentes 3/3 limpias      ← sin key
    nuevo  …| failed 0 | sin datos 0 | fuentes 3/3 limpias | FUENTE NO DISPONIBLE: …

O sea que la única diferencia era el **denominador que se achicaba solo**, y eso no es un
signo que alguien pueda leer: hay que saber de memoria cuántas fuentes se pidieron, y el
mismo número se mueve por motivos que no tienen nada que ver (un universo donde ningún
ticker tenga CIK también deja a ``sec`` fuera de ``src_run``). Lo que sí era literal es el
resto: ``failed 0`` y nivel **INFO**, igual que cualquier día sano.

**El gate calibrado no se toca.** ``unavailable`` no entra a ``SOURCE_FAILURE_ALARM_RATE``
—la fuente no corrió, no tiene tasa de falla— por la misma razón que la 207 dejó afuera a
``cero_resultados`` y la 210 a ``degraded``: meterlo sería inventar un umbral en vez de
calibrarlo. Lo que cambia es que el resumen **lo dice**, y que el renglón sube a WARNING.
"""

from __future__ import annotations

import logging

from data.news_sources import EstimateSnapshot, NewsItem, SourceOutcome, _CollectResult
from scripts.harvest_catalysts import HarvestReport, _anotar_salud, harvest


def _universo(n: int) -> list[str]:
    return [f"T{i:03d}" for i in range(n)]


def _res(ticker: str, *, finnhub: str = "ok", sec: str = "ok"):
    """Un `_CollectResult` con el veredicto de finnhub y sec puesto a mano.

    Las cuatro fuentes son las que produce `--sources yfinance,sec,finnhub`, que es lo
    que corre producción (`analysis/news_digest.py`, los dos caminos).
    """
    motivos = {
        "unavailable": "sin FINNHUB_API_KEY",
        "skipped": "sin CIK",
        "failed": "boom",
    }
    out = [SourceOutcome("yfinance_news", "ok", 1), SourceOutcome("yfinance_estimates", "ok", 1)]
    out.append(SourceOutcome("sec", sec, 1 if sec == "ok" else 0, motivos.get(sec, "")))
    out.append(SourceOutcome("finnhub", finnhub, 1 if finnhub == "ok" else 0, motivos.get(finnhub, "")))
    r = _CollectResult(outcomes=out)
    r.news.append(
        NewsItem(ticker=ticker, title=f"n {ticker}", source="yfinance", published_at=None, url=None)
    )
    r.estimates.append(EstimateSnapshot(ticker, "eps", "0q", 1.0, 3))
    return r


def _collector(**kw):
    return lambda ticker, sources=None: _res(ticker, **kw)


# ── El kill-criteria, en sus DOS direcciones ─────────────────────────────────


def test_sin_key_el_resumen_es_DISTINGUIBLE_del_de_una_corrida_sana(test_db):
    """La dirección que faltaba: pedir finnhub y que no pueda correr tiene que verse."""
    sin_key = harvest(_universo(127), collector=_collector(finnhub="unavailable"), budget_seconds=0)
    sana = harvest(_universo(127), collector=_collector(), budget_seconds=0)

    assert sin_key.summary() != sana.summary()
    assert "FUENTE NO DISPONIBLE: finnhub (sin FINNHUB_API_KEY)" in sin_key.summary()
    assert sin_key.src_unavailable == {"finnhub": "sin FINNHUB_API_KEY"}


def test_con_key_el_resumen_NO_cambia(test_db):
    """La otra dirección, y es la que hace que la línea sirva: un reporte que acusa
    siempre es tan inútil como uno que no acusa nunca."""
    sana = harvest(_universo(127), collector=_collector(), budget_seconds=0)

    assert "FUENTE NO DISPONIBLE" not in sana.summary()
    assert sana.src_unavailable == {}
    assert not sana.hay_fuente_no_disponible


def test_lo_dice_UNA_vez_y_no_127(test_db):
    """El punto (2) del alcance. El motivo es el mismo para los 127 tickers, así que
    decirlo 127 veces sería ruido — y es la razón de que `src_unavailable` sea un `dict`
    por fuente y no un `Counter` por ocurrencia."""
    rep = harvest(_universo(127), collector=_collector(finnhub="unavailable"), budget_seconds=0)

    assert rep.tickers == 127, "los 127 se consultaron: no es un corte por presupuesto"
    assert rep.summary().count("sin FINNHUB_API_KEY") == 1
    assert rep.summary().count("FUENTE NO DISPONIBLE") == 1
    assert len(rep.src_unavailable) == 1


# ── El nivel del log, que es el punto (3) del alcance ────────────────────────


def test_una_fuente_no_disponible_sube_el_resumen_a_WARNING(test_db, caplog):
    """El criterio de la 207: lo raro tiene que destacar. Sin esto el renglón sale a
    INFO y queda indistinguible del ruido normal para quien filtra por nivel."""
    with caplog.at_level(logging.INFO, logger="scripts.harvest_catalysts"):
        harvest(_universo(20), collector=_collector(finnhub="unavailable"), budget_seconds=0)

    resumenes = [r for r in caplog.records if r.getMessage().startswith("Harvest:")]
    assert resumenes, "no salió ningún resumen"
    assert all(r.levelno == logging.WARNING for r in resumenes), [r.levelname for r in resumenes]


def test_la_corrida_sana_sigue_saliendo_a_INFO(test_db, caplog):
    """La contraprueba del nivel: si todo saliera a WARNING, el nivel dejaría de
    informar — que es exactamente lo que la 207 vino a arreglar."""
    with caplog.at_level(logging.INFO, logger="scripts.harvest_catalysts"):
        harvest(_universo(20), collector=_collector(), budget_seconds=0)

    resumenes = [r for r in caplog.records if r.getMessage().startswith("Harvest:")]
    assert resumenes and all(r.levelno == logging.INFO for r in resumenes)


# ── La distinción, que es el punto (1): estructural ≠ por ticker ─────────────


def test_el_skip_POR_TICKER_no_se_reporta_como_fuente_caida(test_db):
    """**La línea que no se puede cruzar.** Un ADR sin CIK en EDGAR es un skip del
    ticker, no de la fuente: si esto apareciera como FUENTE NO DISPONIBLE, el reporte
    acusaría a `sec` todos los días en cualquier universo con un ADR — que es
    exactamente lo que la 207 decidió evitar."""
    rep = harvest(_universo(127), collector=_collector(sec="skipped"), budget_seconds=0)

    assert rep.src_unavailable == {}
    assert "FUENTE NO DISPONIBLE" not in rep.summary()
    assert not rep.hay_fuente_no_disponible


def test_las_dos_formas_a_la_vez_se_reportan_distinto(test_db):
    """El caso mixto, que es donde la distinción se paga: `sec` se saltea por ticker y
    `finnhub` no corrió nunca. Sólo la segunda es una fuente caída."""
    rep = harvest(
        _universo(127),
        collector=_collector(sec="skipped", finnhub="unavailable"),
        budget_seconds=0,
    )

    assert set(rep.src_unavailable) == {"finnhub"}, "sec se salteó por ticker, no de raíz"
    assert "finnhub" in rep.summary() and "sec" not in rep.summary().split("FUENTE NO DISPONIBLE")[1]


# ── El gate calibrado NO se toca (la disciplina de la 207 y la 210) ──────────


def test_unavailable_no_entra_al_denominador_ni_dispara_la_alarma(test_db):
    """`SOURCE_FAILURE_ALARM_RATE` se calibró sobre tasas de falla de fuentes que SÍ
    corrieron. Una que no corrió no tiene tasa, así que meterla al gate sería inventar
    un umbral en vez de calibrarlo — la misma decisión que la 207 con `cero_resultados`
    y la 210 con `degraded`."""
    rep = harvest(_universo(127), collector=_collector(finnhub="unavailable"), budget_seconds=0)

    assert "finnhub" not in rep.source_failure_rates(), "no corrió: no tiene tasa"
    assert rep.src_run["finnhub"] == 0
    assert rep.src_fail["finnhub"] == 0
    assert not rep.degraded, "el gate calibrado no se mueve"
    assert rep.sources_alarming() == []
    # Y las dos condiciones se mantienen separadas: ésta no es aquélla.
    assert rep.hay_fuente_no_disponible and not rep.degraded


def test_unavailable_no_se_cuenta_como_fuente_LIMPIA(test_db):
    """El defecto que la 210 arregló para `degraded`, en su versión de acá: la etiqueta
    para humanos no puede afirmar que está limpio algo que no corrió. `finnhub` queda
    fuera de las dos cuentas, y el renglón dice por qué."""
    rep = harvest(_universo(20), collector=_collector(finnhub="unavailable"), budget_seconds=0)

    assert "fuentes 3/3 limpias" in rep.summary(), rep.summary()
    assert "FUENTE NO DISPONIBLE" in rep.summary()


# ── Los productores declaran el estado; el reporte no lo adivina ─────────────


def test_finnhub_sin_key_declara_UNAVAILABLE(monkeypatch):
    """**El ancla de la mutación.** Volver este `unavailable` a `skipped` —o sea tratar
    el skip estructural como uno por ticker— deja ciego al reporte entero y pone en rojo
    éste y los cuatro de arriba."""
    from data.news_sources import _finnhub_news

    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_TOKEN", raising=False)
    items, o = _finnhub_news("NVDA")

    assert items == []
    assert o.status == "unavailable" and o.unavailable and not o.skipped
    assert "FINNHUB_API_KEY" in o.detail, o.detail


def test_sec_sin_CIK_sigue_declarando_SKIPPED(monkeypatch):
    """La contraparte, y la que impide que el arreglo se pase de largo: el skip por
    ticker **no** se convirtió en estructural de paso."""
    from data.news_sources import _sec_8k

    items, o = _sec_8k("NOEXISTE", mapping={})

    assert items == []
    assert o.status == "skipped" and o.skipped and not o.unavailable


def test_el_motivo_sale_del_detail_del_productor_no_de_adivinarlo(test_db):
    """Decidir «es estructural» leyendo subcadenas del `detail` sería
    [[cross-check-por-substring-acepta-lo-contrario]]: el productor es el único que
    sabe, así que lo **declara** en `status` y el reporte sólo transcribe el motivo."""
    rep = HarvestReport(tickers=1, requested=1)
    res = _CollectResult(outcomes=[SourceOutcome("inventada", "unavailable", 0, "motivo cualquiera")])
    _anotar_salud(rep, "AAPL", res)

    assert rep.src_unavailable == {"inventada": "motivo cualquiera"}
    assert "inventada (motivo cualquiera)" in rep.summary()


def test_un_unavailable_sin_detail_no_rompe_el_resumen(test_db):
    """Fail-open: una fuente futura que declare el estado y se olvide del motivo tiene
    que seguir apareciendo, no desaparecer ni reventar el renglón."""
    rep = HarvestReport(tickers=1, requested=1)
    _anotar_salud(rep, "AAPL", _CollectResult(outcomes=[SourceOutcome("muda", "unavailable", 0)]))

    assert rep.src_unavailable == {"muda": "sin detalle"}
    assert "muda (sin detalle)" in rep.summary()


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
