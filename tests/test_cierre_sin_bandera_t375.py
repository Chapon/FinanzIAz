"""Tarea 375 — un cierre que no pasa por ``shutdown()`` tampoco puede emitir, ni llenar el log.

El 2026-10-20 un proceso de la app entró en *interpreter shutdown* a los 5 s de arrancar
y en 20 s escribió 81 WARNING del tooltip, 12 ERROR con traceback del calendario de
dividendos, uno del ``SignalWorker`` de Cartera, y un ``emit`` sobre ``_FetchSignals`` ya
borrado que terminó en el diálogo «Error inesperado». Que el ``emit`` corriera prueba que la
bandera de la tarea 82 **no se había prendido**.

Lo que se descartó midiendo: que la limpieza de módulos de Python 3.12 la pusiera en
``None`` (con la bandera prendida y sin esperar el drenado, exit 0 en 3 de 3). Lo que queda:
el proceso salió por un camino que no llega a ``shutdown()``, y cuál fue no quedó en el log.
Por eso el arreglo no adivina el camino: la bandera se prende al empezar el apagado del
intérprete, sea cual sea.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")

import data.yahoo_finance as yfd
import ui.ticker_tooltip as tt

ROOT = Path(__file__).resolve().parent.parent

# El escenario de la 82 (fetch en vuelo, ``QApplication`` real, ``app.quit()``) pero
# terminando SIN llamar a ``shutdown()``: el camino que no llega al final de ``main()``.
_ESCENARIO = """
import os, sys, time, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["FINANZIAS_LOG_FILE"] = ""
os.environ.pop("FINANZIAS_DISABLE_TICKER_FETCH", None)
sys.path.insert(0, {root!r})
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import data.yahoo_finance as yf
yf.get_company_info = lambda t: (time.sleep(0.6), {{"name": t}})[1]
{antes_de_importar}
import ui.ticker_tooltip as tt
for t in ("AAPL", "MSFT", "NVDA"):
    tt.ticker_cache.get(t)
QTimer.singleShot(50, app.quit)
app.exec()
"""

# El control negativo: sin el gancho de la 375 (el registro se vuelve un no-op antes de
# importar el módulo), el escenario es el defecto.
_SIN_GANCHO = "threading._register_atexit = lambda fn: None"


def _correr(antes_de_importar: str) -> int:
    src = textwrap.dedent(_ESCENARIO).format(root=str(ROOT), antes_de_importar=antes_de_importar)
    return subprocess.run([sys.executable, "-c", src], capture_output=True, timeout=120).returncode


@pytest.mark.skipif(os.environ.get("CI_SKIP_SUBPROCESS") == "1", reason="subproceso deshabilitado")
def test_salir_sin_llamar_a_shutdown_sale_limpio():
    """EL GUARD: aunque nadie llame a ``shutdown()``, el proceso termina en 0."""
    assert _correr("") == 0


@pytest.mark.skipif(os.environ.get("CI_SKIP_SUBPROCESS") == "1", reason="subproceso deshabilitado")
def test_sin_el_gancho_el_escenario_sigue_siendo_el_defecto():
    """Y sin el gancho muere: si esto pasara a 0, el guard de arriba no probaría nada."""
    assert _correr(_SIN_GANCHO) != 0


def test_el_gancho_prende_la_bandera_y_dice_que_no_paso_por_el_cierre(monkeypatch, caplog):
    """El 20/10 por dónde salió el proceso no quedó en el log: ahora queda una línea."""
    monkeypatch.setattr(tt, "_SHUTTING_DOWN", False)
    caplog.set_level(logging.DEBUG, logger=tt.log.name)
    tt._apagar_al_salir()
    assert tt._SHUTTING_DOWN is True
    assert [r.levelno for r in caplog.records if r.name == tt.log.name] == [logging.WARNING]


def test_despues_de_un_cierre_normal_el_gancho_no_dice_nada(monkeypatch, caplog):
    monkeypatch.setattr(tt, "_SHUTTING_DOWN", True)
    caplog.set_level(logging.DEBUG, logger=tt.log.name)
    tt._apagar_al_salir()
    assert not [r for r in caplog.records if r.name == tt.log.name]


def test_main_drena_en_un_finally():
    """``shutdown()`` corre también si lo que sigue a ``app.exec()`` levanta."""
    txt = (ROOT / "main.py").read_text(encoding="utf-8")
    i_exec = txt.index("code = app.exec()")
    i_finally = txt.index("finally:", i_exec)
    assert i_finally < txt.index("_tooltip_shutdown()", i_exec)


# ── _run_with_timeout con el pool apagado ────────────────────────────────────


@pytest.fixture
def pool_apagado(monkeypatch):
    pool = ThreadPoolExecutor(max_workers=1)
    pool.shutdown()
    monkeypatch.setattr(yfd, "_TIMEOUT_POOL", pool)
    monkeypatch.setattr(yfd, "_cierre_avisado", False)
    yfd.reset_throttle()
    return pool


def test_run_with_timeout_con_el_pool_apagado_avisa_una_vez_sin_traceback(pool_apagado, caplog):
    caplog.set_level(logging.DEBUG, logger=yfd.log.name)
    for _ in range(3):
        with pytest.raises(yfd.CierreDeLaApp):
            yfd._run_with_timeout(lambda: 1)
    propios = [r for r in caplog.records if r.name == yfd.log.name]
    assert [r.levelno for r in propios] == [logging.INFO]
    assert propios[0].exc_info is None
    assert "Cierre de la app" in propios[0].getMessage()


def test_el_corte_sigue_siendo_reconocible_por_la_289(pool_apagado):
    """``get_bulk_prices`` lo reconoce por el texto: tiene que seguir viéndolo."""
    with pytest.raises(yfd.CierreDeLaApp) as exc:
        yfd._run_with_timeout(lambda: 1)
    assert yfd._es_cierre_del_interprete(exc.value)


def test_otro_runtime_error_del_submit_no_se_disfraza(monkeypatch):
    class _Pool:
        def submit(self, *a, **k):
            raise RuntimeError("otra cosa")

    monkeypatch.setattr(yfd, "_TIMEOUT_POOL", _Pool())
    yfd.reset_throttle()
    with pytest.raises(RuntimeError, match="otra cosa") as exc:
        yfd._run_with_timeout(lambda: 1)
    assert not isinstance(exc.value, yfd.CierreDeLaApp)


def test_el_calendario_cortado_por_el_cierre_no_escribe_error(monkeypatch, caplog):
    def _cortado(t):
        raise yfd.CierreDeLaApp("cannot schedule new futures after interpreter shutdown")

    monkeypatch.setattr(yfd, "get_dividend_calendar", _cortado)
    caplog.set_level(logging.DEBUG, logger=yfd.log.name)
    assert yfd.get_bulk_dividend_calendar(["KO", "MO"]) == {"KO": [], "MO": []}
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_el_calendario_con_otra_falla_sigue_escribiendo_error(monkeypatch, caplog):
    """Sanity: lo que no es el cierre sigue con su ERROR."""

    def _roto(t):
        raise ValueError("roto")

    monkeypatch.setattr(yfd, "get_dividend_calendar", _roto)
    caplog.set_level(logging.DEBUG, logger=yfd.log.name)
    assert yfd.get_bulk_dividend_calendar(["KO"]) == {"KO": []}
    assert [r.levelno for r in caplog.records if r.name == yfd.log.name] == [logging.ERROR]


# ── Los que lo atrapan: el worker y el tooltip ───────────────────────────────


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _worker_que_levanta(exc):
    from ui.workers import BaseWorker

    class _W(BaseWorker):
        def do_work(self):
            raise exc

    return _W()


@pytest.mark.parametrize(
    ("exc", "esperado"),
    [
        (yfd.CierreDeLaApp("cannot schedule new futures after shutdown"), []),
        (RuntimeError("cannot schedule new futures after shutdown"), [logging.ERROR]),
    ],
    ids=["cierre", "otro"],
)
def test_el_worker_cortado_por_el_cierre_no_escribe_error(qapp, caplog, exc, esperado):
    import ui.workers as uw

    caplog.set_level(logging.DEBUG, logger=uw.log.name)
    w = _worker_que_levanta(exc)
    w.run()  # sincrónico: el hilo no importa, importa qué escribe
    assert [r.levelno for r in caplog.records if r.levelno >= logging.WARNING] == esperado


class _Espia:
    def __init__(self):
        self.emitidos = []

    def emit(self, *a):
        self.emitidos.append(a)


def test_el_tooltip_cortado_por_el_cierre_ni_avisa_ni_emite(monkeypatch, caplog):
    def _cortado(t):
        raise yfd.CierreDeLaApp("cannot schedule new futures after interpreter shutdown")

    espia = _Espia()
    monkeypatch.setattr(tt, "_SHUTTING_DOWN", False)
    monkeypatch.setattr("data.yahoo_finance.get_company_info", _cortado)
    caplog.set_level(logging.DEBUG, logger=tt.log.name)
    tt._FetchRunnable("AAPL", type("S", (), {"fetched": espia})()).run()
    assert espia.emitidos == []
    assert not [r for r in caplog.records if r.name == tt.log.name]


def test_el_tooltip_con_otra_falla_avisa_y_emite(monkeypatch, caplog):
    """Sanity: una falla de verdad sigue con su WARNING y con el emit (info vacía)."""

    def _roto(t):
        raise ValueError("roto")

    espia = _Espia()
    monkeypatch.setattr(tt, "_SHUTTING_DOWN", False)
    monkeypatch.setattr("data.yahoo_finance.get_company_info", _roto)
    caplog.set_level(logging.DEBUG, logger=tt.log.name)
    tt._FetchRunnable("AAPL", type("S", (), {"fetched": espia})()).run()
    assert [a[0] for a in espia.emitidos] == ["AAPL"]
    assert [r.levelno for r in caplog.records if r.name == tt.log.name] == [logging.WARNING]
