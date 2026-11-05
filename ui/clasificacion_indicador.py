"""
Indicador de la clasificación de noticias en la barra de estado — tarea 409.

Hasta la 409 el refresh diario mostraba una línea por 8 s al arrancar y otra al terminar, y en
el medio —con la cola del 2026-11-05, ~11 h— nada decía que la app estaba clasificando. Esto es
un widget **permanente** de la barra de estado: el avance (*N de M*, con el tiempo restante
estimado) mientras corre, un botón **Detener** que corta guardando lo hecho, y **Reanudar**
cuando quedó detenido. Desaparece cuando la cola está al día.

No habla con el scheduler: emite ``detener_pedido`` / ``reanudar_pedido`` y la ventana los
conecta. Así se testea solo, offscreen.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ui.styles import PALETTE


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _duracion(seg: float) -> str:
    seg = max(0, int(seg))
    h, m = divmod(seg // 60, 60)
    if h:
        return f"{h} h {m:02d} min"
    return f"{max(1, m)} min"


class ClasificacionIndicador(QWidget):
    """Avance de la clasificación + Detener / Reanudar."""

    detener_pedido = pyqtSignal()
    reanudar_pedido = pyqtSignal()

    def __init__(self, parent=None, *, reloj=time.monotonic):
        super().__init__(parent)
        self._reloj = reloj
        self._base: tuple[int, float] | None = None  # (hechos, t) del primer avance con datos
        self._pendientes = 0
        self._estado = "oculto"  # oculto | cosechando | clasificando | deteniendo | detenido

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(8)
        self.label = QLabel()
        self.label.setStyleSheet(f"color: {PALETTE['text2']};")
        self.boton = QPushButton()
        self.boton.clicked.connect(self._on_click)
        lay.addWidget(self.label)
        lay.addWidget(self.boton)
        self.setVisible(False)

    @property
    def estado(self) -> str:
        return self._estado

    # ── Lo que llama la ventana ────────────────────────────────────────────────

    def iniciar(self) -> None:
        """Arrancó el refresh: primero cosecha, después el avance de :meth:`avance`."""
        self._base = None
        self._estado = "cosechando"
        self.label.setText("Noticias: cosechando…")
        self.boton.setText("Detener")
        self.boton.setEnabled(True)
        self.setVisible(True)

    def avance(self, hechos: int, total: int, fallbacks: int) -> None:
        if self._estado == "deteniendo":
            return
        self._estado = "clasificando"
        self._pendientes = max(0, total - hechos)
        ahora = self._reloj()
        if self._base is None:
            self._base = (hechos, ahora)
        texto = f"Clasificando noticias: {_miles(hechos)} de {_miles(total)}"
        h0, t0 = self._base
        if hechos > h0 and ahora > t0 and self._pendientes:
            restante = (ahora - t0) / (hechos - h0) * self._pendientes
            texto += f" (≈ {_duracion(restante)})"
        if fallbacks:
            texto += f" · {_miles(fallbacks)} con heurística: ¿Ollama caído?"
        self.label.setText(texto)
        self.boton.setText("Detener")
        self.boton.setEnabled(True)
        self.setVisible(True)

    def terminado(self, res: dict | None) -> None:
        detenido = bool((res or {}).get("detenido"))
        if detenido and self._pendientes:
            self._estado = "detenido"
            self.label.setText(f"Clasificación detenida: quedan {_miles(self._pendientes)} sin clasificar")
            self.boton.setText("Reanudar")
            self.boton.setEnabled(True)
            self.setVisible(True)
            return
        self.ocultar()

    def ocultar(self) -> None:
        self._estado = "oculto"
        self.setVisible(False)

    # ── El botón ───────────────────────────────────────────────────────────────

    def _on_click(self) -> None:
        if self._estado == "detenido":
            self.reanudar_pedido.emit()
            return
        self._estado = "deteniendo"
        self.label.setText("Deteniendo: guardando lo clasificado…")
        self.boton.setEnabled(False)
        self.detener_pedido.emit()
