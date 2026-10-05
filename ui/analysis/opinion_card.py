"""Tarjeta «Opinión de Claude» de la pestaña Análisis (tarea 320).

Un botón le pide a Claude (vía Claude Code, con la suscripción del usuario) una opinión sobre el
ticker analizado, con los datos que la app ya calculó. Corre en un worker: tarda ~15 s y la GUI
no se puede trabar (la 304). La opinión del día se guarda y, al volver a abrir el ticker, se
muestra sin pedirla de nuevo.

Display-only: lo dice la propia tarjeta, junto con que la opinión **no está validada** y se
registra para medir si acierta (la 321).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout

from ui.styles import PALETTE
from ui.workers import BaseWorker

_COLOR = {"COMPRAR": "#22c55e", "MANTENER": "#fbbf24", "VENDER": "#f87171"}
_ROTULO = {"COMPRAR": "Comprar", "MANTENER": "Mantener", "VENDER": "Vender"}

CUERPO_MAX_ALTO = 260

NOTA = (
    "Opinión de un modelo, no validada: que la tesis sea buena no dice que acierte. "
    "Se registra para medirlo. Usa tu suscripción de Claude Code."
)


class OpinionWorker(BaseWorker):
    """Arma los datos, le pide la opinión a Claude y la guarda. Emite ``listo(ok, opinion|mensaje)``.

    Los fallos esperables (Claude Code no instalado, demora, respuesta inválida) vuelven como
    resultado, no como excepción: el ``run`` de ``BaseWorker`` los loguearía con traceback, y el
    log de producción es evidencia de auditoría (la 287).
    """

    listo = pyqtSignal(bool, object)

    def __init__(self, ticker: str, armar_datos, parent=None):
        super().__init__(parent)
        self.ticker = ticker
        self.armar_datos = armar_datos

    def do_work(self):
        from analysis import opinion_claude as oc

        try:
            datos = self.armar_datos()
            opinion = oc.pedir_opinion(datos)
        except oc.OpinionError as e:
            return (False, str(e))
        oc.guardar(self.ticker, opinion, datos)
        return (True, opinion)

    def on_success(self, result) -> None:
        self.listo.emit(*result)


class OpinionCard(QFrame):
    """La tarjeta. ``set_contexto`` la arma para un ticker; el botón dispara el worker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._ticker = ""
        self._armar_datos = None
        self._worker: OpinionWorker | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        fila = QHBoxLayout()
        titulo = QLabel("Opinión de Claude")
        titulo.setStyleSheet("font-weight: 700;")
        fila.addWidget(titulo)
        fila.addStretch()
        self.boton = QPushButton("Pedir opinión")
        self.boton.setEnabled(False)
        self.boton.clicked.connect(self.pedir)
        fila.addWidget(self.boton)
        lay.addLayout(fila)

        self.chip = QLabel("")
        self.chip.setVisible(False)
        lay.addWidget(self.chip)

        self.cuerpo = QLabel("")
        self.cuerpo.setWordWrap(True)
        self.cuerpo.setTextFormat(Qt.TextFormat.RichText)
        self.cuerpo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Con alto máximo y scroll propio: una opinión completa (tesis, 4 riesgos, 3 cambios) estiraba
        # la tarjeta y aplastaba la lista de indicadores del panel derecho.
        self.cuerpo_scroll = QScrollArea()
        self.cuerpo_scroll.setWidgetResizable(True)
        self.cuerpo_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cuerpo_scroll.setMaximumHeight(CUERPO_MAX_ALTO)
        self.cuerpo_scroll.setWidget(self.cuerpo)
        self.cuerpo_scroll.setVisible(False)
        lay.addWidget(self.cuerpo_scroll)

        self.estado = QLabel("Analizá un ticker para pedir la opinión.")
        self.estado.setWordWrap(True)
        self.estado.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px;")
        lay.addWidget(self.estado)

        nota = QLabel(NOTA)
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 10px; font-style: italic;")
        lay.addWidget(nota)

    # ── contexto ─────────────────────────────────────────────────────────────
    def set_contexto(self, ticker: str, armar_datos) -> None:
        """Arma la tarjeta para ``ticker``; ``armar_datos()`` devuelve el dict a mandar."""
        self._ticker = ticker.upper()
        self._armar_datos = armar_datos
        self.chip.setVisible(False)
        self.cuerpo_scroll.setVisible(False)
        self.boton.setEnabled(True)
        self.boton.setText("Pedir opinión")
        self.estado.setText("Tarda unos 15 segundos.")
        try:
            from analysis.opinion_claude import opinion_de_hoy

            hoy = opinion_de_hoy(self._ticker)
        except Exception:
            hoy = None
        if hoy is not None:
            opinion, cuando = hoy
            self.mostrar(opinion)
            hora = f" a las {cuando:%H:%M} UTC" if cuando else ""
            self.estado.setText(f"Opinión pedida hoy{hora}. «Pedir de nuevo» la reemplaza.")
            self.boton.setText("Pedir de nuevo")

    # ── acción ───────────────────────────────────────────────────────────────
    def pedir(self) -> None:
        if not self._armar_datos or (self._worker is not None and self._worker.isRunning()):
            return
        self.boton.setEnabled(False)
        self.estado.setText(f"Consultando a Claude sobre {self._ticker}…")
        self._worker = OpinionWorker(self._ticker, self._armar_datos, self)
        self._worker.listo.connect(self._listo)
        self._worker.error.connect(lambda e: self._listo(False, f"Error inesperado: {e}"))
        self._worker.start()

    def _listo(self, ok: bool, valor) -> None:
        self.boton.setEnabled(True)
        if not ok:
            self.estado.setText(f"No se pudo obtener la opinión: {valor}")
            return
        self.mostrar(valor)
        self.boton.setText("Pedir de nuevo")
        self.estado.setText(f"Respondió en {valor.segundos:.0f} s ({valor.modelo}).")

    def mostrar(self, op) -> None:
        color = _COLOR.get(op.recomendacion, PALETTE["text2"])
        self.chip.setText(
            f"● {_ROTULO.get(op.recomendacion, op.recomendacion)}  ·  confianza {op.confianza}/100"
        )
        self.chip.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 13px;")
        self.chip.setVisible(True)
        self.cuerpo.setText(html_de(op))
        self.cuerpo.setVisible(True)
        self.cuerpo_scroll.setVisible(True)


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def html_de(op) -> str:
    """El cuerpo de la tarjeta en HTML. Pura; el texto de Claude se escapa (no es HTML de confianza)."""

    def lista(titulo: str, items: list[str]) -> str:
        if not items:
            return ""
        filas = "".join(f"<li>{_esc(x)}</li>" for x in items)
        return f"<p style='margin:6px 0 2px 0'><b>{titulo}</b></p><ul style='margin:0'>{filas}</ul>"

    return (
        f"<p style='margin:0'>{_esc(op.tesis)}</p>"
        + lista("Riesgos", op.riesgos)
        + lista("Qué la haría cambiar", op.cambiaria_opinion)
        + lista("Datos que le faltaron", op.datos_faltantes)
    )
