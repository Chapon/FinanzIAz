"""Tarea 454 — el cierre contra el que se mide «1d» va con su fecha.

El lunes 2026-11-23, con el mercado abierto, Claude escribió «Ayer cerró en 125,53»: el cierre era el
del viernes 20/11. El número estaba bien (165,39 / 1,3175); la fecha no venía en los datos.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from analysis import opinion_claude as oc


def _df(fechas: list[str], cierres: list[float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(fechas))
    c = pd.Series(cierres, index=idx)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1_000.0})


def test_un_lunes_con_el_mercado_abierto_el_cierre_anterior_es_el_del_viernes():
    df = _df(["2026-11-19", "2026-11-20", "2026-11-23"], [140.0, 125.53, 165.39])
    datos = oc.armar_datos("nvda", df, obtenido=datetime(2026, 11, 23, 18, 35, tzinfo=timezone.utc))
    assert datos["cierre_anterior"] == {"fecha": "2026-11-20", "precio": 125.53}
    assert datos["retornos_pct"]["1d"] == 31.75  # contra ese cierre
    assert datos["estado_precio"]["mercado_abierto"] is True


def test_un_martes_a_la_noche_el_cierre_anterior_es_el_del_lunes():
    df = _df(["2026-11-20", "2026-11-23", "2026-11-24"], [125.53, 165.39, 160.0])
    datos = oc.armar_datos("nvda", df, obtenido=datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc))
    assert datos["cierre_anterior"] == {"fecha": "2026-11-23", "precio": 165.39}


def test_con_una_sola_barra_no_hay_cierre_anterior():
    datos = oc.armar_datos("nvda", _df(["2026-11-23"], [165.39]))
    assert datos["cierre_anterior"] is None and datos["retornos_pct"]["1d"] is None


def test_el_prompt_nombra_el_cierre_anterior():
    assert "contra cierre_anterior" in oc.SYSTEM_PROMPT
    assert '"ayer"' in oc.SYSTEM_PROMPT


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 17
