"""Tarea 420 — Claude recibe cómo se movieron los pares de la misma industria y el ETF del sector.

En la opinión de MU del 2026-11-11 pidió la evolución de los precios de DRAM/NAND/HBM, que no
existe gratis, y vio los pares sólo por titulares (*«SK Hynix −25% en un mes»*). Lo que la app sí
tiene son los cierres de los tickers que guarda: ésos van, y el prompt dice que no tiene precios de
commodities ni de insumos.
"""

from __future__ import annotations

from analysis import opinion_claude as oc


def _serie(inicio: float, fin: float, n: int = 30):
    paso = (fin - inicio) / (n - 1)
    return [(f"2026-10-{i + 1:02d}", inicio + paso * i) for i in range(n)]


# Elegido para que sector e industria DIFIERAN: MSFT es del mismo sector y otra industria (no entra);
# RARO es de la misma industria y otro sector (entra). Comparar por sector da exactamente al revés.
_UNIVERSO = {
    "MU": ("Technology", "Semiconductors"),
    "NVDA": ("Technology", "Semiconductors"),
    "RARO": ("Industrials", "Semiconductors"),
    "MSFT": ("Technology", "Software - Infrastructure"),
}
_SERIES = {
    "MU": _serie(90, 130),  # con serie: si no, «no es su par» pasaría sin mirar el ticker
    "NVDA": _serie(100, 120),
    "RARO": _serie(50, 40),
    "MSFT": _serie(400, 410),
    "SOXX": _serie(200, 210),
}


def _bloque(**kw):
    kw.setdefault("universo", _UNIVERSO)
    return oc.bloque_pares("MU", "Semiconductors", "Technology", series=_SERIES.get, **kw)


def test_entran_los_de_la_misma_industria_aunque_sean_de_otro_sector():
    b = _bloque()
    assert [p["ticker"] for p in b["pares"]] == ["NVDA", "RARO"]


def test_el_mismo_sector_de_otra_industria_no_entra():
    assert "MSFT" not in [p["ticker"] for p in _bloque()["pares"]]


def test_el_propio_ticker_no_es_su_par():
    assert "MU" not in [p["ticker"] for p in _bloque()["pares"]]


def test_los_retornos_a_5_y_20_ruedas_calculados_a_mano():
    nvda = next(p for p in _bloque()["pares"] if p["ticker"] == "NVDA")
    serie = _SERIES["NVDA"]
    assert nvda["5d"] == round((serie[-1][1] / serie[-6][1] - 1) * 100, 1)
    assert nvda["20d"] == round((serie[-1][1] / serie[-21][1] - 1) * 100, 1)
    assert nvda["al"] == serie[-1][0]


def test_el_etf_de_semiconductores_es_SOXX_y_si_no_hay_serie_no_va():
    assert _bloque()["etf_del_sector"]["ticker"] == "SOXX"
    sin_etf = oc.bloque_pares(
        "MU", "Semiconductors", "Technology", _UNIVERSO, lambda t: None if t == "SOXX" else _SERIES.get(t)
    )
    assert sin_etf["etf_del_sector"] is None and sin_etf["pares"]


def test_a_lo_sumo_cinco_pares():
    universo = {f"T{i}": ("Technology", "Semiconductors") for i in range(9)}
    b = oc.bloque_pares("MU", "Semiconductors", "Technology", universo, lambda t: _serie(10, 11))
    assert len(b["pares"]) == oc.MAX_PARES


def test_sin_pares_ni_etf_se_calla():
    assert oc.bloque_pares("MU", "Semiconductors", "Technology", _UNIVERSO, lambda t: None) is None
    assert oc.bloque_pares("MU", "N/A", "Technology", _UNIVERSO, _SERIES.get) is None
    assert oc.bloque_pares("MU", None, None, _UNIVERSO, _SERIES.get) is None


def test_una_serie_corta_no_entra():
    b = oc.bloque_pares("MU", "Semiconductors", "Technology", _UNIVERSO, lambda t: _serie(1, 2, n=4))
    assert b is None


def test_armar_datos_lo_manda_solo_si_hay():
    import numpy as np
    import pandas as pd

    idx = pd.bdate_range(end="2026-11-11", periods=30)
    close = pd.Series(np.linspace(100, 129, 30), index=idx)
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1_000.0})
    assert "pares" in oc.armar_datos("mu", df, pares=_bloque())
    assert "pares" not in oc.armar_datos("mu", df)


def test_pares_de_lee_la_industria_del_cache_si_yahoo_dice_NA(test_db, monkeypatch):
    """`get_company_info` devuelve "N/A" sin dato: la industria sale de `company_info_cache`."""
    from data import historical_series
    from database.models import CompanyInfoCache, session_scope

    with session_scope() as s:
        for t, (sector, industria) in _UNIVERSO.items():
            s.add(CompanyInfoCache(ticker=t, name=t, sector=sector, industry=industria))
    monkeypatch.setattr(historical_series, "close_series", lambda con, t: _SERIES.get(t))
    b = oc.pares_de("MU", {"sector": "N/A", "industry": "N/A"}, bajar=lambda t: None)
    assert b is not None and [p["ticker"] for p in b["pares"]] == ["NVDA", "RARO"]


# ── Ampliación (2026-11-20, la opinión de MSFT): índices, bajar el ETF, pares viejos afuera ──


def _serie_hasta(fin: str, inicio: float, ultimo: float, n: int = 30):
    import pandas as pd

    dias = pd.bdate_range(end=fin, periods=n)
    paso = (ultimo - inicio) / (n - 1)
    return [(str(d.date()), inicio + paso * i) for i, d in enumerate(dias)]


def _df_hasta(fin: str):
    import pandas as pd

    return pd.DataFrame({"Close": range(30)}, index=pd.bdate_range(end=fin, periods=30))


def test_un_par_con_la_serie_vieja_no_entra():
    """El cache guarda tickers que nadie refresca: sus retornos serían de otra ventana."""
    series = dict(_SERIES)
    series["RARO"] = _serie(50, 40, n=10)  # termina el 2026-10-10, 20 días antes
    b = oc.bloque_pares("MU", "Semiconductors", "Technology", _UNIVERSO, series.get, al="2026-10-30")
    assert [p["ticker"] for p in b["pares"]] == ["NVDA"]


def test_el_desfase_tolerado_es_de_cinco_dias_justos():
    series = dict(_SERIES)
    series["RARO"] = _serie(50, 40, n=25)  # termina el 2026-10-25: 5 días
    b = oc.bloque_pares("MU", "Semiconductors", "Technology", _UNIVERSO, series.get, al="2026-10-30")
    assert [p["ticker"] for p in b["pares"]] == ["NVDA", "RARO"]
    series["RARO"] = _serie(50, 40, n=24)  # 6 días
    b = oc.bloque_pares("MU", "Semiconductors", "Technology", _UNIVERSO, series.get, al="2026-10-30")
    assert [p["ticker"] for p in b["pares"]] == ["NVDA"]


def test_los_indices_van_y_el_propio_ticker_no_es_su_indice():
    series = dict(_SERIES, SPY=_serie(500, 510), QQQ=_serie(400, 380))
    assert _bloque()["indices"] == []  # sin serie, no van
    b = oc.bloque_pares("MU", "Semiconductors", "Technology", _UNIVERSO, series.get)
    assert [i["ticker"] for i in b["indices"]] == ["SPY", "QQQ"]
    b = oc.bloque_pares("SPY", None, None, {}, series.get)
    assert [i["ticker"] for i in b["indices"]] == ["QQQ"]


def test_sin_industria_van_igual_el_etf_del_sector_y_los_indices():
    """Sin industria no hay pares, pero el sector y el mercado siguen sirviendo."""
    series = dict(_SERIES, XLK=_serie(200, 190), SPY=_serie(500, 510))
    b = oc.bloque_pares("MU", "N/A", "Technology", _UNIVERSO, series.get)
    assert b["pares"] == [] and b["industria"] is None
    assert b["etf_del_sector"]["ticker"] == "XLK"
    assert [i["ticker"] for i in b["indices"]] == ["SPY"]


def _pares_de_con(test_db, monkeypatch, guardadas: dict, bajar, fin: str = "2026-10-30"):
    from data import historical_series
    from database.models import CompanyInfoCache, session_scope

    with session_scope() as s:
        for t, (sector, industria) in _UNIVERSO.items():
            s.add(CompanyInfoCache(ticker=t, name=t, sector=sector, industry=industria))
    monkeypatch.setattr(historical_series, "close_series", lambda con, t: guardadas.get(t))
    company = {"sector": "Technology", "industry": "Semiconductors"}
    return oc.pares_de("MU", company, _df_hasta(fin), bajar=bajar)


def test_pares_de_baja_el_etf_y_los_indices_que_faltan_y_no_los_pares(test_db, monkeypatch):
    """El 2026-11-20 el cache tenía SPY y ningún ETF: leído sólo del cache, el ETF no salía nunca."""
    guardadas = {t: _SERIES[t] for t in ("MU", "NVDA", "MSFT")}
    guardadas["RARO"] = _serie_hasta("2026-10-28", 50, 40)  # dos días atrás: un par no se baja
    bajadas = []

    def bajar(t):
        bajadas.append(t)
        guardadas[t] = _serie_hasta("2026-10-30", 10, 11)

    b = _pares_de_con(test_db, monkeypatch, guardadas, bajar)
    assert sorted(bajadas) == ["QQQ", "SOXX", "SPY"]
    assert [p["ticker"] for p in b["pares"]] == ["NVDA", "RARO"]
    assert b["etf_del_sector"]["ticker"] == "SOXX"
    assert [i["ticker"] for i in b["indices"]] == ["SPY", "QQQ"]


def test_pares_de_no_baja_lo_que_el_cache_tiene_al_dia(test_db, monkeypatch):
    guardadas = dict(_SERIES, SPY=_serie(500, 510), QQQ=_serie(400, 380))
    bajadas = []
    b = _pares_de_con(test_db, monkeypatch, guardadas, bajadas.append)
    assert bajadas == []
    assert b["etf_del_sector"]["ticker"] == "SOXX"


def test_pares_de_baja_de_nuevo_el_etf_que_quedo_atras_del_ticker(test_db, monkeypatch):
    """Un día atrás alcanza: con el mercado abierto, el ticker trae la barra de hoy y el ETF no."""
    guardadas = dict(_SERIES, SPY=_serie_hasta("2026-11-02", 500, 510), QQQ=_serie_hasta("2026-11-02", 4, 3))
    bajadas = []

    def bajar(t):
        bajadas.append(t)
        guardadas[t] = _serie_hasta("2026-11-02", 200, 230)

    b = _pares_de_con(test_db, monkeypatch, guardadas, bajar, fin="2026-11-02")
    assert bajadas == ["SOXX"]
    assert b["etf_del_sector"]["al"] == "2026-11-02"


def test_pares_de_sin_red_sigue_con_lo_que_hay(test_db, monkeypatch):
    def bajar(t):
        raise OSError("sin red")

    b = _pares_de_con(test_db, monkeypatch, dict(_SERIES), bajar)
    assert [p["ticker"] for p in b["pares"]] == ["NVDA", "RARO"]
    assert b["etf_del_sector"]["ticker"] == "SOXX" and b["indices"] == []


def test_bajar_usa_el_periodo_del_scan(monkeypatch):
    """Con el período del scan, bajar SPY reescribe el mismo frame que el scan usa de benchmark."""
    import data.yahoo_finance as yfm
    import paper_trading.engine as eng

    llamadas = []
    monkeypatch.setattr(
        yfm, "get_historical_data", lambda t, period, interval: llamadas.append((t, period, interval))
    )
    monkeypatch.setattr(eng, "_resolve_history_period", lambda: "5y")
    oc._bajar_al_cache("SOXX")
    assert llamadas == [("SOXX", "5y", "1d")]


def test_el_prompt_dice_que_no_hay_precios_de_insumos():
    assert "NO tiene precios de commodities ni de insumos" in oc.SYSTEM_PROMPT


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 8
