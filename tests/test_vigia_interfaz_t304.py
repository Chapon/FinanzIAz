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

    # Tarea 412: se apaga todo DENTRO del loop. Afuera, entre el último latido y ``detener``, el
    # vigía mira una GUI que ya no late; con la máquina cargada eso pasó de 0,5 s.
    def terminar():
        vigia.detener()
        parar.set()
        app.quit()

    QTimer.singleShot(300, funcion_que_traba_la_gui)
    QTimer.singleShot(2500, terminar)
    app.exec()
    """
)


def _correr(tmp_path: Path, traba: float) -> str:
    archivo = tmp_path / "congelamientos.log"
    codigo = _HIJO.format(repo=str(_REPO), archivo=str(archivo), traba=traba)
    subprocess.run([sys.executable, "-c", codigo], check=True, cwd=str(_REPO), timeout=60)
    return archivo.read_text(encoding="utf-8") if archivo.exists() else ""


def _volcados(texto: str) -> list[tuple[str, bool]]:
    """Cada volcado del archivo, y si lo cerró un ``^^^`` (la GUI volvió y midió la traba).

    Tarea 412: con la máquina cargada, el latido de los hilos del hijo se atrasa de verdad más que
    el umbral y el vigía vuelca, bien. Contar los volcados del archivo entero daba rojo por eso.
    """
    out: list[tuple[str, bool]] = []
    for bloque in texto.split("Timeout (")[1:]:
        out.append((bloque, "^^^" in bloque))
    return out


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
    # 1,5 s con umbral 0,5 s: un volcado, no tres. Se cuentan los de la traba —los que hay antes
    # del primer «^^^»—, no los de todo el proceso (tarea 412).
    assert texto.split("^^^", 1)[0].count("Timeout (") == 1, texto


def test_CONTROL_sin_traba_no_vuelca_nada(tmp_path):
    """Sin esto, un vigía que vuelca siempre pasaría el test de arriba.

    Tarea 412: no pide «ningún volcado», que con la máquina cargada era rojo por una demora real;
    pide que todo volcado tenga su traba medida después. El que vuelca siempre vuelca sin traba.
    """
    texto = _correr(tmp_path, traba=0.0)
    assert all(cerrado for _, cerrado in _volcados(texto)), texto
    assert "funcion_que_traba_la_gui" not in texto, texto


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


_ARCHIVO_DEL_9_DE_NOVIEMBRE = """Timeout (0.5 s sin latir)!
Thread 0x00009c7c [GUI] (most recent call first):
  File "<string>", line 30 in funcion_que_traba_la_gui
^^^ 2026-11-09 11:11:10 — la interfaz estuvo trabada 1.5 s (stack en congelamientos.log si pasó de 0.5 s)

Timeout (0.5 s sin latir)!
Thread 0x00009c7c [GUI] (most recent call first):
"""


def test_un_volcado_de_mas_despues_de_la_traba_no_es_de_la_traba():
    """Tarea 412: la forma del archivo que dio rojo en el done de la 394, sin depender de la carga."""
    texto = _ARCHIVO_DEL_9_DE_NOVIEMBRE
    assert texto.count("Timeout (") == 2  # el criterio de antes: rojo
    assert texto.split("^^^", 1)[0].count("Timeout (") == 1  # el de ahora: la traba volcó una vez
    # Y el CONTROL sí lo marcaría: el segundo volcado no tiene su traba medida.
    assert [cerrado for _, cerrado in _volcados(texto)] == [True, False]
