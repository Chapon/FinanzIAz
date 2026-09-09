"""Tarea 135 (SKILLDECAY-DESVIOS) — las skills no escriben a mano un número que el fuente puede contar.

Tres números caducados en los dos archivos que se leen **antes** de escribir un
pre-registro, o sea que dirigen el diseño de la próxima corrida:

* ``backtest-replay-harness/SKILL.md`` decía *«ya está cableado en los **16** runners
  de cartera»*; medido hoy por AST son **21** los que pasan ``window=`` a ``announce()``
  (**22** si se cuenta cualquier llamada — el T7 lo pasa a otra).
* ``auditoria/SKILL.md`` preguntaba *«¿hay un **octavo** desvío…?»* cuando el fuente ya
  numeraba el octavo y sumaba cuatro ejes más.
* ``auditoria/SKILL.md`` daba un conteo de archivos y otro de tests; los dos quedaron
  cortos por más de un 15%. **Acá no se repiten a propósito**: la primera versión de
  este docstring escribió los de hoy y caducaron **dentro de la misma tarea** —los
  cuatro tests de este archivo movieron el total— que es la demostración más corta
  posible de por qué se sacan en vez de actualizarse.

**Lo irónico es el punto.** Ese último párrafo existe **para advertir que el número
caduca** (*«el número de esta frase ya caducó una vez, en 20 minutos»*). El remedio de
entonces —agregar la advertencia y pedir que se contara en el fuente— **funcionó** (la
corrida del 2026-09-08 lo detectó contando) pero **no impidió la recurrencia**. Una
advertencia no es un guard.

Por eso el arreglo fue **sacar los números**, no actualizarlos: *«los runners de
cartera»* y *«¿falta algún desvío?»* no caducan. Y por eso además está este test: es la
única forma de que la lección no dependa de que el próximo lector se acuerde.

**Lo que este guard NO puede ver, y va declarado:** mira **texto**, así que sólo caza
la forma *«N sustantivo-contable»*. Un número caducado escrito de otra manera —*«el
factor 0.50»*, que es la tarea 137— se le escapa entero. Es un guard de una forma, no
de una propiedad; el instrumento correcto para lo otro sería re-medir contra el fuente,
que ninguna prosa permite hacer sola.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parent.parent / ".claude" / "skills"

# Sustantivos cuyo conteo el fuente **puede** dar. Escribirlos a mano en una skill es
# fabricar un claim que caduca solo — la clase de la tarea 138.
_CONTABLES = r"runners?|tests?|archivos?|scripts?|desv[ií]os?"

# El número tiene que **terminar en dígito**, para no confundir un ítem de lista
# numerada (`6. Tests offline del harness`) con un conteo. Lo aprendí midiendo: la
# primera versión de este patrón lo acusaba, igual que el guard de la 128 acusaba a la
# prosa que citaba el defecto arreglado.
_PATRON = re.compile(rf"\b\d+(?:[.,]\d+)*\s+(?:{_CONTABLES})\b", re.IGNORECASE)


def _conteos_a_mano(path: Path) -> list[str]:
    return [
        f"{path.name}:{i}: {m.group(0)}"
        for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for m in _PATRON.finditer(ln)
    ]


@pytest.mark.parametrize(
    "skill",
    ["auditoria", "backtest-replay-harness"],
)
def test_las_skills_del_pre_registro_no_traen_conteos_a_mano(skill):
    """Las dos que se leen ANTES de diseñar una corrida, que es donde más cuesta.

    Un número caducado en una skill no es un error de documentación: **dirige el
    diseño del próximo pre-registro** hacia una premisa falsa.
    """
    culpables = _conteos_a_mano(_SKILLS / skill / "SKILL.md")
    assert not culpables, (
        "estas skills escriben a mano un conteo que el fuente puede dar, y por lo tanto "
        "caduca solo (tarea 135). Sacá el número —la frase suele funcionar igual sin él— "
        "o decí cómo contarlo:\n  " + "\n  ".join(culpables)
    )


def test_el_patron_distingue_un_conteo_de_un_item_de_lista():
    """Contraprueba del instrumento, no del repo.

    Sin esto el test de arriba podría estar pasando porque el patrón no matchea nada.
    """
    assert _PATRON.search("cableado en los 16 runners de cartera")
    assert _PATRON.search("~330 archivos y 2.396 tests")
    assert not _PATRON.search("6. Tests offline del harness (ver abajo)")
    assert not _PATRON.search("la tarea 135 y el commit 94adb58")


def test_el_ordinal_HISTORICO_del_septimo_desvio_sigue_declarado_como_tal():
    """**Lo que NO hay que "arreglar", y por eso está fijado.**

    T48 *es* el séptimo desvío en la numeración **histórica** —el orden en que se
    descubrieron— y ese ordinal no caduca. Confundirlo con el conteo vivo de líneas que
    ``deviations()`` emite hoy fabrica un hallazgo falso, y casi pasó en la corrida del
    2026-09-08. La skill tiene que decir **explícitamente** que ese número es histórico.
    """
    txt = (_SKILLS / "backtest-replay-harness" / "SKILL.md").read_text(encoding="utf-8")
    assert "numeración **histórica**" in txt
    assert 'no lo "arregles"' in txt or "no lo «arregles»" in txt
