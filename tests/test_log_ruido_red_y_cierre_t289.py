"""Tarea 289 — dos casos benignos dejaban de escribir cientos de tracebacks en el log.

[L-2] de ``docs/auditoria_logs_2026-10-02.md``: el 2026-09-21, sin internet, cada
``ticker × fuente`` del harvest hizo un ``log.exception`` completo (1.202 tracebacks en un día);
el 2026-09-30, cerrar la app con un ``get_bulk_prices`` en vuelo escribió 48 ERROR
``Parallel fetch failed`` con ``cannot schedule new futures after shutdown``. El volumen entierra
cualquier otro error del log.
"""

from __future__ import annotations

import logging

import pytest
import requests

from data import news_sources as ns
from data import yahoo_finance as yfm

_MAPA = {f"T{i}": 1000 + i for i in range(6)}


class _SesionSinRed:
    def get(self, *_a, **_k):
        raise requests.exceptions.ConnectionError("NameResolutionError: data.sec.gov")


class _SesionQueParseaMal:
    def get(self, *_a, **_k):
        raise ValueError("respuesta rara")


@pytest.fixture(autouse=True)
def _corrida_limpia():
    ns.cerrar_corrida_de_fallas()
    yield
    ns.cerrar_corrida_de_fallas()


def _tracebacks(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.exc_info]


def test_con_la_red_caida_va_UN_traceback_por_fuente_y_el_resto_en_una_linea(caplog):
    with caplog.at_level(logging.INFO, logger=ns.log.name):
        for t in _MAPA:
            _items, salud = ns._sec_8k(t, session=_SesionSinRed(), mapping=_MAPA)
            assert salud.status == "failed", "la salud de la fuente tiene que seguir viendo cada falla"
    assert len(_tracebacks(caplog)) == 1
    lineas = [r for r in caplog.records if "collect_sec_8k failed for" in r.getMessage()]
    assert len(lineas) == len(_MAPA), "cada ticker sigue dejando su línea"
    assert ns.cerrar_corrida_de_fallas() == {"collect_sec_8k": len(_MAPA) - 1}


def test_un_error_que_no_es_de_red_sigue_con_traceback_cada_vez(caplog):
    """Un bug de parseo no es de la fuente: dos tickers pueden romper por razones distintas."""
    with caplog.at_level(logging.INFO, logger=ns.log.name):
        for t in list(_MAPA)[:3]:
            ns._sec_8k(t, session=_SesionQueParseaMal(), mapping=_MAPA)
    assert len(_tracebacks(caplog)) == 3
    assert ns.cerrar_corrida_de_fallas() == {}


def test_cada_corrida_del_harvest_vuelve_a_escribir_su_primer_traceback_y_resume(test_db, caplog):
    from scripts import harvest_catalysts as hc

    def collector(t, _sources):
        _items, salud = ns._sec_8k(t, session=_SesionSinRed(), mapping=_MAPA)
        return ns._CollectResult(outcomes=[salud])

    with caplog.at_level(logging.INFO):
        # Una falla ANTES de la corrida (otro llamador del mismo proceso, p. ej. la app) no
        # puede comerse el primer traceback del harvest.
        ns._sec_8k("T0", session=_SesionSinRed(), mapping=_MAPA)
        for dry_run in (True, False):  # los dos caminos de salida del harvest
            hc.harvest(list(_MAPA), collector=collector, dry_run=dry_run, budget_seconds=600)

    assert len(_tracebacks(caplog)) == 3, "cada corrida tiene que mostrar su primer traceback"
    resumenes = [r.getMessage() for r in caplog.records if "fallas de red sin traceback" in r.getMessage()]
    assert (
        resumenes
        == [f"harvest: fallas de red sin traceback en esta corrida — collect_sec_8k: {len(_MAPA) - 1}"] * 2
    )


def test_cerrar_la_app_con_un_fetch_en_vuelo_no_escribe_ERROR(monkeypatch, caplog):
    def fetch(_ticker, **_kw):
        raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr(yfm, "_fetch_ticker_info", fetch)
    with caplog.at_level(logging.INFO, logger=yfm.log.name):
        out = yfm.get_bulk_prices(["AAA", "BBB"])

    assert out.get("AAA") is None and out.get("BBB") is None
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
    cierre = [r.getMessage() for r in caplog.records if "cierre de la app" in r.getMessage()]
    assert cierre == ["Parallel fetch cortado por el cierre de la app: 2 tickers sin precio (AAA, BBB)"]


def test_otro_RuntimeError_del_fetch_sigue_siendo_ERROR(monkeypatch, caplog):
    def fetch(_ticker, **_kw):
        raise RuntimeError("otra cosa")

    monkeypatch.setattr(yfm, "_fetch_ticker_info", fetch)
    with caplog.at_level(logging.INFO, logger=yfm.log.name):
        yfm.get_bulk_prices(["AAA"])

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        "Parallel fetch failed for AAA"
    ]
