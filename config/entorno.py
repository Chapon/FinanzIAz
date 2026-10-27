"""
El entorno canónico de FinanzIAs es el ``.venv`` del repo — **tarea 401**.

Es el que fija ``requirements.lock`` y el que instala el CI (``-c requirements.lock``, tarea 391).
Hasta el 2026-10-26 la app corría en la Anaconda, con 37 versiones distintas de las del lock (pillow
10.3 contra 12.2, protobuf 3.20 contra 7.35). La 284 había decidido que el lock describiera el
``.venv``; con la 391 el CI pasó a correr el lock, y Chapa eligió llevar la app al ``.venv`` en vez
de llevar el lock a la Anaconda. Sin dependencias: lo importan ``main.py`` y
``scripts/lock_requirements.py``.
"""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def es_el_venv(prefix: str, root: str = ROOT) -> bool:
    """¿``prefix`` (el ``sys.prefix`` del intérprete) es el ``.venv`` del repo?"""
    venv = os.path.join(root, ".venv")
    return os.path.normcase(os.path.realpath(prefix)) == os.path.normcase(os.path.realpath(venv))
