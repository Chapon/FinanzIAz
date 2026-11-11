"""Tarea 423 — los jobs del CI corren en un runner fijo, y el paso de apt deja su error legible.

Lo que pasó (2026-11-11): el job ``pytest`` de ``605d998`` y de ``a3e909f`` murió en el paso
*«Qt shared libs (headless)»* con ``exit code 100`` y nada más, sin correr un test, después de 28
corridas verdes. ``ubuntu-latest`` migra de a poco a Ubuntu 26 desde el 2026-10-19, y los logs
de Actions piden token: la anotación era la única pista, y no decía nada.

Sin ``yaml``, como el de la 318: PyYAML no está en ``requirements`` y esto corre en el CI.
"""

from __future__ import annotations

import re
from pathlib import Path

_CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def runners(texto: str) -> dict[str, str | None]:
    """``{job: runs-on}`` de los jobs bajo ``jobs:`` (dos espacios de sangría), sin comentario."""
    cuerpo = texto.split("\njobs:\n", 1)[1]
    out: dict[str, str | None] = {}
    actual = None
    for linea in cuerpo.splitlines():
        if m := re.match(r"^  ([A-Za-z][\w-]*):\s*$", linea):
            actual = m.group(1)
            out[actual] = None
        elif actual and (m := re.match(r"^    runs-on:\s*([^#\s]+)", linea)):
            out[actual] = m.group(1)
    return out


def paso(texto: str, nombre: str) -> str:
    """El bloque del paso ``- name: <nombre>`` hasta el paso siguiente."""
    i = texto.index(f"- name: {nombre}")
    j = texto.find("\n      - ", i + 1)
    return texto[i : j if j > 0 else None]


def test_ningun_job_corre_en_una_etiqueta_que_se_mueve():
    rs = runners(_CI.read_text(encoding="utf-8"))
    assert set(rs) >= {"lint", "tests"}, rs  # el parser vio los jobs de verdad
    movedizos = {k: v for k, v in rs.items() if v is None or v.endswith("-latest")}
    assert not movedizos, f"jobs sin runner fijo: {movedizos}"


def test_el_parser_ve_una_etiqueta_latest():
    # Para que el test de arriba no pase en vano: con `ubuntu-latest`, el parser lo devuelve.
    texto = "jobs:\n  a:\n    runs-on: ubuntu-latest  # nada\n  b:\n    runs-on: ubuntu-24.04\n"
    assert runners("x\n" + texto) == {"a": "ubuntu-latest", "b": "ubuntu-24.04"}


def test_el_paso_de_apt_anota_su_error_y_propaga_el_codigo():
    bloque = paso(_CI.read_text(encoding="utf-8"), "Qt shared libs (headless)")
    assert "set +e" in bloque and "set -o pipefail" in bloque, "sin esto bash -e aborta antes de anotar"
    assert "tee apt-output.txt" in bloque
    assert re.search(r'echo "::error title=apt-get[^"]*\$code::\$msg"', bloque)
    assert bloque.rstrip().endswith("exit $code"), "el paso tiene que seguir fallando"
