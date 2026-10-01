"""Tarea 249 — el backlog entra al corpus RECORTADO: header y secciones operativas, no el historial.

La 239 dejó `docs/BACKLOG.md` entero afuera del corpus con el motivo de que las tareas cerradas
citan a propósito lo que corrigieron. Valía para el historial y no para el texto operativo en
presente, que es donde la auditoría del 2026-09-30 encontró dos hallazgos (la instrucción de la
segunda opinión y el «modo kill_only» del header). La segunda tanda lo probó con una mutación en
el sentido del falso positivo: la frase falsa en *Acciones manuales* dejaba el guard en verde.
"""

from __future__ import annotations

import re

from tests.corpus_operativo import CORPUS, RECORTADOS, REPO, recortar
from tests.test_corpus_cuenta_y_killonly_t198 import cuentas_que_no_son_la_viva

_BACKLOG = REPO / "docs" / "BACKLOG.md"
_SECCIONES = RECORTADOS["docs/BACKLOG.md"]


def _crudo() -> str:
    return _BACKLOG.read_bytes().decode("utf-8")


def test_el_backlog_esta_en_el_corpus_y_se_lee_RECORTADO():
    entradas = [p for p in CORPUS if p.relative_to(REPO).as_posix() == "docs/BACKLOG.md"]
    assert len(entradas) == 1
    assert entradas[0].read_text(encoding="utf-8") == recortar(_crudo(), _SECCIONES)


def test_la_mutacion_de_la_auditoria_se_pone_ROJA():
    """La frase falsa en *Acciones manuales pendientes*: antes, verde."""
    # Anclado a inicio de línea: la cadena aparece antes CITADA adentro de tareas cerradas (la
    # trampa que el propio backlog documenta en la tarea 138).
    i = re.search(r"(?m)^## Acciones manuales pendientes", _crudo()).start()
    fin = _crudo().index("\n", i)
    mutado = (
        _crudo()[: fin + 1]
        + '\n- Cuenta activa: "Sim Principal" (id=1), modo kill_only.\n'
        + _crudo()[fin + 1 :]
    )
    assert cuentas_que_no_son_la_viva(recortar(mutado, _SECCIONES)) == [("Sim Principal", 1)]


def test_cada_seccion_declarada_EXISTE_y_entra():
    """Contraprueba: una sección renombrada dejaría el recorte en el header solo, y verde."""
    recorte = recortar(_crudo(), _SECCIONES)
    for s in _SECCIONES:
        assert f"\n## {s}" in _crudo(), f"el backlog ya no tiene la sección {s!r}: actualizá RECORTADOS"
        assert f"## {s}" in recorte


def test_el_historial_queda_AFUERA():
    recorte = recortar(_crudo(), _SECCIONES)
    for s in ("## Hecho reciente", "## En curso", "## Acciones manuales resueltas", "## Próximo"):
        assert s not in recorte, s
    assert "_Última actualización" not in recorte, "la bitácora fechada del header es historia"
