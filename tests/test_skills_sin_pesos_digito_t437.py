"""Tarea 437 (d) — ninguna skill ni comando escribe `$` seguido de un dígito.

El cargador de Claude Code toma `$0`, `$1`… como los argumentos de la invocación: la skill de
auditoría, invocada con argumentos, mostraba `US$0,00` como `UStanda,00`, y un `$4.800` pierde el
`$4`. Un monto se escribe `US$ 4.800`, con espacio.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_PESOS_DIGITO = re.compile(r"\$\d")


def _archivos() -> list[Path]:
    return sorted((RAIZ / ".claude" / "skills").glob("*/SKILL.md")) + sorted(
        (RAIZ / ".claude" / "commands").glob("*.md")
    )


def test_hay_skills_y_comandos_que_mirar():
    """Que el guard no pase por no encontrar nada (la carpeta movida, un glob roto)."""
    nombres = {p.parent.name if p.name == "SKILL.md" else p.stem for p in _archivos()}
    assert {"auditoria", "ship", "test"} <= nombres


def test_ninguna_skill_ni_comando_escribe_pesos_y_digito():
    malos = [
        f"{p.relative_to(RAIZ)}:{n}: {linea.strip()[:80]}"
        for p in _archivos()
        for n, linea in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if _PESOS_DIGITO.search(linea)
    ]
    assert malos == [], "un monto con `$` + dígito lo pisa el cargador de skills:\n" + "\n".join(malos)


def test_el_patron_caza_los_casos_del_hallazgo():
    assert _PESOS_DIGITO.search("La factura: US$0,00")
    assert _PESOS_DIGITO.search("una orden de $844")
    assert not _PESOS_DIGITO.search("La factura: US$ 0,00")
    assert not _PESOS_DIGITO.search("$ARGUMENTS")
