"""Tarea 432 — la app se relanza con el ``.venv`` y, si no puede, lo avisa donde se ve.

El WARNING de la 401 iba sólo al log, y la app se abrió con la Anaconda en los 9 arranques
siguientes. Chapa eligió el 2026-11-19 que ``main.py`` se relance solo con el ``.venv`` cuando
existe, y el aviso pasa a la barra de estado.

Las rutas se arman con ``os.path.join``: un literal de Windows en un test es lo que dejó el CI rojo
19 corridas en la 300.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import entorno

_RAIZ = os.path.join(os.sep, "repo")
_VENV = os.path.join(_RAIZ, ".venv")
_ANACONDA = os.path.join(os.sep, "anaconda3")


def _existe(*rutas):
    return lambda p: p in rutas


def _cmd(executable, prefix, environ=None, existe=None, argv=("main.py",)):
    return entorno.comando_para_relanzar(
        executable,
        prefix,
        list(argv),
        environ or {},
        root=_RAIZ,
        existe=existe
        or _existe(entorno.python_del_venv(_RAIZ), entorno.python_del_venv(_RAIZ, sin_consola=True)),
    )


def test_con_otro_interprete_y_el_venv_presente_se_relanza_con_el_venv():
    cmd = _cmd(os.path.join(_ANACONDA, "python.exe"), _ANACONDA, argv=("main.py", "--algo"))
    assert cmd == [entorno.python_del_venv(_RAIZ), os.path.join(_RAIZ, "main.py"), "--algo"]


def test_sin_consola_se_relanza_sin_consola():
    """Con `pythonw` no hay consola: relanzar con `python.exe` abriría una ventana negra."""
    cmd = _cmd(os.path.join(_ANACONDA, "pythonw.exe"), _ANACONDA)
    assert cmd[0] == entorno.python_del_venv(_RAIZ, sin_consola=True)


def test_con_el_venv_no_se_relanza():
    assert _cmd(os.path.join(_VENV, "Scripts", "python.exe"), _VENV) is None


def test_sin_venv_no_se_relanza():
    assert _cmd(os.path.join(_ANACONDA, "python.exe"), _ANACONDA, existe=lambda p: False) is None


def test_la_variable_corta_el_bucle():
    """Si el `.venv` relanzado no se reconoce como tal (un symlink, otro `prefix`), sin el corte
    se relanzaría para siempre."""
    environ = {entorno.VARIABLE_RELANZADA: os.path.join(_ANACONDA, "python.exe")}
    assert _cmd(os.path.join(_ANACONDA, "python.exe"), _ANACONDA, environ=environ) is None


def test_relanzar_corre_el_comando_con_la_variable_y_sale_con_su_codigo():
    llamadas = []

    def correr(cmd, env, cwd):
        llamadas.append((cmd, env, cwd))
        return 3

    with pytest.raises(SystemExit) as fin:
        entorno.relanzar(["py", "main.py"], {"PATH": "x"}, "yo.exe", correr=correr, root=_RAIZ)
    assert fin.value.code == 3
    cmd, env, cwd = llamadas[0]
    assert cmd == ["py", "main.py"] and env[entorno.VARIABLE_RELANZADA] == "yo.exe" and env["PATH"] == "x"
    assert cwd == _RAIZ


def test_si_el_venv_no_arranca_sigue_con_este_interprete():
    def correr(cmd, env, cwd):
        raise OSError("no se pudo")

    assert entorno.relanzar(["py"], {}, "yo.exe", correr=correr, root=_RAIZ) is False


def test_main_relanza_antes_de_abrir_el_log_o_la_DB():
    """El orden importa: dos procesos con el mismo log rotativo se pisan la rotación en Windows,
    y el padre no tiene que migrar nada."""
    texto = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    cuerpo = texto[texto.index("def main():") :]
    assert cuerpo.index("_relanzar_con_el_venv()") < cuerpo.index("setup_logging()")
