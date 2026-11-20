"""Tarea 399 (LOCK-CON-VULNERABILIDADES) — el job ``audit`` ignora sólo lo aceptado por escrito.

Con el lock limpio, el único aviso que queda es PYSEC-2024-110 (scikit-learn 1.4.2), cuyo
riesgo aceptó la tarea 284 en ``requirements.txt``. El job lo ignora con ``--ignore-vuln``.
Un ``--ignore-vuln`` es un agujero que no se ve en el verde del job, así que cada uno tiene
que tener su aceptación escrita en ``requirements.txt``, y cada aceptación escrita su
``--ignore-vuln``: si alguien silencia un aviso nuevo sin escribir por qué, o borra la
aceptación sin sacar el ignore, esto da rojo.

**La aceptación es una marca afirmativa por id (tarea 435).** Antes alcanzaba con que el bloque de
comentarios dijera *riesgo aceptado* en cualquier lugar: el comentario *«soupsieve CVE-…: NO hay
riesgo aceptado; hay que subirlo»* más su ``--ignore-vuln`` daba **verde** (la forma de la 173 y la
176: un ``in`` sobre el texto acepta la línea que declara lo contrario). Ahora cada id aceptado va
en una línea que **empieza** con ``# Riesgo aceptado:`` y sigue con el id, ``--`` y el motivo.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ID = r"(?:PYSEC|CVE|GHSA)-[0-9A-Za-z-]+"
# `# Riesgo aceptado: PYSEC-2024-110 -- motivo` (con `--` o una raya: `requirements.txt` va sin tildes,
# porque pip lo puede leer con la codificación local). La línea EMPIEZA así: una negación («NO hay riesgo
# aceptado») o una mención al pasar no la forman.
_MARCA = re.compile(
    rf"^#\s*Riesgo aceptado:\s*({_ID}(?:\s*,\s*{_ID})*)\s+(?:—|--)\s+\S", re.IGNORECASE | re.MULTILINE
)


def ignorados_en(ci: str) -> set[str]:
    lineas = [ln for ln in ci.splitlines() if "pip-audit" in ln and not ln.strip().startswith("#")]
    return {m for ln in lineas for m in re.findall(rf"--ignore-vuln[ =]({_ID})", ln)}


def aceptados_en(req: str) -> set[str]:
    """Los ids de las líneas ``# Riesgo aceptado: <id> — <motivo>`` de ``requirements.txt``."""
    return {i for m in _MARCA.finditer(req) for i in re.findall(_ID, m.group(1))}


def _ci() -> str:
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _req() -> str:
    return (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_el_job_audit_corre_estricto():
    (linea,) = [ln for ln in _ci().splitlines() if ln.strip().startswith("pip-audit ")]
    assert "--strict" in linea


def test_cada_ignore_del_ci_tiene_su_aceptacion_escrita_y_viceversa():
    ignorados = ignorados_en(_ci())
    aceptados = aceptados_en(_req())
    assert ignorados, "se esperaba al menos PYSEC-2024-110"
    assert ignorados == aceptados, (
        f"ignorados sin aceptación escrita: {sorted(ignorados - aceptados)}; "
        f"aceptados sin ignore en el CI: {sorted(aceptados - ignorados)}"
    )


def test_la_aceptacion_de_scikit_learn_sigue_siendo_la_de_la_284():
    assert "PYSEC-2024-110" in aceptados_en(_req())


# ── Tarea 435: la mutación de la tanda 2026-11-16, ahora en los tests ───────

_NEGADA = "# soupsieve CVE-2026-126190: NO hay riesgo aceptado; hay que subirlo.\nsoupsieve>=2.10\n"
_IGNORE = "          pip-audit --strict --ignore-vuln PYSEC-2024-110 --ignore-vuln CVE-2026-126190 2>&1\n"


def test_un_comentario_que_NIEGA_la_aceptacion_no_la_da():
    """Era VERDE: el bloque decía «riesgo aceptado» (negado) y el id estaba en el bloque."""
    req = _req() + _NEGADA
    ci = _ci() + _IGNORE
    assert "CVE-2026-126190" in ignorados_en(ci)
    assert "CVE-2026-126190" not in aceptados_en(req)
    assert ignorados_en(ci) != aceptados_en(req)


def test_la_marca_afirmativa_si_la_da():
    req = (
        _req()
        + "# Riesgo aceptado: CVE-2026-126190 — no se usa ningún selector CSS (prueba).\nsoupsieve>=2.10\n"
    )
    assert "CVE-2026-126190" in aceptados_en(req)


def test_una_marca_sin_motivo_no_cuenta():
    assert aceptados_en("# Riesgo aceptado: CVE-2026-126190\n") == set()


def test_una_mencion_al_pasar_no_cuenta():
    assert aceptados_en("# este riesgo aceptado: CVE-2026-126190 — de otro proyecto\n") == set()
