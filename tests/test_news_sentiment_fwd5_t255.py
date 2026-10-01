"""Tarea 255 — el instrumento que mide sentimiento de noticias contra retorno a 5 días.

Lo que se fija es lo que puede dar un número limpio y falso:

1. **La entrada** es la primera apertura POSTERIOR a la publicación, en hora de Nueva York. Los
   casos están elegidos para que difieran de un corte ingenuo en UTC: 13:20 UTC es antes de la
   apertura en verano (09:20 EDT) y 14:20 UTC es después de la apertura en verano pero antes en
   invierno (09:20 EST).
2. **La unidad** es (ticker, rueda) con sentimiento neto: una noticia repetida diez veces no pesa
   diez veces, y un empate se descarta.
3. **El retorno** es en exceso contra SPY, de apertura a cierre de la quinta rueda.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

import scripts.measure_news_sentiment_fwd5_t255 as m


def _idx(*dias: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(dias)))


# 2026-07-02 jueves, 03 viernes (feriado, sin rueda en este índice), 06 lunes
_JUL = _idx("2026-07-01", "2026-07-02", "2026-07-06", "2026-07-07")


@pytest.mark.parametrize(
    ("utc", "esperado"),
    [
        ("2026-07-02 13:20:00", "2026-07-02"),  # 09:20 EDT → abre ese día
        ("2026-07-02 13:40:00", "2026-07-06"),  # 09:40 EDT → ya abrió; el 03 no hay rueda
        ("2026-07-02 03:00:00", "2026-07-02"),  # 23:00 EDT del 01: en UTC ya es el 02, en NY no
        ("2026-07-04 15:00:00", "2026-07-06"),  # sábado → lunes
    ],
)
def test_entrada_en_la_primera_apertura_posterior_hora_NY(utc, esperado):
    pos = m.entry_index(_JUL, datetime.fromisoformat(utc))
    assert _JUL[pos] == pd.Timestamp(esperado)


def test_en_invierno_la_apertura_es_14_30_UTC():
    idx = _idx("2026-01-14", "2026-01-15")
    # 14:20 UTC = 09:20 EST: todavía no abrió → entra ese mismo día (en verano sería el siguiente)
    assert idx[m.entry_index(idx, datetime(2026, 1, 14, 14, 20))] == pd.Timestamp("2026-01-14")
    assert idx[m.entry_index(idx, datetime(2026, 1, 14, 14, 40))] == pd.Timestamp("2026-01-15")


def test_sin_rueda_posterior_no_hay_entrada():
    assert m.entry_index(_JUL, datetime(2026, 7, 7, 15, 0)) is None


def test_neto_y_empate():
    assert m.net_label(["positive"] * 10 + ["negative"]) == 1
    assert m.net_label(["positive", "negative"]) == 0
    assert m.net_label(["negative", "negative", "positive"]) == -1


def _frame(n: int, opens: list[float], closes: list[float], desde="2026-07-01") -> pd.DataFrame:
    idx = pd.bdate_range(desde, periods=n)
    return pd.DataFrame({"Open": opens, "Close": closes}, index=idx)


def test_retorno_de_apertura_de_entrada_a_cierre_de_la_quinta():
    df = _frame(6, [100, 200, 0, 0, 0, 0], [999, 0, 0, 0, 0, 220])
    # entrada en la rueda 1 (apertura 200), salida en la 5 (cierre 220): +10%
    assert m.window_return(df, 1) == pytest.approx(0.10)
    assert m.window_return(df, 2) is None


def test_unidades_netas_en_exceso_contra_SPY_y_sin_duplicar():
    n = 12
    plano = [100.0] * n
    sube = _frame(n, plano, [102.0] * n)  # +2% en cualquier ventana
    baja = _frame(n, plano, [99.0] * n)  # −1%
    spy = _frame(n, plano, [100.5] * n)  # +0,5%
    frames = {"AAA": sube, "BBB": baja}
    pre = "2026-07-01 12:00:00"  # 08:00 EDT → entra el 01
    rows = [("AAA", pre, "positive", "earnings_results")] * 10 + [("BBB", pre, "negative", "other")]
    units = m.build_units(rows, frames, spy, last_day=pd.Timestamp("2027-01-01"))
    assert len(units) == 2  # las diez de AAA son una unidad
    assert m.delta(units) == pytest.approx((0.02 - 0.005) - (-0.01 - 0.005))
    assert [u["earnings"] for u in sorted(units, key=lambda u: u["ticker"])] == [True, False]
    # cada unidad, no sólo la resta: en la resta SPY se cancela si las ventanas coinciden
    assert sorted(u["excess"] for u in units) == pytest.approx([-0.015, 0.015])


def test_la_barra_sin_asentar_no_entra_como_salida():
    n = 5
    df = _frame(n, [100.0] * n, [101.0] * n)
    rows = [("AAA", "2026-07-01 12:00:00", "positive", "other")]
    hoy = df.index[-1]  # la quinta rueda es "hoy"
    assert m.build_units(rows, {"AAA": df}, df, last_day=hoy) == []
    assert len(m.build_units(rows, {"AAA": df}, df, last_day=hoy + pd.Timedelta(days=1))) == 1


def test_veredicto_exige_las_cuatro():
    base = {"delta": 0.01, "ci95": [0.002, 0.02], "delta_h1": 0.01, "delta_h2": 0.008}
    assert m.verdict(base)[0]
    assert not m.verdict({**base, "ci95": [-0.001, 0.02]})[0]
    assert not m.verdict({**base, "delta": 0.004})[0]
    assert not m.verdict({**base, "delta_h2": -0.002})[0]
