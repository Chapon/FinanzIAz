"""Tarea 250 — `check_repo_health.py` deja de anunciar un chequeo que no podía dispararse.

El cuarto chequeo buscaba `finanzias.db` entre los archivos staged para frenar *«escritura de la
DB desde un entorno no-Windows»*. La DB está en `.gitignore` y no versionada: no podía aparecer
nunca (salvo `git add -f`), y además miraba **commitear** cuando la regla 5 de `CLAUDE.md` prohíbe
**escribir**. Inerte desde que se creó (2026-06-24); lo encontró la segunda tanda `/audit` del
2026-09-30 ([G-2] de `docs/auditoria_guards_2026-09-30b.md`).

Decisión: se saca, y la regla 5 queda dicha como **manual**. Un chequeo de verdad tendría que ir
en la capa de DB, y un clon en Linux (CI, nube, la Pi de la 196) ni siquiera tiene la DB, porque
no está versionada.

Lo que se fija: que el chequeo no vuelva a existir **en silencio**, y que ningún texto del corpus
operativo vuelva a anunciarlo como protección.
"""

from __future__ import annotations

import inspect

import scripts.check_repo_health as g
from tests.corpus_operativo import CORPUS, REPO
from tests.test_corpus_cuenta_y_killonly_t198 import _sin_citas

_ANUNCIO = "DB desde no-Windows"


def anuncios(texto: str) -> int:
    """Cuántas veces el texto anuncia el chequeo FUERA de una cita «…»."""
    return _sin_citas(texto).count(_ANUNCIO)


def test_el_chequeo_inerte_ya_no_esta_en_el_script():
    assert not hasattr(g, "check_db_write_env")
    assert "finanzias.db" not in inspect.getsource(g.main)


def test_ningun_texto_operativo_lo_anuncia():
    textos = [
        *CORPUS,
        REPO / ".claude" / "commands" / "ship.md",
        REPO / ".claude" / "agents" / "verificador.md",
    ]
    malos = [p.relative_to(REPO).as_posix() for p in textos if anuncios(p.read_text(encoding="utf-8"))]
    assert not malos, f"anuncian un chequeo que no existe (tarea 250): {malos}"


def test_el_texto_viejo_se_acusa_y_la_cita_no():
    """Mutación en el sentido del falso positivo: la frase vieja de `/ship`; y el control, la
    misma frase citada para contar que se sacó."""
    assert anuncios("Si reporta problemas (CRLF en .bat, null-bytes, DB desde no-Windows), PARÁ") == 1
    assert anuncios("El chequeo «DB desde no-Windows» no podía dispararse") == 0
