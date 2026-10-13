"""
Empaqueta el recolector de la nube (tarea 355) como zip de AWS Lambda (Python 3.12, x86_64).

**Qué lleva el zip.** ``recolector_nube.py`` en la raíz (handler
``recolector_nube.lambda_handler``) y, de la app, **sólo** lo que los colectores necesitan:
``data/news_sources.py`` y ``config/logging_config.py``, tal cual están en el repo, para que
la nube junte lo mismo que la app. Más yfinance, curl_cffi y requests, con sus
dependencias, **en las versiones de ``requirements.lock``** y bajadas para Linux. ``boto3``
no va: viene con el runtime.

**El único archivo que no se copia es ``data/yahoo_finance.py``.** Los colectores le piden
``_ticker``, y el módulo real importa ``database.models`` (SQLAlchemy y la ruta de
``finanzias.db``) al cargarse. En su lugar el zip lleva un módulo con **la misma función,
extraída por AST** del archivo real. Si ``_ticker`` empieza a usar algo además de ``yf``, el
build falla en vez de empaquetar una copia que se comporte distinto.

No despliega nada ni toca credenciales: produce el archivo y dice su tamaño. La subida
directa desde la consola admite hasta 50 MB; si el zip se pasa, el script falla.

Uso:
    python scripts/build_recolector_nube.py
    python scripts/build_recolector_nube.py --out dist/recolector_nube.zip
"""

from __future__ import annotations

import argparse
import ast
import builtins
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.build_probe_lambda_t196 import LIMITE_CONSOLA, pinned_versions

LOCK = _ROOT / "requirements.lock"
HANDLER = _ROOT / "scripts" / "recolector_nube.py"
YAHOO_FINANCE = _ROOT / "data" / "yahoo_finance.py"
PAQUETES = ("yfinance", "curl_cffi", "requests", "urllib3", "pandas", "numpy")
#: Lo que se copia del repo, con su ruta dentro del zip.
ARCHIVOS_DEL_REPO = {
    "recolector_nube.py": HANDLER,
    "config/__init__.py": _ROOT / "config" / "__init__.py",
    "config/logging_config.py": _ROOT / "config" / "logging_config.py",
    "data/__init__.py": _ROOT / "data" / "__init__.py",
    "data/news_sources.py": _ROOT / "data" / "news_sources.py",
}
SHIM = "data/yahoo_finance.py"
VERSION = "recolector_version.txt"
_BASURA = ("__pycache__", "tests")


def shim_yahoo_finance(fuente: str) -> str:
    """Un ``data/yahoo_finance.py`` con sólo el ``_ticker`` de ``fuente`` (el archivo real)."""
    arbol = ast.parse(fuente)
    fn = next((n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == "_ticker"), None)
    if fn is None:
        raise SystemExit("data/yahoo_finance.py ya no define _ticker: revisar el recolector")
    params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    usados = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    ajenos = usados - params - {"yf"} - set(dir(builtins))
    if ajenos:
        raise SystemExit(f"_ticker usa {sorted(ajenos)}: la copia del zip no sería la misma función")
    return (
        '"""Generado por scripts/build_recolector_nube.py: el _ticker de data/yahoo_finance.py, sin\n'
        'el resto del módulo (que importa la DB). No editar: se regenera en cada build."""\n\n'
        "import yfinance as yf\n\n\n" + ast.get_source_segment(fuente, fn) + "\n"
    )


def _git_version() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        sha = "sin-git"
    return f"{sha} {datetime.now(timezone.utc).isoformat(timespec='seconds')}"


def armar_zip(deps: Path | None, out: Path, *, version: str) -> int:
    """Zipea las dependencias (si hay), los archivos del repo y el shim. Devuelve bytes."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        if deps is not None:
            for root, dirs, files in os.walk(deps):
                dirs[:] = [d for d in dirs if d not in _BASURA]
                for f in files:
                    p = Path(root) / f
                    zf.write(p, p.relative_to(deps).as_posix())
        for destino, origen in ARCHIVOS_DEL_REPO.items():
            zf.write(origen, destino)
        zf.writestr(SHIM, shim_yahoo_finance(YAHOO_FINANCE.read_text(encoding="utf-8")))
        zf.writestr(VERSION, version + "\n")
    return out.stat().st_size


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Empaqueta el recolector de la nube (T355) para AWS Lambda.")
    ap.add_argument("--out", default=str(_ROOT / "dist" / "recolector_nube.zip"))
    args = ap.parse_args(argv)

    versiones = pinned_versions(LOCK.read_text(encoding="utf-8"), PAQUETES)
    print("Versiones (requirements.lock): " + ", ".join(f"{k}=={v}" for k, v in versiones.items()))
    with tempfile.TemporaryDirectory() as tmp:
        deps = Path(tmp) / "pkg"
        cmd = [
            sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
            "--target", str(deps),
            # Las dos: pandas 2.3.3 sólo publica `manylinux_2_28`, y el runtime python3.12 de
            # Lambda (Amazon Linux 2023, glibc 2.34) la acepta.
            "--platform", "manylinux2014_x86_64", "--platform", "manylinux_2_28_x86_64",
            "--python-version", "3.12",
            "--implementation", "cp", "--only-binary=:all:",
            *[f"{k}=={v}" for k, v in versiones.items()],
        ]  # fmt: skip
        subprocess.run(cmd, check=True)
        shutil.rmtree(deps / "bin", ignore_errors=True)
        tam = armar_zip(deps, Path(args.out), version=_git_version())

    print(f"Zip: {args.out} — {tam / 1e6:.1f} MB")
    if tam > LIMITE_CONSOLA:
        print("*** Pasa los 50 MB de la subida directa desde la consola de Lambda. ***", file=sys.stderr)
        return 1
    print("Handler: recolector_nube.lambda_handler · runtime Python 3.12 · x86_64")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
