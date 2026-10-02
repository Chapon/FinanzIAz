"""Tarea 263 — un scan que se cae queda en el log y avisa por Slack, una vez por racha.

El defecto (``docs/auditoria_operacion_2026-10-02.md`` [H-2]): ``PaperScanWorker`` atrapaba la
excepción y sólo emitía una señal; la UI mostraba 10 s de barra de estado. Si el scan fallaba
siempre, la cuenta dejaba de operar y de correr stops sin que nadie se enterara. Y el
vigilante ``status()``/``stale_accounts`` no tenía ningún llamador.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from integrations.slack import format_scan_failure_message
from paper_trading.scan_health import RachasDeScan

T0 = datetime(2026, 10, 2, 15, 0)


@pytest.fixture
def qapp():
    """`pytest-qt` no está en el entorno de Chapa: la app de Qt se crea a mano, como en
    `tests/test_alerts_worker_t80.py`."""
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# ── El tracker ───────────────────────────────────────────────────────────────


def test_solo_la_PRIMERA_falla_de_la_racha_avisa():
    r = RachasDeScan()
    assert r.fallo(2, T0) is True
    assert r.fallo(2, T0 + timedelta(minutes=15)) is False
    assert r.fallo(2, T0 + timedelta(minutes=30)) is False
    assert r.en_falla(2) == 3


def test_el_exito_cierra_la_racha_con_cuantas_fueron_y_cuanto_duro():
    r = RachasDeScan()
    r.fallo(2, T0)
    r.fallo(2, T0)
    assert r.exito(2, T0 + timedelta(minutes=45)) == (2, pytest.approx(45.0))
    assert r.en_falla(2) == 0
    assert r.fallo(2, T0) is True, "una racha nueva vuelve a avisar"


def test_un_exito_sin_racha_no_avisa_nada():
    assert RachasDeScan().exito(2, T0) is None


def test_las_rachas_son_POR_CUENTA():
    r = RachasDeScan()
    assert r.fallo(1, T0) is True
    assert r.fallo(2, T0) is True


def test_los_mensajes():
    abre = format_scan_failure_message(
        "open", account="Sim Segundo (#2)", n=1, minutes=0, error="RuntimeError: x"
    )
    assert "Sim Segundo" in abre and "RuntimeError: x" in abre and "stops" in abre
    vuelve = format_scan_failure_message("recovered", account="Sim Segundo (#2)", n=3, minutes=44.6)
    assert "volvió" in vuelve and "3 falla" in vuelve and "45 min" in vuelve
    assert format_scan_failure_message("otra", account="x", n=0, minutes=0) == ""


# ── El worker loguea el traceback ────────────────────────────────────────────


def test_el_worker_LOGUEA_el_traceback(qapp, monkeypatch, caplog):
    from paper_trading import engine, scheduler

    def explota(_aid):
        raise RuntimeError("se rompió el esquema")

    monkeypatch.setattr(engine, "run_scan", explota)
    w = scheduler.PaperScanWorker(2)
    emitidas = []
    w.scan_failed.connect(lambda aid, err: emitidas.append((aid, err)))
    with caplog.at_level(logging.ERROR, logger=scheduler.log.name):
        w.run()  # directo, en este hilo
    assert emitidas == [(2, "RuntimeError: se rompió el esquema")]
    registros = [r for r in caplog.records if "run_scan falló" in r.getMessage()]
    assert registros and registros[0].exc_info is not None, "el traceback no quedó en el log"


# ── El scheduler avisa una vez por racha ─────────────────────────────────────


@pytest.fixture
def sched(qapp, monkeypatch):
    from paper_trading import scheduler

    enviados: list[str] = []
    monkeypatch.setattr(scheduler, "_scan_alert_notifier", lambda texto: enviados.append(texto) or True)
    s = scheduler.PaperScheduler()
    monkeypatch.setattr(s, "_dashboard_account_id", lambda: None)
    monkeypatch.setattr(s, "_nombre_cuenta", staticmethod(lambda aid: f"Cuenta #{aid}"))
    s.enviados = enviados
    return s


def test_tres_fallas_seguidas_UN_slack_y_la_vuelta_OTRO(sched):
    for _ in range(3):
        sched._on_scan_failed(2, "RuntimeError: x")
    assert len(sched.enviados) == 1 and "falló" in sched.enviados[0]
    sched._on_scan_completed(SimpleNamespace(account_id=2))
    assert len(sched.enviados) == 2 and "volvió" in sched.enviados[1] and "tras 3 falla" in sched.enviados[1]
    sched._on_scan_completed(SimpleNamespace(account_id=2))
    assert len(sched.enviados) == 2, "un scan normal no avisa"


def test_una_cuenta_INACTIVA_no_es_una_falla(sched):
    from paper_trading.scheduler import CUENTA_INACTIVA

    sched._on_scan_failed(2, CUENTA_INACTIVA)
    assert sched.enviados == []


def test_el_aviso_respeta_el_switch_de_salud(sched):
    from config.settings_manager import settings

    settings.set("slack_data_outage_enabled", False)
    sched._on_scan_failed(2, "RuntimeError: x")
    assert sched.enviados == []


def test_la_UI_sigue_recibiendo_la_falla(sched):
    recibidas = []
    sched.scan_failed.connect(lambda aid, err: recibidas.append(aid))
    sched._on_scan_failed(2, "RuntimeError: x")
    assert recibidas == [2]


def test_el_vigilante_sin_llamadores_se_fue():
    from paper_trading.scheduler import PaperScheduler

    assert not hasattr(PaperScheduler, "status")


def test_el_scan_LANZADO_por_el_scheduler_pasa_por_el_tracker(sched, monkeypatch):
    """El cable: `_launch_scan` conecta el worker a `_on_scan_failed`, no directo a la UI.

    Sin este test, conectar `worker.scan_failed` a `self.scan_failed.emit` (lo de antes)
    dejaba los demás en verde: llaman a `_on_scan_failed` a mano.
    """
    from PyQt6.QtCore import QObject, pyqtSignal

    from paper_trading import scheduler

    class _WorkerQueFalla(QObject):
        scan_completed = pyqtSignal(object)
        scan_failed = pyqtSignal(int, str)
        finished = pyqtSignal()

        def __init__(self, account_id, parent=None):
            super().__init__(parent)
            self.account_id = account_id

        def isRunning(self):
            return False

        def start(self):
            self.scan_failed.emit(self.account_id, "RuntimeError: x")

    monkeypatch.setattr(scheduler, "PaperScanWorker", _WorkerQueFalla)
    sched._launch_scan(2)
    assert len(sched.enviados) == 1 and "falló" in sched.enviados[0]
