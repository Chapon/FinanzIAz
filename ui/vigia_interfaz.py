"""Vigía de la interfaz: cuando el hilo de la GUI se traba, queda escrito qué lo trababa (tarea 304).

Chapa notó que la app *«queda unresponsive»* y no había con qué saber por qué: Windows sólo
registra un *Application Hang* si el usuario mata la ventana colgada, y el log no dice nada
porque el hilo trabado tampoco loguea. Lo que se descartó midiendo, para no volver a mirarlo:
el ``analyze()`` del scan en su ``QThread`` atrasa el hilo principal 67 ms como máximo (sonda
del 2026-10-04); las lecturas de la interfaz no esperan a un escritor porque la DB está en WAL;
y ``is_market_open()``, que corre cada minuto en la GUI, es cálculo local.

Cómo funciona:

- un ``QTimer`` en el hilo de la GUI late cada ``latido_ms`` y re-arma
  ``faulthandler.dump_traceback_later(umbral_s)``. Si el hilo se traba más de ``umbral_s``, el
  hilo vigía **de C** de ``faulthandler`` —que no necesita el GIL— vuelca el stack de **todos**
  los hilos a ``archivo``. Así se ve la línea que trababa, aunque fuera una extensión C;
- cuando vuelve a latir, mide cuánto estuvo trabado y lo deja en el log (WARNING) y en el
  archivo, con la hora, para cruzarlo con el log. Un atraso de más de ``suspension_s`` se rotula
  como probable suspensión del equipo, no como congelamiento.

Fail-open: si algo del vigía falla, la app sigue igual.
"""

from __future__ import annotations

import faulthandler
import time
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
        self._timer = QTimer(self)
        self._timer.setInterval(latido_ms)
        self._timer.timeout.connect(self.latir)

    def iniciar(self) -> bool:
        try:
            self._archivo.parent.mkdir(parents=True, exist_ok=True)
            # Abierto todo el tiempo: faulthandler escribe en el descriptor desde C.
            self._fh = open(self._archivo, "a", encoding="utf-8")  # noqa: SIM115
            self._ultimo = self._reloj()
            self._armar()
            self._timer.start()
            return True
        except Exception:
            log.exception("Vigía de la interfaz: no arrancó (la app sigue igual)")
            return False

    def detener(self) -> None:
        self._timer.stop()
        try:
            faulthandler.cancel_dump_traceback_later()
        finally:
            if self._fh is not None:
                self._fh.close()
                self._fh = None

    def _armar(self) -> None:
        faulthandler.cancel_dump_traceback_later()
        faulthandler.dump_traceback_later(self._umbral_s, repeat=False, file=self._fh)

    def latir(self) -> None:
        try:
            ahora = self._reloj()
            atraso = ahora - self._ultimo
            self._ultimo = ahora
            texto = describir_atraso(atraso, umbral_s=self._umbral_s)
            if texto is not None:
                log.warning("Vigía: %s", texto)
                if atraso >= self._umbral_s and self._fh is not None:
                    self._fh.write(f"^^^ {datetime.now():%Y-%m-%d %H:%M:%S} — {texto}\n\n")
                    self._fh.flush()
            if self._fh is not None:
                self._armar()
        except Exception:
            log.exception("Vigía de la interfaz: falló un latido (la app sigue igual)")
