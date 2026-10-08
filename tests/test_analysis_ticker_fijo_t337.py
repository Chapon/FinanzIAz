"""Tarea 337 — Análisis guardaba «MU — MICRON TECHNOLOGY» como ticker de la opinión de Claude.

El defecto (``docs/auditoria_tanda_2026-10-07.md`` [I-1]): ``_run_analysis`` cortaba el texto del
campo en « — », pero ``_on_analysis_done`` lo releía **sin cortar** al terminar, y ese valor iba a
``opinion_card.set_contexto`` → ``claude_opinions``. Cuatro filas sucias, dos duplicadas contra su
fila limpia del mismo día. Y releerlo al terminar guardaba la opinión de A como B si se escribía
otro ticker mientras corría.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd

import ui.analysis_tab as at


def test_un_solo_lugar_normaliza_el_ticker():
    assert at.ticker_del_campo("MU — MICRON TECHNOLOGY") == "MU"
    assert at.ticker_del_campo("  googl — Alphabet Inc. (Google) ") == "GOOGL"
    assert at.ticker_del_campo("tsla") == "TSLA"
    assert at.ticker_del_campo("") == ""


class _WorkerFalso:
    creados: list = []

    def __init__(self, ticker, period):
        self.ticker = ticker
        self.callbacks = []
        self.done = MagicMock()
        self.done.connect.side_effect = self.callbacks.append
        _WorkerFalso.creados.append(self)

    def start(self):
        pass

    def isRunning(self):
        return False


def _tab_falsa(texto: str):
    tab = MagicMock()
    tab.ticker_edit.text.return_value = texto
    tab.period_combo.currentText.return_value = next(iter(at.PERIODS))
    tab._worker = None
    return tab


def test_el_ticker_se_fija_al_lanzar_y_no_se_relee_al_terminar(monkeypatch):
    _WorkerFalso.creados = []
    monkeypatch.setattr(at, "AnalysisWorker", _WorkerFalso)
    tab = _tab_falsa("MU — MICRON TECHNOLOGY")
    at.AnalysisTab._run_analysis(tab)
    (worker,) = _WorkerFalso.creados
    assert worker.ticker == "MU"
    # Mientras corre, se escribe otro ticker: la opinión de MU no puede guardarse como TSLA.
    tab.ticker_edit.text.return_value = "TSLA — TESLA INC."
    worker.callbacks[0](None, None, None, None, None)
    assert tab._on_analysis_done.call_args.kwargs["ticker"] == "MU"


def _df():
    n = 60
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    c = np.linspace(100.0, 110.0, n)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1e6}, index=idx)


def test_la_opinion_va_con_el_ticker_limpio_aunque_el_campo_tenga_el_nombre(monkeypatch):
    tab = _tab_falsa("MU — MICRON TECHNOLOGY")
    at.AnalysisTab._on_analysis_done(tab, _df(), None, None, {"name": "Micron"}, None, ticker="MU")
    assert tab.opinion_card.set_contexto.call_args.args[0] == "MU"
    # Y sin el ticker del worker (un llamador viejo), normaliza el campo en vez de guardarlo crudo.
    tab = _tab_falsa("MU — MICRON TECHNOLOGY")
    at.AnalysisTab._on_analysis_done(tab, _df(), None, None, {"name": "Micron"}, None)
    assert tab.opinion_card.set_contexto.call_args.args[0] == "MU"
