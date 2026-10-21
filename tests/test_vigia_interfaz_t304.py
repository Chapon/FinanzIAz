"""Tarea 304 — cuando el hilo de la GUI se traba, queda escrito qué lo trababa.

Los casos de verdad corren en un **subproceso**: el vigía es un hilo que vive lo que el proceso,
y el hijo le prohíbe ``faulthandler`` (tarea 380), cosa que en el proceso de pytest no se puede.
El subproceso arma una ``QCoreApplication`` con el vigía y un umbral corto, con hilos trabajando,
y traba —o no— el hilo principal con un ``time.sleep``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ui.vigia_interfaz import SUSPENSION_S, describir_atraso

_REPO = Path(__file__).resolve().parent.parent

_HIJO = textwrap.dedent(
    """
    import faulthandler, sys, threading, time
    sys.path.insert(0, {repo!r})

    # Tarea 380: el volcado de faulthandler lee los frames de los otros hilos sin el GIL y
    # mató la app el 2026-10-21. Si el vigía lo vuelve a usar, el hijo revienta acá.
    def _prohibido(*a, **k):
        raise AssertionError("el vigía no puede usar faulthandler (tarea 380)")
    faulthandler.dump_traceback_later = _prohibido

    from PyQt6.QtCore import QCoreApplication, QTimer
    from ui.vigia_interfaz import VigiaDeLaInterfaz

    # Hilos creando y destruyendo frames todo el tiempo, como en el arranque de la app. La pausa
    # de 1 ms es para que no le acaparen el GIL a la GUI: sin ella el latido se atrasaba más que
    # el umbral y el CONTROL volcaba sin traba (2 de 3 corridas).
    parar = threading.Event()
    def hilo_que_trabaja():
        while not parar.is_set():
            sorted(str(i) for i in range(200))
            time.sleep(0.001)
    for _ in range(4):
        threading.Thread(target=hilo_que_trabaja, daemon=True).start()

    app = QCoreApplication([])
    vigia = VigiaDeLaInterfaz({archivo!r}, umbral_s=0.5, latido_ms=50, parent=app)
    assert vigia.iniciar()

    def funcion_que_traba_la_gui():
        time.sleep({traba})

    QTimer.singleShot(300, funcion_que_traba_la_gui)
    QTimer.singleShot(2500, app.quit)
    app.exec()
    vigia.detener()
    parar.set()
    """
)


def _correr(tmp_path: Path, traba: float) -> str:
    archivo = tmp_path / "congelamientos.log"
    codigo = _HIJO.format(repo=str(_REPO), archivo=str(archivo), traba=traba)
    subprocess.run([sys.executable, "-c", codigo], check=True, cwd=str(_REPO), timeout=60)
    return archivo.read_text(encoding="utf-8") if archivo.exists() else ""


def test_una_traba_deja_el_stack_de_la_funcion_que_trababa(tmp_path):
    texto = _correr(tmp_path, traba=1.5)
    assert "funcion_que_traba_la_gui" in texto, texto
    assert "^^^" in texto and "trabada" in texto  # la hora y la duración, al volver


def test_el_stack_de_la_gui_va_primero_y_una_vez_por_traba(tmp_path):
    """Tarea 380: el volcado de la app quedó cortado antes de llegar a la GUI, que era el que importaba."""
    texto = _correr(tmp_path, traba=1.5)
    primer_hilo = texto.split("Thread 0x", 2)[1]
    assert primer_hilo.split("\n", 1)[0].count("[GUI]") == 1, texto
    assert "funcion_que_traba_la_gui" in primer_hilo, texto
    assert texto.count("Timeout (") == 1, texto  # 1,5 s con umbral 0,5 s: un volcado, no tres


def test_CONTROL_sin_traba_no_vuelca_nada(tmp_path):
    """Sin esto, un vigía que vuelca siempre pasaría el test de arriba."""
    assert "Thread" not in _correr(tmp_path, traba=0.0)


@pytest.mark.parametrize(
    "atraso,esperado",
    [
        (0.6, None),
        (2.5, "trabada 2.5 s"),
        (30.0, "trabada 30.0 s"),
        (SUSPENSION_S + 1, "suspendido"),
    ],
)
def test_describir_atraso(atraso, esperado):
    texto = describir_atraso(atraso)
    assert (texto is None) if esperado is None else (esperado in texto)


def test_todo_atraso_que_volco_un_stack_lleva_su_linea_de_hora():
    """Con un umbral de volcado menor que el aviso fijo, el stack quedaba sin la hora."""
    assert describir_atraso(1.0, umbral_s=0.5) is not None
