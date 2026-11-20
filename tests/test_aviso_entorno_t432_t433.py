"""Tareas 432 y 433 — la barra de estado dice cuando la app no corre con lo probado.

- **432**: un intérprete que no es el ``.venv`` (el WARNING de la 401 iba sólo al log, y la app se
  abrió con la Anaconda en los 9 arranques siguientes).
- **433**: ``.py`` sin commitear en el árbol (la opinión de MU del 2026-11-11 salió del WIP de la
  425, y nada lo decía en pantalla).

Nació en la 433 como ``test_aviso_wip_t433.py``; la 432 le sumó el intérprete. El cableado se
prueba con el ``_build_ui`` de verdad sobre una ventana con las pestañas reemplazadas por widgets
vacíos: sacar la llamada de ``main_window`` tiene que dar rojo.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

from config.codigo import EstadoDelCodigo
from ui import aviso_entorno

_APP = QApplication.instance() or QApplication([])

_LIMPIO = EstadoDelCodigo("a" * 40)
_SUCIO = EstadoDelCodigo("a" * 40, ("analysis/opinion_claude.py", "tests/test_x.py"))


def test_sin_WIP_no_hay_aviso():
    assert aviso_entorno.textos_del_aviso(_LIMPIO) == []


def test_con_WIP_dice_cuantos_py_y_el_detalle_los_lista():
    (texto,) = aviso_entorno.textos_del_aviso(_SUCIO)
    assert "WIP" in texto and "2 .py" in texto
    detalle = aviso_entorno.detalle_del_aviso(_SUCIO)
    assert "analysis/opinion_claude.py" in detalle and "tests/test_x.py" in detalle and "aaaaaaa" in detalle


_PESTANIAS = (
    "HomeTab",
    "PortfolioTab",
    "AnalysisTab",
    "LeadsTab",
    "AlertsTab",
    "PaperTradingTab",
    "ReportsTab",
    "FailedTickersTab",
    "SettingsTab",
    "NewsTab",
    "MetricsTab",
)


def _barra_de_la_ventana(monkeypatch, estado, es_venv=True):
    from ui import main_window

    for nombre in _PESTANIAS:
        monkeypatch.setattr(main_window, nombre, QWidget)
    monkeypatch.setattr(main_window, "al_arrancar", lambda: estado)
    # Fijado: el CI no tiene `.venv`, y sin esto la ventana avisaría siempre (tarea 432).
    monkeypatch.setattr(main_window, "es_el_venv", lambda prefix: es_venv)
    ventana = QMainWindow()
    main_window.MainWindow._build_ui(ventana)
    return ventana, ventana.status_bar


def _avisos(barra):
    return [w for w in barra.findChildren(QLabel) if w.objectName() == "aviso_entorno"]


def test_la_ventana_principal_muestra_el_aviso_con_WIP(monkeypatch):
    _ventana, barra = _barra_de_la_ventana(monkeypatch, _SUCIO)
    (aviso,) = _avisos(barra)
    assert "WIP" in aviso.text()


def test_CONTROL_sin_WIP_la_ventana_no_avisa(monkeypatch):
    _ventana, barra = _barra_de_la_ventana(monkeypatch, _LIMPIO)
    assert _avisos(barra) == []


# ── Tarea 432: el intérprete ─────────────────────────────────────────────────

_ANACONDA = os.path.join(os.sep, "anaconda3", "python.exe")


def test_fuera_del_venv_dice_con_que_corre_y_como_abrirla():
    (texto,) = aviso_entorno.textos_del_aviso(_LIMPIO, es_venv=False, executable=_ANACONDA)
    assert "anaconda3" in texto and "abrir_app.bat" in texto
    assert _ANACONDA in aviso_entorno.detalle_del_aviso(_LIMPIO, False, _ANACONDA)


def test_fuera_del_venv_y_con_WIP_avisa_las_dos_cosas():
    textos = aviso_entorno.textos_del_aviso(_SUCIO, es_venv=False, executable=_ANACONDA)
    assert len(textos) == 2


def test_la_ventana_principal_muestra_el_aviso_fuera_del_venv(monkeypatch):
    _ventana, barra = _barra_de_la_ventana(monkeypatch, _LIMPIO, es_venv=False)
    (aviso,) = _avisos(barra)
    assert "abrir_app.bat" in aviso.text()
