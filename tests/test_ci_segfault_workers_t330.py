"""Tarea 330 — el segfault intermitente del CI (exit 139).

La anotación del crash (parte 1) lo nombró: un ``AlertCheckWorker`` consultaba la DB en su hilo
mientras el teardown de ``_guard_real_db`` hacía ``engine.dispose()``. Lo arrancaba el ``QTimer``
de 120 s de un ``AlertsTab`` que un test anterior había dejado vivo.
"""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication

from ui.workers import BaseWorker, workers_corriendo

_APP = QApplication.instance() or QApplication([])


class _Lento(BaseWorker):
    def __init__(self, soltar: threading.Event):
        super().__init__()
        self.soltar = soltar
        self.termino = False

    def do_work(self):
        self.soltar.wait(5)
        self.termino = True


def test_antes_de_cerrar_la_DB_se_espera_al_worker_que_corre():
    from tests.conftest import _sin_hilos_de_qt_sobre_la_db

    soltar = threading.Event()
    w = _Lento(soltar)
    w.start()
    assert w in workers_corriendo()
    threading.Timer(0.3, soltar.set).start()
    _sin_hilos_de_qt_sobre_la_db()
    assert w.termino and not w.isRunning(), "se cerraría la DB con el worker adentro"
    assert w.is_cancelled()  # se le pidió que corte, por si hace polling


def test_un_worker_que_ya_termino_no_figura():
    w = _Lento(threading.Event())
    w.soltar.set()
    w.start()
    w.wait(5000)
    assert w not in workers_corriendo()
