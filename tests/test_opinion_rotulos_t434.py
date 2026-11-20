"""Tarea 434 — lo que recibe la opinión de Claude dice lo que dicen sus rótulos.

En la opinión de MU del 2026-11-11: la calidad iba con las claves crudas (``roe: 20`` con un ROE de
~61 % el último año, porque la pata es el ROE de 10 años **menos su desvío**; ``deuda: 100``, que es
la **menos** endeudada) y Claude anotó *«solo hay un percentil de deuda»*; 7 de las 15 noticias eran
de otras empresas, sin su relevancia, y Claude tomó una de relevancia 0,0 (Nvidia, tono −1) como
riesgo de MU; y el ``current`` de los objetivos (787,35, de las 10:01 ET) iba al lado de un precio
de 811,53 de las 15:59 ET, sin rótulo.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from analysis import opinion_claude as oc
from analysis.calidad import PATAS
from analysis.valuation import Valuacion


def _df():
    idx = pd.bdate_range(end="2026-11-11", periods=30)
    close = pd.Series(np.linspace(100, 129, 30), index=idx)
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1_000.0})


def _valuacion(generado="2026-10-21", al="2026-10-21"):
    v = Valuacion(precio=811.53, eps=7.0)
    v.calidad = {
        "puntaje": 60.0,
        "percentiles": {"roe": 20.0, "rentab_bruta": 70.0, "deuda": 100.0, "regularidad": 50.0},
        "n": 126,
        "al": al,
    }
    v.generado = generado
    return v


def test_la_calidad_trae_su_corte_y_la_definicion_de_cada_pata():
    c = oc.bloque_valuacion(_valuacion())["calidad"]
    assert c["con_lo_presentado_antes_del"] == "2026-10-21"
    assert set(c["definiciones"]) == set(PATAS)
    assert "menos su desvío" in c["definiciones"]["roe"]
    assert "100 = la menos endeudada" in c["definiciones"]["deuda"]
    assert "100 es lo mejor" in c["sentido"]


def test_las_definiciones_cubren_todas_las_patas_de_calidad():
    """Si `analysis/calidad.py` suma una pata, la opinión la tiene que definir."""
    assert set(oc.DEFINICIONES_CALIDAD) == set(PATAS)


def test_sin_una_pata_no_se_define_la_que_no_vino():
    v = _valuacion()
    del v.calidad["percentiles"]["rentab_bruta"]
    assert "rentab_bruta" not in oc.bloque_valuacion(v)["calidad"]["definiciones"]


def test_la_fuente_dice_cuando_se_bajaron_los_fundamentals():
    """Decía «lo presentado hasta hoy», un literal, con el almacén del 21/10."""
    fuente = oc.bloque_valuacion(_valuacion(generado="2026-10-21"))["fuente"]
    assert "2026-10-21" in fuente and "hoy" not in fuente


def test_sin_fecha_la_fuente_no_afirma_hasta_cuando():
    fuente = oc.bloque_valuacion(_valuacion(generado=None))["fuente"]
    assert fuente == "EDGAR (10-K)"


def test_los_objetivos_van_sin_el_current_de_yahoo():
    analyst = {"price_targets": {"current": 787.35, "mean": 900.0, "low": 700.0, "high": 1_100.0}}
    datos = oc.armar_datos("mu", _df(), analyst=analyst)
    assert datos["analistas"]["precios_objetivo"] == {"mean": 900.0, "low": 700.0, "high": 1_100.0}


def test_sin_objetivos_no_rompe():
    assert (
        oc.armar_datos("mu", _df(), analyst={"price_targets": None})["analistas"]["precios_objetivo"] is None
    )


def test_el_prompt_explica_la_relevancia_y_el_sentido_de_la_calidad():
    p = oc.SYSTEM_PROMPT
    assert "relevancia_0_a_1" in p and "0,2 o menos" in p
    assert "100 es la menos endeudada" in p
    assert "\\n" not in p, "una continuación de línea rota deja un \\n literal en el prompt"


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 6


# ── Las noticias, con la DB de test ──────────────────────────────────────────


def _noticia(s, titulo, relevance, event_type="other", classified_by="ollama-7n", h=None):
    from database.models import NewsEvent

    s.add(
        NewsEvent(
            ticker="MU",
            title=titulo,
            source="finnhub:Benzinga",
            content_hash=h or titulo,
            published_at=datetime(2026, 11, 11, 15, 0),
            fetched_at=datetime(2026, 11, 11, 15, 5),
            event_type=event_type,
            sentiment="negative",
            sentiment_score=-0.33,
            classified_by=classified_by,
            relevance=relevance,
        )
    )


def test_cada_noticia_trae_su_relevancia(test_db, monkeypatch):
    from database.models import session_scope

    monkeypatch.setattr("database.models.utcnow_naive", lambda: datetime(2026, 11, 12, 0, 0))
    with session_scope() as s:
        _noticia(s, "Nvidia cae", 0.0)
        _noticia(s, "Micron sube", 0.9)
    rel = {n["titulo"]: n["relevancia_0_a_1"] for n in oc.noticias_recientes("MU")}
    assert rel == {"Nvidia cae": 0.0, "Micron sube": 0.9}


def test_la_heuristica_provisional_tambien_trae_relevancia(test_db, monkeypatch):
    """Las que qwen todavía no clasificó van con la heurística al vuelo (406): su relevancia también."""
    from database.models import NewsEvent, session_scope

    monkeypatch.setattr("database.models.utcnow_naive", lambda: datetime(2026, 11, 12, 0, 0))
    with session_scope() as s:
        s.add(
            NewsEvent(
                ticker="MU",
                title="Micron Technology reports record revenue",
                source="finnhub:Benzinga",
                content_hash="p1",
                published_at=datetime(2026, 11, 11, 15, 0),
            )
        )
    (n,) = oc.noticias_recientes("MU")
    assert "heuristica provisional" in n["clasificador"]
    assert isinstance(n["relevancia_0_a_1"], float)
