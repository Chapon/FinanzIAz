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
sección que no deba leerse va en ``FUERA_DEL_CORPUS`` **con el motivo**; uno que deba leerse
**en parte** (el backlog: header y secciones operativas, no el historial) va en
``RECORTADOS`` con las secciones que entran (tarea 249); y
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
    "docs/roadmap_v3_2026-06-09.md": (
        "doc estratégico FECHADO en su nombre: dice lo que era verdad el 2026-06-09, como un "
        "doc de veredicto de una tarea cerrada"
    ),
}


# Tarea 249 — el backlog entra RECORTADO. Hasta acá estaba entero en `FUERA_DEL_CORPUS`, con
# el motivo de que las tareas cerradas citan a propósito lo que corrigieron; eso vale para el
# HISTORIAL, no para el texto operativo en presente. Esta mañana dos hallazgos vivían ahí (la
# instrucción de la segunda opinión en *Acciones manuales* y el «modo kill_only» del header).
# Entra el header (todo lo anterior a la primera sección) y estas secciones, por su título:
RECORTADOS: dict[str, tuple[str, ...]] = {
    "docs/BACKLOG.md": (
        "Acciones manuales pendientes",
        "Bloqueado",
        "Calidad de datos",
    ),
}


def recortar(texto: str, secciones: tuple[str, ...]) -> str:
    """El header (lo anterior al primer ``## ``) más el cuerpo de las secciones nombradas."""
    partes = re.split(r"(?m)^## ", texto)
    # El párrafo «_Última actualización: …_» del header es una BITÁCORA fechada (la de agosto
    # de 2026, abandonada): historia, como las tareas cerradas. Se saca del recorte.
    bloques = re.split(r"\n\s*\n", partes[0])
    header = "\n\n".join(b for b in bloques if not b.startswith("_Última actualización"))
    elegidas = [header]
    for parte in partes[1:]:
        titulo = parte.split("\n", 1)[0]
        if any(titulo.startswith(s) for s in secciones):
            elegidas.append("## " + parte)
    return "\n".join(elegidas)


class _Recorte(type(Path())):
    """Un archivo del corpus del que se lee sólo un recorte: los guards siguen llamando
    ``read_text`` y ``relative_to`` sin saber que es un pedazo (tarea 249)."""

    def read_text(self, encoding=None, errors=None, newline=None):
        rel = self.relative_to(REPO).as_posix()
        return recortar(super().read_text(encoding=encoding or "utf-8", errors=errors), RECORTADOS[rel])


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
    refs = [
        _Recorte(REPO / d) if d in RECORTADOS else REPO / d
        for d in docs_de_referencia()
        if d not in FUERA_DEL_CORPUS
    ]
    return [CLAUDE_MD, *sorted((REPO / ".claude").rglob("*.md")), *refs]


CORPUS: list[Path] = corpus()
