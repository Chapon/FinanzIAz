"""
Tests del etiquetado triple-barrera y las features pooled — **Tarea 9**.

Pre-registro: ``docs/meta_labeling_t9_2026-07-21.md``. Los tests verifican que el
código hace *literalmente* lo que ese doc congeló, porque el veredicto de la
tarea depende de eso: una etiqueta que mira High/Low en vez del close, o features
en unidades de precio, darían números distintos y no comparables.

Todo sintético/offline.

Cubre:
  etiqueta      — TP antes que stop, stop antes que TP, timeout, orden temporal
  close-only    — un pico intradía que revierte NO cuenta como toque
  ventana       — sin 20 ruedas completas de futuro ⇒ None (no se imputa)
  degenerados   — ATR ausente/cero/no finito ⇒ None
  features      — macd_hist normalizado por precio, atr_rel presente, orden fijo
  momentum 12-1 — saltea el último mes y es PIT
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from analysis.meta_labeling import (
    FEATURE_COLUMNS,
    MAX_DAYS,
    build_pooled_features,
    momentum_12_1,
    triple_barrier_label,
)


def _d(i: int) -> str:
    return (date(2020, 1, 1) + timedelta(days=i)).isoformat()


def _bars(closes: list[float], *, high=None, low=None) -> list:
    """(iso, open, high, low, close). Por defecto OHLC plano = close."""
    out = []
    for i, c in enumerate(closes):
        h = c if high is None else high[i]
        lo = c if low is None else low[i]
        out.append((_d(i), c, h, lo, c))
    return out


def _flat_atr(n: int, value: float = 1.0) -> list:
    return [value] * n


# ── La etiqueta (§3) ─────────────────────────────────────────────────────────


def test_tp_before_stop_is_label_1():
    """Entrada a 100, ATR 1 ⇒ TP=104, stop=98. Sube a 105 ⇒ y=1."""
    closes = [100.0] + [100.0, 101.0, 105.0] + [100.0] * 30
    bars = _bars(closes)
    assert triple_barrier_label(bars, 0, _flat_atr(len(bars))) == 1


def test_stop_before_tp_is_label_0():
    """Baja a 97 antes de tocar el TP ⇒ y=0."""
    closes = [100.0] + [99.0, 97.0, 110.0] + [100.0] * 30
    bars = _bars(closes)
    assert triple_barrier_label(bars, 0, _flat_atr(len(bars))) == 0


def test_timeout_counts_as_zero():
    """Ni TP ni stop en 20 ruedas ⇒ y=0 (el slot se desperdició)."""
    closes = [100.0] + [100.5] * 40
    bars = _bars(closes)
    assert triple_barrier_label(bars, 0, _flat_atr(len(bars))) == 0


def test_first_barrier_touched_wins():
    """El stop pega el día 1 y el TP el día 2: manda el primero en el tiempo."""
    closes = [100.0, 97.0, 106.0] + [100.0] * 30
    bars = _bars(closes)
    assert triple_barrier_label(bars, 0, _flat_atr(len(bars))) == 0

    closes = [100.0, 106.0, 97.0] + [100.0] * 30
    bars = _bars(closes)
    assert triple_barrier_label(bars, 0, _flat_atr(len(bars))) == 1


def test_intraday_spike_does_not_count():
    """El engine es un scanner EOD: un High que toca el TP pero cierra abajo NO
    cuenta. Si esto cambiara, la tasa de y=1 se inflaría y el modelo aprendería
    una capacidad que el sistema no tiene."""
    closes = [100.0] + [100.5] * 40
    highs = list(closes)
    highs[3] = 120.0  # pico intradía muy por encima del TP=104
    bars = _bars(closes, high=highs)
    assert triple_barrier_label(bars, 0, _flat_atr(len(bars))) == 0


def test_incomplete_window_is_none_not_zero():
    """Sin 20 ruedas completas de futuro la etiqueta es None y la muestra se
    descarta. Imputar 0 sesgaría sistemáticamente el final de cada serie."""
    bars = _bars([100.0] * (MAX_DAYS))  # entry_idx + 20 > n-1
    assert triple_barrier_label(bars, 0, _flat_atr(len(bars))) is None
    bars = _bars([100.0] * (MAX_DAYS + 1))  # justo alcanza
    assert triple_barrier_label(bars, 0, _flat_atr(len(bars))) == 0


@pytest.mark.parametrize("atr_value", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_degenerate_atr_is_none(atr_value):
    bars = _bars([100.0] * 40)
    atrs = [atr_value] * len(bars)
    assert triple_barrier_label(bars, 0, atrs) is None


def test_out_of_range_index_is_none():
    bars = _bars([100.0] * 40)
    assert triple_barrier_label(bars, -1, _flat_atr(len(bars))) is None
    assert triple_barrier_label(bars, 999, _flat_atr(len(bars))) is None


def test_multipliers_are_the_live_engine_values():
    """Los defaults tienen que ser los del engine vivo (AtrParams), no otros:
    el pre-registro los congeló como 'los valores vivos, no elegidos por
    performance'."""
    from analysis.exit_replay import AtrParams
    from analysis.meta_labeling import STOP_MULT, TP_MULT

    live = AtrParams()
    assert live.stop_mult == STOP_MULT
    assert live.tp_mult == TP_MULT


# ── Las features (§4) ────────────────────────────────────────────────────────


def _frame(n: int = 300, start: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    steps = rng.normal(0.0, 1.0, n).cumsum()
    close = start + steps
    idx = pd.date_range("2019-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": rng.integers(1_000, 10_000, n).astype(float),
        },
        index=idx,
    )


def test_features_have_the_frozen_columns_in_order():
    feat = build_pooled_features(_frame())
    assert list(feat.columns) == FEATURE_COLUMNS


def test_macd_hist_is_scaled_by_price():
    """La misma serie de precios ×10 tiene que dar el MISMO macd_hist normalizado.

    Sin esta corrección, poolear AAPL (~$200) con F (~$12) haría que el modelo
    aprendiera el nivel de precio del ticker en vez del momentum.
    """
    df = _frame()
    df10 = df * 10.0
    a = build_pooled_features(df)["macd_hist"].dropna()
    b = build_pooled_features(df10)["macd_hist"].dropna()
    assert len(a) > 50
    assert np.allclose(a.to_numpy(), b.to_numpy(), rtol=1e-9, atol=1e-12)


def test_atr_rel_is_present_and_scale_free():
    df = _frame()
    a = build_pooled_features(df)["atr_rel"].dropna()
    b = build_pooled_features(df * 10.0)["atr_rel"].dropna()
    assert len(a) > 50
    assert np.allclose(a.to_numpy(), b.to_numpy(), rtol=1e-9, atol=1e-12)


def test_missing_columns_are_filled_with_nan_not_dropped():
    """Un frame sin Volume no puede romper el armado: la columna queda NaN y la
    muestra se descarta después, en build_dataset."""
    df = _frame().drop(columns=["Volume"])
    feat = build_pooled_features(df)
    assert list(feat.columns) == FEATURE_COLUMNS
    assert feat["volume_ratio"].isna().all()


# ── Momentum 12-1 (§6, brazo F1) ─────────────────────────────────────────────


def test_momentum_12_1_skips_the_last_month():
    """Serie que sube 252 ruedas y después se desploma el último mes: el 12-1 no
    tiene que enterarse del desplome (esa es la razón de saltear el mes)."""
    up = pd.Series(list(np.linspace(100.0, 200.0, 260)) + [50.0] * 21)
    mom = momentum_12_1(up)
    last = mom.iloc[-1]
    assert last > 0.0, "el 12-1 miró el último mes cuando no debía"


def test_momentum_12_1_is_point_in_time():
    """El valor en t no puede cambiar por lo que pase después de t."""
    base = pd.Series(np.linspace(100.0, 200.0, 300))
    extended = pd.concat([base, pd.Series([1.0] * 50)], ignore_index=True)
    a = momentum_12_1(base).iloc[299]
    b = momentum_12_1(extended).iloc[299]
    assert (math.isnan(a) and math.isnan(b)) or a == pytest.approx(b)


def test_momentum_12_1_is_nan_before_warmup():
    short = pd.Series(np.linspace(100.0, 110.0, 100))
    assert momentum_12_1(short).isna().all()
