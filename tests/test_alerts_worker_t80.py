"""Tarea 80 — el chequeo de alertas sale del hilo de la GUI.

El defecto: ``_check_alerts`` corría **sincrónico en el hilo de la GUI**, y
adentro ``AlertManager.check_alerts`` pide precio **por ticker en serie**. La
tarea 74 le sacó los 38,97 ms de disco por lookup (ahora 0,02), pero lo que
quedaba era peor y el índice no lo tocaba: con ``PRICE_CACHE_TTL_MINUTES = 5``
contra un timer de **120 s**, alrededor de un tercio de las corridas encuentra el
cache vencido y **sale a la red** con la UI congelada.

Lo que se fija acá no es "hay un worker" —eso es una clase, no un invariante—
sino las tres cosas que hacen que el worker sirva y no rompa nada:

1. el camino de la pestaña **no llama** ``check_alerts`` en el hilo de la GUI;
2. lo que cruza la señal son **valores planos**, no objetos ORM detachados;
3. el popup **no** se abre desde el hilo del worker, y dos ticks encimados **no
   apilan** workers.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication

from alerts.alert_manager import AlertManager
from database.models import Alert, Portfolio, session_scope
from integrations.slack import AlertNotice
from ui.alerts_tab import AlertCheckWorker, AlertsTab
from ui.workers import BaseWorker


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def portfolio_id(test_db):
    with session_scope() as s:
        p = Portfolio(name="Test PF")
        s.add(p)
        s.flush()
        return p.id


def _prices(mapping):
    def _fn(ticker):
        return {"price": mapping[ticker]} if ticker in mapping else None

    return _fn


# ── (1) el trabajo no corre en el hilo de la GUI ─────────────────────────────


def test_el_worker_es_un_qthread():
    """Si dejara de serlo, todo lo demás de este archivo pasaría igual y no diría nada."""
    assert issubclass(AlertCheckWorker, BaseWorker)


def test_la_pestana_no_llama_check_alerts_en_su_hilo(qapp, portfolio_id, monkeypatch):
    """``_check_alerts`` **lanza** el worker; no ejecuta el chequeo él mismo.

    Es el invariante de la tarea: si alguien vuelve a llamar ``check_alerts``
    derecho desde el slot del ``QTimer``, la UI vuelve a congelarse y este test
    es lo único que lo dice.
    """
    llamadas: list = []
    monkeypatch.setattr(
        AlertManager, "check_alerts", lambda self, pid=None: llamadas.append(pid) or []
    )
    arrancados: list = []
    monkeypatch.setattr(AlertCheckWorker, "start", lambda self: arrancados.append(self))

    tab = AlertsTab()
    tab.set_portfolio_id(portfolio_id)
    tab._check_alerts()

    assert llamadas == [], "check_alerts corrió en el hilo de la GUI"
    assert len(arrancados) == 1


def test_dos_ticks_encimados_no_apilan_workers(qapp, portfolio_id, monkeypatch):
    """El timer es de 120 s y una corrida con la red lenta puede pasarse.

    Sin el guard, cada tick lanzaría otro worker pidiendo los mismos precios —
    justo cuando la red ya está lenta.
    """
    arrancados: list = []
    monkeypatch.setattr(AlertCheckWorker, "start", lambda self: arrancados.append(self))
    monkeypatch.setattr(AlertCheckWorker, "isRunning", lambda self: True)

    tab = AlertsTab()
    tab.set_portfolio_id(portfolio_id)
    tab._check_alerts()
    tab._check_alerts()
    tab._check_alerts()

    assert len(arrancados) == 1


# ── (2) lo que cruza la señal son valores planos ─────────────────────────────


def test_el_worker_devuelve_notices_planos_no_orm(portfolio_id, monkeypatch):
    """``check_alerts`` devuelve ``Alert``es que quedan **detachados** al cerrar la sesión.

    Mandarlos por una señal entre hilos es pedir un ``DetachedInstanceError`` el
    día que alguien toque un atributo que no estaba cargado. Lo que cruza tiene
    que ser el snapshot plano.
    """
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0, "rebote")
    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"MARA": 13.0}))

    notices = AlertCheckWorker(portfolio_id).do_work()

    assert [type(n) for n in notices] == [AlertNotice]
    assert not any(isinstance(n, Alert) for n in notices)
    n = notices[0]
    assert (n.ticker, n.alert_type, n.target_value, n.current_price, n.message) == (
        "MARA",
        "BELOW",
        14.0,
        13.0,
        "rebote",
    )


def test_el_worker_no_inventa_disparos(portfolio_id, monkeypatch):
    """Sin alerta disparada, la lista viene vacía (y el slot no abre ningún popup)."""
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 10.0)
    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"MARA": 13.0}))

    assert AlertCheckWorker(portfolio_id).do_work() == []


def test_el_worker_marca_la_alerta_en_la_db(portfolio_id, monkeypatch):
    """Mover el trabajo de hilo no puede perder el efecto: la alerta queda desactivada."""
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)
    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"MARA": 13.0}))

    AlertCheckWorker(portfolio_id).do_work()

    with session_scope() as s:
        a = s.query(Alert).filter(Alert.ticker == "MARA").one()
        assert a.is_active is False
        assert a.triggered_at is not None


# ── (3) el popup no sale del hilo del worker ─────────────────────────────────


def test_el_popup_no_se_abre_desde_el_worker(qapp, portfolio_id, monkeypatch):
    """Un ``QMessageBox`` desde un hilo que no es el de la GUI es comportamiento indefinido.

    El worker usa un ``AlertManager`` **propio** cuyo ``on_triggered`` sólo
    acumula; el popup lo abre el slot, ya en el hilo de la GUI.
    """
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)
    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"MARA": 13.0}))
    popups: list = []
    monkeypatch.setattr(AlertsTab, "_on_alert_triggered", lambda self, n: popups.append(n))

    tab = AlertsTab()
    tab.set_portfolio_id(portfolio_id)
    worker = AlertCheckWorker(portfolio_id)
    notices = worker.do_work()

    assert popups == [], "el worker abrió el popup desde su propio hilo"

    tab._on_check_done(notices)
    assert [n.ticker for n in popups] == ["MARA"]
    assert tab.check_btn.isEnabled()
    assert "1 alerta(s)" in tab.status_label.text()


def test_un_error_del_worker_no_deja_el_boton_colgado(qapp, portfolio_id):
    """Fail-open como el resto de los workers: se avisa y el botón vuelve."""
    tab = AlertsTab()
    tab.set_portfolio_id(portfolio_id)
    tab.check_btn.setEnabled(False)

    tab._on_check_error(RuntimeError("yahoo caído"))

    assert tab.check_btn.isEnabled()
    assert "yahoo caído" in tab.status_label.text()
