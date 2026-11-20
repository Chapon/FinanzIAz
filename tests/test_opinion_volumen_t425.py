"""Tarea 425: Claude recibe el volumen, y con el mercado abierto no pide un cierre que no existe.

La segunda opinión de MU del 2026-11-11 anotó como faltante *«precio y volumen al cierre de hoy
(el dato es intradiario)»*. La mitad era pedir algo imposible —ya sabía, por la 417, que el día no
había cerrado—; la otra mitad era real: el volumen nunca se mandaba.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from analysis import opinion_claude as oc


def _df(ultimo_vol: float = 3_000.0):
    idx = pd.bdate_range(end="2026-11-11", periods=30)
    close = pd.Series(np.linspace(100, 129, 30), index=idx)
    vol = pd.Series(1_000.0, index=idx)
    vol.iloc[-1] = ultimo_vol
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": vol})


def test_el_promedio_no_cuenta_la_ultima_barra():
    # 20 previas de 1.000 y la última de 3.000: sin la última, promedio 1.000 y relación 3,0.
    # Contándola (las 20 últimas), el promedio sería 1.100 y la relación 2,73.
    b = oc.bloque_volumen(_df(), intradiario=False)
    assert b["ultima_barra"] == 3_000
    assert b["promedio_20_ruedas_previas"] == 1_000
    assert b["relacion"] == pytest.approx(3.0)
    assert "parcial" not in b


def test_intradiario_lo_dice():
    b = oc.bloque_volumen(_df(400.0), intradiario=True)
    assert b["relacion"] == pytest.approx(0.4)
    assert "intradiaria" in b["parcial"]


def test_sin_volumen_no_hay_bloque():
    df = _df().drop(columns=["Volume"])
    assert oc.bloque_volumen(df, intradiario=False) is None


def test_armar_datos_marca_parcial_solo_con_el_mercado_abierto():
    abierto = oc.armar_datos("mu", _df(), obtenido=datetime(2026, 11, 11, 18, 13, tzinfo=timezone.utc))
    cerrado = oc.armar_datos("mu", _df(), obtenido=datetime(2026, 11, 11, 22, 0, tzinfo=timezone.utc))
    sin_hora = oc.armar_datos("mu", _df())
    assert "parcial" in abierto["volumen"]
    assert "parcial" not in cerrado["volumen"] and "parcial" not in sin_hora["volumen"]
    assert abierto["version_datos"] == oc.VERSION_DATOS >= 5


def test_el_prompt_dice_que_el_cierre_de_hoy_no_existe_todavia():
    p = oc.SYSTEM_PROMPT
    assert "el cierre y el volumen del día todavía no existen" in p
