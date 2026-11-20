"""
El aviso permanente de la barra de estado: con qué corre la app, cuando no es lo probado.

Dos casos, y los dos se veían sólo en el log:

- **Tarea 432** — la app corre con un intérprete que no es el ``.venv`` del repo (el del lock y del
  CI): ``main.py`` se relanza solo con el ``.venv``, así que esto queda para cuando no pudo (no hay
  ``.venv``, o no arrancó). El WARNING de la 401 iba sólo al log y la app se abrió con la Anaconda
  en los 9 arranques siguientes: nadie lee el log al abrir la app.
- **Tarea 433** — hay ``.py`` modificados o sin trackear en el árbol: la app corre ese WIP, que no
  pasó por el done. El 2026-11-11 la opinión de MU salió del WIP de la 425 y nada lo decía.

Fail-open: sin nada que avisar, no hay widget; y si algo falla al armarlo, la app abre igual.
"""

from __future__ import annotations

import os

from PyQt6.QtWidgets import QLabel, QStatusBar

from config.codigo import EstadoDelCodigo

_ESTILO = "color: #f0b429; font-weight: 600; padding: 0 8px;"


def _interprete(executable: str) -> str:
    """La carpeta del intérprete (``anaconda3``): el nombre corto que entra en la barra."""
    return os.path.basename(os.path.dirname(executable)) or executable


def textos_del_aviso(estado: EstadoDelCodigo, es_venv: bool = True, executable: str = "") -> list[str]:
    """Las partes del aviso; vacía si corre con el ``.venv`` y sin WIP."""
    textos: list[str] = []
    if not es_venv:
        textos.append(
            f"No corre con el .venv del repo sino con {_interprete(executable)}: abrila con abrir_app.bat"
        )
    if estado.wip:
        textos.append(f"Corre WIP sin commitear ({len(estado.modificados)} .py)")
    return textos


def detalle_del_aviso(estado: EstadoDelCodigo, es_venv: bool = True, executable: str = "") -> str:
    """El tooltip: el intérprete completo, el commit y la lista de archivos."""
    lineas = [f"Intérprete: {executable}"] if executable else []
    lineas.append(f"Código: {estado.resumen(maximo=20)}")
    if not es_venv:
        lineas.append("Las versiones de los paquetes pueden no ser las del lock (tarea 432).")
    if estado.wip:
        lineas.append("Lo que la app muestra y guarda sale de código que no pasó por el done (tarea 433).")
    return "\n".join(lineas)


def instalar(
    barra: QStatusBar, estado: EstadoDelCodigo, es_venv: bool = True, executable: str = ""
) -> QLabel | None:
    """Agrega el aviso a la barra como widget permanente, o nada si no hay que avisar."""
    textos = textos_del_aviso(estado, es_venv, executable)
    if not textos:
        return None
    etiqueta = QLabel("⚠ " + " · ".join(textos))
    etiqueta.setObjectName("aviso_entorno")
    etiqueta.setStyleSheet(_ESTILO)
    etiqueta.setToolTip(detalle_del_aviso(estado, es_venv, executable))
    barra.addPermanentWidget(etiqueta)
    return etiqueta
