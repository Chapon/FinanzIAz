"""
Tests del cache de modelos XGBoost entre scans (tarea 24 / XGB-CACHE).

El problema que cierran
-----------------------
En runtime el ``_XGB_CACHE`` no sobrevivía a ningún scan: los ~58 tickers se
reentrenaban walk-forward cada ~15 min y devolvían secuencias de ``val_acc``
byte-por-byte idénticas — o sea, se pagaba el cómputo entero para obtener
exactamente el mismo modelo. Eran **dos defectos independientes**:

(a) **Key inestable.** ``_xgb_cache_key`` hasheaba ``Close.tail(20)``, que
    durante la sesión incluye el **bar parcial del día** (su Close se mueve con
    cada re-fetch), mientras el set de entrenamiento descarta las últimas
    ``PREDICTION_HORIZON`` filas sin label. La key se movía con un dato que el
    modelo no usa.

(b) **Capacidad y desalojo.** El cap era 64 contra 131 tickers distintos entre
    las dos cuentas, y el overflow se resolvía con un ``clear()`` entero
    ejecutado **dentro de la función que calcula la key** → un scan vaciaba el
    cache a mitad de camino y se llevaba los modelos de la otra cuenta.

Qué verifican estos tests
-------------------------
1. HIT intradía: el bar parcial se mueve → misma key, mismo modelo (sin
   reentreno). Es el criterio central del kill-criteria congelado.
2. MISS al cerrar el día: aparece un bar nuevo → key distinta → reentreno.
3. MISS por revisión de datos: un split/ajuste reescribe el histórico
   entrenable → key distinta (no servir un modelo viejo sobre datos nuevos).
4. La key NO muta el cache (el efecto colateral de (b)).
5. El LRU acotado desaloja de a uno el menos-usado, y el cap alcanza para el
   universo real de las dos cuentas.

Los tests 1-3 y 5 son puros (no entrenan). Solo el 1b/2b entrenan de verdad,
para probar identidad del modelo servido — el resto sería tiempo de CPU sin
información extra.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# Igual que test_walkforward.py: sin el stack ML opcional, este módulo no aplica.
pytest.importorskip("xgboost")
pytest.importorskip("sklearn.calibration")

from analysis.ml_signals import (  # noqa: E402
    _XGB_CACHE,
    _XGB_CACHE_MAX,
    PREDICTION_HORIZON,
    _lru_get,
    _lru_put,
    _xgb_cache_key,
    clear_ml_cache,
    train_xgboost_signal,
)

# Universo real medido en la DB viva al momento de la tarea 24: cuenta 1 con
# 52 watchlist + 5 posiciones, cuenta 2 con 128 + 10 → 131 tickers distintos
# compartiendo un cache module-level. El cap tiene que cubrirlo o vuelve el
# thrash que la tarea arregla.
LIVE_DISTINCT_TICKERS = 131


# ── Helpers ───────────────────────────────────────────────────────────────────


def _frame(n: int = 400, seed: int = 0) -> pd.DataFrame:
    """OHLCV sintético con índice de días hábiles (mismo molde que test_walkforward)."""
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    wiggle = np.abs(rng.normal(0, 0.002, n))
    idx = pd.date_range(end=pd.Timestamp("2026-08-11"), periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": np.r_[close[0], close[:-1]],
            "High": close * (1 + wiggle),
            "Low": close * (1 - wiggle),
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
        },
        index=idx,
    )


def _with_moved_partial_bar(df: pd.DataFrame, factor: float = 1.03) -> pd.DataFrame:
    """Copia del frame con el ÚLTIMO bar movido — el bar parcial de la sesión abierta.

    Es exactamente lo que devuelve un re-fetch de Yahoo con el mercado abierto:
    mismo índice, mismas filas cerradas, distinto Close en la última.
    """
    out = df.copy()
    out.iloc[-1, out.columns.get_loc("Close")] = float(df["Close"].iloc[-1]) * factor
    out.iloc[-1, out.columns.get_loc("High")] = float(df["High"].iloc[-1]) * factor
    return out


def _with_new_bar(df: pd.DataFrame) -> pd.DataFrame:
    """Copia con un bar hábil nuevo al final (el día cerró y arrancó el siguiente)."""
    nxt = df.index[-1] + pd.tseries.offsets.BDay(1)
    last_close = float(df["Close"].iloc[-1])
    row = pd.DataFrame(
        {
            "Open": [last_close],
            "High": [last_close * 1.01],
            "Low": [last_close * 0.99],
            "Close": [last_close * 1.004],
            "Volume": [2_000_000.0],
        },
        index=[nxt],
    )
    return pd.concat([df, row])


@pytest.fixture(autouse=True)
def _clean_cache():
    """Cada test arranca y termina con los caches vacíos."""
    clear_ml_cache()
    yield
    clear_ml_cache()


# ── 1. Key: estable intradía ──────────────────────────────────────────────────


def test_key_is_stable_when_the_partial_bar_moves():
    """El corazón de la tarea: mover el bar parcial NO puede cambiar la key.

    Ese bar no entra al entrenamiento (cae en las últimas PREDICTION_HORIZON
    filas sin label), así que si la key se mueve con él el cache falla en cada
    scan mientras entrena un modelo idéntico.
    """
    df = _frame()
    cols = ["mom_5", "rsi"]
    k1 = _xgb_cache_key(df, cols, 300)
    k2 = _xgb_cache_key(_with_moved_partial_bar(df), cols, 300)

    assert k1 != ""
    assert k1 == k2


def test_key_is_stable_across_the_whole_unlabelled_tail():
    """No solo el último bar: ninguna de las PREDICTION_HORIZON filas sin label
    debe entrar a la key (son las que ``dropna`` descarta del entrenamiento)."""
    df = _frame()
    cols = ["mom_5"]
    base = _xgb_cache_key(df, cols, 300)

    for offset in range(1, PREDICTION_HORIZON + 1):
        moved = df.copy()
        moved.iloc[-offset, moved.columns.get_loc("Close")] *= 1.05
        assert _xgb_cache_key(moved, cols, 300) == base, f"cambió con offset -{offset}"


# ── 2. Key: cambia cuando cambian los datos entrenables ───────────────────────


def test_key_changes_when_a_new_daily_bar_closes():
    """Un bar hábil nuevo corre la región entrenable → key distinta → reentreno
    (el ``1×/día/ticker`` que la tarea busca, no ``nunca más``)."""
    df = _frame()
    cols = ["mom_5"]
    # n_samples también avanza en producción (len(combined) crece con el bar).
    assert _xgb_cache_key(df, cols, 300) != _xgb_cache_key(_with_new_bar(df), cols, 301)


def test_key_changes_on_historical_revision():
    """Un split/ajuste reescribe el histórico: el cache no puede servir el modelo
    viejo. Se toca una fila BIEN adentro de la región entrenable."""
    df = _frame()
    cols = ["mom_5"]
    revised = df.copy()
    revised.iloc[-30, revised.columns.get_loc("Close")] *= 0.5

    assert _xgb_cache_key(df, cols, 300) != _xgb_cache_key(revised, cols, 300)


def test_key_changes_with_feature_spec_and_sample_count():
    """Guard de regresión: la key sigue discriminando el resto de sus entradas."""
    df = _frame()
    base = _xgb_cache_key(df, ["mom_5"], 300)

    assert _xgb_cache_key(df, ["mom_5", "rsi"], 300) != base
    assert _xgb_cache_key(df, ["mom_5"], 301) != base


def test_key_is_empty_for_frames_without_a_trainable_region():
    """Sin Close, o con menos filas que el horizonte, no hay nada que cachear."""
    df = _frame(n=50)

    assert _xgb_cache_key(df.drop(columns=["Close"]), ["mom_5"], 10) == ""
    assert _xgb_cache_key(df.iloc[: PREDICTION_HORIZON - 1], ["mom_5"], 10) == ""


def test_key_does_not_mutate_the_cache():
    """Defecto (b): calcular una key no puede tener efectos colaterales.

    El ``clear()`` vivía adentro de ``_xgb_cache_key``, así que el simple hecho
    de preguntar por un ticker podía vaciar el cache de los demás.
    """
    df = _frame()
    _lru_put(_XGB_CACHE, "sentinela", ("modelo", 0.5, 0.5, 0.0), _XGB_CACHE_MAX)

    for i in range(_XGB_CACHE_MAX * 2):
        _xgb_cache_key(df, [f"f{i}"], 300 + i)

    assert "sentinela" in _XGB_CACHE


# ── 3. LRU acotado ────────────────────────────────────────────────────────────


def test_lru_holds_the_live_universe_without_self_eviction():
    """El cap tiene que cubrir los 131 tickers distintos de las dos cuentas.

    Con el cap viejo (64) el scan de la cuenta 2 desalojaba a la 1 y todos
    reentrenaban en el scan siguiente.
    """
    assert _XGB_CACHE_MAX >= LIVE_DISTINCT_TICKERS

    for i in range(LIVE_DISTINCT_TICKERS):
        _lru_put(_XGB_CACHE, f"ticker-{i}", i, _XGB_CACHE_MAX)

    assert len(_XGB_CACHE) == LIVE_DISTINCT_TICKERS
    for i in range(LIVE_DISTINCT_TICKERS):
        assert _lru_get(_XGB_CACHE, f"ticker-{i}") == i


def test_lru_evicts_one_at_a_time_not_the_whole_cache():
    """Pasado el cap se cae el menos-usado, no todo (el bug de (b))."""
    cap = 4
    cache = type(_XGB_CACHE)()
    for i in range(cap):
        _lru_put(cache, f"k{i}", i, cap)

    _lru_put(cache, "k4", 4, cap)

    assert len(cache) == cap  # sigue lleno, no vaciado
    assert _lru_get(cache, "k0") is None  # el más viejo se fue
    assert _lru_get(cache, "k4") == 4
    for i in range(1, cap):
        assert _lru_get(cache, f"k{i}") == i


def test_lru_get_refreshes_recency():
    """Una lectura protege a la entrada del próximo desalojo."""
    cap = 3
    cache = type(_XGB_CACHE)()
    for i in range(cap):
        _lru_put(cache, f"k{i}", i, cap)

    _lru_get(cache, "k0")  # k0 pasa a ser el más reciente
    _lru_put(cache, "k3", 3, cap)

    assert _lru_get(cache, "k0") == 0
    assert _lru_get(cache, "k1") is None  # ahora k1 es el más viejo


def test_lru_ignores_empty_keys():
    """La key vacía (frame sin región entrenable) no debe ensuciar el cache."""
    cache = type(_XGB_CACHE)()
    _lru_put(cache, "", "algo", 10)

    assert len(cache) == 0
    assert _lru_get(cache, "") is None


# ── 4. End-to-end: el modelo se reusa de verdad ───────────────────────────────


def test_second_scan_of_the_day_reuses_the_trained_model():
    """La evidencia del log, cerrada: dos scans del mismo día con el bar parcial
    movido tienen que devolver **el mismo objeto modelo**, sin reentrenar."""
    df = _frame(n=420, seed=7)

    assert train_xgboost_signal(df) is not None
    assert len(_XGB_CACHE) == 1
    first_model = next(iter(_XGB_CACHE.values()))[0]

    assert train_xgboost_signal(_with_moved_partial_bar(df)) is not None

    assert len(_XGB_CACHE) == 1, "el segundo scan entrenó de nuevo"
    assert next(iter(_XGB_CACHE.values()))[0] is first_model


def test_new_trading_day_retrains():
    """El contrapunto: cuando el día cierra, el modelo SÍ se reentrena."""
    df = _frame(n=420, seed=7)

    assert train_xgboost_signal(df) is not None
    first_model = next(iter(_XGB_CACHE.values()))[0]

    assert train_xgboost_signal(_with_new_bar(df)) is not None

    assert len(_XGB_CACHE) == 2
    models = [v[0] for v in _XGB_CACHE.values()]
    assert first_model in models
    assert any(m is not first_model for m in models)
