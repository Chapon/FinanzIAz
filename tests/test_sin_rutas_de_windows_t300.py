"""Tarea 300 — ningún test escribe una ruta de Windows literal.

**El defecto.** ``tests/test_log_con_origen_t288.py`` le pasaba a ``origen_del_proceso``
``r"D:\\…\\main.py"``. En Windows pasa; en Linux ``\\`` no separa rutas, ``Path(...).name`` devuelve
la ruta entera y el test falla. El CI quedó rojo **19 corridas** y **17 tareas** se cerraron con
los cuatro comandos del done en verde, porque el cuarto (``run_suite_sin_estado_vivo.py``) corre
en Windows y declara justamente ese punto ciego. Es la tercera vez que el CI rojo pasa sin que el
proceso se entere (106, 175).

**Lo que hace este guard:** mueve **esta clase** de rotura de Linux a la suite de Windows, que es
la que corre antes del commit. Barre con ``ast`` las constantes de texto de ``tests/`` y rechaza
las que empiezan con una letra de unidad y ``\\`` (``C:\\``, ``D:\\``). La ruta se construye con
``Path`` (``str(Path(_REPO.anchor, "x", "a.py"))``), que da la forma nativa en cada plataforma; si
un test necesita la forma de Windows en cualquier plataforma, usa ``PureWindowsPath`` y compara
contra ella.

**Lo que NO ve, y va dicho:** el resto de lo que sólo rompe en Linux —mayúsculas en nombres de
archivo, permisos, locale, ``os.sep`` armado a mano, un ``"\\\\"`` que no es una ruta absoluta—. Para eso
está la otra mitad de la tarea 300: la tarea no se cierra hasta que ``scripts/check_ci.py`` lee el
CI del commit pusheado en verde.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TESTS = _REPO / "tests"

# Letra de unidad + barra invertida al principio del texto. La barra normal (``C:/x``) no entra:
# en Linux tampoco separa la unidad, pero ``Path("C:/x/a.py").name`` sí da ``a.py``, que es el caso
# que importa; y ``C:/`` aparece en URLs y textos de ayuda.
_RUTA_WINDOWS = re.compile(r"^[A-Za-z]:\\")


def rutas_de_windows(fuente: str) -> list[tuple[int, str]]:
    """``(línea, texto)`` de cada constante de texto que es una ruta de Windows literal."""
    hallados = []
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) and _RUTA_WINDOWS.match(nodo.value):
            hallados.append((nodo.lineno, nodo.value))
    return hallados


def test_ningun_test_escribe_una_ruta_de_windows_literal():
    hallados = []
    for archivo in sorted(_TESTS.rglob("*.py")):
        for linea, texto in rutas_de_windows(archivo.read_text(encoding="utf-8")):
            hallados.append(f"{archivo.relative_to(_REPO).as_posix()}:{linea}: {texto!r}")
    assert not hallados, (
        "rutas de Windows literales en tests —en Linux (el CI) `\\` no separa y el test rompe "
        "sólo ahí. Construí la ruta con Path(...) o usá PureWindowsPath:\n" + "\n".join(hallados)
    )


def test_CONTROL_el_barrido_ve_la_forma_del_defecto_y_no_la_inofensiva():
    """La población real hoy no contiene el caso: sin este control el guard podría ser ciego.

    Los literales se arman concatenando para que este archivo no se acuse a sí mismo.
    """
    unidad = "D" + ":"
    con_defecto = f"x = r'{unidad}\\Rodrigo\\main.py'\ny = '{unidad}\\\\a\\\\b.py'\n"
    assert [linea for linea, _ in rutas_de_windows(con_defecto)] == [1, 2]
    inofensivo = f"a = '{unidad}/x/main.py'\nb = 'https://x.com/{unidad}\\\\y'\nc = 'no {unidad}\\\\z'\n"
    assert rutas_de_windows(inofensivo) == []


def test_CONTROL_el_test_de_la_288_ya_no_tiene_la_forma():
    assert rutas_de_windows((_TESTS / "test_log_con_origen_t288.py").read_text(encoding="utf-8")) == []
