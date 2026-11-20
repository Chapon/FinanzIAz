"""Tarea 442 — pedida la opinión de un ticker sin noticias recientes, se bajan al pedir; y Claude
recibe qué noticias tiene la app, de qué días, y por qué no hay cuando no hay.

La opinión de TTWO del 2026-11-20 anotó *«No vino el bloque de noticias»*: TTWO no está en el
universo que se cosecha y no tenía ninguna fila. La de MSFT, pedida a mitad del harvest, tenía la
más nueva del 11/11 y ninguna del 12 al 17.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from analysis import news_digest as nd
from analysis import opinion_claude as oc
from data.news_sources import NewsItem, _CollectResult

_AHORA = datetime(2026, 11, 20, 4, 0)  # UTC naive, como persiste la app
_ET = ZoneInfo("America/New_York")


@pytest.fixture
def ahora(monkeypatch):
    monkeypatch.setattr("database.models.utcnow_naive", lambda: _AHORA)
    return _AHORA


def _item(i: int, cuando: datetime, ticker: str = "TTWO") -> NewsItem:
    return NewsItem(
        ticker=ticker,
        title=f"Take-Two noticia {i}",
        source="yfinance:search",
        url=f"https://example.com/{ticker}/{i}",
        published_at=cuando,
    )


def _collector(items, pedidos=None):
    def collector(ticker, sources):
        if pedidos is not None:
            pedidos.append((ticker, frozenset(sources)))
        return _CollectResult(news=list(items))

    return collector


def _sembrar(*cuandos, ticker="TTWO"):
    from database.models import NewsEvent, session_scope

    with session_scope() as s:
        for i, c in enumerate(cuandos):
            s.add(
                NewsEvent(
                    ticker=ticker,
                    title=f"guardada {i}",
                    source="finnhub:Benzinga",
                    content_hash=f"g{ticker}{i}",
                    published_at=c,
                    fetched_at=c,
                )
            )


# ── bajar_noticias ───────────────────────────────────────────────────────────


def test_bajar_guarda_con_el_dedup_del_harvest_y_sin_pedirle_a_la_SEC(test_db):
    from database.models import NewsEvent, session_scope

    pedidos = []
    items = [_item(1, _AHORA - timedelta(hours=3)), _item(2, _AHORA - timedelta(hours=5))]
    assert oc.bajar_noticias("ttwo", collector=_collector(items, pedidos)) == 2
    assert pedidos == [("TTWO", frozenset({"yfinance_news", "finnhub"}))]
    # La segunda vez son las mismas: el dedup del harvest no las vuelve a meter.
    assert oc.bajar_noticias("TTWO", collector=_collector(items)) == 0
    with session_scope() as s:
        assert s.query(NewsEvent).filter(NewsEvent.ticker == "TTWO").count() == 2


def test_bajar_sin_red_devuelve_None_y_no_levanta(test_db):
    def explota(ticker, sources):
        raise ConnectionError("sin red")

    assert oc.bajar_noticias("TTWO", collector=explota) is None


def test_bajar_corta_en_el_tope(test_db):
    def lento(ticker, sources):
        time.sleep(1.0)
        return _CollectResult(news=[_item(1, _AHORA)])

    t0 = time.monotonic()
    assert oc.bajar_noticias("TTWO", collector=lento, tope_s=0.1) is None
    assert time.monotonic() - t0 < 0.9


# ── cuándo se baja ───────────────────────────────────────────────────────────


def test_sin_noticias_se_bajan_y_entran_al_bloque(test_db, ahora):
    llamadas = []

    def bajar(t):
        llamadas.append(t)
        return oc.bajar_noticias(t, collector=_collector([_item(1, ahora - timedelta(hours=2))]))

    noticias, cob = oc.noticias_y_cobertura("TTWO", bajar=bajar)
    assert llamadas == ["TTWO"]
    assert [n["titulo"] for n in noticias] == ["Take-Two noticia 1"]
    assert cob["bajadas_al_pedir"] == 1 and cob["en_la_ventana"] == 1


def test_con_noticias_frescas_no_se_baja_nada(test_db, ahora):
    _sembrar(ahora - timedelta(hours=3))
    llamadas = []
    noticias, cob = oc.noticias_y_cobertura("TTWO", bajar=lambda t: llamadas.append(t) or 0)
    assert llamadas == [] and len(noticias) == 1
    assert "bajadas_al_pedir" not in cob


def test_con_la_mas_nueva_vieja_se_baja():
    """El caso de MSFT: había noticias, pero la más nueva era de días antes."""
    fila = type("F", (), {"published_at": _AHORA - timedelta(hours=30), "fetched_at": None})()
    assert oc.hay_que_bajar([fila], _AHORA)
    fila.published_at = _AHORA - timedelta(hours=20)
    assert not oc.hay_que_bajar([fila], _AHORA)
    assert oc.hay_que_bajar([], _AHORA)


def test_sin_red_el_bloque_dice_que_no_hay_y_por_que(test_db, ahora):
    noticias, cob = oc.noticias_y_cobertura("TTWO", bajar=lambda t: None)
    assert noticias == []
    assert cob["en_la_ventana"] == 0 and cob["bajadas_al_pedir"] is None
    assert "no se pudieron bajar" in cob["nota"]


def test_si_las_fuentes_no_traen_nada_lo_dice_distinto(test_db, ahora):
    _, cob = oc.noticias_y_cobertura("TTWO", bajar=lambda t: 0)
    assert "no trajeron" in cob["nota"]


# ── la cobertura ─────────────────────────────────────────────────────────────


def test_los_dias_sin_noticias_van_en_hora_del_Este():
    """La de las 02:00 UTC del 12/11 es del 11/11 a las 21:00 ET: ese día tiene, el 12 no."""
    filas = [
        type("F", (), {"published_at": c, "fetched_at": None})()
        for c in (datetime(2026, 11, 10, 15, 0), datetime(2026, 11, 12, 2, 0))
    ]
    desde, hasta = datetime(2026, 11, 9, 17, 0), datetime(2026, 11, 13, 17, 0)
    cob = oc.bloque_cobertura(filas, desde, hasta, dias=4, zona=_ET)
    assert cob["dias_sin_noticias"] == ["2026-11-09", "2026-11-12", "2026-11-13"]
    assert cob["mas_vieja"] == "2026-11-10 10:00 ET"
    assert cob["mas_nueva"] == "2026-11-11 21:00 ET"


def test_dice_cuantas_hay_y_cuantas_se_mandan():
    filas = [
        type("F", (), {"published_at": _AHORA - timedelta(hours=i), "fetched_at": None})() for i in range(20)
    ]
    cob = oc.bloque_cobertura(filas, _AHORA - timedelta(days=14), _AHORA, dias=14, zona=_ET)
    assert cob["en_la_ventana"] == 20 and cob["se_mandan"] == oc.MAX_NOTICIAS


def test_armar_datos_manda_la_cobertura_aunque_no_haya_noticias():
    import numpy as np
    import pandas as pd

    idx = pd.bdate_range(end="2026-11-19", periods=30)
    close = pd.Series(np.linspace(100, 129, 30), index=idx)
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1_000.0})
    cob = {"ventana_dias": 14, "en_la_ventana": 0, "se_mandan": 0, "nota": "la app no tiene"}
    datos = oc.armar_datos("ttwo", df, noticias=[], cobertura_noticias=cob)
    assert datos["cobertura_noticias"] == cob and "noticias" not in datos


# ── el harvest corriendo ─────────────────────────────────────────────────────


def test_el_harvest_se_marca_mientras_corre_y_se_desmarca_aunque_falle():
    visto = []

    def main(argv):
        visto.append(nd.harvest_en_curso())
        return 0

    def explota(argv):
        raise RuntimeError("se cayó")

    assert not nd.harvest_en_curso()
    nd.run_catalyst_harvest_only(harvest_main=main)
    nd.run_catalyst_refresh(harvest_main=main, classify_main=lambda argv, **kw: 0)
    assert visto == [True, True] and not nd.harvest_en_curso()
    nd.run_catalyst_harvest_only(harvest_main=explota)
    assert not nd.harvest_en_curso()


def test_con_el_harvest_corriendo_el_bloque_y_la_tarjeta_lo_dicen(test_db, ahora, monkeypatch):
    from ui.analysis import opinion_card

    monkeypatch.setattr(nd, "harvest_en_curso", lambda: True)
    _sembrar(ahora - timedelta(hours=2))
    _, cob = oc.noticias_y_cobertura("TTWO")
    assert cob["harvest_en_curso"] is True and "pueden no estar todavía" in cob["nota"]
    assert opinion_card.aviso_harvest() == opinion_card.AVISO_HARVEST
    monkeypatch.setattr(nd, "harvest_en_curso", lambda: False)
    assert opinion_card.aviso_harvest() == ""


def test_el_prompt_explica_la_cobertura():
    assert "cobertura_noticias" in oc.SYSTEM_PROMPT and "no las tiene" in oc.SYSTEM_PROMPT


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 12
