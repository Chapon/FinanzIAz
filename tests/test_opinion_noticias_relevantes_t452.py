"""Tarea 452 — la opinión recibe las noticias más relevantes de cada día, no las 15 más nuevas.

El 2026-11-23 NVDA tenía 933 noticias en la ventana de 14 días. Las 15 que se mandaron eran de ese
día —7 de otras empresas (relevancia ≤ 0,2)— y quedaron afuera las 231 de los días anteriores con
relevancia ≥ 0,8, entre ellas la renuncia de Huang y las investigaciones. Claude anotó justamente
eso como faltante.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from analysis import opinion_claude as oc
from analysis.news_digest import _Row

_ET = timezone(timedelta(hours=-5))
_HOY = datetime(2026, 11, 23, 17, 0)  # UTC naive, como la DB: 12:00 ET


def _fila(i: int, cuando: datetime, rel: float | None, titulo: str = "", por: str = "ollama-qwen") -> _Row:
    return _Row(
        id=i,
        ticker="NVDA",
        title=titulo or f"noticia {i}",
        source="finnhub:Yahoo",
        url=None,
        published_at=cuando,
        event_type="other",
        sentiment="neutral",
        classifier_confidence=0.9,
        sentiment_score=0.0,
        classified_by=por,
        relevance=rel,
    )


def _ventana_nvda() -> list[_Row]:
    """Como la del 23/11: el último día lleno (la mitad de otras empresas), y días previos con lo que
    explica la caída. De la más nueva a la más vieja, como la devuelve ``fetch_news_window``."""
    filas = []
    i = 0
    for k in range(40):  # el 23/11: 40 noticias, una de cada dos de otra empresa
        i += 1
        filas.append(_fila(i, _HOY - timedelta(minutes=k), 0.0 if k % 2 else 1.0))
    for dias, titulo in [
        (1, "Nvidia faces US accounting probe amid deepening turmoil"),
        (3, "Nvidia Stock Plunges 12% After Reuters Reports an SEC Probe of Its Accounting"),
        (4, "Nvidia (NVDA) Rules Out Jensen Huang Return As Record Q3 Reshapes Leadership"),
        (6, "Nvidia reports record quarter"),
    ]:
        for k in range(6):
            i += 1
            rel = 1.0 if k == 0 else (0.6 if k < 3 else 0.1)
            filas.append(_fila(i, _HOY - timedelta(days=dias, minutes=k), rel, titulo if k == 0 else ""))
    return filas


def test_ninguna_de_otra_empresa_y_cada_dia_con_relevantes_tiene_la_suya():
    elegidas, descartadas = oc.elegir_noticias(_ventana_nvda(), _ET)
    assert len(elegidas) == oc.MAX_NOTICIAS
    assert all(f.relevance > oc.RELEVANCIA_DE_OTRA for f in elegidas)
    dias = {oc.hora_et(f.published_at, _ET)[:10] for f in elegidas}
    assert dias == {"2026-11-23", "2026-11-22", "2026-11-20", "2026-11-19", "2026-11-17"}
    titulos = {f.title for f in elegidas}
    assert "Nvidia Stock Plunges 12% After Reuters Reports an SEC Probe of Its Accounting" in titulos
    assert "Nvidia (NVDA) Rules Out Jensen Huang Return As Record Q3 Reshapes Leadership" in titulos
    assert descartadas == 20 + 4 * 3


def test_salen_de_la_mas_nueva_a_la_mas_vieja():
    elegidas, _ = oc.elegir_noticias(_ventana_nvda(), _ET)
    momentos = [f.published_at for f in elegidas]
    assert momentos == sorted(momentos, reverse=True)


def test_en_cada_dia_va_primero_la_mas_relevante():
    filas = [
        _fila(1, _HOY, 0.5, "media"),
        _fila(2, _HOY - timedelta(minutes=5), 0.9, "alta"),
        _fila(3, _HOY - timedelta(days=1), 0.7, "ayer"),
    ]
    elegidas, _ = oc.elegir_noticias(filas, _ET, maximo=2)
    assert [f.title for f in elegidas] == ["alta", "ayer"]


def test_las_que_no_midio_un_modelo_no_se_descartan():
    """La heurística no mide la relevancia (la 449): se toma como desconocida, no como de otra empresa."""
    filas = [_fila(1, _HOY, 0.2, "de otra"), _fila(2, _HOY, 0.2, "provisional", por="heuristic")]
    elegidas, descartadas = oc.elegir_noticias(filas, _ET)
    assert [f.title for f in elegidas] == ["provisional"] and descartadas == 1


def test_con_pocas_van_todas_las_relevantes():
    filas = [_fila(i, _HOY - timedelta(days=i), 0.8) for i in range(1, 6)]
    elegidas, descartadas = oc.elegir_noticias(filas, _ET)
    assert len(elegidas) == 5 and descartadas == 0


def test_la_cobertura_dice_cuantas_se_mandan_cuantas_se_descartaron_y_el_criterio(monkeypatch):
    import analysis.news_digest as nd

    monkeypatch.setattr(nd, "fetch_news_window", lambda *a, **k: _ventana_nvda())
    monkeypatch.setattr(nd, "harvest_en_curso", lambda: False)
    monkeypatch.setattr("database.models.utcnow_naive", lambda: _HOY)
    noticias, cob = oc.noticias_y_cobertura("NVDA")
    assert cob["en_la_ventana"] == 64 and cob["se_mandan"] == len(noticias) == oc.MAX_NOTICIAS
    assert cob["descartadas_de_otras_empresas"] == 32
    assert "más relevantes de cada día" in cob["nota"] and "otras empresas" in cob["nota"]
    assert all(n["relevancia_0_a_1"] > oc.RELEVANCIA_DE_OTRA for n in noticias)


def test_el_prompt_explica_el_criterio():
    assert "no son las más nuevas" in oc.SYSTEM_PROMPT
    assert "más relevantes de cada día" in oc.SYSTEM_PROMPT


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 15
