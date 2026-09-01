"""REPRO-LITERALES (tarea 71) — un runner no puede imprimir un "esperado" que no
salga de la constante contra la que realmente compara.

`run_prio_event_t49.py` tenía los tres valores esperados **hardcodeados como
literales de string** en el `print`, no interpolados. Cuando la tarea 68 re-ancló
esas constantes (`0.0371 → 0.0347`, `0.0792 → 0.0761`, `0.0197 → 0.0081`), el
`print` siguió diciendo los viejos, así que una corrida imprimía:

    E_analyze 3.47% (esperado 3.71%) · OK

El runner **se contradice a sí mismo** y el `OK` al lado de dos números que no
coinciden se lee como un bug de cañería — exactamente lo contrario de lo que el
sanity de reproducción existe para comunicar.

El patrón correcto ya estaba a dos archivos de distancia (`run_rank_neutral_t39`
y `run_anom_profile_t45` interpolan). Este test existe para que la próxima
re-anclada no vuelva a dejar el log mintiendo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# Un "esperado"/"expected" seguido de un número **literal** dentro de una f-string.
# Lo válido es `esperado {100 * CONSTANTE:.2f}%`; lo que este test caza es
# `esperado 3.71%`, que no puede seguir a la constante cuando ésta se mueve.
_LITERAL = re.compile(r"(?:esperad[oa]|expected)\s+-?\d")


def _runners() -> list[Path]:
    return sorted(_SCRIPTS.glob("run_*.py"))


def _lineas_de_codigo(texto: str) -> list[tuple[int, str]]:
    """Las líneas que NO son comentarios.

    El chequeo va sobre **código**, no sobre comentarios — mismo criterio que el
    test de la 69. Un comentario que cita el valor viejo (*"antes decía esperado
    3.71%"*) es exactamente lo que hay que conservar: quien lea el arreglo tiene
    que ver qué decía antes.
    """
    return [(i, linea) for i, linea in enumerate(texto.splitlines(), 1) if not linea.lstrip().startswith("#")]


def test_hay_runners_que_inspeccionar():
    """Si el glob deja de encontrar runners, el test de abajo pasa por vacío."""
    assert len(_runners()) >= 20


@pytest.mark.parametrize("runner", _runners(), ids=lambda p: p.name)
def test_ningun_runner_imprime_un_esperado_hardcodeado(runner: Path):
    """El número esperado tiene que salir de la constante, o el log puede mentir.

    Si este test se pone rojo: interpolá la constante (`{100 * MI_CONSTANTE:.2f}%`)
    en vez de escribir el número. No lo silencies — el caso real fue un `OK`
    impreso al lado de dos números distintos.
    """
    ofensivas = [
        f"{runner.name}:{i}: {linea.strip()[:100]}"
        for i, linea in _lineas_de_codigo(runner.read_text(encoding="utf-8"))
        if _LITERAL.search(linea)
    ]
    assert not ofensivas, "esperado con literal en vez de la constante:\n  " + "\n  ".join(ofensivas)


def test_el_t49_interpola_sus_tres_constantes():
    """Regresión puntual del caso que abrió la tarea: las tres, por nombre."""
    texto = (_SCRIPTS / "run_prio_event_t49.py").read_text(encoding="utf-8")
    for constante in ("SANITY_T45_ANALYZE", "SANITY_T45_MERGED_PRIO", "SANITY_T33_CAGR"):
        assert f"100 * {constante}:.2f" in texto, constante
    # y los literales viejos no volvieron **como código** (el comentario del arreglo
    # sí los cita, a propósito: quien lo lea tiene que ver qué decía antes)
    codigo = [linea for _, linea in _lineas_de_codigo(texto)]
    for viejo in ("3.71%", "7.92%", "1.97%"):
        assert not any(viejo in linea for linea in codigo), viejo


def test_los_docstrings_de_los_runners_no_fijan_el_numero_re_anclado():
    """`run_rank_neutral_t39` fijaba el 1.97% en su docstring de cabecera. Un
    docstring que repite una constante re-anclable caduca igual que un `print`,
    sólo que sin que nadie lo corra."""
    texto = (_SCRIPTS / "run_rank_neutral_t39.py").read_text(encoding="utf-8")
    cabecera = texto.split('"""')[1]
    assert "1.97%" not in cabecera
    assert "SANITY_T33_CAGR" in cabecera  # nombra la constante, no el valor
