"""Tarea 288 — cada línea del log dice de qué proceso viene, y las de la app quedan iguales.

El defecto (``docs/auditoria_logs_2026-10-02.md`` [L-1]): ``get_logger`` configura
``finanzias.log`` para **cualquier** proceso que importe un módulo del proyecto, y el formato no
decía de dónde venía la línea. La auditoría encontró dos firmas *desconocidas* que no eran de la
app: una corrida a mano del cuadre (266) y una prueba de stooq desde el ``.venv``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from config.logging_config import (
    DEFAULT_DATEFMT,
    DEFAULT_FORMAT,
    FormatterQueEnmascara,
    _FiltroOrigen,
    origen_del_proceso,
)

_REPO = Path(__file__).resolve().parent.parent


# Las rutas absolutas van construidas con ``Path`` y no escritas como ``r"D:\…"``: así son las
# que el sistema le pasa de verdad a ``argv[0]`` —con ``\`` en Windows, con ``/`` en Linux—. La
# primera versión las tenía literales de Windows, y en Linux ``\`` no separa: el CI quedó rojo
# 19 corridas y 17 tareas se cerraron en verde sin enterarse (tarea 300).
_MAIN_ABSOLUTO = str(Path(_REPO.anchor, "Rodrigo", "FinanzIAs", "main.py"))
_SCRIPT_ABSOLUTO = str(Path(_REPO.anchor, "x", "scripts", "medir_cobertura_de_scan_t265.py"))


@pytest.mark.parametrize(
    "argv,esperado",
    [
        ([_MAIN_ABSOLUTO], None),
        (["main.py", "--algo"], None),
        (["scripts/harvest_catalysts.py"], "harvest_catalysts"),
        ([_SCRIPT_ABSOLUTO], "medir_cobertura_de_scan_t265"),
        (["-c"], "python -c"),
        ([], "python -c"),
        (["-"], "python stdin"),
    ],
)
def test_el_origen_del_proceso(argv, esperado):
    assert origen_del_proceso(argv) == esperado


def _linea(origen):
    rec = logging.LogRecord("paper_trading.cuadre", logging.ERROR, __file__, 1, "no cuadra", None, None)
    _FiltroOrigen(origen).filter(rec)
    return FormatterQueEnmascara(DEFAULT_FORMAT, datefmt=DEFAULT_DATEFMT).format(rec)


def test_la_linea_de_la_APP_queda_igual_que_antes():
    """Los que parsean el log (el censo, la telemetría) no se rompen: la app no lleva sufijo."""
    assert _linea(None).endswith("] paper_trading.cuadre: no cuadra")


def test_la_linea_de_otro_proceso_lleva_su_origen():
    assert _linea("python -c").endswith("no cuadra  [proceso: python -c]")


def _correr(argv0: Path, tmp_log: Path) -> str:
    env = dict(os.environ, FINANZIAS_LOG_FILE=str(tmp_log), PYTHONPATH=str(_REPO))
    subprocess.run([sys.executable, str(argv0)], env=env, check=True, cwd=str(_REPO), timeout=60)
    return tmp_log.read_text(encoding="utf-8")


_CUERPO = (
    "from config.logging_config import get_logger\nget_logger('prueba.t288').error('hola desde un proceso')\n"
)


def test_un_SCRIPT_queda_marcado_en_el_archivo(tmp_path):
    script = tmp_path / "prueba_a_mano.py"
    script.write_text(_CUERPO, encoding="utf-8")
    texto = _correr(script, tmp_path / "f.log")
    assert "hola desde un proceso  [proceso: prueba_a_mano]" in texto


def test_un_proceso_que_se_llama_main_py_no_lleva_marca(tmp_path):
    d = tmp_path / "app"
    d.mkdir()
    script = d / "main.py"
    script.write_text(_CUERPO, encoding="utf-8")
    texto = _correr(script, tmp_path / "f.log")
    linea = next(ln for ln in texto.splitlines() if "hola desde un proceso" in ln)
    assert linea.endswith("hola desde un proceso")
