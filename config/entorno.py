"""
El entorno canónico de FinanzIAs es el ``.venv`` del repo — **tarea 401**.

Es el que fija ``requirements.lock`` y el que instala el CI (``-c requirements.lock``, tarea 391).
Hasta el 2026-10-26 la app corría en la Anaconda, con 37 versiones distintas de las del lock (pillow
10.3 contra 12.2, protobuf 3.20 contra 7.35). La 284 había decidido que el lock describiera el
``.venv``; con la 391 el CI pasó a correr el lock, y Chapa eligió llevar la app al ``.venv`` en vez
de llevar el lock a la Anaconda. Sin dependencias: lo importan ``main.py`` y
``scripts/lock_requirements.py``.

**Tarea 432:** la decisión de la 401 no movió la práctica —la app se abrió con la Anaconda en los 9
arranques siguientes, porque el aviso iba sólo al log—, así que ``main.py`` se relanza solo con el
``.venv`` cuando existe (:func:`comando_para_relanzar`), y la barra de estado avisa si no pudo.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def es_el_venv(prefix: str, root: str = ROOT) -> bool:
    """¿``prefix`` (el ``sys.prefix`` del intérprete) es el ``.venv`` del repo?"""
    venv = os.path.join(root, ".venv")
    return os.path.normcase(os.path.realpath(prefix)) == os.path.normcase(os.path.realpath(venv))


# ── Tarea 432: relanzar con el .venv ─────────────────────────────────────────
#
# El aviso de la 401 iba sólo al log y no movió la práctica: la app se abrió con la Anaconda en
# los 9 arranques siguientes. Chapa eligió el 2026-11-19 que `main.py` se relance solo.

VARIABLE_RELANZADA = "FINANZIAS_RELANZADA"  # el intérprete del que se relanzó; corta el bucle


def python_del_venv(root: str = ROOT, sin_consola: bool = False) -> str:
    return os.path.join(root, ".venv", "Scripts", "pythonw.exe" if sin_consola else "python.exe")


def comando_para_relanzar(
    executable: str,
    prefix: str,
    argv: list[str],
    environ: Mapping[str, str],
    root: str = ROOT,
    existe: Callable[[str], bool] = os.path.isfile,
) -> list[str] | None:
    """El comando que vuelve a lanzar la app con el ``.venv``, o ``None`` si no hace falta o no se puede.

    No hace falta si ya es el ``.venv``; no se puede si no existe; y nunca dos veces: si la variable
    está, este proceso ya es el relanzado (si el ``.venv`` no se reconociera como tal, sin el corte
    se relanzaría para siempre). Con ``pythonw`` se relanza con ``pythonw``: sin consola.
    """
    if environ.get(VARIABLE_RELANZADA) or es_el_venv(prefix, root):
        return None
    sin_consola = os.path.basename(executable).lower().startswith("pythonw")
    py = python_del_venv(root, sin_consola)
    if not existe(py):
        return None
    return [py, os.path.join(root, "main.py"), *argv[1:]]


def _correr(cmd: list[str], env: dict[str, str], cwd: str) -> int:
    return subprocess.run(cmd, env=env, cwd=cwd).returncode


def relanzar(
    cmd: list[str],
    environ: Mapping[str, str],
    executable: str,
    correr: Callable[[list[str], dict[str, str], str], int] = _correr,
    root: str = ROOT,
) -> bool:
    """Corre la app con ``cmd`` y sale con su código. ``False`` si no pudo lanzarla: la app sigue con
    este intérprete, y el WARNING y el aviso de la barra lo dicen."""
    env = {**environ, VARIABLE_RELANZADA: executable}
    try:
        rc = correr(cmd, env, root)
    except OSError:
        return False
    sys.exit(rc)
