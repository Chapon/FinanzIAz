"""Tarea 316 — el día seleccionado en Análisis usa las mismas reglas que la señal general.

El defecto (pregunta de Chapa, 2026-10-05, MU): con un día seleccionado la pestaña calculaba la
señal con una reimplementación propia —cuatro indicadores, el cruce SMA20/50 en vez de 50/200,
Bollinger *Vender* con el precio entre la media y la banda superior, sin XGBoost— y la pintaba
en el badge de «Señal general». MU el 05/10: *Compra Fuerte* seleccionado, *Mantener* sin
seleccionar, con la línea *«2 alcistas · 1 bajistas · 4 neutrales»* debajo de las dos.

El caso sintético está construido para que la regla vieja y la nueva DIFIERAN, y el test lo
verifica antes de usarlo: el precio entre la media y la banda superior, la SMA20 sobre la SMA50
(el cruce viejo decía compra) y la SMA50 bajo la SMA200 (el de `analyze()` dice venta).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from analysis.technical import (
    NO_RECONSTRUIBLES_POR_DIA,
    analyze,
    compute_bollinger_bands,
    compute_sma,
    technical_signals_at,
)


def _serie(n_baja: int = 260, n_rebote: int = 40) -> pd.DataFrame:
    """Una caída larga y un rebote reciente, con ruido determinístico."""
    rng = np.random.default_rng(316)
    baja = np.linspace(200, 100, n_baja)
    rebote = np.linspace(100, 112, n_rebote)
    close = np.concatenate([baja, rebote]) * (1 + rng.normal(0, 0.004, n_baja + n_rebote))
    idx = pd.bdate_range("2025-01-02", periods=len(close))
    vol = rng.integers(1_000_000, 2_000_000, len(close)).astype(float)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": vol}, index=idx
    )


def _fila(sigs, indicador):
    return next(s for s in sigs if s.indicator == indicador)


def test_el_ultimo_dia_da_LAS_MISMAS_senales_que_analyze():
    df = _serie()
    general = analyze("TST", df, enable_xgboost=False)
    dia = technical_signals_at("TST", df, len(df) - 1)
    clave = lambda s: (s.indicator, s.signal, s.strength, s.value, s.description)
    assert [clave(s) for s in dia] == [clave(s) for s in general.signals]


def test_el_caso_DISTINGUE_las_reglas_viejas_de_las_nuevas():
    """Precondiciones: si no se cumplen, el test de abajo no probaría nada."""
    df = _serie()
    close = float(df["Close"].iloc[-1])
    upper, middle, _lower = (float(x.iloc[-1]) for x in compute_bollinger_bands(df))
    sma20, sma50, sma200 = (float(compute_sma(df, n).iloc[-1]) for n in (20, 50, 200))
    assert middle < close < upper, "el precio tiene que estar entre la media y la banda superior"
    assert sma20 > sma50 > 0 and sma50 < sma200, "el cruce 20/50 y el 50/200 tienen que discrepar"


def test_bollinger_entre_media_y_superior_es_MANTENER_y_el_cruce_es_50_200():
    df = _serie()
    dia = technical_signals_at("TST", df, len(df) - 1)
    assert _fila(dia, "Bollinger Bands").signal == "HOLD"  # la regla vieja decía «Vender»
    cruce = _fila(dia, "Golden/Death Cross")
    assert cruce.signal == "SELL" and "SMA200" in cruce.description  # la vieja: compra por 20/50


def test_un_dia_PASADO_usa_solo_los_datos_hasta_ese_dia():
    """Los indicadores son causales: evaluar en idx == analizar df[:idx+1]."""
    df = _serie()
    idx = len(df) - 30
    corto = analyze("TST", df.iloc[: idx + 1].copy(), enable_xgboost=False)
    dia = technical_signals_at("TST", df, idx)
    assert [(s.indicator, s.signal, s.strength) for s in dia] == [
        (s.indicator, s.signal, s.strength) for s in corto.signals
    ]


@pytest.mark.parametrize("idx", [-1, 10_000])
def test_un_indice_fuera_de_rango_no_inventa_senales(idx):
    assert technical_signals_at("TST", _serie(), idx) == []


def test_lo_que_no_se_reconstruye_por_dia_son_indicadores_que_existen():
    """El rótulo del panel nombra GARCH y XGBoost: tienen que ser los indicadores que agrega analyze()."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    fuente = (raiz / "analysis/ml_signals.py").read_text(encoding="utf-8") + (
        raiz / "analysis/garch_signals.py"
    ).read_text(encoding="utf-8")
    for nombre in NO_RECONSTRUIBLES_POR_DIA:
        assert f'"{nombre}' in fuente, f"{nombre} no es el comienzo del nombre de ningún indicador"


# ── La pantalla ──────────────────────────────────────────────────────────────


def _tab_falsa(df):
    from ui.analysis_tab import AnalysisTab

    tab = MagicMock()
    tab._current_df = df
    tab._current_ticker = "TST"
    tab.chart._hover_data = None
    tab._hover_ind_widgets = {
        k: (MagicMock(), MagicMock())
        for k in ("RSI", "MACD", "Bollinger Bands", "Golden/Death Cross", "Volumen")
    }
    tab._compute_day_signals = lambda data: AnalysisTab._compute_day_signals(tab, data)
    return tab


def _data_del_grafico(df, idx):
    """El dict que emite `ChartWidget.hover_data`, con los valores que la UI vieja leía: sin
    ellos, la versión vieja no calculaba nada y pasaba los tests por vacío (caso degenerado)."""
    from analysis.technical import compute_macd, compute_rsi

    macd, sig, hist = compute_macd(df)
    upper, middle, lower = compute_bollinger_bands(df)
    v = lambda s: float(s.iloc[idx])
    return {
        "idx": idx,
        "date": df.index[idx],
        "close": v(df["Close"]),
        "rsi": v(compute_rsi(df)),
        "macd_line": v(macd),
        "signal_line": v(sig),
        "histogram": v(hist),
        "upper": v(upper),
        "lower": v(lower),
        "middle": v(middle),
        "sma20": v(compute_sma(df, 20)),
        "sma50": v(compute_sma(df, 50)),
    }


def test_seleccionar_un_dia_NO_pisa_la_senal_general():
    from ui.analysis_tab import AnalysisTab

    df = _serie()
    tab = _tab_falsa(df)
    AnalysisTab._on_chart_hover(tab, _data_del_grafico(df, len(df) - 1))
    tab.overall_badge.set_signal.assert_not_called()
    tab.hover_overall_sig_lbl.setText.assert_called()


def test_la_fila_de_bollinger_del_panel_dice_MANTENER():
    from ui.analysis_tab import AnalysisTab

    df = _serie()
    tab = _tab_falsa(df)
    AnalysisTab._on_chart_hover(tab, _data_del_grafico(df, len(df) - 1))
    _val, sig = tab._hover_ind_widgets["Bollinger Bands"]
    assert "Mantener" in sig.setText.call_args[0][0]
    _val, sig = tab._hover_ind_widgets["Volumen"]
    assert "—" not in sig.setText.call_args[0][0], "Volumen se puede calcular por día y tiene que aparecer"


def test_CADA_fila_del_ultimo_dia_dice_lo_mismo_que_la_senal_general():
    """El caso de MU: el último día seleccionado y la vista sin selección, indicador por indicador."""
    from analysis.technical import to_yahoo_level
    from ui.analysis_tab import _YAHOO_LABELS_ES, AnalysisTab

    df = _serie()
    general = {s.indicator: s for s in analyze("TST", df, enable_xgboost=False).signals}
    tab = _tab_falsa(df)
    AnalysisTab._on_chart_hover(tab, _data_del_grafico(df, len(df) - 1))
    for ind, (_val, sig) in tab._hover_ind_widgets.items():
        g = general[ind]
        esperado = _YAHOO_LABELS_ES[to_yahoo_level(g.signal, g.strength)]
        assert sig.setText.call_args[0][0] == f"● {esperado}", ind
