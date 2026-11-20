"""Tarea 433 — con qué código corre la app: el commit y el WIP sin commitear.

El 2026-11-11 la opinión de MU salió del WIP de la 425 (``version_datos=5``, que ``HEAD`` no
tenía), y nada lo registraba: ni el log ni ``claude_opinions``. Ahora el arranque lo loguea, la
barra lo avisa y cada opinión guarda el commit y la marca de WIP.

Los casos con git van sobre un repo de prueba en ``tmp_path``, no sobre éste: el árbol de este repo
está sucio o limpio según el momento, y el test no puede depender de eso.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from config import codigo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="sin git")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "notas.md").write_text("hola\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "inicial")
    return tmp_path


def test_un_arbol_limpio_no_es_WIP(repo):
    estado = codigo.estado_del_codigo(str(repo))
    assert estado.commit and len(estado.commit) == 40
    assert not estado.wip and estado.resumen() == f"commit {estado.commit[:7]}"


def test_un_py_modificado_y_uno_sin_trackear_son_WIP(repo):
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / "nuevo.py").write_text("y = 1\n", encoding="utf-8")
    estado = codigo.estado_del_codigo(str(repo))
    assert estado.modificados == ("a.py", "sub/nuevo.py")
    assert "WIP sin commitear en 2 .py" in estado.resumen()


def test_lo_que_no_es_py_no_cuenta(repo):
    """Un doc o el backlog modificados no cambian lo que corre la app."""
    (repo / "notas.md").write_text("chau\n", encoding="utf-8")
    assert not codigo.estado_del_codigo(str(repo)).wip


def test_un_py_borrado_no_corre_y_no_cuenta(repo):
    (repo / "a.py").unlink()
    assert not codigo.estado_del_codigo(str(repo)).wip


def test_fuera_de_un_repo_no_afirma_nada(tmp_path):
    estado = codigo.estado_del_codigo(str(tmp_path))
    assert estado.commit is None and not estado.wip and estado.corto == "?"


@pytest.mark.parametrize(
    "porcelana,esperado",
    [
        (" M a.py\0?? b.py\0", ("a.py", "b.py")),
        ("R  nuevo.py\0viejo.py\0 M c.py\0", ("c.py", "nuevo.py")),
        (" D borrado.py\0 M doc.md\0", ()),
        ("", ()),
    ],
)
def test_la_porcelana_con_renombres(porcelana, esperado):
    """Con ``-z``, el origen de un renombre viene en la entrada siguiente: no es otro archivo."""
    assert codigo.modificados_de_porcelana(porcelana) == esperado


# ── El arranque y la opinión ─────────────────────────────────────────────────


class _Log:
    def __init__(self):
        self.lineas = []

    def warning(self, msg, *a):
        self.lineas.append(("WARNING", msg % a))

    def info(self, msg, *a):
        self.lineas.append(("INFO", msg % a))


_SUCIO = codigo.EstadoDelCodigo("b" * 40, ("analysis/opinion_claude.py",))
_LIMPIO = codigo.EstadoDelCodigo("b" * 40)


def test_el_arranque_con_WIP_deja_un_WARNING_con_los_archivos():
    log = _Log()
    codigo.loguear_arranque(log, _SUCIO)
    ((nivel, texto),) = log.lineas
    assert nivel == "WARNING" and "bbbbbbb" in texto and "analysis/opinion_claude.py" in texto


def test_el_arranque_limpio_deja_el_commit_en_INFO():
    log = _Log()
    codigo.loguear_arranque(log, _LIMPIO)
    assert log.lineas == [("INFO", "Código: commit bbbbbbb")]


def test_main_loguea_el_codigo_al_arrancar():
    """Si `main` deja de llamarlo, el log vuelve a no decir con qué código corrió la app."""
    from pathlib import Path

    texto = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    cuerpo = texto[texto.index("def main():") :]
    assert "loguear_arranque(log, al_arrancar())" in cuerpo
    assert cuerpo.index("setup_logging()") < cuerpo.index("loguear_arranque(")


def _opinion():
    from analysis import opinion_claude as oc

    return oc.Opinion("MANTENER", 40, "tesis", [], [], [], oc.MODELO, 1.0)


def _arranco_con(monkeypatch, estado):
    """El arranque y el árbol de ahora, iguales: desde la 449 ``guardar`` compara los dos."""
    monkeypatch.setattr(codigo, "al_arrancar", lambda: estado)
    monkeypatch.setattr(codigo, "estado_del_codigo", lambda *a, **k: estado)


def _fila(test_db):
    from database.models import ClaudeOpinion, session_scope

    with session_scope() as s:
        f = s.query(ClaudeOpinion).one()
        return f.codigo_commit, f.codigo_wip


def test_la_opinion_guardada_trae_el_commit_y_el_WIP(test_db, monkeypatch):
    from datetime import date

    from analysis import opinion_claude as oc

    _arranco_con(monkeypatch, _SUCIO)
    oc.guardar("MU", _opinion(), {"precio": 1.0}, hoy=date(2026, 11, 19))
    assert _fila(test_db) == ("b" * 40, True)


def test_la_opinion_sin_WIP_dice_False(test_db, monkeypatch):
    from datetime import date

    from analysis import opinion_claude as oc

    _arranco_con(monkeypatch, _LIMPIO)
    oc.guardar("MU", _opinion(), {"precio": 1.0}, hoy=date(2026, 11, 19))
    assert _fila(test_db) == ("b" * 40, False)


def test_la_opinion_sin_git_no_afirma_nada(test_db, monkeypatch):
    """Sin commit no se sabe si había WIP: NULL, no False."""
    from datetime import date

    from analysis import opinion_claude as oc

    _arranco_con(monkeypatch, codigo.EstadoDelCodigo(None))
    oc.guardar("MU", _opinion(), {"precio": 1.0}, hoy=date(2026, 11, 19))
    assert _fila(test_db) == (None, None)
