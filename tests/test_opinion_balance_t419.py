"""Tarea 419: Claude recibe la fecha del próximo balance y las sorpresas de EPS de los últimos trimestres.

Las dos opiniones de MU del 2026-11-11 pidieron *«la fecha del próximo reporte»*. La app ya la
bajaba para el Gate 6, con una trampa: ``get_next_earnings_date`` devuelve **a propósito** la
última fecha pasada cuando no hay una futura (la ventana post-balance del gate). Mandada tal cual,
Claude habría recibido como «próxima» una fecha vieja: la fila de MU en ``earnings_cache`` decía
2026-09-23 el 2026-11-11.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from analysis import opinion_claude as oc

HOY = date(2026, 11, 11)
SORPRESAS = [
    ("2026-09-30", 31.82, 33.42),
    ("2026-06-24", 20.69, 25.11),
    ("2026-03-18", 9.16, 12.2),
    ("2025-12-17", 3.96, 4.78),
    ("2025-09-23", 1.0, 1.1),
]


def test_una_fecha_futura_va_como_proxima_con_sus_dias():
    b = oc.bloque_balance(datetime(2026, 12, 23), [], HOY)
    assert b == {"proximo": "2026-12-23", "dias_hasta": 42}


def test_una_fecha_pasada_NO_va_como_proxima():
    # El caso de MU: el cache decía 2026-09-23.
    b = oc.bloque_balance(datetime(2026, 9, 23), [], HOY)
    assert b["proximo"] is None
    assert b["ultimo_conocido"] == "2026-09-23" and b["dias_desde"] == 49
    assert "dias_hasta" not in b


def test_el_mismo_dia_es_proximo_con_cero_dias():
    assert oc.bloque_balance(date(2026, 11, 11), [], HOY) == {"proximo": "2026-11-11", "dias_hasta": 0}


def test_las_sorpresas_a_mano_y_solo_las_ultimas_cuatro():
    b = oc.bloque_balance(None, SORPRESAS, HOY)
    assert b["proximo"] is None and "dias_hasta" not in b
    assert [s["fecha"] for s in b["sorpresas_eps"]] == [s[0] for s in SORPRESAS[:4]]
    assert b["sorpresas_eps"][0]["sorpresa_pct"] == pytest.approx(5.0, abs=0.05)  # 1,60 / 31,82
    assert "vista ACTUAL de Yahoo" in b["aviso"]


def test_con_estimado_negativo_la_sorpresa_tiene_el_signo_del_resultado():
    # Estimado −0,50 y reportado −0,25: le fue MEJOR de lo esperado, la sorpresa es positiva.
    b = oc.bloque_balance(None, [("2023-09-27", -0.50, -0.25), ("2023-06-28", 0.0, 0.1)], HOY)
    assert b["sorpresas_eps"][0]["sorpresa_pct"] == pytest.approx(50.0)
    assert b["sorpresas_eps"][1]["sorpresa_pct"] is None  # estimado cero: no hay porcentaje


def test_sin_nada_no_hay_bloque():
    assert oc.bloque_balance(None, [], HOY) is None


def test_balance_de_no_levanta_si_yahoo_falla(monkeypatch):
    import data.yahoo_finance as yfm

    def revienta(*a, **k):
        raise RuntimeError("Yahoo caído")

    monkeypatch.setattr(yfm, "get_next_earnings_date", revienta)
    assert oc.balance_de("MU", HOY) is None


def test_balance_de_arma_con_lo_que_devuelve_yahoo(monkeypatch):
    import data.news_sources as ns
    import data.yahoo_finance as yfm

    monkeypatch.setattr(yfm, "get_next_earnings_date", lambda t: datetime(2026, 12, 23))
    monkeypatch.setattr(ns, "collect_yfinance_earnings_history", lambda t, limit=16: SORPRESAS)
    b = oc.balance_de("MU", HOY)
    assert b["proximo"] == "2026-12-23" and len(b["sorpresas_eps"]) == 4


def test_armar_datos_lo_manda_y_sube_la_version():
    idx = pd.bdate_range(end="2026-11-11", periods=30)
    close = pd.Series(np.linspace(100, 129, 30), index=idx)
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1e6})
    datos = oc.armar_datos("mu", df, balance=oc.bloque_balance(datetime(2026, 12, 23), SORPRESAS, HOY))
    assert datos["balance"]["dias_hasta"] == 42
    assert datos["version_datos"] == oc.VERSION_DATOS >= 4
    assert "balance" not in oc.armar_datos("mu", df)
