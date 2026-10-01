"""
Empaqueta el probe de la tarea 196 como zip de AWS Lambda (Python 3.12, x86_64).

Decisión de Chapa (2026-10-01): la recolección continua va en **AWS Lambda + DynamoDB**
en lugar de la Pi. Antes de construir nada, el probe contesta la única pregunta que la
corrida desde GitHub (IPs de Azure) no podía: **¿responde Yahoo desde una IP de AWS?**
Ver ``docs/harvest_nube_t196_2026-09-14.md`` §5.

El zip lleva ``scripts/probe_yahoo_datacenter_t196.py`` en la raíz (handler
``probe_yahoo_datacenter_t196.lambda_handler``) y yfinance + curl_cffi **en las versiones de
``requirements.lock``**: el probe tiene que medir la misma yfinance que corre la app, no la
última que haya en PyPI. Las wheels se bajan para Linux (``manylinux2014_x86_64``), no para
esta máquina.

No despliega nada ni toca credenciales de AWS: produce el archivo y dice su tamaño. La
subida directa desde la consola admite hasta 50 MB; si el zip se pasa, el script falla en
vez de dejar un archivo que la consola va a rechazar.

Uso:
    python scripts/build_probe_lambda_t196.py
    python scripts/build_probe_lambda_t196.py --out dist/probe.zip
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PROBE = _ROOT / "scripts" / "probe_yahoo_datacenter_t196.py"
LOCK = _ROOT / "requirements.lock"
PAQUETES = ("yfinance", "curl_cffi")
LIMITE_CONSOLA = 50 * 1024 * 1024
_BASURA = ("__pycache__", "tests")


def pinned_versions(lock_text: str, paquetes=PAQUETES) -> dict[str, str]:
    """``{paquete: versión}`` desde un ``requirements.lock`` (``nombre==versión``)."""
    out = {}
    for linea in lock_text.splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+)==([^\s;#]+)", linea)
        if m and m.group(1).lower().replace("-", "_") in {p.lower().replace("-", "_") for p in paquetes}:
            out[m.group(1)] = m.group(2)
    faltan = set(paquetes) - set(out)
    if faltan:
        raise SystemExit(f"requirements.lock no fija: {', '.join(sorted(faltan))}")
    return out


def zip_dir(src: Path, out: Path, probe: Path) -> int:
    """Zipea ``src`` (sin ``__pycache__`` ni ``tests``) más el probe en la raíz. Devuelve bytes."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in _BASURA]
            for f in files:
                p = Path(root) / f
                zf.write(p, p.relative_to(src).as_posix())
        zf.write(probe, probe.name)
    return out.stat().st_size


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Empaqueta el probe T196 para AWS Lambda.")
    ap.add_argument("--out", default=str(_ROOT / "dist" / "probe_lambda_t196.zip"))
    args = ap.parse_args(argv)

    versiones = pinned_versions(LOCK.read_text(encoding="utf-8"))
    print("Versiones (requirements.lock): " + ", ".join(f"{k}=={v}" for k, v in versiones.items()))
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / "pkg"
        cmd = [
            sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
            "--target", str(destino),
            "--platform", "manylinux2014_x86_64", "--python-version", "3.12",
            "--implementation", "cp", "--only-binary=:all:",
            *[f"{k}=={v}" for k, v in versiones.items()],
        ]  # fmt: skip
        subprocess.run(cmd, check=True)
        shutil.rmtree(destino / "bin", ignore_errors=True)
        tam = zip_dir(destino, Path(args.out), PROBE)

    print(f"Zip: {args.out} — {tam / 1e6:.1f} MB")
    if tam > LIMITE_CONSOLA:
        print("*** Pasa los 50 MB de la subida directa desde la consola de Lambda. ***", file=sys.stderr)
        return 1
    print("Handler: probe_yahoo_datacenter_t196.lambda_handler · runtime Python 3.12 · x86_64")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
