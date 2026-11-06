"""Tarea 399 (LOCK-CON-VULNERABILIDADES) — el job ``audit`` ignora sólo lo aceptado por escrito.

Con el lock limpio, el único aviso que queda es PYSEC-2024-110 (scikit-learn 1.4.2), cuyo
riesgo aceptó la tarea 284 en ``requirements.txt``. El job lo ignora con ``--ignore-vuln``.
Un ``--ignore-vuln`` es un agujero que no se ve en el verde del job, así que cada uno tiene
que tener su aceptación escrita en ``requirements.txt``, y cada aceptación escrita su
``--ignore-vuln``: si alguien silencia un aviso nuevo sin escribir por qué, o borra la
aceptación sin sacar el ignore, esto da rojo.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ID = r"(?:PYSEC|CVE|GHSA)-[0-9A-Za-z-]+"


def _ignorados_en_el_ci() -> set[str]:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lineas = [ln for ln in ci.splitlines() if "pip-audit" in ln and not ln.strip().startswith("#")]
    return {m for ln in lineas for m in re.findall(rf"--ignore-vuln[ =]({_ID})", ln)}


def _aceptados_en_requirements() -> set[str]:
    """Los ids de las líneas de ``requirements.txt`` que dicen *aceptado* (comentarios)."""
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    # Cada bloque: los comentarios seguidos y la línea del paquete que comentan.
    bloques = re.findall(r"(?:^#.*\n)*^[^#\n].*$", req, re.MULTILINE)
    aceptados = set()
    for b in bloques:
        if re.search(r"riesgo\s+aceptado", b, re.IGNORECASE):
            aceptados |= set(re.findall(_ID, b))
    return aceptados


def test_el_job_audit_corre_estricto():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    (linea,) = [ln for ln in ci.splitlines() if ln.strip().startswith("pip-audit ")]
    assert "--strict" in linea


def test_cada_ignore_del_ci_tiene_su_aceptacion_escrita_y_viceversa():
    ignorados = _ignorados_en_el_ci()
    aceptados = _aceptados_en_requirements()
    assert ignorados, "se esperaba al menos PYSEC-2024-110"
    assert ignorados == aceptados, (
        f"ignorados sin aceptación escrita: {sorted(ignorados - aceptados)}; "
        f"aceptados sin ignore en el CI: {sorted(aceptados - ignorados)}"
    )


def test_la_aceptacion_de_scikit_learn_sigue_siendo_la_de_la_284():
    assert "PYSEC-2024-110" in _aceptados_en_requirements()
