"""Tarea 408 — el `.bat` del harvest manual corre con el `.venv` del repo, no con la Anaconda.

Ninguna tarea programada lo llama desde el 2026-07-12 (la 240), pero se puede correr a mano: con la
Anaconda corría fuera del lock (la 401). Tiene que seguir en CRLF (regla 4).
"""

from __future__ import annotations

from pathlib import Path

_BAT = Path(__file__).resolve().parent.parent / "scripts" / "daily_catalyst_harvest.bat"


def test_usa_el_venv_y_no_la_anaconda():
    texto = _BAT.read_bytes().decode("utf-8")
    assert r"set PY=%REPO%\.venv\Scripts\python.exe" in texto.splitlines()
    assert "anaconda" not in texto.lower()


def test_sigue_en_crlf():
    datos = _BAT.read_bytes()
    assert datos.count(b"\n") == datos.count(b"\r\n") > 0
