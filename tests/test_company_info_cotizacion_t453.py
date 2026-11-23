"""Tarea 453 — el P/E, el EPS y la beta de Yahoo llegan a la opinión y al tooltip aunque el cache esté vigente.

``get_company_info`` lee primero ``CompanyInfoCache`` (7 días, desde el 2026-07-08), que guarda sólo
nombre, sector e industria: con fila vigente devolvía eso y nada más. De las 7 opiniones con el bloque
``yfinance`` de la 418, sólo la de TTWO (que no estaba en el cache) lo recibió; la de NVDA del 23/11
sumó por su cuenta los EPS trimestrales. El tooltip de ticker perdía además el dividendo, la bolsa y
el país.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

import data.yahoo_finance as yfm
from analysis import opinion_claude as oc

_INFO = {
    "longName": "NVIDIA Corporation",
    "sector": "Technology",
    "industry": "Semiconductors",
    "trailingPE": 33.6,
    "trailingEps": 4.9,
    "beta": 2.1,
    "dividendYield": 0.8,  # Yahoo lo da en porcentaje: 0,8 %
    "exchange": "NMS",
    "country": "United States",
}
_CACHEADO = {"name": "NVIDIA Corporation", "sector": "Technology", "industry": "Semiconductors"}


class _TickerFalso:
    def __init__(self, info):
        self.info = info


@pytest.fixture
def cache_vigente(test_db, monkeypatch):
    """Una fila vigente en ``CompanyInfoCache`` y un Yahoo falso que anota cada pedido."""
    monkeypatch.setattr(yfm, "_cache_enabled", lambda: True)
    yfm._write_company_info_cache("NVDA", _CACHEADO)
    pedidos: list[str] = []

    def _ticker(simbolo):
        pedidos.append(simbolo)
        return _TickerFalso(_INFO)

    monkeypatch.setattr(yfm, "_ticker", _ticker)
    return pedidos


def test_con_el_cache_vigente_el_pedido_de_siempre_no_va_a_yahoo(cache_vigente):
    """Métricas y el import siguen igual: nombre, sector e industria, sin red."""
    assert yfm.get_company_info("NVDA") == _CACHEADO
    assert cache_vigente == []


def test_fresco_saltea_el_cache_y_trae_la_cotizacion(cache_vigente):
    info = yfm.get_company_info("NVDA", fresco=True)
    assert (info["pe_ratio"], info["eps"], info["beta"]) == (33.6, 4.9, 2.1)
    assert info["dividend_yield"] == pytest.approx(0.008)
    assert (info["exchange"], info["country"]) == ("NMS", "United States")
    assert cache_vigente == ["NVDA"]


def test_fresco_sin_respuesta_devuelve_lo_cacheado_y_no_el_nombre_pelado(cache_vigente, monkeypatch):
    monkeypatch.setattr(yfm, "_run_with_timeout", lambda fn, *a, **k: k.get("default"))
    assert yfm.get_company_info("NVDA", fresco=True) == _CACHEADO


def test_completar_cotizacion_suma_lo_de_cotizacion_sin_pisar_lo_demas():
    company = {"name": "NVIDIA Corporation", "sector": "Technology", "industry": "Semiconductors"}
    # Yahoo no contestó: el nombre pelado no tapa nada.
    assert oc.completar_cotizacion(company, {"name": "NVDA", "sector": "N/A"}) == company
    completo = oc.completar_cotizacion(company, {"name": "NVDA", "pe_ratio": 33.6, "eps": 4.9, "beta": None})
    assert completo == {**company, "pe_ratio": 33.6, "eps": 4.9}
    assert oc.completar_cotizacion(None, None) == {}


def _df():
    n = 60
    idx = pd.date_range("2026-08-01", periods=n, freq="B")
    c = np.linspace(100.0, 110.0, n)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1e6}, index=idx)


def test_la_opinion_de_la_pestana_lleva_el_pe_de_yahoo_con_el_cache_vigente(cache_vigente, monkeypatch):
    """El camino de la app: la pestaña arma los datos con el `company` del cache; al pedir la opinión,
    la cotización se consulta de nuevo."""
    import ui.analysis_tab as at

    tab = MagicMock()
    at.AnalysisTab._on_analysis_done(tab, _df(), None, None, dict(_CACHEADO), None, ticker="NVDA")
    armar = tab.opinion_card.set_contexto.call_args.args[1]
    monkeypatch.setattr(oc, "noticias_y_cobertura", lambda *a, **k: ([], {}))
    monkeypatch.setattr(oc, "clasificador_a_demanda", lambda: None)
    for nombre in ("anuales_de", "balance_de", "pares_de"):
        monkeypatch.setattr(oc, nombre, lambda *a, **k: None)
    datos = armar()
    assert datos["yfinance"] == {"pe_trailing": 33.6, "eps_trailing": 4.9, "beta": 2.1}
    assert datos["empresa"] == "NVIDIA Corporation"
    assert cache_vigente == ["NVDA"]


def test_el_tooltip_pide_la_info_fresca(monkeypatch):
    from ui import ticker_tooltip as tt

    # La suite apaga los fetch del tooltip (la 82). Acá corre sincrónico —sin el pool— y con el
    # `get_company_info` falso: ni red ni DB desde otro hilo.
    monkeypatch.setattr(tt, "_SHUTTING_DOWN", False)
    llamadas = []
    monkeypatch.setattr(yfm, "get_company_info", lambda t, **k: llamadas.append(k) or {"pe_ratio": 33.6})
    senales = MagicMock()
    tt._FetchRunnable("NVDA", senales).run()
    assert llamadas == [{"fresco": True}]
    assert senales.fetched.emit.call_args.args[1]["pe_ratio"] == 33.6


def test_el_dividendo_de_yahoo_viene_en_porcentaje_y_el_tooltip_no_lo_multiplica_de_mas():
    """NVDA 0,8 y KO 2,19 (yfinance 1.4.1, medido el 2026-11-23): los dos son porcentajes."""
    from ui import ticker_tooltip as tt

    assert tt._fmt_pct(yfm.dividendo_como_fraccion(0.8)) == "0.80%"
    assert tt._fmt_pct(yfm.dividendo_como_fraccion(2.19)) == "2.19%"
    assert yfm.dividendo_como_fraccion(None) is None


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 16
