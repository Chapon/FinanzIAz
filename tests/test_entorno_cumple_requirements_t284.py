"""Tarea 284 — el entorno donde corre la suite cumple lo que declara ``requirements.txt``.

El defecto (``docs/auditoria_dependencias_2026-10-02.md`` [K-3]): la Anaconda de Chapa —donde
corre la app— tenía ``pyarrow 14.0.2`` contra ``pyarrow>=16.0`` declarado, con el cache de
producción (ARQ1) sobre esa versión, y nada lo veía: el CI instala lo último que permiten los
rangos. Este test corre con el intérprete del *done* (la Anaconda) y con el del CI, y exige que
cada dependencia declarada esté instalada y dentro de su especificador.
"""

from __future__ import annotations

import importlib.metadata as md
from pathlib import Path

import pytest

packaging = pytest.importorskip("packaging.requirements")

_REQ = Path(__file__).resolve().parent.parent / "requirements.txt"


def _declaradas():
    for linea in _REQ.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#")[0].strip()
        if linea and not linea.startswith("-"):
            yield packaging.Requirement(linea)


def test_cada_dependencia_declarada_esta_instalada_y_en_rango():
    fuera = []
    for req in _declaradas():
        if req.marker is not None and not req.marker.evaluate():
            continue
        try:
            version = md.version(req.name)
        except md.PackageNotFoundError:
            fuera.append(f"{req.name}: NO instalado (pide {req.specifier})")
            continue
        if not req.specifier.contains(version, prereleases=True):
            fuera.append(f"{req.name} {version} fuera de {req.specifier}")
    assert not fuera, "el entorno no cumple requirements.txt: " + "; ".join(fuera)


def test_urllib3_esta_declarado_porque_se_importa_directo():
    assert any(r.name.lower() == "urllib3" for r in _declaradas())
