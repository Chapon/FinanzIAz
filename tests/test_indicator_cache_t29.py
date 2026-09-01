"""CACHE-IND (tarea 29) — el cache de indicadores nunca acertaba, y arreglarlo a
medias lo habría hecho MENTIR.

Dos defectos que sólo se pueden arreglar juntos, y son los dos de la T24 cruzados:

* **(a) capacidad:** ``_INDICATOR_CACHE_MAX`` era **50** contra **128 tickers** por
  scan. Con LRU de 50 y barrido secuencial de 128, ninguna entrada sobrevive una
  pasada — **hit rate 0%**, y RSI + MACD + Bollinger + SMA20/50/200 se recalculaban
  enteros en cada scan.
* **(b) la trampa:** la huella era ``(len(df), último timestamp)``, **ciega al
  close**. Durante la rueda la barra parcial de hoy cambia de valor pero no de
  largo ni de fecha ⇒ **misma clave**. Hoy eso está enmascarado porque el cache
  nunca acierta; con el cap arreglado **solo**, los indicadores del día quedarían
  congelados en la primera lectura de la mañana mientras el precio se mueve.

El test que fija la trampa es ``test_the_key_moves_when_the_partial_bar_moves``:
es el que falla si alguien "optimiza" el cap sin tocar la huella.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis import technical as T


def _frame(n: int = 300, base: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=n)
    rng = np.random.default_rng(29)
    close = base * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1e6},
        index=idx,
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    T.clear_indicator_cache()
    yield
    T.clear_indicator_cache()


# ── (b) la huella ─────────────────────────────────────────────────────────────


def test_the_key_moves_when_the_partial_bar_moves():
    """**El test que existe para que no se arregle a medias.** La barra parcial de
    hoy no cambia ni el largo ni la fecha: si la huella no mira el close, el cache
    sirve los indicadores de la mañana toda la rueda."""
    df = _frame()
    movido = df.copy()
    movido.iloc[-1, movido.columns.get_loc("Close")] = float(df["Close"].iloc[-1]) * 1.03

    assert len(movido) == len(df) and movido.index[-1] == df.index[-1]
    assert T._df_fingerprint(movido) != T._df_fingerprint(df)


def test_the_key_moves_on_a_retroactive_revision_far_back():
    """Un split o un re-ajuste por dividendos reescribe closes **viejos** sin tocar
    el largo ni la última fecha. Una huella de cola no lo vería, y serviría
    indicadores calculados sobre una historia que ya no existe."""
    df = _frame()
    revisado = df.copy()
    revisado.iloc[3, revisado.columns.get_loc("Close")] = 1.0
    assert T._df_fingerprint(revisado) != T._df_fingerprint(df)


def test_the_same_frame_gives_the_same_key():
    """Lo obvio, que es lo que hace que el cache sirva para algo: dos lecturas del
    mismo dataset son un hit."""
    df = _frame()
    assert T._df_fingerprint(df) == T._df_fingerprint(df.copy())


def test_a_new_daily_bar_moves_the_key():
    df = _frame()
    assert T._df_fingerprint(_frame(301)) != T._df_fingerprint(df)


def test_non_numeric_closes_never_collide():
    """Mejor no cachear que una clave que no distingue dos datasets: con closes no
    numéricos la huella es irrepetible a propósito."""
    df = _frame()
    roto = df.copy()
    roto["Close"] = "no soy un número"
    assert T._df_fingerprint(roto) != T._df_fingerprint(roto)


def test_an_empty_frame_does_not_explode():
    vacio = pd.DataFrame({"Open": [], "High": [], "Low": [], "Close": [], "Volume": []})
    assert T._df_fingerprint(vacio) == (0, "", "")


# ── (a) la capacidad ──────────────────────────────────────────────────────────


def test_the_cache_holds_the_live_universe_without_self_eviction():
    """El defecto (a): con cap 50 y 128 tickers, la segunda pasada del mismo scan
    —o el segundo scan de la sesión— encontraba el cache **vacío de lo suyo**."""
    assert T._INDICATOR_CACHE_MAX >= 128

    from analysis.ml_signals import _XGB_CACHE_MAX

    assert T._INDICATOR_CACHE_MAX == _XGB_CACHE_MAX  # mismo criterio que la T24


def test_a_second_pass_over_the_live_universe_is_all_hits():
    """La medición del kill-criteria, en chico: 128 tickers, dos pasadas. Con el cap
    viejo (50) la segunda pasada daba **0 hits**; ahora da 128."""
    frames = {f"T{i:03d}": _frame(260, base=50 + i) for i in range(128)}
    for ticker, df in frames.items():
        T.get_cached_indicators(ticker, df)
    assert T.indicator_cache_stats()["hits"] == 0  # primera pasada: todo miss

    for ticker, df in frames.items():
        T.get_cached_indicators(ticker, df)
    stats = T.indicator_cache_stats()
    assert stats["hits"] == 128 and stats["misses"] == 128
    assert stats["size"] == 128


def test_with_the_old_cap_the_second_pass_would_have_missed_everything(monkeypatch):
    """La contraprueba, para que el número de arriba signifique algo: con 50 el
    barrido se come a sí mismo y la segunda pasada no encuentra **nada**."""
    monkeypatch.setattr(T, "_INDICATOR_CACHE_MAX", 50)
    frames = {f"T{i:03d}": _frame(260, base=50 + i) for i in range(128)}
    for _ in range(2):
        for ticker, df in frames.items():
            T.get_cached_indicators(ticker, df)
    assert T.indicator_cache_stats()["hits"] == 0


def test_eviction_drops_one_at_a_time_not_the_whole_cache(monkeypatch):
    monkeypatch.setattr(T, "_INDICATOR_CACHE_MAX", 3)
    for i in range(5):
        T.get_cached_indicators(f"T{i}", _frame(260, base=50 + i))
    assert T.indicator_cache_stats()["size"] == 3


def test_a_hit_refreshes_recency(monkeypatch):
    """LRU de verdad: el ticker que se vuelve a leer no puede ser el próximo en
    salir, o el barrido secuencial desaloja justo lo que se está usando."""
    monkeypatch.setattr(T, "_INDICATOR_CACHE_MAX", 3)
    frames = {f"T{i}": _frame(260, base=50 + i) for i in range(3)}
    for t, d in frames.items():
        T.get_cached_indicators(t, d)
    T.get_cached_indicators("T0", frames["T0"])  # T0 pasa a ser el más reciente
    T.get_cached_indicators("T9", _frame(260, base=99))  # desaloja a T1, no a T0

    claves = {k[0] for k in T._INDICATOR_CACHE}
    assert "T0" in claves and "T1" not in claves


# ── (d) el cache de stacking, latente ────────────────────────────────────────


def test_the_stacking_cache_is_sized_for_the_live_universe_too():
    """Hoy no molesta (`stacking_enabled=False`), pero prenderlo traía de regalo el
    mismo cache que nunca acierta."""
    from analysis.ml_signals import _STACK_CACHE_MAX, _XGB_CACHE_MAX

    assert _STACK_CACHE_MAX == _XGB_CACHE_MAX >= 128


# ── (c) la clave de GARCH, que NO se tocó ────────────────────────────────────


def test_the_garch_key_still_sees_the_partial_bar():
    """Regresión de una **decisión**, no de un bug (tarea 29c). La huella de GARCH
    incluye el último close y por eso hace miss en cada scan intradía — el enunciado
    proponía keyearla a día, como hizo la T24 con el XGBoost.

    **Medido y descartado** (`docs/garch_intraday_t29_2026-09-01.md`): sobre 133
    tickers del universo vivo, **3 (2,3%) cambian la señal emitida** entre el primer
    y el último scan del día. El criterio pre-declarado pedía **100%** idénticas, así
    que la clave se queda como está. Si alguien la keyea a día, este test se pone
    rojo y el comentario dice por qué.
    """
    from analysis import garch_signals as G

    df = _frame()
    movido = df.copy()
    movido.iloc[-1, movido.columns.get_loc("Close")] = float(df["Close"].iloc[-1]) * 1.02
    assert G._fingerprint(movido, 5) != G._fingerprint(df, 5)
