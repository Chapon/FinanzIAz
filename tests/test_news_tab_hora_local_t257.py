"""Tarea 257 — la pestaña Noticias muestra la hora de publicación en hora LOCAL.

``published_at`` se guarda en UTC naive, como todo lo que persiste la app, y la celda lo
formateaba con ``strftime`` directo: *«Accenture (ACN) Tops Q4…»*, publicada a las 06:45 ET,
salía como 10:45 (en Argentina eran las 07:45).

El test no compara contra la hora local de la máquina: en el CI la zona es UTC y ahí la versión
defectuosa y la correcta dan lo mismo. Reemplaza ``fmt_local`` por un centinela y verifica que
la celda pase por él.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication

from analysis.news_digest import DigestItem


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _item(published_at):
    return DigestItem(
        news_id=1,
        ticker="ACN",
        title="Accenture (ACN) Tops Q4 Earnings",
        source="finnhub:Yahoo",
        url=None,
        published_at=published_at,
        event_type="earnings_results",
        sentiment="positive",
        classifier_confidence=0.6,
        impact=0.36,
        direction=1,
        basis="prior",
    )


def test_la_hora_de_la_celda_pasa_por_fmt_local(qapp, monkeypatch):
    import ui.news_tab as nt

    vistos = []

    def centinela(dt, fmt="%d/%m %H:%M"):
        vistos.append((dt, fmt))
        return "HORA-LOCAL"

    monkeypatch.setattr(nt, "fmt_local", centinela)
    tab = nt.NewsTab()
    utc = datetime(2026, 10, 1, 10, 45, 1)
    tab._populate_table([_item(utc)])
    assert tab.table.item(0, 0).text() == "HORA-LOCAL"
    assert vistos == [(utc, "%m-%d %H:%M")]


def test_sin_fecha_sigue_mostrando_guion(qapp):
    import ui.news_tab as nt

    tab = nt.NewsTab()
    tab._populate_table([_item(None)])
    assert tab.table.item(0, 0).text() == "—"
