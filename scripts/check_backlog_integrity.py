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
5. **Ninguna tarea abierta se cae de la cola (tarea 195).** El (3) corre en la
   dirección *puntero → tarea*; ésta es la inversa, *tarea abierta → cola*. El
   2026-09-12 la nota de repriorización del cierre de la 184 reescribió el orden sin
   la **180**, y el backlog llegó a declarar *«la cola queda VACÍA»* con ella
   abierta. Lo que se lee como cola es el ``El orden queda …`` de la **última**
   nota ``> **Repriorizado AAAA-MM-DD[x]**`` —la última por **fecha**, no por
   posición: en el archivo no están en orden—, y se exige que toda tarea abierta
   con número **menor o igual al mayor que esa nota ordena** figure en el orden o
   esté declarada ``la **NN** fuera de la cola``.

   **Por qué esa cota y no «toda tarea abierta»:** medido contra el historial, la
   versión sin cota habría puesto en rojo decenas de commits del 9 al 11/09 —tareas
   creadas **después** de la nota y encadenadas por los ``la próxima es la NN`` de
   cada WIP—, que no eran ningún defecto. Como los números se asignan en orden, una
   tarea con número menor al mayor de la nota **ya existía** cuando se escribió: si
   no está, la nota la perdió. **Lo que esta mitad no ve, dicho:** una tarea con
   número **mayor** que todos los de la nota y omitida por ella. Eso lo cubre la
   mitad ``--staged``, en el momento de escribir la nota.

Los ejes que necesitan el diff no se pueden chequear leyendo un archivo: corren con
``--staged``, contra el índice de git, y su cableado operativo es el paso 3a de
``/ship`` (tarea 97 — no hay hooks de git instalados). Son dos: *"perdió más de N
líneas en un commit"* (``check_staged_shrink``) y *"la nota de repriorización que
este commit escribe omite una tarea abierta"* (``check_staged_queue``, tarea 195).

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
from dataclasses import dataclass
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
# Tarea 195. Una tarea está ABIERTA si su título no arranca tachado (`### 12. ~~…~~`).
_TAREA_TITULO = re.compile(r"^### (\d+[a-z]?)\.(.*)$", re.MULTILINE)
_NOTA = re.compile(r"^> \*\*Repriorizado (\d{4}-\d{2}-\d{2})([a-z]?)\*\*(.*)$", re.MULTILINE)
# «El orden queda **195 → 198** → 199 → 29/30/31»: la cadena de flechas, con negritas
# parciales. Sólo la cadena: el resto de la oración («…, con la 186 fuera de la cola»)
# nombra tareas que NO están en el orden.
_TOKEN = r"(?:\*\*)?[0-9][0-9a-z/]*(?:\*\*)?"
_ORDEN = re.compile(rf"[Ee]l orden queda\s+({_TOKEN}(?:\s*→\s*{_TOKEN})*)")
_FUERA = re.compile(r"\*\*(\d+[a-z]?)\*\*\s+fuera de la cola")


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


def open_tasks(text: str) -> list[str]:
    """Los ``### NN.`` cuyo título no arranca tachado, en orden de aparición."""
    return [n for n, resto in _TAREA_TITULO.findall(text) if not resto.strip().startswith("~~")]


@dataclass(frozen=True)
class Cola:
    """Lo que la última nota de repriorización declara como cola."""

    nota: str  # «2026-09-13b»
    orden: tuple[str, ...]  # vacío si la nota no trae «El orden queda …»
    fuera: frozenset[str]
    duplicada: bool  # otra nota con la misma fecha y sufijo: «la última» es ambigua

    def contiene(self, tarea: str) -> bool:
        return tarea in self.orden or _numero(tarea) in {_numero(t) for t in self.orden}

    def excluye(self, tarea: str) -> bool:
        return tarea in self.fuera or _numero(tarea) in {_numero(t) for t in self.fuera}


def _numero(tarea: str) -> str:
    return tarea.rstrip("abcdefghijklmnopqrstuvwxyz")


def latest_queue(text: str) -> Cola | None:
    """La cola que declara la nota ``> **Repriorizado …**`` más RECIENTE, o None si no hay.

    Por **fecha y sufijo**, no por posición: en el archivo las notas no están en orden
    cronológico (la del 2026-09-09c aparece después de la del 2026-09-12b), así que
    "la de más abajo" no es "la última".
    """
    notas = [(fecha, sufijo, cuerpo) for fecha, sufijo, cuerpo in _NOTA.findall(text)]
    if not notas:
        return None
    clave = max((fecha, sufijo) for fecha, sufijo, _ in notas)
    cuerpos = [cuerpo for fecha, sufijo, cuerpo in notas if (fecha, sufijo) == clave]
    cuerpo = cuerpos[-1]
    cadenas = _ORDEN.findall(cuerpo)
    orden = tuple(re.findall(r"[0-9][0-9a-z]*", cadenas[-1].replace("/", " "))) if cadenas else ()
    return Cola(
        nota=clave[0] + clave[1],
        orden=orden,
        fuera=frozenset(_FUERA.findall(cuerpo)),
        duplicada=len(cuerpos) > 1,
    )


def queue_problems(text: str, *, exact: bool = False) -> list[str]:
    """Tareas abiertas que la última nota de repriorización perdió (tarea 195).

    ``exact=False`` es la mitad de la suite: sólo acusa a las abiertas con número menor o
    igual al mayor que la nota ordena, porque ésas ya existían cuando se escribió.
    ``exact=True`` es la mitad ``--staged``: se usa cuando el commit **escribe** la nota,
    y ahí toda tarea abierta tiene que estar.
    """
    cola = latest_queue(text)
    if cola is None:
        return []
    if cola.duplicada:
        return [
            f"hay dos notas '> **Repriorizado {cola.nota}**': con la misma fecha y sufijo no se "
            "sabe cuál es la última. Poné un sufijo a la nueva (b, c, …)."
        ]
    if not cola.orden:
        return [
            f"la última repriorización ({cola.nota}) no declara 'El orden queda …': sin eso el "
            "backlog no dice cuál es la cola, y ninguna tarea abierta se puede verificar contra ella"
        ]
    tope = max(int(_numero(t)) for t in cola.orden if _numero(t).isdigit())
    perdidas = [
        t
        for t in open_tasks(text)
        if not cola.contiene(t) and not cola.excluye(t) and (exact or int(_numero(t)) <= tope)
    ]
    if not perdidas:
        return []
    lista = ", ".join(perdidas)
    return [
        f"la tarea abierta {lista} no está en la cola: la última repriorización ({cola.nota}) "
        f"dice 'El orden queda {' → '.join(cola.orden)}'. Agregala al orden, cerrala, o declarala "
        "'la **NN** fuera de la cola' con el motivo (tarea 195: así se perdió la 180)."
    ]


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
    problemas += queue_problems(text)
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


def _git_show(spec: str) -> str | None:
    r = subprocess.run(
        ["git", "show", spec], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False
    )
    return r.stdout if r.returncode == 0 else None


def check_staged_queue(path: Path = BACKLOG) -> list[str]:
    """Si el commit staged escribe o cambia la última nota de repriorización, toda tarea
    abierta tiene que estar en su orden — sin la cota de la mitad de la suite (tarea 195).

    Es el momento en que la omisión es un error seguro: quien escribe el orden tiene
    todas las tareas abiertas delante. Fail-open sin git o sin HEAD.
    """
    try:
        rel = path.relative_to(REPO).as_posix()
        antes, ahora = _git_show(f"HEAD:{rel}"), _git_show(f":{rel}")
    except Exception:
        return []
    if antes is None or ahora is None:
        return []
    cola_antes, cola_ahora = latest_queue(antes), latest_queue(ahora)
    if cola_ahora is None or cola_ahora == cola_antes:
        return []
    return [f"[--staged] {p}" for p in queue_problems(ahora, exact=True)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Integridad de docs/BACKLOG.md (tareas 66 y 195)")
    ap.add_argument("--staged", action="store_true", help="además, mirar el diff staged")
    args = ap.parse_args(argv)

    problemas = check_file()
    if args.staged:
        problemas += check_staged_shrink()
        # Sin duplicar lo que la mitad de la suite ya acusó sobre el mismo archivo.
        problemas += [p for p in check_staged_queue() if p.removeprefix("[--staged] ") not in problemas]
    if not problemas:
        print("docs/BACKLOG.md: OK")
        return 0
    print(f"docs/BACKLOG.md: {len(problemas)} problema(s)", file=sys.stderr)
    for p in problemas:
        print(f"  - {p}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
