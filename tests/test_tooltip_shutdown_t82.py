"""Tarea 82 — cerrar con un fetch de tooltip en vuelo no puede matar al proceso.

El síntoma era el peor posible: **todos los tests en verde y exit 127**. Un
proceso que muere *después* de pasar no señala a nada, y por eso las pestañas con
tooltip no se podían cubrir con tests.

El diagnóstico, medido 2×2 con tres corridas por celda (fetch en vuelo,
`QApplication` real, cierre por ``app.quit()``):

===========================  ==========  ==========
modo                         n=2         n=8
===========================  ==========  ==========
sin nada                     **127 ×3**  **127 ×3**
sólo la bandera              0 ×3        0 ×3
bandera + ``waitForDone``    0 ×3        0 ×3
===========================  ==========  ==========

O sea: **lo que mata al proceso es el `emit`**, no los hilos corriendo. El
destructor del ``QThreadPool`` global espera igual a los runnables, así que
despiertan con el intérprete ya bajando y emiten sobre un ``QObject`` a medio
destruir. El drenado *no* era necesario — contra lo que suponía el enunciado — y
tampoco cuesta: medido, el cierre tarda ~3,1 s con y sin él, porque Qt ya
esperaba.

El test de abajo corre el escenario en un **subproceso**: es la única forma de
afirmar algo sobre un código de salida.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")

import ui.ticker_tooltip as tt

ROOT = Path(__file__).resolve().parent.parent

_ESCENARIO = """
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["FINANZIAS_LOG_FILE"] = ""
# El escenario simula LA APP, no un proceso de test: los fetch tienen que estar
# prendidos. Sin esto el subproceso hereda el apagado del conftest y el control
# negativo pasaría por no reproducir nada.
os.environ.pop("FINANZIAS_DISABLE_TICKER_FETCH", None)
sys.path.insert(0, {root!r})
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import data.yahoo_finance as yf
yf.get_company_info = lambda t: (time.sleep(0.6), {{"name": t}})[1]
import ui.ticker_tooltip as tt
for t in ("AAPL", "MSFT", "NVDA"):
    tt.ticker_cache.get(t)
QTimer.singleShot(50, app.quit)
app.exec()
{cierre}
"""


def _correr(cierre: str) -> int:
    src = textwrap.dedent(_ESCENARIO).format(root=str(ROOT), cierre=cierre)
    return subprocess.run([sys.executable, "-c", src], capture_output=True, timeout=120).returncode


@pytest.mark.skipif(os.environ.get("CI_SKIP_SUBPROCESS") == "1", reason="subproceso deshabilitado")
def test_cerrar_con_un_fetch_en_vuelo_sale_limpio():
    """EL GUARD: con ``shutdown()``, el proceso termina en 0 aunque haya fetch en vuelo.

    Es el escenario real —la app se cierra mientras un tooltip está buscando el
    nombre de una empresa— y el único que puede afirmar algo sobre un código de
    salida, porque hay que mirarlo desde afuera.
    """
    assert _correr("tt.shutdown()") == 0


def test_el_escenario_sin_el_arreglo_sigue_siendo_el_defecto():
    """Y sin cortar los fetch, el proceso **muere**: si esto pasara a 0, el guard
    de arriba dejaría de probar nada y nadie se enteraría."""
    assert _correr("pass") != 0


# ── Contrato de shutdown(), sin subprocesos ──────────────────────────────────


def test_shutdown_prende_la_bandera():
    previo = tt._SHUTTING_DOWN
    try:
        tt._SHUTTING_DOWN = False
        tt.shutdown(0)
        assert tt._SHUTTING_DOWN is True
    finally:
        tt._SHUTTING_DOWN = previo


def test_un_runnable_no_emite_despues_del_apagado(monkeypatch):
    """La línea que arregla la tarea: con la bandera puesta, el runnable vuelve mudo."""

    class _Espia:
        def __init__(self):
            self.emitidos = []

        def emit(self, *a):
            self.emitidos.append(a)

    espia = _Espia()
    señales = type("S", (), {"fetched": espia})()
    monkeypatch.setattr(tt, "_SHUTTING_DOWN", True)
    tt._FetchRunnable("AAPL", señales).run()
    assert espia.emitidos == []


def test_un_runnable_si_emite_en_operacion_normal(monkeypatch):
    """Sanity: sin la bandera el camino normal sigue funcionando — si no, el test
    de arriba pasaría por estar todo roto."""

    class _Espia:
        def __init__(self):
            self.emitidos = []

        def emit(self, *a):
            self.emitidos.append(a)

    espia = _Espia()
    señales = type("S", (), {"fetched": espia})()
    monkeypatch.setattr(tt, "_SHUTTING_DOWN", False)
    monkeypatch.setattr("data.yahoo_finance.get_company_info", lambda t: {"name": t})
    tt._FetchRunnable("AAPL", señales).run()
    assert [a[0] for a in espia.emitidos] == ["AAPL"]


def test_la_app_lo_llama_al_cerrar():
    """El arreglo sirve si alguien lo invoca: ``main.py`` lo hace después del event loop."""
    txt = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "ticker_tooltip import shutdown" in txt
    assert txt.index("app.exec()") < txt.index("_tooltip_shutdown()")
