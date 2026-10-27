"""Tarea 401 — el ``.venv`` del repo es el entorno canónico: el del lock, el del CI y el de la app.

Hasta el 2026-10-26 la app corría en la Anaconda con 37 versiones distintas de las del lock, y desde
la 391 el CI corre el lock: lo que se probaba no era lo que corría.
"""

from __future__ import annotations

import importlib.metadata as md
import os
import sys
from pathlib import Path

from config.entorno import es_el_venv

_REPO = Path(__file__).resolve().parent.parent


def test_el_interprete_del_done_tiene_las_versiones_del_lock():
    """Todo paquete del lock que esté instalado, en la versión exacta del lock.

    Las directas de ``requirements.txt`` coincidían también en la Anaconda: la diferencia estaba en
    las transitivas (pillow 10.3 contra 12.2, protobuf 3.20 contra 7.35). Los que no están
    instalados no cuentan: el CI, en Linux, no instala todo lo del lock de Windows. Rojo con la
    Anaconda, verde en el ``.venv`` y en el CI, que instala con ``-c requirements.lock``.
    """
    distintas = []
    for linea in (_REPO / "requirements.lock").read_text(encoding="utf-8").splitlines():
        if "==" not in linea or linea.startswith("#"):
            continue
        nombre, version = (x.strip() for x in linea.split("==", 1))
        try:
            instalada = md.version(nombre)
        except md.PackageNotFoundError:
            continue
        if instalada != version:
            distintas.append(f"{nombre} {instalada} (el lock dice {version})")
    assert not distintas, f"{sys.prefix} no es el entorno del lock: " + "; ".join(distintas)


def test_es_el_venv_compara_el_prefix_con_el_venv_del_repo(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / "otra").mkdir()
    assert es_el_venv(str(tmp_path / ".venv"), root=str(tmp_path))
    assert es_el_venv(str(tmp_path / ".venv") + os.sep, root=str(tmp_path))
    assert not es_el_venv(str(tmp_path / "otra"), root=str(tmp_path))
    assert not es_el_venv(str(tmp_path), root=str(tmp_path))


def test_el_lock_no_se_regenera_desde_otro_entorno(tmp_path, monkeypatch, capsys):
    import scripts.lock_requirements as lr

    destino = tmp_path / "requirements.lock"
    monkeypatch.setattr(lr, "LOCK_PATH", destino)
    monkeypatch.setattr(lr.sys, "prefix", str(tmp_path))
    assert lr.main([]) == 2
    assert not destino.exists()
    assert "tarea 401" in capsys.readouterr().err


def test_el_lock_dice_de_que_entorno_salio():
    cabecera = (_REPO / "requirements.lock").read_text(encoding="utf-8").splitlines()[:8]
    entorno = [c for c in cabecera if c.startswith("# Entorno:")]
    assert entorno and entorno[0].rstrip().endswith(".venv")


def test_abrir_app_usa_el_python_del_venv():
    bat = (_REPO / "abrir_app.bat").read_bytes()
    assert b"\r\n" in bat and bat.count(b"\n") == bat.count(b"\r\n")  # regla 4: CRLF
    texto = bat.decode("ascii")
    assert 'set "PY=.venv\\Scripts\\python.exe"' in texto
    assert '"%PY%" main.py' in texto
    assert "\npython main.py" not in texto


def test_main_avisa_si_no_corre_en_el_venv():
    fuente = (_REPO / "main.py").read_text(encoding="utf-8")
    assert "if not es_el_venv(sys.prefix):" in fuente and "log.warning(" in fuente
