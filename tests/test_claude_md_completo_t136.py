"""Tarea 136 (CLAUDEMD-TRUNCADO) — el corpus no termina a mitad de palabra.

``CLAUDE.md`` terminaba en ``- `docs/DB_SCHEMA.md` — dicc``: **a mitad de la palabra
«diccionario» y sin salto de línea final** (5.042 bytes, verificado con `od -c`).

**No lo truncó ningún commit: nació así.** Los tamaños del blob a lo largo de su
historia van 2.438 → 2.641 → 3.081 → 3.749 → 3.944 → 4.352 → 5.042 y **las siete
versiones terminan en `— dicc`**. Creció monotónicamente y el corte estuvo siempre.

**Por qué sobrevivió siete commits:** todos tocan el **principio** del archivo —reglas
no-negociables, mapa, cómo correr— y el corte está en el último renglón de la última
sección. Es el archivo que se carga como instrucciones **en cada sesión**, y que haya
llegado hasta acá dice que nadie lo leyó entero.

**Lo que no se puede saber, y va dicho:** si había entradas *después* de esa línea. El
corte es anterior a toda la historia registrada, así que no hay versión sana de dónde
recuperarlas. Lo que sí se hizo fue revisar la lista: faltaban ``schema_management.md``
(que el propio `CLAUDE.md` necesita para la sección de migraciones) y el roadmap, y se
agregaron.

**El guard es del corpus entero, no de un archivo.** Medido antes de escribirlo:
`CLAUDE.md` era **el único** de los 137 `.md` sin newline final, así que la propiedad
ya se cumplía en todos lados y sostenerla no cuesta nada. Un guard de un archivo solo
habría sido la lista de la 133 con otra ropa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

_CORPUS = [
    _REPO / "CLAUDE.md",
    *sorted((_REPO / ".claude").rglob("*.md")),
    *sorted((_REPO / "docs").glob("*.md")),
]


def test_ningun_md_del_corpus_termina_sin_salto_de_linea():
    """Un archivo sin newline final es la firma de una escritura que se cortó.

    No es una convención de estilo: es la evidencia mecánica de que el contenido puede
    estar incompleto, y es lo único que habría cazado este defecto en su primer commit.
    """
    sin_newline = [
        f"{p.relative_to(_REPO).as_posix()}: …{p.read_text(encoding='utf-8').splitlines()[-1][-50:]}"
        for p in _CORPUS
        if (b := p.read_bytes()) and not b.endswith(b"\n")
    ]
    assert not sin_newline, (
        "estos archivos del corpus no terminan en salto de línea, que es la firma de "
        "una escritura cortada (tarea 136):\n  " + "\n  ".join(sin_newline)
    )


def test_el_corpus_no_esta_vacio():
    """Contraprueba: un barrido que no encontró archivos pasa igual de verde."""
    assert len(_CORPUS) >= 100


def test_la_ultima_linea_de_CLAUDE_md_es_una_entrada_COMPLETA():
    """El defecto concreto: la última línea era un ítem de lista cortado a la mitad.

    ``- `x` — dicc`` no termina en punto; ``- `x` — diccionario de tablas.`` sí. Es el
    chequeo más barato que distingue una línea terminada de una cortada, y sólo se le
    puede pedir a un archivo cuya última sección **es** una lista de referencias.
    """
    ultima = (_REPO / "CLAUDE.md").read_text(encoding="utf-8").rstrip("\n").splitlines()[-1]
    assert ultima.startswith("- "), f"la última línea dejó de ser un ítem de lista: {ultima!r}"
    assert ultima.endswith("."), f"la última línea parece cortada: {ultima!r}"


@pytest.mark.parametrize(
    "doc",
    ["docs/BACKLOG.md", "docs/ARCHITECTURE.md", "docs/SETTINGS_REFERENCE.md", "docs/DB_SCHEMA.md"],
)
def test_cada_doc_que_CLAUDE_md_lista_EXISTE(doc):
    """La lista de referencias no puede apuntar a un archivo que no está.

    Se fija sobre los cuatro que ya estaban antes de esta tarea: si mañana alguien
    renombra uno, el archivo de instrucciones manda a leer algo inexistente **en cada
    sesión**, que es el mismo daño que la línea cortada.
    """
    assert (_REPO / doc).is_file(), f"{doc} no existe y CLAUDE.md lo lista"
    assert doc in (_REPO / "CLAUDE.md").read_text(encoding="utf-8"), f"{doc} salió de la lista"
