"""
El aviso permanente de la barra de estado: con qué corre la app, cuando no es lo probado.

**Tarea 433** — hay ``.py`` modificados o sin trackear en el árbol: la app corre ese WIP, que no
pasó por el done. El 2026-11-11 la opinión de MU salió del WIP de la 425 y nada lo decía: ni el log
ni la pantalla.

Fail-open: sin nada que avisar, no hay widget; y si algo falla al armarlo, la app abre igual.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QStatusBar

from config.codigo import EstadoDelCodigo

_ESTILO = "color: #f0b429; font-weight: 600; padding: 0 8px;"


def textos_del_aviso(estado: EstadoDelCodigo) -> list[str]:
    """Las partes del aviso; vacía si no hay nada que avisar."""
    textos: list[str] = []
    if estado.wip:
        textos.append(f"Corre WIP sin commitear ({len(estado.modificados)} .py)")
    return textos


def detalle_del_aviso(estado: EstadoDelCodigo) -> str:
    """El tooltip: el commit y la lista de archivos."""
    lineas = [f"Código: {estado.resumen(maximo=20)}"]
    if estado.wip:
        lineas.append("Lo que la app muestra y guarda sale de código que no pasó por el done (tarea 433).")
    return "\n".join(lineas)


def instalar(barra: QStatusBar, estado: EstadoDelCodigo) -> QLabel | None:
    """Agrega el aviso a la barra como widget permanente, o nada si no hay que avisar."""
    textos = textos_del_aviso(estado)
    if not textos:
        return None
    etiqueta = QLabel("⚠ " + " · ".join(textos))
    etiqueta.setObjectName("aviso_entorno")
    etiqueta.setStyleSheet(_ESTILO)
    etiqueta.setToolTip(detalle_del_aviso(estado))
    barra.addPermanentWidget(etiqueta)
    return etiqueta
