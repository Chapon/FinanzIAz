"""Tarea 431 — el cierre tiene un camino para el «no se sabe» del CI, y es el mismo en todos lados.

Cinco lugares declaran cómo se cierra una tarea, y ninguno decía qué pasa con el registro de
*En curso* cuando el CI no contesta: con los runs huérfanos del 2026-11-11, la 428 ocupó *En curso*
ocho días, la 425 quedó sin commitear y sin registro, y la tanda 429 no se pudo registrar.

Chapa eligió el camino el 2026-11-19: el registro pasa igual a *Hecho reciente*, rotulado
*«CI sin verificar»* con la causa, y la tarea siguiente relee ese sha antes de cerrarse. Se exige
**la misma frase** en los cinco: una paráfrasis en uno solo es la forma en que la 300 encontró
tres lugares con el cierre y uno sin él (la 310).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent

CAMINO = (
    "*no se sabe* ⇒ el registro pasa igual a *Hecho reciente*, rotulado *«CI sin verificar»* con la "
    "causa, y la tarea siguiente relee ese sha con `python scripts/check_ci.py --sha <sha>` antes de "
    "cerrarse"
)

_DECLARAN_EL_CIERRE = (
    "CLAUDE.md",
    "docs/BACKLOG.md",
    ".claude/commands/ship.md",
    ".claude/skills/git-workflow/SKILL.md",
    ".claude/skills/finanzias-conventions/SKILL.md",
)


def _plano(texto: str) -> str:
    """Sin saltos de línea ni sangría: el camino puede caer partido en dos renglones."""
    return re.sub(r"\s+", " ", texto)


def _cuerpo(rel: str) -> str:
    texto = (_RAIZ / rel).read_text(encoding="utf-8")
    return _plano(re.sub(r"\A---\n.*?\n---\n", "", texto, count=1, flags=re.S))


@pytest.mark.parametrize("rel", _DECLARAN_EL_CIERRE)
def test_cada_lugar_que_declara_el_cierre_trae_el_camino_del_no_se_sabe(rel):
    assert CAMINO in _cuerpo(rel), f"{rel} no dice qué pasa con el registro si el CI no contesta"


def test_el_backlog_lo_dice_en_el_contrato_y_en_la_nota_de_En_curso():
    """El contrato del header y la nota de *En curso* son los dos que se leen al cerrar."""
    texto = (_RAIZ / "docs/BACKLOG.md").read_text(encoding="utf-8")
    contrato = texto[texto.index("**Contrato para Claude Code:**") : texto.index("**Secciones obligatorias")]
    en_curso = texto[texto.index("## En curso") : texto.index("## Acciones manuales pendientes")]
    assert CAMINO in _plano(contrato)
    assert CAMINO in _plano(en_curso)


def test_CONTROL_una_parafrasis_no_alcanza():
    """El test pide la frase, no la idea: decir lo mismo con otras palabras en un lugar es rojo."""
    parafrasis = CAMINO.replace("relee ese sha", "vuelve a leer el sha")
    assert parafrasis not in _cuerpo("CLAUDE.md")


def test_la_cuenta_1_es_equal_weight_en_el_header():
    """[A-2]: decía `signal_weighted`; la tarea 10 la renombró a `equal_weight` el 2026-09-07."""
    texto = (_RAIZ / "docs/BACKLOG.md").read_text(encoding="utf-8")
    parrafo = texto[texto.index("**Config viva (Sim Segundo") : texto.index("**Política de decisión")]
    assert "`is_active=0`—: `manual`, `equal_weight`" in parrafo
