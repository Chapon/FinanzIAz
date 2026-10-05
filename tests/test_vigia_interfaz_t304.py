"""Tarea 304 — cuando el hilo de la GUI se traba, queda escrito qué lo trababa.

Los casos de verdad corren en un **subproceso**: ``faulthandler.dump_traceback_later`` es global
al proceso, y compartirlo con pytest (que también usa ``faulthandler``) mezclaría los dos. El
subproceso arma una ``QCoreApplication`` con el vigía y un umbral corto, y traba —o no— el hilo
principal con un ``time.sleep``.
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
    import sys, time
    sys.path.insert(0, {repo!r})
    from PyQt6.QtCore import QCoreApplication, QTimer
    from ui.vigia_interfaz import VigiaDeLaInterfaz

    app = QCoreApplication([])
    vigia = VigiaDeLaInterfaz({archivo!r}, umbral_s=0.5, latido_ms=50, parent=app)
    assert vigia.iniciar()

    def funcion_que_traba_la_gui():
        time.sleep({traba})

    QTimer.singleShot(300, funcion_que_traba_la_gui)
    QTimer.singleShot(2500, app.quit)
    app.exec()
    vigia.detener()
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
