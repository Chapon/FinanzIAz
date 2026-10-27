"""Tarea 391 — toda dependencia de tiempo de ejecución tiene techo, y el CI instala con el lock.

El defecto (``docs/auditoria_tanda_2026-10-23.md`` [K-1]): once dependencias de ``requirements.txt``
sin ``<``, ``yfinance`` entre ellas, y el CI instalando lo último que permitían los rangos. Es la
forma de la 348: ``pyarrow`` 26 salió, el CI la instaló y quedó rojo sin que cambiara el código.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

packaging = pytest.importorskip("packaging.requirements")

_REPO = Path(__file__).resolve().parent.parent

# Las que no llevan techo, cada una con su motivo. Hoy ninguna.
EXCEPCIONES: dict[str, str] = {}


def _declaradas():
    for linea in (_REPO / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linea = linea.split("#")[0].strip()
        if linea and not linea.startswith("-"):
            yield packaging.Requirement(linea)


def _lock() -> dict[str, str]:
    out = {}
    for linea in (_REPO / "requirements.lock").read_text(encoding="utf-8").splitlines():
        if "==" in linea and not linea.startswith("#"):
            nombre, version = linea.split("==", 1)
            out[re.sub(r"[-_.]+", "-", nombre.strip().lower())] = version.strip()
    return out


def test_toda_dependencia_de_tiempo_de_ejecucion_tiene_techo():
    sin_techo = [
        str(r)
        for r in _declaradas()
        if r.name.lower() not in EXCEPCIONES
        and not any(s.operator in ("<", "<=", "==", "===", "~=") for s in r.specifier)
    ]
    assert not sin_techo, f"sin techo de versión (o declarar el motivo en EXCEPCIONES): {sin_techo}"


def test_el_techo_no_deja_afuera_la_version_del_lock():
    """Si el techo quedara debajo del lock, el CI —que instala con ``-c requirements.lock``— no resuelve."""
    lock = _lock()
    fuera = []
    for r in _declaradas():
        version = lock.get(re.sub(r"[-_.]+", "-", r.name.lower()))
        if version is None:
            fuera.append(f"{r.name}: no está en el lock")
        elif not r.specifier.contains(version, prereleases=True):
            fuera.append(f"{r.name} {version} fuera de {r.specifier}")
    assert not fuera, "; ".join(fuera)


def test_cada_instalacion_del_ci_va_con_el_lock():
    sueltas = []
    for wf in sorted((_REPO / ".github" / "workflows").glob("*.yml")):
        for n, linea in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            orden = linea.split("#")[0].strip()
            if not orden.startswith("pip install") or "-c requirements.lock" in orden:
                continue
            # Las herramientas del propio job no son del proyecto: pip, setuptools y pip-audit.
            if re.fullmatch(r"(python -m )?pip install( --upgrade)?( (pip|setuptools|pip-audit))+", orden):
                continue
            sueltas.append(f"{wf.name}:{n}: {orden}")
    assert not sueltas, f"instalaciones del CI sin el lock: {sueltas}"
