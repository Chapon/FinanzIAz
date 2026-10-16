"""Tarea 364 — el cache de XGBoost tolera el ruido de ~2·10⁻⁷ con que Yahoo devuelve los cierres.

La 340 midió que cada bajada trae los cierres viejos con ese ruido, que la clave (hash de los
cierres redondeados a 4 decimales) lo veía como historia nueva y que se re-entrenaban ~115
modelos por hora de mercado. Ahora, con el ticker, los cierres se comparan con
``XGB_RTOL_CIERRES``; un ajuste por dividendo (≥ 10⁻³) sigue re-entrenando.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("xgboost")
pytest.importorskip("sklearn.calibration")

from analysis import ml_signals as ml
from tests.test_xgb_cache import _frame, _with_moved_partial_bar


@pytest.fixture(autouse=True)
def _limpio():
    ml.clear_ml_cache()
    yield
    ml.clear_ml_cache()


@pytest.fixture
def entrenamientos(monkeypatch):
    """Cuenta los entrenamientos de verdad (los dos caminos)."""
    n = {"n": 0}
    wf, ss = ml._train_walkforward, ml._train_single_split

    def _wf(*a, **k):
        n["n"] += 1
        return wf(*a, **k)

    def _ss(*a, **k):
        n["n"] += 1
        return ss(*a, **k)

    monkeypatch.setattr(ml, "_train_walkforward", _wf)
    monkeypatch.setattr(ml, "_train_single_split", _ss)
    return n


def _con_ruido(df, rel=3e-7, seed=1):
    """Lo que devuelve otra bajada de Yahoo: los mismos cierres, con ruido relativo ``rel``."""
    out = df.copy()
    rng = np.random.default_rng(seed)
    out["Close"] = df["Close"] * (1 + rng.choice([-rel, rel], len(df)))
    return out


def _con_dividendo(df, factor=0.999):
    """Un ajuste por dividendo: toda la historia anterior se re-escala por ``factor``."""
    out = df.copy()
    out.iloc[:-10, out.columns.get_loc("Close")] *= factor
    return out


def test_el_caso_no_es_degenerado_el_ruido_SI_cambia_la_clave_vieja():
    """Sin esto, el test de abajo podría pasar porque el ruido no movía nada."""
    df = _frame()
    cols = ["mom_5"]
    assert ml._xgb_cache_key(df, cols, 300) != ml._xgb_cache_key(_con_ruido(df), cols, 300)


def test_con_ticker_el_ruido_de_yahoo_NO_re_entrena(entrenamientos):
    df = _frame()
    a = ml.train_xgboost_signal(df, "MSFT")
    b = ml.train_xgboost_signal(_con_ruido(_with_moved_partial_bar(df)), "MSFT")

    assert entrenamientos["n"] == 1
    assert a is not None and b is not None


def test_un_ajuste_por_dividendo_SI_re_entrena(entrenamientos):
    df = _frame()
    ml.train_xgboost_signal(df, "MSFT")
    ml.train_xgboost_signal(_con_dividendo(df), "MSFT")

    assert entrenamientos["n"] == 2


def test_dos_tickers_con_las_mismas_fechas_no_comparten_modelo(entrenamientos):
    a, b = _frame(seed=0), _frame(seed=7)
    assert a.index.equals(b.index)

    ml.train_xgboost_signal(a, "AAA")
    ml.train_xgboost_signal(b, "BBB")
    ml.train_xgboost_signal(_con_ruido(a), "AAA")
    ml.train_xgboost_signal(_con_ruido(b), "BBB")

    assert entrenamientos["n"] == 2


def test_el_mismo_ticker_con_OTRA_serie_re_entrena(entrenamientos):
    """La clave sin cierres no puede servir el modelo de una historia distinta."""
    ml.train_xgboost_signal(_frame(seed=0), "AAA")
    ml.train_xgboost_signal(_frame(seed=7), "AAA")

    assert entrenamientos["n"] == 2


def test_sin_ticker_queda_la_clave_de_antes(entrenamientos):
    df = _frame()
    ml.train_xgboost_signal(df)
    ml.train_xgboost_signal(_con_ruido(df))

    assert entrenamientos["n"] == 2


def test_la_tolerancia_queda_tres_ordenes_por_debajo_de_un_dividendo():
    base = np.array([100.0, 101.0, 102.0])
    assert ml._cierres_coinciden(base, base * (1 + 4.4e-7))  # el máximo medido
    assert not ml._cierres_coinciden(base, base * 0.999)
    assert not ml._cierres_coinciden(base, base[:2])
    assert not ml._cierres_coinciden(None, base)


def test_los_cierres_guardados_se_podan_con_el_cache(monkeypatch):
    monkeypatch.setattr(ml, "_XGB_CACHE_MAX", 1)
    ml.train_xgboost_signal(_frame(seed=0), "AAA")
    ml.train_xgboost_signal(_frame(seed=7), "BBB")

    assert set(ml._XGB_CIERRES) == set(ml._XGB_CACHE)
    assert len(ml._XGB_CIERRES) == 1
