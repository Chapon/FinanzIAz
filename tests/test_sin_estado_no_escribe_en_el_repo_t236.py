"""Tarea 236 — SIN-ESTADO-ESCRIBE-EN-EL-REPO.

`scripts/run_suite_sin_estado_vivo.py` movía `HOME` y `USERPROFILE` a un directorio
**pelado**. En Windows `platformdirs` resuelve por `SHGetFolderPathW`, que expande
`%USERPROFILE%\\AppData\\Local`; con esa carpeta inexistente la API devuelve `''`,
`user_cache_dir()` vale `'.'`, y yfinance creaba `py-yfinance/` en el cwd: la raíz del repo.
Apareció sin trackear al cerrar la 233, en el segundo en que arrancó la corrida sin estado.

Los casos que distinguen el arreglo del defecto son los de Windows (en Linux `platformdirs`
cuelga del `HOME` y el home pelado ya alcanzaba), así que esos se saltean afuera de Windows.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import scripts.run_suite_sin_estado_vivo as m

_REPO = Path(__file__).resolve().parent.parent
_SOLO_WINDOWS = pytest.mark.skipif(
    sys.platform != "win32", reason="platformdirs resuelve por la API de Windows"
)


def test_el_montaje_crea_el_AppData_y_le_apunta_las_variables(tmp_path):
    env = m.montar_home_vacio(tmp_path, base={})
    assert env["HOME"] == env["USERPROFILE"] == str(tmp_path)
    assert Path(env["LOCALAPPDATA"]) == tmp_path / "AppData" / "Local"
    assert Path(env["APPDATA"]) == tmp_path / "AppData" / "Roaming"
    assert Path(env["LOCALAPPDATA"]).is_dir() and Path(env["APPDATA"]).is_dir()


def test_con_el_montaje_la_contraprueba_no_encuentra_fallas(tmp_path):
    """Corre la sonda de verdad: `Path.home()` y el cache de `platformdirs`, adentro."""
    assert m.fallas_del_aislamiento(m.montar_home_vacio(tmp_path), tmp_path) == []


@_SOLO_WINDOWS
def test_el_home_PELADO_de_antes_lo_acusa_la_contraprueba(tmp_path):
    """El defecto de la 236, reproducido: sólo las variables de home, sin `AppData`. La
    contraprueba vieja (sólo `Path.home()`) lo daba por bueno."""
    import os

    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    fallas = m.fallas_del_aislamiento(env, tmp_path)
    assert len(fallas) == 1 and "platformdirs" in fallas[0], fallas


@_SOLO_WINDOWS
def test_mover_solo_HOME_lo_sigue_acusando(tmp_path):
    """La contraprueba de la 176 no se perdió en el camino."""
    import os

    env = dict(os.environ, HOME=str(tmp_path))
    assert any("Path.home()" in f for f in m.fallas_del_aislamiento(env, tmp_path))


# ── la verificación de después: la suite no deja nada en el repo ─────────────


class _Hecho:
    def __init__(self, returncode):
        self.returncode = returncode


def _main_con(monkeypatch, antes, despues, codigo_pytest=0):
    estados = iter([antes, despues])
    monkeypatch.setattr(m, "fallas_del_aislamiento", lambda env, home: [])
    monkeypatch.setattr(m, "estado_del_repo", lambda: next(estados))
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: _Hecho(codigo_pytest))
    return m.main(["tests/nada.py"])


def test_una_suite_verde_que_deja_un_archivo_NUEVO_no_reporta_verde(monkeypatch, capsys):
    codigo = _main_con(monkeypatch, {" M data/x.json"}, {" M data/x.json", "?? py-yfinance/cookies.db"})
    assert codigo == 3
    assert "?? py-yfinance/cookies.db" in capsys.readouterr().err


def test_lo_que_YA_estaba_sucio_antes_no_cuenta(monkeypatch):
    """El `surprise_profiles.json` que reescribe el scheduler está modificado casi siempre:
    se compara contra el antes, no contra un repo limpio."""
    sucio = {" M data/catalyst/surprise_profiles.json", "?? py-yfinance/tkr-tz.db"}
    assert _main_con(monkeypatch, sucio, set(sucio)) == 0


def test_una_suite_ROJA_conserva_su_codigo(monkeypatch):
    assert _main_con(monkeypatch, set(), {"?? basura.txt"}, codigo_pytest=1) == 1


def test_sin_git_no_se_inventa_una_falla(monkeypatch, capsys):
    assert _main_con(monkeypatch, None, None) == 0
    assert "sin git" in capsys.readouterr().out


def test_el_estado_del_repo_es_el_de_git_de_verdad():
    estado = m.estado_del_repo()
    assert estado is not None
    esperado = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=_REPO, capture_output=True, text=True
    ).stdout.splitlines()
    assert estado == set(esperado)


def test_el_gitignore_tiene_la_red():
    lineas = (_REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "py-yfinance/" in lineas
