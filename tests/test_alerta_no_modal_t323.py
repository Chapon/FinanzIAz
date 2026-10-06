"""Tarea 323 — el aviso de una alerta disparada no bloquea la app.

El defecto (Chapa, 2026-10-06: *«la ui no responde»*): el chequeo automático de alertas (un
``QTimer`` cada 120 s) abría ``QMessageBox.information``, que es **modal**. La ventana principal
quedaba deshabilitada (``IsWindowEnabled = False``) hasta que alguien cerrara el aviso, y Qt lo
había abierto en el segundo monitor (x = 4170 con la app en el primero). El proceso «respondía»
para Windows y el vigía de la 304 no saltó: el bucle de eventos seguía vivo; lo bloqueado era la
ventana.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMainWindow

from ui import alerts_tab

# Una referencia GLOBAL, que vive todo el proceso: un fixture de alcance de módulo soltaba la
# QApplication al terminar el módulo, Qt la destruía y con ella singletons que usan otros tests
# (`_TickerInfoCache` de la tarea 80) — tarea 323.
_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def qapp():
    return _APP


def _aviso(t="AAA", precio=10.0):
    return SimpleNamespace(ticker=t, current_price=precio, alert_type="ABOVE", target_value=9.0, message="")


def test_el_aviso_NO_es_modal_y_la_ventana_sigue_usable(qapp):
    ventana = QMainWindow()
    ventana.setGeometry(100, 100, 1200, 800)
    ventana.show()
    caja = alerts_tab.aviso_no_modal(ventana, "texto")
    try:
        assert caja.isVisible()
        assert caja.windowModality() == Qt.WindowModality.NonModal and not caja.isModal()
        assert ventana.isEnabled()
        assert QApplication.activeModalWidget() is None, "un modal activo bloquea toda la app"
    finally:
        caja.close()
        ventana.close()


def test_el_aviso_va_centrado_sobre_la_ventana_principal(qapp):
    """Qt lo había abierto en el otro monitor: lejos de la ventana, nadie lo ve."""
    ventana = QMainWindow()
    ventana.setGeometry(200, 150, 1200, 800)
    ventana.show()
    caja = alerts_tab.aviso_no_modal(ventana, "texto")
    try:
        c_v, c_c = ventana.frameGeometry().center(), caja.frameGeometry().center()
        assert abs(c_v.x() - c_c.x()) < 40 and abs(c_v.y() - c_c.y()) < 40
    finally:
        caja.close()
        ventana.close()


def test_varias_alertas_del_mismo_chequeo_van_en_UN_aviso(monkeypatch):
    llamadas = []
    caja = SimpleNamespace(destroyed=SimpleNamespace(connect=lambda f: None))
    monkeypatch.setattr(alerts_tab, "aviso_no_modal", lambda v, html: llamadas.append(html) or caja)
    falso = SimpleNamespace(
        _load_alerts=lambda: None,
        status_label=SimpleNamespace(setText=lambda t: None),
        check_btn=SimpleNamespace(setEnabled=lambda b: None),
        window=lambda: None,
        _avisos=[],
    )
    falso._avisar = lambda ns: alerts_tab.AlertsTab._avisar(falso, ns)
    alerts_tab.AlertsTab._on_check_done(falso, [_aviso("PFE"), _aviso("CRM")])
    assert len(llamadas) == 1 and "PFE" in llamadas[0] and "CRM" in llamadas[0]


def test_el_texto_lleva_cada_alerta():
    html = alerts_tab.texto_avisos([_aviso("PFE", 25.5), _aviso("CRM", 300.0)])
    assert "<b>PFE</b>" in html and "$25.5000" in html and "<b>CRM</b>" in html
