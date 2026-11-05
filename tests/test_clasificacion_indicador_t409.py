"""Tarea 409 — el indicador de la barra de estado dice que la app está clasificando, y Detener/Reanudar."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication

from ui.clasificacion_indicador import ClasificacionIndicador

# Global a propósito: soltar la QApplication al terminar el módulo rompe a otros tests (tarea 323).
_APP = QApplication.instance() or QApplication([])


class _Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _ind():
    reloj = _Reloj()
    return ClasificacionIndicador(reloj=reloj), reloj


def test_oculto_hasta_que_arranca_y_visible_mientras_clasifica():
    ind, _ = _ind()
    assert ind.isHidden()
    ind.iniciar()
    assert not ind.isHidden()
    assert "cosechando" in ind.label.text()
    ind.avance(0, 14154, 0)
    assert ind.label.text() == "Clasificando noticias: 0 de 14.154"
    assert ind.boton.text() == "Detener"


def test_el_avance_estima_el_tiempo_restante():
    ind, reloj = _ind()
    ind.iniciar()
    ind.avance(0, 1000, 0)
    reloj.t = 300.0  # 100 filas en 5 min → 900 restantes ≈ 45 min
    ind.avance(100, 1000, 0)
    assert ind.label.text() == "Clasificando noticias: 100 de 1.000 (≈ 45 min)"
    reloj.t = 600.0
    ind.avance(200, 10000, 0)  # 200 en 10 min → 9.800 ≈ 490 min
    assert "(≈ 8 h 10 min)" in ind.label.text()


def test_dice_cuando_cae_a_la_heuristica():
    ind, _ = _ind()
    ind.avance(10, 100, 3)
    assert "3 con heurística" in ind.label.text()


def test_detener_emite_y_bloquea_el_boton_hasta_que_termina():
    ind, _ = _ind()
    pedidos = []
    ind.detener_pedido.connect(lambda: pedidos.append("detener"))
    ind.iniciar()
    ind.avance(40, 100, 0)
    ind.boton.click()
    assert pedidos == ["detener"]
    assert not ind.boton.isEnabled()
    ind.avance(50, 100, 0)  # un checkpoint que llega después del pedido no lo pisa
    assert ind.estado == "deteniendo"


def test_detenido_ofrece_reanudar_con_lo_que_falta():
    ind, _ = _ind()
    pedidos = []
    ind.reanudar_pedido.connect(lambda: pedidos.append("reanudar"))
    ind.iniciar()
    ind.avance(40, 100, 0)
    ind.boton.click()
    ind.terminado({"harvest_rc": 0, "classify_rc": 0, "detenido": True})
    assert ind.estado == "detenido"
    assert ind.label.text() == "Clasificación detenida: quedan 60 sin clasificar"
    assert ind.boton.text() == "Reanudar" and ind.boton.isEnabled()
    ind.boton.click()
    assert pedidos == ["reanudar"]


def test_al_dia_desaparece():
    ind, _ = _ind()
    ind.iniciar()
    ind.avance(100, 100, 0)
    ind.terminado({"harvest_rc": 0, "classify_rc": 0, "detenido": False})
    assert ind.isHidden()
