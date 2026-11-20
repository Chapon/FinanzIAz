"""Tarea 427 — al pedir la opinión, qwen clasifica las noticias que se mandan y todavía no vio.

En la opinión de MU del 2026-11-11, 12 de las 15 noticias iban con la heurística provisional (la
406), que la 413 midió floja; *«Micron Stocks Jump 11.2% as Memory Rebound Meets $1 Billion
Anthropic Placement»* salió `other`, tono 0. qwen sólo clasifica en la corrida diaria. Ahora, al
pedir, clasifica las pendientes de las que se mandan, con un tope de tiempo, y las guarda.
"""

from __future__ import annotations

from datetime import datetime

from analysis import opinion_claude as oc
from analysis.news_digest import _Row
from data.catalyst_classifier import Classification


def _fila(i, event_type=None, classified_by=None, source="finnhub:Benzinga"):
    return _Row(
        id=i,
        ticker="MU",
        title=f"titular {i}",
        source=source,
        url=None,
        published_at=datetime(2026, 11, 11, 15, i),
        event_type=event_type,
        sentiment=None,
        classifier_confidence=None,
        classified_by=classified_by,
    )


class _Qwen:
    def __init__(self, tag="ollama-7n"):
        self.llamadas = []
        self.tag = tag

    def __call__(self, title, content, source, ticker):
        self.llamadas.append(title)
        return Classification("earnings", "positive", 0.9, self.tag, 0.66, 0.95)


def test_las_pendientes_salen_con_la_clasificacion_del_modelo_y_se_guardan():
    qwen, guardadas = _Qwen(), []
    out = oc.clasificar_a_demanda(
        [_fila(1), _fila(2)], qwen, guardar=lambda i, c: guardadas.append((i, c.classifier))
    )
    assert [(f.classified_by, f.provisional, f.event_type) for f in out] == [
        ("ollama-7n", False, "earnings")
    ] * 2
    assert guardadas == [(1, "ollama-7n"), (2, "ollama-7n")]


def test_lo_que_ya_clasifico_qwen_no_se_vuelve_a_pedir():
    qwen = _Qwen()
    oc.clasificar_a_demanda([_fila(1, "other", "ollama-7n")], qwen, guardar=lambda i, c: None)
    assert qwen.llamadas == []


def test_el_respaldo_de_la_436_es_pendiente():
    qwen = _Qwen()
    oc.clasificar_a_demanda([_fila(1, "other", "fallback")], qwen, guardar=lambda i, c: None)
    assert qwen.llamadas == ["titular 1"]


def test_las_8K_no_se_le_piden_al_modelo():
    qwen = _Qwen()
    oc.clasificar_a_demanda([_fila(1, source="sec_8k")], qwen, guardar=lambda i, c: None)
    assert qwen.llamadas == []


def test_sin_qwen_no_insiste_y_quedan_para_la_heuristica():
    """El modelo caído devuelve el respaldo: una llamada, no quince timeouts."""
    caido, guardadas = _Qwen(tag="fallback"), []
    filas = [_fila(i) for i in range(1, 6)]
    out = oc.clasificar_a_demanda(filas, caido, guardar=lambda i, c: guardadas.append(i))
    assert len(caido.llamadas) == 1 and guardadas == []
    assert out == filas


def test_si_el_clasificador_levanta_no_rompe_el_pedido():
    def explota(*a):
        raise ConnectionError("sin Ollama")

    filas = [_fila(1)]
    assert oc.clasificar_a_demanda(filas, explota, guardar=lambda i, c: None) == filas


def test_el_tope_de_tiempo_corta():
    """Cada noticia tarda 20 s en el reloj falso; con 45 s de tope entran tres (0, 20 y 40 s)."""
    t = [0.0]

    class _Lento(_Qwen):
        def __call__(self, *a):
            t[0] += 20.0
            return super().__call__(*a)

    lento = _Lento()
    oc.clasificar_a_demanda(
        [_fila(i) for i in range(1, 8)], lento, tope_s=45.0, reloj=lambda: t[0], guardar=lambda i, c: None
    )
    assert len(lento.llamadas) == 3


def test_noticias_recientes_clasifica_y_guarda_en_la_DB(test_db, monkeypatch):
    from database.models import NewsEvent, session_scope

    monkeypatch.setattr("database.models.utcnow_naive", lambda: datetime(2026, 11, 12, 0, 0))
    with session_scope() as s:
        s.add(
            NewsEvent(
                ticker="MU",
                title="Micron Stocks Jump 11.2% as Memory Rebound Meets $1 Billion Anthropic Placement",
                source="finnhub:Benzinga",
                content_hash="m1",
                published_at=datetime(2026, 11, 11, 15, 0),
            )
        )
    (n,) = oc.noticias_recientes("MU", clasificar=_Qwen())
    assert n["clasificador"] == "ollama-7n" and n["tipo"] == "earnings"
    with session_scope() as s:
        (e,) = s.query(NewsEvent).all()
        assert (e.classified_by, e.event_type, e.relevance) == ("ollama-7n", "earnings", 0.95)


def test_sin_clasificador_es_como_antes(test_db, monkeypatch):
    from database.models import NewsEvent, session_scope

    monkeypatch.setattr("database.models.utcnow_naive", lambda: datetime(2026, 11, 12, 0, 0))
    with session_scope() as s:
        s.add(
            NewsEvent(
                ticker="MU",
                title="algo",
                source="finnhub:Benzinga",
                content_hash="m1",
                published_at=datetime(2026, 11, 11, 15, 0),
            )
        )
    (n,) = oc.noticias_recientes("MU")
    assert "heuristica provisional" in n["clasificador"]


def test_el_backend_de_ollama_usa_el_timeout_que_se_le_pasa():
    from data.catalyst_classifier import make_ollama_backend

    pedidos = []

    def post(url, json=None, timeout=None):
        pedidos.append(timeout)
        raise TimeoutError

    make_ollama_backend(model="qwen", http_post=post, timeout=7.5)("t", None, "yfinance", "MU")
    assert pedidos == [7.5]


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 10
