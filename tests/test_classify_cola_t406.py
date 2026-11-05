"""Tarea 406 — el classify ya no apaga el harvest horario, procesa lo más nuevo primero,
avisa cuando la cola no se vacía, y lo que qwen no clasificó todavía se dice como tal.

El defecto (``docs/auditoria_tanda_2026-11-05.md`` [I-1]): con 14.154 noticias en cola el classify
corría ~11 h, y mientras tanto ``hourly_harvest_due`` cortaba con el worker vivo, así que no entraba
ninguna noticia en toda la rueda. Tres corridas seguidas no terminaron sin ningún aviso, y la pestaña
Noticias y la opinión de Claude mostraban la heurística al vuelo (o ``None``) sin decirlo.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from analysis.news_digest import _Row, classify_missing, rank_news
from data.catalyst_classifier import Classification
from database.models import NewsEvent, session_scope
from scripts.classify_catalysts import COLA_ATRASADA_HORAS, aviso_cola_atrasada, classify_events

AHORA = datetime(2026, 11, 5, 20, 0)


# ── El harvest horario sólo espera al harvest del refresh diario ──────────────


class _RefreshFalso:
    def __init__(self, *, cosechando: bool):
        self._cosechando = cosechando

    def isRunning(self):
        return True

    def cosechando(self):
        return self._cosechando


class _HarvestFalso:
    lanzados = 0

    def __init__(self, parent=None):
        from unittest.mock import MagicMock

        self.harvest_completed = MagicMock()
        self.harvest_failed = MagicMock()
        self.finished = MagicMock()

    def start(self):
        type(self).lanzados += 1


def _horario_con(monkeypatch, refresh) -> int:
    from paper_trading import scheduler

    monkeypatch.setattr(scheduler, "_is_market_open_now", lambda: True)
    monkeypatch.setattr(scheduler, "CatalystHarvestWorker", _HarvestFalso)
    _HarvestFalso.lanzados = 0
    s = scheduler.PaperScheduler()
    s._catalyst_worker = refresh
    s._maybe_hourly_harvest()
    return _HarvestFalso.lanzados


def test_el_harvest_horario_corre_mientras_el_refresh_diario_clasifica(qapp, monkeypatch):
    # Antes de la 406 el gate miraba isRunning(): con el classify vivo, 0 lanzados.
    assert _horario_con(monkeypatch, _RefreshFalso(cosechando=False)) == 1


def test_el_harvest_horario_espera_al_harvest_del_refresh_diario(qapp, monkeypatch):
    assert _horario_con(monkeypatch, _RefreshFalso(cosechando=True)) == 0


def test_el_worker_pasa_a_clasificando_con_el_primer_aviso_del_classify():
    from paper_trading.scheduler import CatalystRefreshWorker

    w = CatalystRefreshWorker()
    assert not w._clasificando.is_set()
    w._progreso(0, 100, 0)
    assert w._clasificando.is_set()
    # «Reanudar» no cosecha: arranca ya en la fase del classify.
    assert CatalystRefreshWorker(harvest=False)._clasificando.is_set()


def test_un_worker_que_no_corre_no_esta_cosechando():
    from paper_trading.scheduler import CatalystRefreshWorker

    assert CatalystRefreshWorker().cosechando() is False


# ── Lo más nuevo primero ─────────────────────────────────────────────────────


def test_el_classify_procesa_primero_lo_publicado_mas_reciente(test_db):
    publicadas = [AHORA - timedelta(days=d) for d in (5, 1, 3)] + [None]
    with session_scope() as s:
        for i, p in enumerate(publicadas):
            s.add(
                NewsEvent(
                    ticker="NVDA", title=f"t{i}", source="yfinance", content_hash=f"h{i}", published_at=p
                )
            )
    vistas: list[str] = []

    def clasificar(title, content, source, ticker):
        vistas.append(title)
        return Classification("other", "neutral", 0.2, classifier="ollama-7n")

    classify_events(classifier=clasificar)
    # Hace 1 día, hace 3, hace 5 y la sin fecha al final. Antes: por id (t0, t1, t2, t3).
    assert vistas == ["t1", "t2", "t0", "t3"]


# ── El aviso de la cola atrasada ─────────────────────────────────────────────


def test_el_aviso_salta_pasado_el_umbral_y_no_antes():
    justo = AHORA - timedelta(hours=COLA_ATRASADA_HORAS)
    assert aviso_cola_atrasada(100, justo, AHORA) is None
    texto = aviso_cola_atrasada(14154, justo - timedelta(hours=1), AHORA)
    assert texto is not None
    assert "14154" in texto and "11.4 h" in texto
    assert aviso_cola_atrasada(0, justo - timedelta(days=9), AHORA) is None


def test_classify_avisa_si_la_pendiente_mas_vieja_es_de_hace_dias(test_db, caplog):
    with session_scope() as s:
        s.add(
            NewsEvent(
                ticker="NVDA",
                title="vieja",
                source="yfinance",
                content_hash="v",
                fetched_at=AHORA - timedelta(days=13),
            )
        )
        s.add(NewsEvent(ticker="NVDA", title="nueva", source="yfinance", content_hash="n", fetched_at=AHORA))
    with caplog.at_level(logging.WARNING, logger="scripts.classify_catalysts"):
        classify_events(classifier=lambda *a: Classification("other", "neutral", 0.2), now=AHORA)
    avisos = [r for r in caplog.records if "la cola no se vacía" in r.getMessage()]
    assert len(avisos) == 1 and avisos[0].levelno == logging.WARNING


def test_classify_no_avisa_con_la_cola_al_dia(test_db, caplog):
    with session_scope() as s:
        s.add(
            NewsEvent(
                ticker="NVDA",
                title="hoy",
                source="yfinance",
                content_hash="h",
                fetched_at=AHORA - timedelta(hours=3),
            )
        )
    with caplog.at_level(logging.WARNING, logger="scripts.classify_catalysts"):
        classify_events(classifier=lambda *a: Classification("other", "neutral", 0.2), now=AHORA)
    assert not [r for r in caplog.records if "la cola no se vacía" in r.getMessage()]


# ── Lo que qwen no clasificó todavía se dice ─────────────────────────────────


def _fila(classified_by=None, event_type=None, i=1):
    return _Row(
        id=i,
        ticker="NVDA",
        title=f"Nvidia beats estimates {i}",
        source="yfinance",
        url=None,
        published_at=AHORA,
        event_type=event_type,
        sentiment="positive" if event_type else None,
        classifier_confidence=0.8 if event_type else None,
        sentiment_score=0.67 if event_type else None,
        classified_by=classified_by,
    )


def test_la_celda_de_tono_distingue_provisional_heuristica_vieja_y_qwen():
    from ui.news_tab import TONO_ESCALA_VIEJA, TONO_HEURISTICO, TONO_PROVISIONAL, tono_tooltip

    filas = classify_missing(
        [
            _fila(i=1),
            _fila("heuristic", "earnings_beat", i=2),
            _fila("ollama", "earnings_beat", i=3),
            _fila("ollama-7n", "earnings_beat", i=4),
        ]
    )
    tips = {it.news_id: tono_tooltip(it) for it in rank_news(filas, top_n=None)}
    assert tips == {1: TONO_PROVISIONAL, 2: TONO_HEURISTICO, 3: TONO_ESCALA_VIEJA, 4: ""}


def test_la_opinion_de_claude_no_manda_noticias_sin_tipo_ni_tono(monkeypatch):
    import analysis.news_digest as nd
    from analysis import opinion_claude

    monkeypatch.setattr(
        nd, "fetch_news_window", lambda *a, **k: [_fila(i=1), _fila("ollama-7n", "earnings_beat", i=2)]
    )
    noticias = opinion_claude.noticias_recientes("NVDA")
    pendiente, clasificada = noticias
    # Antes de la 406: tipo y tono en None, sin decir por qué.
    assert pendiente["tipo"] is not None and pendiente["tono_-3_a_3"] is not None
    assert pendiente["clasificador"].startswith("heuristica provisional")
    assert clasificada["clasificador"] == "ollama-7n"
