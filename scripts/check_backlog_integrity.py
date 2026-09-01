"""Guard de integridad de `docs/BACKLOG.md` — Tarea 66 (BACKLOG-TRUNC).

Por qué existe
-------------
El 2026-08-31 el commit de cierre de la tarea 65 fue un diff de **+12 / −767**:
escribió bien su bloque de retro arriba y en el mismo commit se llevó puesto todo
el archivo desde el segundo ítem de *Acciones manuales pendientes* hasta el final
— las **69** secciones ``### NN.``, las diez notas de repriorización y cinco
secciones ``##`` enteras. El archivo pasó de 956 a 201 líneas.

**Y fue invisible durante cuatro commits.** Nada en la suite cubría este archivo,
``git status`` sale limpio y el CI estaba verde. Peor: **el archivo truncado se lee
entero como un backlog válido** —tiene header, contrato y una sección *En curso*
con diez retros—, así que no hay nada que despierte a nadie. Saltó de casualidad,
porque el *"la próxima es la 62"* del retro no tenía a dónde apuntar.

El backlog es el **único** lugar donde viven la cola priorizada, los kill-criteria
de las tareas que todavía no se corrieron y los enunciados de los hallazgos que la
regla 6 obliga a anotar. Si se puede vaciar en silencio, la regla 6 no tiene dónde
apoyarse.

Qué chequea, y por qué cada cosa
--------------------------------
1. **Las secciones que el propio archivo declara obligatorias existen.** La lista
   vive en el header del backlog, no acá: si el guard trajera su propia lista
   hardcodeada, renombrar una sección sería un fallo del guard y no un cambio de
   documento. El contrato es la fuente de verdad (opción (b) del enunciado).
2. **Ninguna de esas secciones está vacía.** Una sección que sobrevive como título
   y sin contenido es la misma pérdida con otra forma.
3. **Todo puntero ``la próxima es la NN`` resuelve a una sección ``### NN.``.** Es
   exactamente lo que se rompió, y es un invariante **estructural**: no necesita
   un umbral ni una cuenta mínima que alguien tenga que ir subiendo.
4. **El archivo declara al menos una tarea.** El caso extremo del truncamiento.

El otro eje —*"perdió más de N líneas en un commit"*— no se puede chequear leyendo
un archivo: necesita el diff. Vive en el hook de ``pre-commit`` (``--staged``), que
compara contra el índice de git.

Uso
---
    python scripts/check_backlog_integrity.py              # chequea el archivo
    python scripts/check_backlog_integrity.py --staged     # + el diff staged

Sale con 1 y lista los problemas si algo falla. Corre también dentro de la suite
(``tests/test_backlog_integrity.py``), que es lo que lo pone en el CI.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKLOG = REPO / "docs" / "BACKLOG.md"

# Cuántas líneas puede perder el backlog en UN commit sin que el hook pregunte.
# No es un límite de estilo: es el orden de magnitud que separa "saqué un ítem
# viejo" de "me llevé puesta media cola". El caso real fueron 767.
MAX_LINES_LOST = 60

_DECLARACION = re.compile(r"^\*\*Secciones obligatorias[^:]*:\*\*(.+)$", re.MULTILINE)
_BACKTICKED = re.compile(r"`([^`]+)`")
# El puntero admite las dos formas que usa el archivo: «la próxima es la **62**»
# y «la próxima es la **29/30/31**» (un bloque de tareas chicas que van juntas).
_PROXIMA = re.compile(r"[Ll]a próxima es la \*\*([0-9][0-9a-z/]*)\*\*")
_TAREA = re.compile(r"^### (\d+)[a-z]?\.", re.MULTILINE)


def declared_sections(text: str) -> list[str]:
    """Las secciones que el propio backlog declara obligatorias, en su orden."""
    m = _DECLARACION.search(text)
    if not m:
        return []
    return [s.strip() for s in _BACKTICKED.findall(m.group(1))]


def _section_bodies(text: str) -> dict[str, str]:
    """``{título completo: cuerpo}`` para cada ``## `` del archivo."""
    out: dict[str, str] = {}
    actual: str | None = None
    buf: list[str] = []
    for line in text.split("\n"):
        if line.startswith("## "):
            if actual is not None:
                out[actual] = "\n".join(buf)
            actual, buf = line[3:].strip(), []
        elif actual is not None:
            buf.append(line)
    if actual is not None:
        out[actual] = "\n".join(buf)
    return out


def check_text(text: str) -> list[str]:
    """Los problemas de integridad del backlog. Lista vacía ⇒ está sano."""
    problemas: list[str] = []

    obligatorias = declared_sections(text)
    if not obligatorias:
        return [
            "el header no declara las secciones obligatorias — se esperaba una línea "
            "'**Secciones obligatorias …:** `A` · `B` · …'. Sin esa declaración el "
            "guard de la 66 no tiene fuente de verdad y no puede chequear nada."
        ]

    cuerpos = _section_bodies(text)
    for nombre in obligatorias:
        coincide = [t for t in cuerpos if t.startswith(nombre)]
        if not coincide:
            problemas.append(f"FALTA la sección obligatoria '## {nombre}' (la declara el header)")
        elif not cuerpos[coincide[0]].strip():
            problemas.append(f"la sección obligatoria '## {nombre}' quedó VACÍA")

    tareas = set(_TAREA.findall(text))
    if not tareas:
        problemas.append("el backlog no tiene ni una sección de tarea '### NN.' — se vació la cola")
    apuntadas = {
        n.rstrip("abcdefghijklmnopqrstuvwxyz")
        for bloque in _PROXIMA.findall(text)
        for n in bloque.split("/")
        if n[:1].isdigit()
    }
    for n in sorted(apuntadas, key=int):
        if n not in tareas:
            problemas.append(f"'la próxima es la {n}' no apunta a ningún lado: falta la sección '### {n}.'")
    return problemas


def check_file(path: Path = BACKLOG) -> list[str]:
    if not path.exists():
        return [f"no existe {path}"]
    return check_text(path.read_text(encoding="utf-8"))


def check_staged_shrink(path: Path = BACKLOG, max_lost: int = MAX_LINES_LOST) -> list[str]:
    """Problemas por un borrado grande en el diff **staged**. Fail-open sin git."""
    try:
        rel = path.relative_to(REPO).as_posix()
        out = subprocess.run(
            ["git", "diff", "--cached", "--numstat", "--", rel],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except Exception:
        return []
    if not out:
        return []
    campos = out.split("\n")[0].split("\t")
    if len(campos) < 2 or not campos[1].isdigit():
        return []
    borradas, agregadas = int(campos[1]), int(campos[0]) if campos[0].isdigit() else 0
    if borradas - agregadas <= max_lost:
        return []
    return [
        f"este commit le saca {borradas} líneas a {rel} y le agrega {agregadas} "
        f"(neto −{borradas - agregadas}, el máximo sin preguntar es {max_lost}). "
        f"El 2026-08-31 un cierre de tarea perdió 767 así y nadie lo notó en cuatro "
        f"commits (tarea 66). Si el borrado es a propósito, commiteá con --no-verify."
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Integridad de docs/BACKLOG.md (tarea 66)")
    ap.add_argument("--staged", action="store_true", help="además, mirar el diff staged")
    args = ap.parse_args(argv)

    problemas = check_file()
    if args.staged:
        problemas += check_staged_shrink()
    if not problemas:
        print("docs/BACKLOG.md: OK")
        return 0
    print(f"docs/BACKLOG.md: {len(problemas)} problema(s)", file=sys.stderr)
    for p in problemas:
        print(f"  - {p}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
