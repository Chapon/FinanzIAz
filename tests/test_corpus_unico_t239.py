"""Tarea 239 — los guards de corpus leen UN corpus, derivado de lo que `CLAUDE.md` declara.

Ver el docstring de `tests/corpus_operativo.py` para el porqué.
"""

from __future__ import annotations

import pytest

import tests.test_corpus_cuenta_y_killonly_t198 as t198
import tests.test_corpus_operativo_t72 as t72
import tests.test_corpus_valores_vivos_t137 as t137
from tests.corpus_operativo import CORPUS, FUERA_DEL_CORPUS, REPO, docs_de_referencia


def test_todo_doc_de_referencia_esta_en_el_corpus_o_excluido_con_motivo():
    """El test que evita que vuelva a pasar: un doc nuevo en la lista de `CLAUDE.md` que no
    entra al corpus ni se excluye con motivo pone esto en rojo."""
    en_corpus = {p.relative_to(REPO).as_posix() for p in CORPUS}
    sin_clasificar = [d for d in docs_de_referencia() if d not in en_corpus and d not in FUERA_DEL_CORPUS]
    assert not sin_clasificar, sin_clasificar


def test_no_hay_exclusiones_FANTASMA():
    """Una exclusión de un doc que `CLAUDE.md` ya no lista no excluye nada y desgasta la tabla."""
    fantasmas = set(FUERA_DEL_CORPUS) - set(docs_de_referencia())
    assert not fantasmas, fantasmas


def test_cada_exclusion_dice_POR_QUE():
    cortas = [d for d, motivo in FUERA_DEL_CORPUS.items() if len(motivo) < 60]
    assert not cortas, cortas


def test_la_seccion_se_parsea_de_verdad():
    """Contraprueba: si el parseo dejara de matchear, el corpus caería a `CLAUDE.md` + skills y
    los tests de arriba pasarían sin mirar ningún doc."""
    refs = docs_de_referencia()
    assert "docs/DB_SCHEMA.md" in refs and "docs/ARCHITECTURE.md" in refs
    assert all((REPO / d).is_file() for d in refs), refs


def test_DB_SCHEMA_esta_en_el_corpus():
    """El caso que abrió la tarea."""
    assert REPO / "docs" / "DB_SCHEMA.md" in CORPUS


@pytest.mark.parametrize("guard", [t72, t137, t198], ids=["t72", "t137", "t198"])
def test_los_tres_guards_leen_EL_MISMO_corpus(guard):
    assert guard._CORPUS is CORPUS


def test_un_doc_nuevo_en_CLAUDE_md_sin_clasificar_se_detecta():
    """Mutación en el sentido del falso positivo, sobre el parseo: un doc declarado y no leído."""
    texto = (REPO / "CLAUDE.md").read_text(encoding="utf-8") + "\n- `docs/NUEVO.md` — algo.\n"
    assert "docs/NUEVO.md" in docs_de_referencia(texto)
