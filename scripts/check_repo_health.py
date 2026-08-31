#!/usr/bin/env python3
"""
check_repo_health.py — guard contra los footguns documentados de FinanzIAs.

Chequea, en orden, los tres bugs caros que ya nos mordieron (ver CLAUDE.md /
skill finanzias-conventions):

  1. .bat sin CRLF  — cmd.exe los mata en silencio (rompio el scheduler del
     harvest desde su creacion).
  2. Null-byte padding — los edits que achican un archivo pueden dejar \x00 al
     final; corrompe el fuente sin error visible.
  3. Escritura de finanzias.db desde un entorno no-Windows — corrupcion
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
