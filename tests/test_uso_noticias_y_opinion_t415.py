"""Tarea 415 — el log registra cuándo se entra a la pestaña Noticias y cuándo se pide una opinión.

La 413 no pudo saber si alguien mira la pestaña: es lo único que usa la clasificación de qwen
(49,6 h de GPU en dos meses). Al cabo de cuatro semanas, ``grep "USO "`` en el log decide.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock


def _usos(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("USO ")]


def test_entrar_a_la_pestana_deja_la_linea_y_refresca(caplog):
    from ui.news_tab import NewsTab

    tab = MagicMock()
    with caplog.at_level(logging.INFO):
        NewsTab.al_mostrarse(tab)
    assert _usos(caplog) == ["USO pestaña Noticias: abierta (tarea 415)"]
    tab.maybe_refresh.assert_called_once()


def test_la_navegacion_de_la_ventana_pasa_por_ahi():
    """Entrar con los datos frescos no refresca: la línea tiene que salir de la navegación."""
    from ui.main_window import MainWindow

    win = MagicMock()
    win._PAGE_IDX = {}
    win.PAGE_TITLES = {}
    MainWindow._navigate(win, "news")
    win.news_tab.al_mostrarse.assert_called_once()


def test_cargar_la_pestana_dice_cuantas_noticias(caplog):
    from ui.news_tab import NewsTab

    tab = MagicMock()
    tab.days_input.value.return_value = 3
    with caplog.at_level(logging.INFO):
        NewsTab._on_rows_ready(tab, ["a", "b"])
    assert _usos(caplog) == ["USO pestaña Noticias: cargada con 2 noticias de 3 día(s) (tarea 415)"]


def test_pedir_una_opinion_deja_la_linea(caplog, monkeypatch):
    from ui.analysis import opinion_card as oc_ui

    card = MagicMock()
    card._armar_datos = lambda: {}
    card._worker = None
    card._ticker = "NVDA"
    monkeypatch.setattr(oc_ui, "OpinionWorker", MagicMock())
    with caplog.at_level(logging.INFO):
        oc_ui.OpinionCard.pedir(card)
    assert _usos(caplog) == ["USO opinión de Claude: pedida para NVDA (tarea 415)"]
