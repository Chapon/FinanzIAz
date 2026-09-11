#!/usr/bin/env python3
"""
run_suite_sin_estado_vivo.py — la suite en la condición del CI, sin salir de Windows.

**Tarea 176.** El criterio de *done* de `CLAUDE.md` son comandos que corren **en la
máquina de Chapa**, y esa máquina tiene estado que el CI no tiene: sobre todo
``~/.finanzias/settings.json``, el archivo de perillas vivas. Un test que lo lea
—directamente, salteando el ``_disable_settings_persistence`` de ``conftest``— pasa
acá y falla allá, y el done **no puede verlo por diseño**.

Ya pasó dos veces con el mismo desenlace:

* **tarea 106** — el job ``lint`` quedó rojo el 2026-09-02 y **trece** tareas se
  cerraron declarando *«suite verde»*. La respuesta fue agregar ruff al done. Cubrió
  ese job, no el agujero.
* **tarea 175** — el job ``pytest`` quedó rojo el 2026-09-09, en el **mismo commit**
  que shipeó el guard de la 130, y **36** commits de tarea se cerraron declarando
  *«suite Windows verde»*, que era **verdad**. 35 corridas. Lo reportó Chapa.

Este script cierra la mitad que ataca la causa. La otra mitad —leer la conclusión del
pipeline— se evaluó y **no se eligió**: el CI corre *después* del push, así que lo más
temprano que puede saber es *«el commit anterior quedó verde»*, o sea que avisa con
retraso uno. Esto, en cambio, corre antes de commitear y no necesita red.

Qué aísla, y por qué eso
------------------------
``HOME`` y ``USERPROFILE`` apuntan a un directorio **vacío y temporal**. Las dos: en
Windows ``Path.home()`` resuelve por ``USERPROFILE``, así que setear sólo ``HOME`` no
cambia nada — y ése es justo el error que haría pasar a este script sin aislar nada.

Con eso, todo lo que cuelgue de ``Path.home()`` deja de existir para la suite:
``~/.finanzias/settings.json`` (perillas vivas), ``~/.finanzias/finanzias.log``, y
cualquier cosa que alguien agregue ahí mañana. Es un **predicado sobre la raíz**, no
una lista de archivos — que es la diferencia entre esto y parchear un test.

Lo que NO aísla, dicho en vez de sobreentendido
-----------------------------------------------
* **La ``finanzias.db``.** No hace falta: ``conftest`` ya la re-liga a una temporal por
  PID (``_guard_real_db``) y además el archivo **no está versionado**, así que el CI
  nunca lo tuvo. Igual se declara acá porque es lo primero que uno supondría.
* **Lo que sólo rompe en Linux de verdad:** separadores de path, permisos, locale,
  ``case`` del filesystem. Eso lo ve el CI y no esto. Este script cubre la clase
  *«estado vivo de la máquina»*, que es la que mordió dos veces, y no *«Windows vs
  Linux»*.
* **Las variables de entorno de Chapa** (``SLACK_BOT_TOKEN``, ``SLACK_CHANNEL``). Van
  a propósito: ``conftest`` pone ``FINANZIAS_DISABLE_SLACK`` (tarea 148) y dejarlas
  puestas mantiene ejercitado **ese** bloqueo, que es el que evita postear de verdad.
  Borrarlas acá haría pasar la suite por el camino que el CI recorre, sí, pero
  apagaría la contraprueba del arreglo de la 148 en el único lugar donde existe.

Uso
---
    python scripts/run_suite_sin_estado_vivo.py
    python scripts/run_suite_sin_estado_vivo.py tests/test_espejos_vivos_t130.py

Sin argumentos corre el mismo selector que el done (``tests/ -m "not network"``).
Con argumentos, se los pasa tal cual a pytest — útil para reproducir un caso puntual.
Exit code = el de pytest.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# El mismo selector del criterio de done (`CLAUDE.md` regla 1). Si cambia allá, cambia
# acá: son el mismo comando corrido en dos entornos, y que difieran sería el defecto.
ARGS_DEL_DONE = ["tests/", "-ra", "-m", "not network", "--tb=short"]

# Las dos variables que hay que mover, con el motivo. `Path.home()` en Windows lee
# `USERPROFILE`; en POSIX, `HOME`. Setear una sola deja el aislamiento a medias **y el
# script pasando en verde**, que es peor que no tenerlo.
_VARS_DE_HOME = ("HOME", "USERPROFILE")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pytest_args = argv or ARGS_DEL_DONE

    with tempfile.TemporaryDirectory(prefix="finanzias_sin_estado_") as home_vacio:
        env = dict(os.environ)
        for var in _VARS_DE_HOME:
            env[var] = home_vacio

        # Contraprueba del propio montaje: si `Path.home()` no cae adentro del
        # directorio vacío, este script no está aislando nada y **no puede** reportar
        # verde. Es el chequeo que convierte "seteé unas variables" en "el aislamiento
        # funciona" — y el que caza el error de mover sólo `HOME` en Windows.
        comprobacion = subprocess.run(
            [sys.executable, "-c", "from pathlib import Path; print(Path.home())"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        visto = comprobacion.stdout.strip()
        if Path(visto).resolve() != Path(home_vacio).resolve():
            print(
                "run_suite_sin_estado_vivo: el aislamiento NO funcionó — "
                f"Path.home() devolvió {visto!r} y se esperaba {home_vacio!r}. "
                "La suite habría corrido contra el estado vivo de la máquina.",
                file=sys.stderr,
            )
            return 2

        print(f"Suite en la condición del CI — HOME vacío en {home_vacio}")
        print("  (sin ~/.finanzias/settings.json, sin log de producción)\n")
        return subprocess.run([sys.executable, "-m", "pytest", *pytest_args], cwd=ROOT, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
