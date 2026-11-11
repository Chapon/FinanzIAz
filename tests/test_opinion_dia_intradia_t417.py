"""Tarea 417: Claude recibe el retorno del día, si el precio es intradiario y la hora ET de las noticias.

La opinión de MU del 2026-11-11 se pidió a las 15:02 UTC, con el precio intradiario (+8,5 % en el
día). Claude vio −1 % a 5 días y una nota de *«+7 % hoy»* y anotó en ``datos_faltantes`` que los datos
podían estar desincronizados. Los datos eran coherentes (el 05/11 MU cayó 17,5 % y la ventana de 5
días lo incluye); faltaba decirle que el día no había cerrado y cuánto iba.

Los casos están elegidos para que la versión defectuosa dé otra cosa: horas donde UTC y ET caen en
días distintos o a ambos lados del cierre de las 16:00.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from analysis import opinion_claude as oc
from data.yahoo_finance import market_timezone

ET = market_timezone()


def _df(ultimo: str = "2026-11-11"):
    idx = pd.bdate_range(end=ultimo, periods=30)
    close = pd.Series(np.linspace(100, 129, 30), index=idx)
    close.iloc[-2] = 110.0  # el cierre anterior, lejos del de hace 5 ruedas
    close.iloc[-1] = 121.0
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1e6})


def test_el_retorno_del_dia_es_contra_el_cierre_anterior():
    datos = oc.armar_datos("mu", _df())
    assert datos["retornos_pct"]["1d"] == pytest.approx(10.0)
    # El de 5 días sigue siendo otro número: si el "1d" mirara otra rueda, no daría 10 %.
    assert datos["retornos_pct"]["5d"] != pytest.approx(10.0)


def test_los_datos_llevan_su_version_para_la_321():
    datos = oc.armar_datos("mu", _df())
    assert datos["version_datos"] == oc.VERSION_DATOS >= 2


def test_a_las_15_30_ET_el_precio_es_intradiario_aunque_en_UTC_sean_las_20_30():
    # 20:30 UTC = 15:30 ET (EST, noviembre): una versión que mirara la hora UTC lo daría cerrado.
    e = oc.estado_precio(date(2026, 11, 11), datetime(2026, 11, 11, 20, 30, tzinfo=timezone.utc), ET)
    assert e["mercado_abierto"] is True
    assert e["precio_es"].startswith("intradiario")
    assert e["precio_consultado"] == "2026-11-11 15:30 ET"


def test_despues_del_cierre_es_el_cierre_del_dia():
    e = oc.estado_precio(date(2026, 11, 11), datetime(2026, 11, 11, 21, 5, tzinfo=timezone.utc), ET)
    assert e["mercado_abierto"] is False and e["precio_es"] == "cierre del 2026-11-11"


def test_en_la_preapertura_la_ultima_barra_es_el_cierre_de_ayer():
    # 13:00 UTC = 08:00 ET: la barra de hoy todavía no existe.
    e = oc.estado_precio(date(2026, 11, 10), datetime(2026, 11, 11, 13, 0, tzinfo=timezone.utc), ET)
    assert e["mercado_abierto"] is False and e["precio_es"] == "cierre del 2026-11-10"


def test_a_la_noche_ET_ya_es_otro_dia_en_UTC_y_no_confunde_la_barra():
    # 02:00 UTC del 12 = 21:00 ET del 11: la barra del 11 es su cierre, no "un día viejo".
    e = oc.estado_precio(date(2026, 11, 11), datetime(2026, 11, 12, 2, 0, tzinfo=timezone.utc), ET)
    assert e == {
        "mercado_abierto": False,
        "precio_es": "cierre del 2026-11-11",
        "precio_consultado": "2026-11-11 21:00 ET",
    }


def test_armar_datos_manda_el_estado_solo_si_sabe_cuando_llego_el_precio():
    sin = oc.armar_datos("mu", _df())
    con = oc.armar_datos("mu", _df(), obtenido=datetime(2026, 11, 11, 15, 2, tzinfo=timezone.utc))
    assert "estado_precio" not in sin
    assert con["estado_precio"]["mercado_abierto"] is True
    assert con["estado_precio"]["precio_consultado"] == "2026-11-11 10:02 ET"
    json.dumps(con)  # sigue siendo serializable, se guarda en datos_json


def test_la_hora_de_la_noticia_va_en_ET_y_no_la_fecha_UTC():
    # 01:30 UTC del 12 = 20:30 ET del 11. Cortar a la fecha UTC decía "2026-11-12".
    assert oc.hora_et(datetime(2026, 11, 12, 1, 30), ET) == "2026-11-11 20:30 ET"
    assert oc.hora_et(None, ET) is None


def test_noticias_recientes_manda_la_hora_ET(monkeypatch):
    import analysis.news_digest as nd

    fila = SimpleNamespace(
        published_at=datetime(2026, 11, 11, 14, 8, 42),  # la nota de "Micron Climbs 7%"
        fetched_at=datetime(2026, 11, 11, 14, 43),
        title="Micron Climbs 7%",
        event_type="stock_movement",
        sentiment_score=0.66,
        source="yahoo",
        provisional=False,
        classified_by="ollama",
    )
    monkeypatch.setattr(nd, "fetch_news_window", lambda *a, **k: [fila])
    monkeypatch.setattr(nd, "classify_missing", lambda filas: filas)
    (n,) = oc.noticias_recientes("MU")
    assert n["publicada"] == "2026-11-11 09:08 ET"
    assert "fecha" not in n


def test_el_prompt_explica_el_1d_lo_intradiario_y_la_hora_ET():
    p = oc.SYSTEM_PROMPT
    assert '"1d"' in p and "intradiario" in p and "(ET)" in p
