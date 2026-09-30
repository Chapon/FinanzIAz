"""El corpus operativo, UNO para todos los guards de corpus (tarea 239).

Los guards de la 72 (constantes muertas), la 137 (valores vivos) y la 198 (cuenta y
kill_only) tenían **cada uno** su lista de archivos escrita a mano, las tres distintas, y
ninguna incluía `docs/DB_SCHEMA.md` — que `CLAUDE.md` declara doc de referencia y que decía
*«Cuenta activa: "Sim Principal" (id=1), modo kill_only»*, la frase exacta que el test de
parseo de la 198 usa como ejemplo. Lo encontró la auditoría del 2026-09-30 ([G-1] de
`docs/auditoria_guards_2026-09-30.md`): el guard descubría las **frases** y enumeraba los
**archivos**, la forma de la 231 un nivel más arriba.

**La población se deriva de lo que `CLAUDE.md` declara**, no se enumera: `CLAUDE.md`, todo
`.claude/**/*.md`, y los docs de su sección *Documentación de referencia*. Un doc de esa
sección que no deba leerse va en ``FUERA_DEL_CORPUS`` **con el motivo**, y
``tests/test_corpus_unico_t239.py`` falla si aparece uno nuevo sin clasificar.

**Lo que NO ve, dicho:** un doc operativo que `CLAUDE.md` no declare de referencia.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO / "CLAUDE.md"

_SECCION = "## Documentación de referencia"
_ITEM = re.compile(r"^- `([^`]+\.md)`", re.M)

# Doc de referencia → por qué NO entra al corpus operativo. Dict y no lista: excluir obliga
# a escribir el motivo (el criterio de `_NO_SON_CONSTANTES` de la 72).
FUERA_DEL_CORPUS: dict[str, str] = {
    "docs/BACKLOG.md": (
        "es historia además de cola: las tareas cerradas CITAN a propósito las afirmaciones "
        "viejas que corrigieron, y su propio guard (tarea 66) cubre la estructura"
    ),
    "docs/roadmap_v3_2026-06-09.md": (
        "doc estratégico FECHADO en su nombre: dice lo que era verdad el 2026-06-09, como un "
        "doc de veredicto de una tarea cerrada"
    ),
}


def docs_de_referencia(texto: str | None = None) -> list[str]:
    """Los ``docs/…md`` que la sección *Documentación de referencia* de `CLAUDE.md` lista."""
    if texto is None:
        texto = CLAUDE_MD.read_text(encoding="utf-8")
    if _SECCION not in texto:
        return []
    seccion = texto.split(_SECCION, 1)[1].split("\n## ", 1)[0]
    return _ITEM.findall(seccion)


def corpus() -> list[Path]:
    """`CLAUDE.md` + `.claude/**/*.md` + los docs de referencia que no están excluidos."""
    refs = [REPO / d for d in docs_de_referencia() if d not in FUERA_DEL_CORPUS]
    return [CLAUDE_MD, *sorted((REPO / ".claude").rglob("*.md")), *refs]


CORPUS: list[Path] = corpus()
