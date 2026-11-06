"""Diagnóstico de las excepciones *unraisable* de la suite (tarea 411).

Una *unraisable* es una excepción que nadie puede atrapar: la levanta un ``__del__``, un
callback de ``weakref`` o un finalizador mientras el GC junta un objeto, y Python se la pasa a
``sys.unraisablehook``. pytest instala ahí su hook, que **formatea el traceback adentro del
hook**. El 2026-11-06 una corrida dio rojo en un test que no tenía nada que ver
(``test_toggle_wiring.py::test_hmm_enabled_off_skips_hmm``) con
``RuntimeError: Failed to process unraisable exception`` causado por ``RecursionError`` en
``traceback.format_exception``: el GC disparó con la pila cerca del límite y el formateo se
quedó sin pila. Resultado: un rojo **sin ningún dato** de qué objeto era.

Este envoltorio, instalado por ``tests/conftest.py`` encima del hook de pytest:

1. escribe en ``sys.stderr`` —que pytest muestra en la sección del test que falla— una línea
   con el test en curso, el tipo de la excepción, el tipo del objeto, la profundidad de pila
   y el último frame del traceback, **antes** de formatear nada y sin ``repr`` del objeto
   (que puede ser justo lo que recursa);
2. le da a pytest ``MARGEN_DE_PILA`` niveles más de recursión mientras formatea, así el
   traceback completo llega entero.

Y ``pyproject.toml`` convierte ``PytestUnraisableExceptionWarning`` en error: sin eso, una
unraisable que sí se formatea queda como un aviso más del resumen, que nadie lee.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable

import pytest

MARCA = "UNRAISABLE (tarea 411)"
MARGEN_DE_PILA = 2000

#: El test en curso, que actualizan los hooks de fase de abajo.
contexto: dict[str, str] = {"nodeid": "(fuera de un test)", "fase": "-"}


def _profundidad() -> int:
    f, n = sys._getframe(), 0
    while f is not None:
        n += 1
        f = f.f_back
    return n


def _nombre(objeto) -> str:
    """Qué es el objeto, sin ``repr``. Para un ``__del__`` que levanta, Python pasa la
    **función** ``__del__``: su ``__qualname__`` (``Clase.__del__``) es lo que sirve."""
    try:
        qual = object.__getattribute__(objeto, "__qualname__")
        mod = object.__getattribute__(objeto, "__module__")
        if isinstance(qual, str):
            return f"{mod}.{qual}"
    except BaseException:
        pass
    tipo = type(objeto)
    return f"{tipo.__module__}.{tipo.__qualname__} (instancia)"


def describir(u) -> str:
    """Una línea con lo que hace falta para encontrar el origen, sin formatear el traceback."""
    tb, frames, ultimo = u.exc_traceback, 0, None
    while tb is not None:
        frames += 1
        ultimo = tb
        tb = tb.tb_next
    donde = f"{ultimo.tb_frame.f_code.co_filename}:{ultimo.tb_lineno}" if ultimo is not None else "-"
    return (
        f"{MARCA}: {contexto['nodeid']} [{contexto['fase']}] | "
        f"exc {getattr(u.exc_type, '__name__', u.exc_type)} | err_msg {u.err_msg} | "
        f"objeto {_nombre(u.object)} | "
        f"pila {_profundidad()} de {sys.getrecursionlimit()} | "
        f"traceback {frames} frames, el último en {donde}"
    )


#: El límite a devolver cuando no se pudo en el momento (ver ``envolver``).
_limite_pendiente: list[int] = []


def restaurar_limite_pendiente() -> None:
    """Devuelve el límite de recursión que el hook no pudo devolver. Se llama desde los hooks
    de fase de pytest, donde la pila es baja."""
    while _limite_pendiente:
        limite = _limite_pendiente.pop()
        try:
            sys.setrecursionlimit(limite)
        except RecursionError:
            _limite_pendiente.append(limite)
            return


def envolver(previo: Callable) -> Callable:
    """El hook que va encima de ``previo`` (el de pytest).

    Devolver el límite **en el momento** puede ser imposible: si el hook corre con la pila
    más honda que el límite original, ``setrecursionlimit`` lo rechaza. Entonces queda
    pendiente y lo devuelve ``restaurar_limite_pendiente`` en la próxima fase del test.
    """

    def hook(u, /) -> None:
        # Primero el margen: al borde de la pila hasta un ``with`` gasta un frame de más.
        # ``getrecursionlimit``/``setrecursionlimit`` son de C y no ocupan frame de Python.
        limite = sys.getrecursionlimit()
        sys.setrecursionlimit(limite + MARGEN_DE_PILA)
        try:
            with contextlib.suppress(BaseException):  # el diagnóstico no tapa lo que diagnostica
                sys.stderr.write(describir(u) + "\n")
            previo(u)
        finally:
            try:
                sys.setrecursionlimit(limite)
            except RecursionError:
                _limite_pendiente.append(limite)

    hook.envoltorio_t411 = True
    return hook


# ── Plugin: lo carga ``tests/conftest.py`` vía ``pytest_plugins`` ────────────


@pytest.hookimpl(trylast=True)
def pytest_configure(config) -> None:
    # ``trylast``: el ``pytest_configure`` de ``_pytest.unraisableexception`` ya instaló el
    # suyo, y éste va encima. pytest restaura el hook previo al suyo en su cleanup.
    sys.unraisablehook = envolver(sys.unraisablehook)


def _fase(nodeid: str, fase: str) -> None:
    restaurar_limite_pendiente()
    contexto.update(nodeid=nodeid, fase=fase)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item) -> None:
    _fase(item.nodeid, "setup")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item) -> None:
    _fase(item.nodeid, "call")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item) -> None:
    _fase(item.nodeid, "teardown")
