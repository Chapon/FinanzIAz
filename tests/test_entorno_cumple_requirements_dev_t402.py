"""Tarea 402 — el intérprete del *done* cumple también ``requirements-dev.txt``.

El defecto (2026-10-26, preparando la 399): el done corría en la Anaconda con ``ruff`` 0.15.12 y
``pytest`` 7.4.4, mientras ``requirements-dev.txt`` pinea ``ruff==0.15.20`` **exacto a propósito**
(tarea 65: el formateador cambia entre versiones) y el CI corría 0.15.20. O sea que el
``ruff format --check`` del done y el del CI no eran el mismo instrumento, y nada lo veía: el
test de la 284 sólo mira ``requirements.txt``.

Desde la 401 el done corre en el ``.venv``, que tiene lo del pin; este test es lo que hace que
siga así. Corre con el intérprete del done y con el del CI (el job ``pytest`` instala
``requirements-dev.txt``).
"""

from __future__ import annotations

import importlib.metadata as md
from pathlib import Path

import pytest

packaging = pytest.importorskip("packaging.requirements")

_REQ_DEV = Path(__file__).resolve().parent.parent / "requirements-dev.txt"


def _declaradas():
    for linea in _REQ_DEV.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#")[0].strip()
        if linea and not linea.startswith("-"):
            yield packaging.Requirement(linea)


def _problemas(reqs, version_de=md.version) -> list[str]:
    fuera = []
    for req in reqs:
        if req.marker is not None and not req.marker.evaluate():
            continue
        try:
            version = version_de(req.name)
        except md.PackageNotFoundError:
            fuera.append(f"{req.name}: NO instalado (pide {req.specifier})")
            continue
        if not req.specifier.contains(version, prereleases=True):
            fuera.append(f"{req.name} {version} fuera de {req.specifier}")
    return fuera


def test_cada_dependencia_de_desarrollo_esta_instalada_y_en_rango():
    fuera = _problemas(_declaradas())
    assert not fuera, (
        "el intérprete del done no cumple requirements-dev.txt (¿corre en la Anaconda y no en el "
        ".venv? tarea 401): " + "; ".join(fuera)
    )


def test_ruff_sigue_pineado_exacto():
    """El pin exacto es la decisión de la 65; un ``>=`` haría que el CI y el done diverjan solos."""
    (ruff,) = [r for r in _declaradas() if r.name.lower() == "ruff"]
    (spec,) = list(ruff.specifier)
    assert spec.operator == "=="


def test_la_anaconda_del_2026_10_26_no_pasaba():
    """El caso que distingue: con las versiones medidas en la Anaconda, el chequeo da rojo."""
    anaconda = {"ruff": "0.15.12", "pytest": "7.4.4"}

    def version_de(nombre):
        if nombre.lower() in anaconda:
            return anaconda[nombre.lower()]
        return md.version(nombre)

    fuera = _problemas(_declaradas(), version_de)
    assert any(f.startswith("ruff 0.15.12 fuera de ==") for f in fuera), fuera
