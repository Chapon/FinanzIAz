"""Tarea 387 — sin Ollama, el resumen automático dice por qué y que «Actualizar» lo reintenta.

El 2026-10-22 la app arrancó a las 11:22 y a las 11:24 Ollama todavía no aceptaba conexiones;
un minuto después contestaba. La pantalla decía *«Briefing IA no disponible — resumen
automático»*, sin causa ni salida, y el log escribía un ERROR con ~50 líneas de traceback de
urllib3 por algo esperable al arrancar.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import pytest
import requests

import analysis.news_digest as nd
from analysis.news_digest import fallback_briefing, make_ollama_briefer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _items():
    from tests.test_news_digest import _items as items_de_news_digest

    return items_de_news_digest()


def _que_levanta(exc):
    def _post(url, json=None, timeout=None):
        raise exc

    return _post


class _Resp:
    def __init__(self, data=None, roto=False):
        self._data, self._roto = data, roto

    def raise_for_status(self):
        return None

    def json(self):
        if self._roto:
            raise ValueError("no es JSON")
        return self._data


def _propios(caplog):
    return [r for r in caplog.records if r.name == nd.log.name]


@pytest.mark.parametrize(
    "exc",
    [requests.exceptions.ConnectionError("WinError 10061"), ConnectionError("rechazada")],
    ids=["requests", "builtin"],
)
def test_conexion_rechazada_es_un_warning_de_una_linea(caplog, exc):
    caplog.set_level(logging.DEBUG, logger=nd.log.name)
    b = make_ollama_briefer(http_post=_que_levanta(exc))
    assert b(_items()) is None
    assert b.motivo == "no_responde"
    regs = _propios(caplog)
    assert [r.levelno for r in regs] == [logging.WARNING]
    assert regs[0].exc_info is None


def test_timeout_es_un_warning_de_una_linea(caplog):
    caplog.set_level(logging.DEBUG, logger=nd.log.name)
    b = make_ollama_briefer(http_post=_que_levanta(requests.exceptions.ReadTimeout("lento")))
    assert b(_items()) is None
    assert b.motivo == "timeout"
    assert [(r.levelno, r.exc_info) for r in _propios(caplog)] == [(logging.WARNING, None)]


def test_una_respuesta_mal_formada_sigue_con_traceback(caplog):
    caplog.set_level(logging.DEBUG, logger=nd.log.name)
    b = make_ollama_briefer(http_post=lambda url, json=None, timeout=None: _Resp(roto=True))
    assert b(_items()) is None
    assert b.motivo == "error"
    regs = _propios(caplog)
    assert [r.levelno for r in regs] == [logging.ERROR]
    assert regs[0].exc_info is not None


def test_una_respuesta_vacia_y_un_exito_dejan_su_motivo(caplog):
    vacio = make_ollama_briefer(
        http_post=lambda url, json=None, timeout=None: _Resp({"message": {"content": " "}})
    )
    assert vacio(_items()) is None
    assert vacio.motivo == "vacio"
    ok = make_ollama_briefer(
        http_post=lambda url, json=None, timeout=None: _Resp({"message": {"content": "Hola."}})
    )
    assert ok(_items()) == "Hola."
    assert ok.motivo is None


def test_el_motivo_se_resetea_en_cada_llamada():
    respuestas = iter([ConnectionError("x"), None])

    def _post(url, json=None, timeout=None):
        r = next(respuestas)
        if r is not None:
            raise r
        return _Resp({"message": {"content": "Ahora sí."}})

    b = make_ollama_briefer(http_post=_post)
    assert b(_items()) is None and b.motivo == "no_responde"
    assert b(_items()) == "Ahora sí." and b.motivo is None


def test_el_resumen_dice_la_causa_la_hora_y_la_salida():
    texto = fallback_briefing(_items(), motivo="no_responde", cuando=datetime(2026, 10, 22, 11, 24))
    assert "Ollama no respondía a las 11:24" in texto
    assert "«Actualizar» lo reintenta" in texto
    assert "Briefing IA no disponible" not in texto


def test_sin_motivo_el_resumen_queda_como_antes():
    """Con el LLM apagado no hubo falla que contar."""
    assert fallback_briefing(_items()).endswith("(Briefing IA no disponible — resumen automático.)")


# ── La pestaña ───────────────────────────────────────────────────────────────


@pytest.fixture
def pestaña(test_db):
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    global _APP
    _APP = QApplication.instance() or QApplication([])
    from ui.news_tab import NewsTab

    t = NewsTab()
    yield t
    t.deleteLater()


@pytest.mark.parametrize(("fallido", "refresca"), [(True, True), (False, False)])
def test_al_volver_a_la_pestaña_reintenta_si_fallo_ollama(pestaña, monkeypatch, fallido, refresca):
    llamadas = []
    monkeypatch.setattr(pestaña, "refresh", lambda: llamadas.append(1))
    pestaña._last_loaded = datetime.utcnow()  # recién cargada: por edad no refrescaría
    pestaña._on_briefing_ready("texto", fallido)
    pestaña.maybe_refresh()
    assert bool(llamadas) is refresca


@pytest.mark.parametrize(
    ("use_llm", "motivo", "fallido"),
    [(True, "no_responde", True), (True, None, False), (False, None, False)],
    ids=["ollama_caido", "ollama_ok", "llm_apagado"],
)
def test_el_worker_avisa_si_fallo_ollama(pestaña, monkeypatch, use_llm, motivo, fallido):
    import ui.news_tab as nt

    def _briefer_falso():
        def b(items):
            return None if motivo else "Briefing."

        b.motivo = motivo
        return b

    monkeypatch.setattr(nt, "fetch_news_window", lambda since, until=None: [])
    monkeypatch.setattr(nt, "classify_missing", lambda rows: rows)
    monkeypatch.setattr(nt, "rank_news", lambda rows: _items())
    monkeypatch.setattr(nt, "make_ollama_briefer", _briefer_falso)
    w = nt.NewsDigestWorker(days=1, use_llm=use_llm)
    recibidos = []
    w.briefing_ready.connect(lambda texto, f: recibidos.append((texto, f)))
    w.do_work()
    assert [f for _, f in recibidos] == [fallido]
    if motivo:
        assert "Ollama no respondía a las" in recibidos[0][0]
