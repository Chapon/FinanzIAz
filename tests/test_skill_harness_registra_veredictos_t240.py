"""Tarea 240 — la skill del harness registra cada veredicto de la tabla de validez.

`.claude/skills/backtest-replay-harness/SKILL.md` es donde este repo guarda sus lecciones de
harness (cómo construir un oráculo, la rejilla cerrada, la población de un barrido). Dos veces se
quedó atrás: la 180 (no registraba T167 ni T170) y la auditoría del 2026-09-30 (no registraba la
T219, que cerró un eje y dejó la trampa de ``stop_mult=0.0``). El arreglo de la 180 fue un
párrafo, no un mecanismo, y volvió a pasar a la primera.

El mecanismo: toda tarea con fila en `docs/VALIDEZ_VEREDICTOS.md` —la población que la 189
descubre, runners con sanity anclado o de clase `magnitud`— tiene que estar **nombrada** en la
skill.

**Lo que NO ve, dicho:** un veredicto sin runner en esa población (la T220, por ejemplo, que no
tiene runner) y la **calidad** de la entrada: nombrar la tarea no garantiza que la lección esté
bien escrita. Es un piso, no un revisor.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TABLA = _REPO / "docs" / "VALIDEZ_VEREDICTOS.md"
_SKILL = _REPO / ".claude" / "skills" / "backtest-replay-harness" / "SKILL.md"

_FILA = re.compile(r"^\| `[^`]+` \| (T\d+[a-z]?) \|", re.M)


def tareas_de_la_tabla(texto: str) -> list[str]:
    return _FILA.findall(texto)


def no_registradas(tabla: str, skill: str) -> list[str]:
    return [t for t in tareas_de_la_tabla(tabla) if not re.search(rf"\b{re.escape(t)}\b", skill)]


def test_todo_veredicto_de_la_tabla_esta_en_la_skill():
    faltan = no_registradas(_TABLA.read_text(encoding="utf-8"), _SKILL.read_text(encoding="utf-8"))
    assert not faltan, (
        "la skill del harness no nombra estos veredictos de `docs/VALIDEZ_VEREDICTOS.md` "
        f"(tarea 240): {faltan}. Registrá la lección en *Lecciones registradas*."
    )


def test_la_tabla_se_parsea_de_verdad():
    """Contraprueba: si el patrón de fila dejara de matchear, el test de arriba pasaría vacío."""
    tareas = tareas_de_la_tabla(_TABLA.read_text(encoding="utf-8"))
    assert len(tareas) >= 10 and "T219" in tareas and "T26b" in tareas, tareas


def test_una_fila_nueva_sin_leccion_se_acusa():
    """Mutación en el sentido del falso positivo: un veredicto nuevo que nadie registró."""
    tabla = _TABLA.read_text(encoding="utf-8") + "| `run_x_t999.py` | T999 | NO-SHIP | ... |\n"
    assert no_registradas(tabla, _SKILL.read_text(encoding="utf-8")) == ["T999"]


def test_T26_no_se_da_por_registrada_con_T26b():
    """El borde de palabra importa: nombrar la T26b no registra la T26, ni al revés."""
    assert no_registradas("| `a.py` | T26 | x |\n", "sólo la T26b") == ["T26"]
