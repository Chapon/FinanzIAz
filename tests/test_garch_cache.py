"""GARCH2X — un solo fit por (frame, horizonte) dentro de un análisis.

El log 2026-07-15 mostraba cada mensaje de GARCH exactamente dos veces con
parámetros idénticos: `train_garch_signal` (la señal) y `compute_annual_volatility`
(dentro de `detect_market_regime*`) fitean el MISMO df. Estos tests fijan las
cuatro propiedades que el memo tiene que cumplir, incluida la que se pasó por
alto en el primer intento: **los fits degenerados también se cachean** — son
justo los que el log mostraba duplicados.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis import garch_signals as gs


class _Result:
    """Resultado de `arch` falso, parametrizable para el caso sano y el degenerado."""

    def __init__(self, *, convergence_flag=0, alpha=0.1, beta=0.2):
        self.convergence_flag = convergence_flag
        self.conditional_volatility = pd.Series([0.01] * 3, index=pd.RangeIndex(3))
        self.params = {"omega": 0.01, "alpha[1]": alpha, "beta[1]": beta}

    def forecast(self, horizon=1, reindex=False):
        class _F:
            variance = pd.DataFrame([[0.01]], index=[0], columns=[0])

        return _F()


@pytest.fixture
def fit_counter(monkeypatch):
    """Instala un `arch_model` falso que cuenta fits. Devuelve (contador, config)."""
    calls = {"n": 0}
    cfg = {"convergence_flag": 0, "alpha": 0.1, "beta": 0.2}

    class _Model:
        def __init__(self, returns, **kwargs):
            pass

        def fit(self, **kwargs):
            calls["n"] += 1
            return _Result(**cfg)

    monkeypatch.setattr(gs, "_ARCH_OK", True)
    monkeypatch.setattr(gs, "arch_model", lambda returns, **kw: _Model(returns, **kw))
    gs.reset_garch_cache()
    yield calls, cfg
    gs.reset_garch_cache()


def _make_df(offset: float = 0.0, periods: int = 140) -> pd.DataFrame:
    idx = pd.date_range("2020-01-02", periods=periods, freq="B")
    close = 100.0 + offset + np.cumsum(np.linspace(0.01, 0.6, len(idx)))
    return pd.DataFrame({"Close": close}, index=idx)


# ── 1. Un solo fit por los dos consumidores reales ───────────────────────────


def test_both_call_sites_share_one_fit(fit_counter):
    """El caso que motivó la tarea: los DOS consumidores reales, un solo fit."""
    calls, _ = fit_counter
    df = _make_df()

    gs.compute_annual_volatility(df)  # vía detect_market_regime*
    gs.train_garch_signal(df)  # la señal GARCH

    assert calls["n"] == 1, "el mismo df se fiteó más de una vez"


def test_degenerate_fit_is_also_cached(fit_counter):
    """Un fit que NO converge devuelve None — y ese None también se cachea.

    Regresión del primer intento: solo se cacheaba el éxito, así que los fits
    degenerados (los del log) seguían pagándose dos veces.
    """
    calls, cfg = fit_counter
    cfg["convergence_flag"] = 4  # no convergió → return None
    df = _make_df()

    assert gs.compute_annual_volatility(df)[2] == "EWMA"  # cayó al fallback
    gs.train_garch_signal(df)

    assert calls["n"] == 1, "el fit degenerado se repitió"


def test_out_of_valid_region_is_also_cached(fit_counter):
    """Mismo caso para α+β≥1 (el 'out of valid region' del log)."""
    calls, cfg = fit_counter
    cfg["alpha"], cfg["beta"] = 0.07058, 0.9294  # persistencia > 1
    df = _make_df()

    gs.fit_garch_forecast(df)
    gs.fit_garch_forecast(df)

    assert calls["n"] == 1


# ── 2. Paridad: el memo no cambia el resultado ───────────────────────────────


def test_cached_result_matches_uncached(fit_counter):
    """El valor servido del cache es idéntico al que sale de fitear de nuevo."""
    df = _make_df()

    primero = gs.fit_garch_forecast(df)
    gs.reset_garch_cache()
    recomputado = gs.fit_garch_forecast(df)
    del_cache = gs.fit_garch_forecast(df)

    assert primero == recomputado == del_cache
    assert del_cache is not None


def test_different_frames_get_different_results(fit_counter):
    """Frames distintos no comparten entrada (la huella discrimina)."""
    calls, _ = fit_counter

    gs.fit_garch_forecast(_make_df(offset=0.0))
    gs.fit_garch_forecast(_make_df(offset=50.0))

    assert calls["n"] == 2


def test_frame_with_nan_closes_still_hits_the_cache(fit_counter):
    """Un NaN en la muestra de closes no puede romper el matching de la huella.

    Si los closes van a la clave como tupla de floats, `NaN != NaN` hace que la
    huella nunca se iguale a sí misma: el lookup falla SIEMPRE, vuelve el doble
    fit y el cache se llena de entradas inalcanzables. Por eso van como bytes.
    """
    calls, _ = fit_counter
    df = _make_df()
    df.iloc[2, 0] = np.nan  # NaN dentro de los primeros 5 closes

    gs.compute_annual_volatility(df)
    gs.train_garch_signal(df)

    assert calls["n"] == 1, "el frame con NaN se fiteó dos veces"
    assert len(gs._garch_cache) == 1, "se creó una entrada inalcanzable por cada llamada"


def test_fingerprint_is_stable_across_calls(fit_counter):
    """La huella del mismo frame tiene que ser igual y hashear igual."""
    df = _make_df()
    df.iloc[0, 0] = np.nan

    a = gs._fingerprint(df, 5)
    b = gs._fingerprint(df, 5)

    assert a == b
    assert a in {b: 1}


def test_different_horizon_is_a_different_entry(fit_counter):
    """El horizonte es parte de la huella: cambiarlo obliga a refitear."""
    calls, _ = fit_counter
    df = _make_df()

    gs.fit_garch_forecast(df, horizon=5)
    gs.fit_garch_forecast(df, horizon=10)

    assert calls["n"] == 2


# ── 3. El cache está acotado ─────────────────────────────────────────────────


def test_cache_is_bounded(fit_counter):
    """La app corre horas y cada barra nueva es una huella nueva: sin tope, crece infinito."""
    for i in range(gs._GARCH_CACHE_MAXSIZE + 50):
        gs.fit_garch_forecast(_make_df(offset=float(i)))

    assert len(gs._garch_cache) <= gs._GARCH_CACHE_MAXSIZE


# ── 4. La huella nunca rompe el scan ─────────────────────────────────────────


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame({"Close": []}),
        pd.DataFrame({"Close": [100.0]}),  # 1 fila → squeeze da escalar
        pd.DataFrame({"Close": [100.0, 101.0]}),
        pd.DataFrame({"Close": [np.nan, np.nan, np.nan]}),
    ],
    ids=["vacio", "una_fila", "dos_filas", "todo_nan"],
)
def test_degenerate_frames_return_none_without_raising(fit_counter, frame):
    """Regresión: `_fingerprint` corría antes del try y tiraba AttributeError.

    Con un df de 1 fila, `df["Close"].squeeze()` devuelve un escalar y `.head(5)`
    explotaba, propagando la excepción a `analyze()` en pleno scan.
    """
    assert gs.fit_garch_forecast(frame) is None


def test_fingerprint_failure_falls_back_to_computing(fit_counter, monkeypatch):
    """Si la huella no se puede calcular, se fitea igual (fail-open, sin cachear)."""
    calls, _ = fit_counter
    monkeypatch.setattr(gs, "_fingerprint", lambda df, horizon: None)
    df = _make_df()

    assert gs.fit_garch_forecast(df) is not None
    assert gs.fit_garch_forecast(df) is not None
    assert calls["n"] == 2, "sin huella no se cachea, pero tampoco se rompe"
