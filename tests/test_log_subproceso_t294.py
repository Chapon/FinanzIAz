"""Tarea 294 — los subprocesos de la suite tampoco escriben en el log de producción.

La 78 cortó el log dentro de la suite con ``FINANZIAS_LOG_FILE=""``. Pero en Windows
una variable de entorno **vacía no se hereda**: el hijo la ve sin setear, cae al
default y escribe en ``~/.finanzias/finanzias.log``. Lo encontró la auditoría del
2026-10-03 ([L-1]): las 22 líneas ``[proceso: dashboard_data]`` de una noche con la
app cerrada eran las corridas del done.

El hijo se lanza **sin** ``env=``, heredando: con ``env=dict(os.environ)`` la vacía sí
llega, y el test pasaría con el defecto puesto. ``HOME``/``USERPROFILE`` van a un
temporal para que el «log de producción» del hijo sea uno que el test puede mirar sin
tocar el real.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import config.logging_config as lc

_REPO = Path(__file__).resolve().parent.parent
_HIJO = (
    "from config.logging_config import get_logger\nget_logger('prueba.t294').error('hola desde el hijo')\n"
)


def _correr_hijo_heredando(tmp_path: Path, monkeypatch) -> Path:
    """Lanza el hijo con el entorno de la suite y devuelve el log de producción que vería."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    subprocess.run([sys.executable, "-c", _HIJO], check=True, cwd=str(_REPO), timeout=60)
    return home / ".finanzias" / "finanzias.log"


def test_un_hijo_de_la_suite_no_escribe_en_el_log_de_produccion(tmp_path, monkeypatch):
    log_del_hijo = _correr_hijo_heredando(tmp_path, monkeypatch)
    assert not log_del_hijo.exists(), (
        f"un subproceso de la suite escribió en el log de producción: {log_del_hijo.read_text(encoding='utf-8')!r}"
    )


def test_CONTROL_sin_la_variable_el_mismo_hijo_si_escribe(tmp_path, monkeypatch):
    """El instrumento ve la escritura: sin esto, el test de arriba pasaría con un HOME mal redirigido."""
    monkeypatch.delenv("FINANZIAS_LOG_FILE", raising=False)
    log_del_hijo = _correr_hijo_heredando(tmp_path, monkeypatch)
    assert "hola desde el hijo" in log_del_hijo.read_text(encoding="utf-8")


def test_el_conftest_usa_el_centinela_y_no_la_vacia():
    assert os.environ.get("FINANZIAS_LOG_FILE") == lc.SIN_ARCHIVO


def test_setup_logging_ni_siquiera_intenta_abrir_un_archivo_con_el_centinela(monkeypatch):
    """Se mira si se **pidió** un archivo, no si quedó un handler.

    En Windows ``:sin-archivo:`` no es un nombre válido: si ``setup_logging`` no lo
    reconociera, abrir el archivo fallaría y quedaría «sin archivo» de casualidad —el
    test por handlers pasaba con esa mutación—. En Linux (el CI) crearía un archivo
    ``:sin-archivo:`` en el directorio de trabajo, que es el repo.
    """
    monkeypatch.setenv("FINANZIAS_LOG_FILE", lc.SIN_ARCHIVO)
    monkeypatch.setattr(lc, "_INITIALIZED", False)
    pedidos: list = []
    monkeypatch.setattr(lc.logging.handlers, "RotatingFileHandler", lambda p, **kw: pedidos.append(p))
    raiz = logging.getLogger()
    previos = list(raiz.handlers)
    try:
        lc.setup_logging()
    finally:
        raiz.handlers[:] = previos
        lc._INITIALIZED = True
    assert pedidos == []
