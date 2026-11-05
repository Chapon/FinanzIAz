"""Tarea 409 — el classify guarda por checkpoints, se puede detener y reanudar, e informa su avance.

El defecto (``docs/auditoria_tanda_2026-11-05.md`` [I-1], tarea 406): ``classify_events``
clasificaba TODA la cola en memoria y recién escribía al final. Con 14.154 noticias en cola
(~11 h a ~2,9 s cada una), cada cierre de la app tiraba lo clasificado: desde el 23/10 no se
había persistido nada. Ahora persiste cada ``checkpoint`` filas, en transacciones cortas; como la
selección es ``event_type IS NULL``, lo guardado ya es el punto de reanudación.
"""

from __future__ import annotations

import threading

import pytest

from data.catalyst_classifier import Classification
from database.models import NewsEvent, session_scope
from scripts.classify_catalysts import classify_events


class _Apagon(BaseException):
    """Un corte que no es un error de una fila: la app que se cierra o se cae a mitad."""


def _sembrar(n: int) -> None:
    with session_scope() as s:
        for i in range(n):
            s.add(NewsEvent(ticker="NVDA", title=f"titular {i}", source="yfinance", content_hash=f"h{i}"))


def _clasificadas() -> int:
    with session_scope() as s:
        return s.query(NewsEvent).filter(NewsEvent.event_type.isnot(None)).count()


def _clasificador(llamadas: list, cortar_en: int | None = None):
    def clasificar(title, content, source, ticker):
        if cortar_en is not None and len(llamadas) == cortar_en:
            raise _Apagon()
        llamadas.append(title)
        return Classification("other", "neutral", 0.2, classifier="ollama-7n")

    return clasificar


def test_un_corte_a_mitad_deja_persistido_lo_clasificado_hasta_el_ultimo_checkpoint(test_db):
    _sembrar(25)
    llamadas: list = []
    with pytest.raises(_Apagon):
        classify_events(classifier=_clasificador(llamadas, cortar_en=17), checkpoint=5)
    # 17 clasificadas en memoria; los checkpoints de 5 guardaron 15. Antes de la 409: 0.
    assert _clasificadas() == 15


def test_la_corrida_siguiente_sigue_desde_el_checkpoint_sin_reclasificar(test_db):
    _sembrar(25)
    with pytest.raises(_Apagon):
        classify_events(classifier=_clasificador([], cortar_en=17), checkpoint=5)
    llamadas: list = []
    rep = classify_events(classifier=_clasificador(llamadas), checkpoint=5)
    assert rep.scanned == 10
    assert len(llamadas) == 10
    assert _clasificadas() == 25


def test_detener_corta_despues_de_guardar_lo_hecho(test_db):
    _sembrar(25)
    llamadas: list = []
    rep = classify_events(
        classifier=_clasificador(llamadas),
        checkpoint=10,
        detener=lambda: len(llamadas) >= 7,
    )
    assert rep.detenido
    assert len(llamadas) == 7
    # Lo hecho se guarda aunque no llegue al checkpoint: detener no es perder.
    assert _clasificadas() == 7
    assert "DETENIDO" in rep.summary()


def test_progreso_informa_hechos_y_total(test_db):
    _sembrar(12)
    avances: list = []
    classify_events(
        classifier=_clasificador([]),
        checkpoint=5,
        progreso=lambda hechos, total, fallbacks: avances.append((hechos, total)),
    )
    assert avances[0] == (0, 12)
    assert avances[-1] == (12, 12)
    assert [h for h, _ in avances] == sorted(h for h, _ in avances)


def test_dry_run_no_escribe_aunque_haya_checkpoints(test_db):
    _sembrar(12)
    classify_events(classifier=_clasificador([]), checkpoint=5, dry_run=True)
    assert _clasificadas() == 0


def test_run_catalyst_refresh_le_pasa_avance_y_detener_al_classify():
    from analysis.news_digest import run_catalyst_refresh

    recibido = {}

    def classify_main(argv, **kw):
        recibido.update(kw)
        return 0

    def progreso(h, t, f):
        return None

    def detener():
        return False

    run_catalyst_refresh(
        harvest_main=lambda argv: 0, classify_main=classify_main, progreso=progreso, detener=detener
    )
    assert recibido == {"progreso": progreso, "detener": detener}


def test_run_catalyst_refresh_sin_avance_llama_al_classify_como_antes():
    """Los ``classify_main`` inyectados de los tests viejos sólo aceptan ``argv``."""
    from analysis.news_digest import run_catalyst_refresh

    res = run_catalyst_refresh(harvest_main=lambda argv: 0, classify_main=lambda argv: 0)
    assert res == {"harvest_rc": 0, "classify_rc": 0}


def test_reanudar_no_vuelve_a_cosechar():
    from analysis.news_digest import run_catalyst_refresh

    cosechas: list = []
    res = run_catalyst_refresh(
        harvest_main=lambda argv: cosechas.append(argv) or 0, classify_main=lambda argv: 0, harvest=False
    )
    assert cosechas == []
    assert res == {"harvest_rc": None, "classify_rc": 0}


class _WorkerFalso:
    def __init__(self, corriendo=True):
        self.corriendo = corriendo
        self.pedidos = 0
        self.esperas: list[int] = []

    def isRunning(self):
        return self.corriendo

    def pedir_detener(self):
        self.pedidos += 1

    def wait(self, ms):
        self.esperas.append(ms)
        return True


def test_detener_clasificacion_le_pide_al_worker_que_corte(qapp):
    from paper_trading import scheduler

    s = scheduler.PaperScheduler()
    assert s.detener_clasificacion() is False  # nada corriendo
    w = _WorkerFalso()
    s._catalyst_worker = w
    assert s.detener_clasificacion() is True
    assert w.pedidos == 1


def test_reanudar_lanza_sin_cosechar_y_no_duplica(qapp, monkeypatch):
    from paper_trading import scheduler

    s = scheduler.PaperScheduler()
    lanzados: list = []
    monkeypatch.setattr(s, "_launch_catalyst_refresh", lambda **kw: lanzados.append(kw))
    assert s.reanudar_clasificacion() is True
    assert lanzados == [{"harvest": False}]
    s._catalyst_worker = _WorkerFalso()
    assert s.reanudar_clasificacion() is False
    assert len(lanzados) == 1


def test_cerrar_la_app_pide_el_corte_ordenado_antes_de_esperar(qapp):
    from paper_trading import scheduler

    s = scheduler.PaperScheduler()
    w = _WorkerFalso()
    s._catalyst_worker = w
    s.stop()
    assert w.pedidos == 1
    assert w.esperas == [scheduler.PaperScheduler._CATALYST_STOP_WAIT_MS]


def test_el_worker_traduce_el_pedido_de_detener():
    from paper_trading.scheduler import CatalystRefreshWorker

    w = CatalystRefreshWorker()
    assert not w.detener_pedido()
    w.pedir_detener()
    assert w.detener_pedido()
    assert isinstance(w._detener, threading.Event)
