"""Vigía de la interfaz: cuando el hilo de la GUI se traba, queda escrito qué lo trababa (tarea 304).

Chapa notó que la app *«queda unresponsive»* y no había con qué saber por qué: Windows sólo
registra un *Application Hang* si el usuario mata la ventana colgada, y el log no dice nada
porque el hilo trabado tampoco loguea. Lo que se descartó midiendo, para no volver a mirarlo:
el ``analyze()`` del scan en su ``QThread`` atrasa el hilo principal 67 ms como máximo (sonda
del 2026-10-04); las lecturas de la interfaz no esperan a un escritor porque la DB está en WAL;
y ``is_market_open()``, que corre cada minuto en la GUI, es cálculo local.

Cómo funciona:

- un ``QTimer`` en el hilo de la GUI late cada ``latido_ms`` y anota la hora del latido;
- un hilo vigía **de Python** mira esa hora. Si la GUI no latió en ``umbral_s``, vuelca el stack
  de **todos** los hilos a ``archivo``, el de la GUI primero, una sola vez por traba;
- cuando vuelve a latir, mide cuánto estuvo trabado y lo deja en el log (WARNING) y en el
  archivo, con la hora, para cruzarlo con el log. Un atraso de más de ``suspension_s`` se rotula
  como probable suspensión del equipo, no como congelamiento.

**Por qué no ``faulthandler`` (tarea 380).** Hasta la 380 el volcado era
``faulthandler.dump_traceback_later``: su hilo de C recorre los frames de los otros hilos **sin
el GIL** y sin frenarlos, y CPython lo documenta como inseguro con hilos corriendo. El
2026-10-21 la GUI se trabó al arrancar con ~20 hilos trabajando (scan, harvest, dashboard,
precios), el vigía leyó un frame a medio crear y **mató la app** (``0xc0000005`` en
``python312.dll``, volcado cortado a mitad de línea). Medido aparte: 16 hilos con pandas y
``faulthandler`` volcando en loop, segfault 3 de 3; ``sys._current_frames()`` con el mismo
estrés, 3 de 3 vivos. El hilo de Python toma el GIL para leer los frames, y con el GIL ningún
otro hilo los está tocando.

**Lo que cuesta:** si la GUI se traba **dentro de una extensión de C que retiene el GIL**, el
vigía no puede correr hasta que la suelte. El stack sale tarde —muestra dónde quedó la GUI
después—, y la línea de hora y duración sigue saliendo igual. Una traba que suelta el GIL
(red, disco, ``sleep``, la mayoría de numpy/pandas) sale en el momento.

Fail-open: si algo del vigía falla, la app sigue igual.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer

from config.logging_config import get_logger

log = get_logger(__name__)

UMBRAL_S = 5.0  # lo que Windows tarda en rotular una ventana como «No responde»
AVISO_S = 2.0  # un atraso perceptible se loguea aunque no llegue a volcar el stack
SUSPENSION_S = 120.0  # más que esto, sin stack de por medio, es el equipo suspendido
LATIDO_MS = 500


def describir_atraso(
    atraso_s: float,
    *,
    umbral_s: float = UMBRAL_S,
    aviso_s: float = AVISO_S,
    suspension_s: float = SUSPENSION_S,
) -> str | None:
    """Texto para el log de un atraso del hilo de la GUI, o ``None`` si no merece aviso. Pura.

    El aviso nunca es más exigente que el volcado: todo atraso que dejó un stack en el archivo
    lleva su línea de hora y duración (con ``aviso_s`` fijo sobre un umbral menor, el stack
    quedaba sin la hora que permite cruzarlo con el log).
    """
    if atraso_s < min(aviso_s, umbral_s):
        return None
    if atraso_s >= suspension_s:
        return f"la interfaz no latió durante {atraso_s:.0f} s — probablemente el equipo estuvo suspendido"
    return (
        f"la interfaz estuvo trabada {atraso_s:.1f} s (stack en congelamientos.log si pasó de {umbral_s:g} s)"
    )


def volcar_hilos(id_gui: int, *, excluir: int | None = None) -> str:
    """El stack de todos los hilos, el de la GUI primero, en el formato de ``faulthandler``.

    Se llama con el GIL tomado (desde Python), así que ningún frame cambia mientras se lee.
    """
    nombres = {t.ident: t.name for t in threading.enumerate()}
    frames = sys._current_frames()
    orden = sorted(frames, key=lambda tid: tid != id_gui)
    partes = []
    for tid in orden:
        if tid == excluir:
            continue
        rotulo = "GUI" if tid == id_gui else nombres.get(tid, "?")
        lineas = [f"Thread 0x{tid:08x} [{rotulo}] (most recent call first):"]
        for fs in reversed(traceback.extract_stack(frames[tid])):
            lineas.append(f'  File "{fs.filename}", line {fs.lineno} in {fs.name}')
        partes.append("\n".join(lineas))
    return "\n\n".join(partes) + "\n"


class VigiaDeLaInterfaz(QObject):
    def __init__(
        self,
        archivo: Path,
        *,
        umbral_s: float = UMBRAL_S,
        latido_ms: int = LATIDO_MS,
        reloj: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._archivo = Path(archivo)
        self._umbral_s = umbral_s
        self._reloj = reloj
        self._fh = None
        self._ultimo = reloj()
        self._volcado = False  # ya se volcó el stack de la traba en curso
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._id_gui = threading.get_ident()
        self._timer = QTimer(self)
        self._timer.setInterval(latido_ms)
        self._timer.timeout.connect(self.latir)

    def iniciar(self) -> bool:
        try:
            self._archivo.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._archivo, "a", encoding="utf-8")  # noqa: SIM115
            self._id_gui = threading.get_ident()
            self._ultimo = self._reloj()
            self._parar.clear()
            self._hilo = threading.Thread(target=self._vigilar, name="vigia-interfaz", daemon=True)
            self._hilo.start()
            self._timer.start()
            return True
        except Exception:
            log.exception("Vigía de la interfaz: no arrancó (la app sigue igual)")
            return False

    def detener(self) -> None:
        self._timer.stop()
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2)
            self._hilo = None
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None

    def _vigilar(self) -> None:
        paso = min(self._umbral_s / 10, 0.5)
        while not self._parar.wait(paso):
            try:
                with self._lock:
                    trabada = self._reloj() - self._ultimo >= self._umbral_s
                    if trabada and not self._volcado and self._fh is not None:
                        self._volcado = True
                        self._fh.write(f"Timeout ({self._umbral_s:g} s sin latir)!\n")
                        self._fh.write(volcar_hilos(self._id_gui, excluir=threading.get_ident()))
                        self._fh.flush()
            except Exception:
                log.exception("Vigía de la interfaz: falló un volcado (la app sigue igual)")

    def latir(self) -> None:
        try:
            with self._lock:
                ahora = self._reloj()
                atraso = ahora - self._ultimo
                self._ultimo = ahora
                self._volcado = False
                texto = describir_atraso(atraso, umbral_s=self._umbral_s)
                if texto is not None:
                    log.warning("Vigía: %s", texto)
                    if atraso >= self._umbral_s and self._fh is not None:
                        self._fh.write(f"^^^ {datetime.now():%Y-%m-%d %H:%M:%S} — {texto}\n\n")
                        self._fh.flush()
        except Exception:
            log.exception("Vigía de la interfaz: falló un latido (la app sigue igual)")
