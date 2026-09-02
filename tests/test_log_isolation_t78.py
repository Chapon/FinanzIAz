"""Tarea 78 — la suite no escribe en el log de producción.

El defecto no era una línea fea: el log vivo tenía **950 líneas con paths de
`tests/`** y mensajes como ``Earnings cache write failed for TSLA: database is
locked`` que **parecen un defecto de producción y no lo son** — el traceback
apunta a ``tests/test_earnings_gate.py``. Medido antes del arreglo: **551 líneas
por corrida** de la suite.

Por qué importa más de lo que sugiere su severidad: este proyecto **usa el log
como evidencia** para priorizar (las tareas 18, 19 y 25 salieron de triagear
logs de runtime), y la auditoría del 2026-09-02 estuvo a punto de reportar esos
mensajes como un defecto de la app. Un log contaminado no es ruido: es una
**fábrica de falsos positivos**.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import config.logging_config as lc


def _file_handlers(logger: logging.Logger) -> list[logging.FileHandler]:
    return [h for h in logger.handlers if isinstance(h, logging.FileHandler)]


def test_ningun_handler_apunta_al_log_de_produccion():
    """EL GUARD: mientras corre la suite, nada escribe en ``~/.finanzias/finanzias.log``.

    Se mira el logger **raíz** porque es donde ``setup_logging`` instala el
    handler, y todos los módulos heredan de ahí.
    """
    prod = Path(lc.LOG_FILE).resolve()
    destinos = [Path(h.baseFilename).resolve() for h in _file_handlers(logging.getLogger())]
    assert prod not in destinos, f"la suite está escribiendo en el log vivo: {destinos}"


def test_la_variable_esta_seteada_vacia_por_el_conftest():
    """Y el motivo por el que no apunta ahí es explícito, no un accidente de import."""
    assert os.environ.get("FINANZIAS_LOG_FILE") == ""


def test_setup_logging_sin_archivo_cuando_la_variable_esta_vacia(monkeypatch):
    """Vacía ⇒ **sin** file handler. Es distinto de «no seteada»."""
    monkeypatch.setenv("FINANZIAS_LOG_FILE", "")
    monkeypatch.setattr(lc, "_INITIALIZED", False)
    raiz = logging.getLogger()
    previos = list(raiz.handlers)
    try:
        lc.setup_logging()
        assert _file_handlers(raiz) == []
    finally:
        raiz.handlers[:] = previos
        lc._INITIALIZED = True


def test_setup_logging_respeta_la_ruta_de_la_variable(tmp_path, monkeypatch):
    """Con una ruta, escribe ahí — que es lo que permite depurar una corrida puntual."""
    destino = tmp_path / "corrida.log"
    monkeypatch.setenv("FINANZIAS_LOG_FILE", str(destino))
    monkeypatch.setattr(lc, "_INITIALIZED", False)
    raiz = logging.getLogger()
    previos = list(raiz.handlers)
    try:
        lc.setup_logging()
        assert [Path(h.baseFilename) for h in _file_handlers(raiz)] == [destino]
        logging.getLogger("t78").warning("hola")
        for h in _file_handlers(raiz):
            h.flush()
        assert "hola" in destino.read_text(encoding="utf-8")
    finally:
        for h in _file_handlers(raiz):
            h.close()
        raiz.handlers[:] = previos
        lc._INITIALIZED = True


def test_el_argumento_explicito_le_gana_a_la_variable(tmp_path, monkeypatch):
    """Precedencia declarada en el docstring: argumento > entorno > default.

    Importa porque ``main.py`` llama ``setup_logging()`` sin argumento: si mañana
    alguien le pasa una ruta, la variable no puede pisársela.
    """
    monkeypatch.setenv("FINANZIAS_LOG_FILE", str(tmp_path / "de_la_variable.log"))
    monkeypatch.setattr(lc, "_INITIALIZED", False)
    explicito = tmp_path / "del_argumento.log"
    raiz = logging.getLogger()
    previos = list(raiz.handlers)
    try:
        lc.setup_logging(log_file=explicito)
        assert [Path(h.baseFilename) for h in _file_handlers(raiz)] == [explicito]
    finally:
        for h in _file_handlers(raiz):
            h.close()
        raiz.handlers[:] = previos
        lc._INITIALIZED = True


def test_sin_la_variable_sigue_yendo_al_log_de_siempre(monkeypatch):
    """Y la app **no cambia de comportamiento**: sin la variable, el default es el de siempre.

    Se verifica sin instalar el handler (no queremos que el test escriba en el
    log vivo — sería el defecto que la tarea arregla).
    """
    monkeypatch.delenv("FINANZIAS_LOG_FILE", raising=False)
    monkeypatch.setattr(lc, "_INITIALIZED", False)
    creados: list = []
    monkeypatch.setattr(lc.logging.handlers, "RotatingFileHandler", lambda p, **kw: creados.append(p))
    raiz = logging.getLogger()
    previos = list(raiz.handlers)
    try:
        lc.setup_logging()
    except Exception:
        pass  # el fake devuelve None; sólo importa qué ruta se pidió
    finally:
        raiz.handlers[:] = previos
        lc._INITIALIZED = True
    assert creados == [lc.LOG_FILE]
