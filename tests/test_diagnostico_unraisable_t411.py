"""Tarea 411 — una excepción *unraisable* da rojo CON el dato, no un rojo mudo.

El 2026-11-06 una corrida dio ``RuntimeError: Failed to process unraisable exception``
causado por ``RecursionError`` en ``traceback.format_exception``: el GC disparó con la pila
cerca del límite y el hook de pytest no pudo ni formatear. Se fija:

* que el envoltorio (``tests/_diagnostico_unraisable.py``) está instalado en la sesión;
* que con la pila al borde, el mismo hook que formatea **revienta sin** el envoltorio y
  **anda con** él (el caso no es degenerado: se prueba primero que sin él falla);
* que la línea de diagnóstico no hace ``repr`` del objeto;
* de punta a punta, en un pytest aparte: un ``__del__`` que levanta da rojo, con la marca,
  el test y el tipo del objeto en la salida;
* que ``pyproject.toml`` convierte el aviso en error.
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import tomllib

from tests import _diagnostico_unraisable as diag

ROOT = Path(__file__).resolve().parent.parent


def _unraisable(objeto=None):
    def _hondo(n):
        if n == 0:
            raise ValueError("desde un __del__")
        _hondo(n - 1)

    try:
        _hondo(40)
    except ValueError as e:
        return SimpleNamespace(
            exc_type=ValueError,
            exc_value=e,
            exc_traceback=e.__traceback__,
            err_msg="Exception ignored in",
            object=objeto,
        )


def _hook_como_el_de_pytest(resultado: list):
    def previo(u, /):
        resultado.append("".join(traceback.format_exception(u.exc_type, u.exc_value, u.exc_traceback)))

    return previo


def _al_borde_de_la_pila(fn, holgura: int):
    """Llama ``fn`` con la pila a ``holgura`` niveles del límite de recursión."""

    def bajar():
        f, n = sys._getframe(), 0
        while f is not None:
            n += 1
            f = f.f_back
        if n >= sys.getrecursionlimit() - holgura:
            return fn()
        return bajar()

    return bajar()


def test_el_envoltorio_esta_instalado_en_la_sesion():
    assert getattr(sys.unraisablehook, "envoltorio_t411", False)


def _holgura_que_revienta(u) -> int | None:
    """La holgura MÁS GRANDE a la que el hook pelado todavía revienta, en ESTA versión.

    No es una constante: en Windows/3.12 es 6, y en 3.11 las llamadas a funciones de C
    también cuentan contra el límite, así que con una holgura fija chica el envoltorio no
    alcanzaba ni a subir el límite (el CI de ``acb0abd`` lo dio rojo). Probar el envoltorio
    en la más grande que revienta le deja el mayor espacio y sigue distinguiendo."""
    for h in range(60, 1, -1):
        try:
            _al_borde_de_la_pila(lambda: _hook_como_el_de_pytest([])(u), h)
        except RecursionError:
            return h
    return None


def test_sin_el_envoltorio_el_formateo_revienta_al_borde_de_la_pila():
    """El caso que distingue: sin esto, el test de abajo pasaría aunque el margen no hiciera nada."""
    assert _holgura_que_revienta(_unraisable()) is not None


def test_con_el_envoltorio_formatea_entero_y_anota_antes(capsys):
    u = _unraisable()
    holgura = _holgura_que_revienta(u)
    assert holgura is not None
    res: list[str] = []
    limite = sys.getrecursionlimit()
    try:
        _al_borde_de_la_pila(lambda: diag.envolver(_hook_como_el_de_pytest(res))(u), holgura)
        # Al borde puede no poder devolverlo en el momento (queda pendiente); en todo caso
        # lo devuelve la próxima fase del test, con la pila baja.
        diag.restaurar_limite_pendiente()
        assert sys.getrecursionlimit() == limite
    finally:
        sys.setrecursionlimit(limite)
        diag._limite_pendiente.clear()
    (texto,) = res
    assert "ValueError: desde un __del__" in texto and "_hondo" in texto
    err = capsys.readouterr().err
    assert diag.MARCA in err and "exc ValueError" in err
    assert "traceback 42 frames" in err


def test_con_la_pila_baja_el_limite_se_devuelve_en_el_momento():
    limite = sys.getrecursionlimit()
    diag.envolver(_hook_como_el_de_pytest([]))(_unraisable())
    assert sys.getrecursionlimit() == limite and not diag._limite_pendiente


def test_si_no_puede_devolver_el_limite_en_el_momento_queda_pendiente(monkeypatch):
    """Lo que hace Python cuando la pila es más honda que el límite a devolver:
    ``setrecursionlimit`` levanta ``RecursionError``. Se simula con un ``sys`` falso para
    que el camino no dependa de la profundidad exacta de la versión."""
    llamadas: list[int] = []

    def setrecursionlimit(n):
        llamadas.append(n)
        if len(llamadas) == 2:  # la segunda es la restauración
            raise RecursionError("cannot set the recursion limit: the limit is too low")

    falso = SimpleNamespace(
        getrecursionlimit=lambda: 1000,
        setrecursionlimit=setrecursionlimit,
        stderr=sys.stderr,
        _getframe=sys._getframe,
    )
    monkeypatch.setattr(diag, "sys", falso)
    monkeypatch.setattr(diag, "_limite_pendiente", [])
    diag.envolver(_hook_como_el_de_pytest([]))(_unraisable())
    assert llamadas == [1000 + diag.MARGEN_DE_PILA, 1000]
    assert diag._limite_pendiente == [1000]


def test_cada_fase_del_test_devuelve_el_limite_pendiente():
    limite = sys.getrecursionlimit()
    sys.setrecursionlimit(limite + 7)
    diag._limite_pendiente.append(limite)
    try:
        diag._fase("x::y", "call")
        assert sys.getrecursionlimit() == limite and not diag._limite_pendiente
    finally:
        sys.setrecursionlimit(limite)
        diag._limite_pendiente.clear()


def test_la_linea_no_hace_repr_del_objeto():
    class ReprQueRecursa:
        def __repr__(self):
            return repr(self)

    linea = diag.describir(_unraisable(ReprQueRecursa()))  # con repr, RecursionError
    assert f"objeto {__name__}." in linea and ".ReprQueRecursa (instancia) |" in linea


def test_para_un_del_nombra_la_clase_y_no_builtins_function():
    """Python pasa la función ``__del__`` como objeto: ``builtins.function`` no dice nada."""

    class ConDel:
        def __del__(self):
            pass

    linea = diag.describir(_unraisable(ConDel.__del__))
    assert ".ConDel.__del__ |" in linea and "builtins.function" not in linea


def test_de_punta_a_punta_un_del_que_levanta_da_rojo_con_el_dato(tmp_path):
    (tmp_path / "test_del.py").write_text(
        "import gc\n"
        "class Rompe:\n"
        "    def __del__(self):\n"
        "        raise ValueError('finalizador roto')\n"
        "def test_crea_y_suelta():\n"
        "    r = Rompe()\n"
        "    r.yo = r\n"
        "    del r\n"
        "    gc.collect()\n",
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]))
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(tmp_path / "test_del.py"),
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "tests._diagnostico_unraisable",
            "-W",
            "error::pytest.PytestUnraisableExceptionWarning",
            "--rootdir",
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    salida = r.stdout + r.stderr
    assert r.returncode != 0, salida
    assert diag.MARCA in salida, salida
    assert "test_del.py::test_crea_y_suelta" in salida and "objeto test_del.Rompe.__del__" in salida
    assert "finalizador roto" in salida


def test_pyproject_convierte_el_aviso_en_error():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert (
        "error::pytest.PytestUnraisableExceptionWarning"
        in cfg["tool"]["pytest"]["ini_options"]["filterwarnings"]
    )
