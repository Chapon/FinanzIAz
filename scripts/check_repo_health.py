#!/usr/bin/env python3
"""
check_repo_health.py — guard contra los footguns documentados de FinanzIAs.

Chequea, en orden, los cuatro bugs caros que ya nos mordieron (ver CLAUDE.md /
skill finanzias-conventions):

  1. .bat sin CRLF  — cmd.exe los mata en silencio (rompio el scheduler del
     harvest desde su creacion).
  2. CRLF en el working tree de un archivo versionado — `.gitattributes` declara
     `eol=lf`, asi que CRLF en disco no vino de un checkout: lo escribio una
     herramienta que ignoro la convencion (tareas 165, 172 y 173). git normaliza
     al comparar, asi que `git status` queda limpio y el desvio se acumula solo.
  3. Null-byte padding — los edits que achican un archivo pueden dejar \x00 al
     final; corrompe el fuente sin error visible.
  4. Escritura de finanzias.db desde un entorno no-Windows — corrupcion
     intermitente via mounts de Linux/sandbox.

Uso:
    python scripts/check_repo_health.py            # chequea todo el repo
    python scripts/check_repo_health.py --staged   # solo archivos staged (pre-commit)

Exit code 0 = sano, 1 = hay problemas. Pensado para correr a mano o como hook
pre-commit. NO depende de paquetes externos (solo stdlib).
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Extensiones de texto donde un null-byte es casi seguro corrupcion.
TEXT_EXTS = {".py", ".md", ".txt", ".json", ".toml", ".cfg", ".ini", ".bat", ".ps1", ".csv"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "backups", "assets"}


def _staged_files() -> list[Path]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return [ROOT / line.strip() for line in out.stdout.splitlines() if line.strip()]


@lru_cache(maxsize=1)
def _tracked() -> frozenset[str]:
    """Los archivos que git versiona, como rutas POSIX relativas."""
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return frozenset(ln.strip() for ln in out.stdout.splitlines() if ln.strip())


def _all_files() -> list[Path]:
    files: list[Path] = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        files.append(p)
    return files


def check_bat_crlf(files: list[Path]) -> list[str]:
    problems = []
    for p in files:
        if p.suffix.lower() != ".bat" or not p.exists():
            continue
        data = p.read_bytes()
        if not data:
            continue
        # Cada \n debe venir precedido de \r.
        lf = data.count(b"\n")
        crlf = data.count(b"\r\n")
        if lf != crlf:
            problems.append(f"  [.bat sin CRLF] {p.relative_to(ROOT)} ({crlf}/{lf} lineas con CRLF)")
    return problems


# Los que SÍ pueden tener CRLF en el working tree, con su motivo. No es una lista de
# conveniencia: son las dos excepciones que `.gitattributes` declara.
_CRLF_PERMITIDO = {
    ".bat": "cmd.exe los mata con LF (regla 4 de CLAUDE.md) — `.gitattributes` los fija en crlf",
    ".cmd": (
        "mismo motivo que .bat: los interpreta cmd.exe y con LF se come caracteres al "
        "inicio de linea — `.gitattributes` los fija en crlf"
    ),
}
# Mismo mecanismo, por patron de ruta. **Hoy esta VACIO a proposito** (tarea 173): la unica
# entrada que tuvo, `data/catalyst/*.json`, se apoyaba en una lectura equivocada de
# `.gitattributes` — esa linea declara `eol=lf`, o sea **LF en el working tree**, igual que la
# regla global; no "acepta CRLF". El defecto real estaba en los dos builders, que escribian con
# `write_text` sin `newline` — el mismo de la 165, que a esos dos los habia excluido llamandolos
# "no versionados" cuando `git ls-files` los lista. Arreglado el writer, la excepcion sobra.
_CRLF_PERMITIDO_GLOBS: dict[str, str] = {}


def check_crlf_en_working_tree(files: list[Path]) -> list[str]:
    """El eje que le faltaba al guard: un archivo versionado con CRLF **en disco**.

    **Tarea 172.** `.gitattributes` declara `* text=auto eol=lf`, o sea que git escribe
    **LF** en el working tree; las únicas excepciones son `.bat`/`.cmd`, que lo **necesitan**
    (regla 4 de `CLAUDE.md`) y por eso `.gitattributes` los fija en `eol=crlf`.
    Cualquier otro archivo con CRLF en disco **no vino de un checkout**: lo escribió una
    herramienta que ignoró la convención — `Path.write_text()` en Windows, PowerShell, o un
    script regenerador (los tres que arregló la tarea **165**).

    **Tarea 173 — la excepción por glob que tuvo acá era ella misma el defecto.** Los dos
    JSON de `data/catalyst/` están versionados y sus builders los re-escribían con CRLF, así
    que se los exceptuó en vez de arreglar al que escribe. El argumento citaba a
    `.gitattributes`, que para ese glob declara `eol=lf` — lo **contrario** de lo que la
    excepción suponía. Arreglados los dos writers, no queda ninguna excepción por glob.

    **Por qué nadie lo veía:** git normaliza al comparar, así que `git status` queda
    **limpio** y el desvío se acumula en silencio. Medido el 2026-09-10: **16** archivos
    versionados estaban CRLF contra un blob LF, incluidos seis `scripts/*.py`, cuatro docs,
    `requirements.lock` y `.claude/settings.json`. Ninguno mixto, que es la única buena
    noticia: lo que se rompe no es el contenido, es cualquier comparación byte a byte (un
    hash, un `diff` fuera de git, un guard que lea bytes).

    Chequea sólo lo que git **versiona**: un artefacto no versionado con CRLF no le importa
    a nadie.
    """
    problems = []
    versionados = _tracked()
    for p in files:
        if not p.exists() or p.suffix.lower() in _CRLF_PERMITIDO:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel not in versionados:
            continue
        if any(fnmatch(rel, g) for g in _CRLF_PERMITIDO_GLOBS):
            continue
        data = p.read_bytes()
        if b"\x00" in data[:8192]:  # binario: el null-byte lo cubre el otro chequeo
            continue
        crlf = data.count(b"\r\n")
        if crlf:
            lf = data.count(b"\n") - crlf
            detalle = f"{crlf} CRLF" + (f" + {lf} LF (MIXTO)" if lf else "")
            problems.append(f"  [CRLF en el working tree] {rel} ({detalle})")
    return problems


def check_null_bytes(files: list[Path]) -> list[str]:
    problems = []
    for p in files:
        if p.suffix.lower() not in TEXT_EXTS or not p.exists():
            continue
        n = p.read_bytes().count(b"\x00")
        if n:
            problems.append(f"  [null-byte] {p.relative_to(ROOT)} ({n} bytes \\x00)")
    return problems


def check_db_write_env(files: list[Path], *, staged_only: bool) -> list[str]:
    # Solo es un riesgo si la DB esta por COMMITEARSE desde un entorno no-Windows.
    # En el scan de todo el repo la DB siempre existe, asi que ese chequeo solo
    # corre en modo --staged (donde la lista son cambios reales por commitear).
    if not staged_only or platform.system() == "Windows":
        return []
    touching_db = [p for p in files if p.name == "finanzias.db"]
    if touching_db:
        return [
            "  [DB desde no-Windows] finanzias.db aparece en los cambios y NO estas en Windows. "
            "No escribas la DB desde Linux/sandbox (corrupcion via mounts). Ver CLAUDE.md."
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Guard de salud del repo FinanzIAs.")
    ap.add_argument("--staged", action="store_true", help="Chequear solo archivos staged (pre-commit).")
    args = ap.parse_args(argv)

    files = _staged_files() if args.staged else _all_files()
    scope = "staged" if args.staged else "todo el repo"

    problems: list[str] = []
    problems += check_bat_crlf(files)
    problems += check_crlf_en_working_tree(files)
    problems += check_null_bytes(files)
    problems += check_db_write_env(files, staged_only=args.staged)

    if problems:
        print(f"check_repo_health: PROBLEMAS encontrados ({scope}):", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        print(
            "\nArreglalos antes de commitear. Detalle en CLAUDE.md / skill finanzias-conventions.",
            file=sys.stderr,
        )
        return 1

    print(f"check_repo_health: sin problemas ({scope}, {len(files)} archivos).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
