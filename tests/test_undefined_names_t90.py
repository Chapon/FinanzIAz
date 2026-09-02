"""Tarea 90 — ningún archivo del repo usa un nombre que no existe.

**Dos veces en dos días.** La tarea 76 cableó un guard en 20 runners con un script
que verificaba que `bars_by` apareciera *en el texto* antes del punto de
inserción: en `run_regime_power_t46.py` aparecía —en otra función— y el runner
quedó muerto con `NameError` (tarea 84). Al arreglarlo, la 83 le agregó
`artifact_window(bars_by)` a las funciones de población **sin importarlo**, y el
runner volvió a quedar muerto por lo mismo. Las dos veces pasó la suite, el
`--help` y `compileall`.

`compileall` no lo caza porque un nombre indefinido es **legal** al compilar: sólo
falla al ejecutar esa línea. Y la suite no ejecuta el `main` de ningún runner.

Lo que sí lo caza es `F821` de ruff, que ya está en el repo. **Se gatea sólo esa
regla, no el estilo:** el proyecto tiene deuda de formato conocida (tarea 65, 654
errores) y gatear todo dejaría el test rojo para siempre. `F821` es de
**corrección**, no de estilo, y hoy está en cero — que es lo que lo hace gateable.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent


def _ruff() -> list[str] | None:
    """El ejecutable de ruff, o ``None`` si no está instalado."""
    if shutil.which("ruff"):
        return ["ruff"]
    try:
        subprocess.run(
            [sys.executable, "-m", "ruff", "--version"], capture_output=True, check=True, timeout=60
        )
    except Exception:
        return None
    return [sys.executable, "-m", "ruff"]


def test_no_hay_nombres_indefinidos():
    """EL GUARD: `F821` en cero sobre todo el repo.

    Si esto se pone rojo, alguien usó un nombre que no importó o no asignó — y el
    modo de falla es que **ese camino de código explota recién cuando se ejecuta**,
    que en un runner de harness es en medio de una corrida larga.
    """
    ruff = _ruff()
    if ruff is None:
        pytest.skip("ruff no está instalado en este entorno")

    r = subprocess.run(
        [*ruff, "check", "--select", "F821", "--output-format", "concise", "."],
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, "nombres indefinidos (F821):\n" + (r.stdout or r.stderr)


def test_el_guard_mira_la_regla_correcta():
    """Contraprueba: sobre un archivo con un nombre indefinido, `F821` tiene que
    dispararse. Sin esto, el test de arriba podría estar pasando porque la regla
    no existe o porque el comando no corre."""
    ruff = _ruff()
    if ruff is None:
        pytest.skip("ruff no está instalado en este entorno")

    r = subprocess.run(
        [*ruff, "check", "--select", "F821", "--output-format", "concise", "-"],
        input="def f():\n    return nombre_que_no_existe\n",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode != 0 and "F821" in r.stdout, r.stdout or r.stderr
