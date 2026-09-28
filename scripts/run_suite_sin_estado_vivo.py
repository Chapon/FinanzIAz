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

**Y el home vacío tiene que tener forma de home de Windows (tarea 236).** Mover
``USERPROFILE`` a un directorio pelado dejaba a ``platformdirs`` —que resuelve por
``SHGetFolderPathW``, no por variables de entorno— sin ``AppData\\Local`` que
expandir: la API devuelve ``''``, ``user_cache_dir()`` vale ``'.'``, y yfinance
creaba ``py-yfinance/`` en el **cwd**, que es la raíz del repo. O sea que la suite
«sin estado» escribía estado en el repo y lo reusaba en la corrida siguiente. Por eso
se crean ``AppData\\Local`` y ``AppData\\Roaming`` adentro, se les apunta
``LOCALAPPDATA``/``APPDATA`` (las leen otras librerías), la contraprueba del montaje
exige que el cache de ``platformdirs`` caiga adentro del home vacío, y al terminar se
compara el ``git status`` de antes y de después: si la suite dejó algo nuevo en el
repo, el comando no reporta verde.

Lo que NO aísla, dicho en vez de sobreentendido
-----------------------------------------------
* **La ``finanzias.db``.** No hace falta: ``conftest`` ya la re-liga a una temporal por
  PID (``_guard_real_db``) y además el archivo **no está versionado**, así que el CI
  nunca lo tuvo. Igual se declara acá porque es lo primero que uno supondría.
* **Lo que sólo rompe en Linux de verdad:** separadores de path, permisos, locale,
  ``case`` del filesystem. Eso lo ve el CI y no esto. Este script cubre la clase
  *«estado vivo de la máquina»*, que es la que mordió dos veces, y no *«Windows vs
  Linux»*.
* **Las variables de entorno de Chapa** (``SLACK_BOT_TOKEN``, ``SLACK_CHANNEL``, y
  desde la tarea 209 también ``FINNHUB_API_KEY`` y ``SEC_EDGAR_USER_AGENT``). Van a
  propósito, y por el mismo argumento en los dos casos: ``conftest`` pone
  ``FINANZIAS_DISABLE_SLACK`` (tarea 148) y el autouse ``_cortafuegos_de_red`` (209),
  y dejar las variables puestas mantiene ejercitados **esos** bloqueos, que son los
  que evitan postear y salir a internet de verdad. Borrarlas acá haría pasar la suite
  por el camino que el CI recorre, sí, pero apagaría las dos contrapruebas en el único
  lugar donde existen. Medido el 2026-09-20: con las keys y sin ellas la suite da
  **exactamente el mismo conteo**, que antes del cortafuegos no se cumplía.

Uso
---
    python scripts/run_suite_sin_estado_vivo.py
    python scripts/run_suite_sin_estado_vivo.py tests/test_espejos_vivos_t130.py

Sin argumentos corre el mismo selector que el done (``tests/ -m "not network"``).
Con argumentos, se los pasa tal cual a pytest — útil para reproducir un caso puntual.
Exit code = el de pytest; ``2`` si el aislamiento no se montó, ``3`` si la suite pasó
pero dejó cambios en el repo.
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

# Tarea 236 — las carpetas de datos de aplicación de Windows, adentro del home vacío.
_APPDATA = {"LOCALAPPDATA": ("AppData", "Local"), "APPDATA": ("AppData", "Roaming")}

_SONDA = (
    "from pathlib import Path; import platformdirs; print(Path.home()); print(platformdirs.user_cache_dir())"
)


def montar_home_vacio(home_vacio: str | Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """El entorno de la suite: el de ``base`` con el home y el AppData movidos a ``home_vacio``."""
    env = dict(os.environ if base is None else base)
    for var in _VARS_DE_HOME:
        env[var] = str(home_vacio)
    for var, partes in _APPDATA.items():
        carpeta = Path(home_vacio).joinpath(*partes)
        carpeta.mkdir(parents=True, exist_ok=True)
        env[var] = str(carpeta)
    return env


def fallas_del_aislamiento(env: dict[str, str], home_vacio: str | Path) -> list[str]:
    """Contraprueba del montaje, corrida en un hijo con ``env``: qué raíz quedó afuera.

    Es el chequeo que convierte *«seteé unas variables»* en *«el aislamiento funciona»*: caza
    mover sólo ``HOME`` en Windows (``Path.home()`` afuera) y el home sin ``AppData`` de la
    236 (``platformdirs`` en ``'.'``, o sea en el cwd).
    """
    r = subprocess.run([sys.executable, "-c", _SONDA], cwd=ROOT, env=env, capture_output=True, text=True)
    lineas = r.stdout.strip().splitlines()
    if r.returncode != 0 or len(lineas) != 2:
        return [f"la sonda no corrió: {r.stderr.strip()[-300:]!r}"]
    raiz = Path(home_vacio).resolve()
    fallas = []
    for nombre, visto in zip(("Path.home()", "platformdirs.user_cache_dir()"), lineas, strict=True):
        p = Path(visto).resolve()
        if p != raiz and raiz not in p.parents:
            fallas.append(f"{nombre} devolvió {visto!r}, afuera de {str(raiz)!r}")
    return fallas


def estado_del_repo() -> set[str] | None:
    """Las líneas de ``git status --porcelain``, o ``None`` si git no está a mano."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return set(r.stdout.splitlines()) if r.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pytest_args = argv or ARGS_DEL_DONE

    with tempfile.TemporaryDirectory(prefix="finanzias_sin_estado_") as home_vacio:
        env = montar_home_vacio(home_vacio)

        # Si alguna raíz cae afuera del directorio vacío, este script no está aislando
        # nada y **no puede** reportar verde.
        if fallas := fallas_del_aislamiento(env, home_vacio):
            print(
                "run_suite_sin_estado_vivo: el aislamiento NO funcionó — "
                + "; ".join(fallas)
                + ". La suite habría corrido contra el estado vivo de la máquina.",
                file=sys.stderr,
            )
            return 2

        print(f"Suite en la condición del CI — HOME vacío en {home_vacio}")
        print("  (sin ~/.finanzias/settings.json, sin log de producción, AppData adentro)\n")
        antes = estado_del_repo()
        codigo = subprocess.run([sys.executable, "-m", "pytest", *pytest_args], cwd=ROOT, env=env).returncode
        despues = estado_del_repo()

    if antes is None or despues is None:
        print("\n(sin git: no se pudo verificar que la suite no escribió en el repo)")
    elif nuevo := sorted(despues - antes):
        print(
            "\nrun_suite_sin_estado_vivo: la suite dejó cambios en el repo (tarea 236):\n  "
            + "\n  ".join(nuevo)
            + "\nSi es un proceso ajeno (la app abierta reescribe archivos de datos), re-correr.",
            file=sys.stderr,
        )
        return codigo or 3
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
