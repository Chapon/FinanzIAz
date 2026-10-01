"""Tarea 258, parte 2 — el instrumento que mide el tono −3…+3 contra el retorno a 5 días.

Reusa la entrada, la ventana y el exceso de la 255 (testeados en ``test_news_sentiment_fwd5_t255``).
Lo nuevo, y lo que puede dar un número limpio y falso:

1. **Spearman con empates.** El tono tiene muchísimos empates (la mayoría de las unidades son 0):
   un ranking que no promedie empates da otro ``ρ``. Se compara contra ``scipy``.
2. **Spearman y no Pearson:** los casos son monótonos y no lineales, donde los dos difieren.
3. **El tono de la unidad es la MEDIA** de sus niveles, no el máximo ni el primero.
4. **El nivel es el de la pestaña** (``tone_level``): se mide lo que se muestra.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import scripts.measure_news_tone_fwd5_t258 as m


def test_rangos_promedian_los_empates():
    x = np.array([0.0, 2.0, 0.0, 3.0, 0.0, -2.0])
    assert list(m._rank(x)) == [3.0, 5.0, 3.0, 6.0, 3.0, 1.0]


def test_spearman_coincide_con_scipy_con_empates():
    stats = pytest.importorskip("scipy.stats")
    rng = np.random.default_rng(0)
    tone = rng.choice([-2.0, 0.0, 0.0, 0.0, 2.0, 3.0], size=300)
    excess = 0.01 * tone + rng.normal(0, 0.05, size=300)
    assert m.spearman(tone, excess) == pytest.approx(stats.spearmanr(tone, excess).statistic, abs=1e-12)


def test_es_spearman_y_no_pearson():
    tone = np.array([-2.0, 0.0, 2.0, 3.0])
    excess = np.array([-0.01, 0.0, 0.01, 0.50])  # monótono, no lineal
    assert m.spearman(tone, excess) == pytest.approx(1.0)
    assert np.corrcoef(tone, excess)[0, 1] < 0.9


def test_spearman_constante_es_None():
    assert m.spearman(np.zeros(5), np.arange(5.0)) is None


def _frame(n: int, close: float) -> pd.DataFrame:
    idx = pd.bdate_range("2026-07-01", periods=n)
    return pd.DataFrame({"Open": [100.0] * n, "Close": [close] * n}, index=idx)


def test_el_tono_de_la_unidad_es_la_media_de_los_niveles():
    n = 12
    spy = _frame(n, 100.5)  # SPY con retorno: si fuera 0, restarlo no se notaria
    pre = "2026-07-01 12:00:00"  # 08:00 EDT → entra el 01
    rows = [
        ("AAA", pre, "positive", 0.9),  # +3
        ("AAA", pre, "neutral", 0.0),  # 0
        ("AAA", pre, "neutral", 0.0),  # 0  → media 1,0 (el máximo daría 3)
        ("BBB", pre, "negative", -0.6),  # -2
    ]
    units = m.build_units(
        rows, {"AAA": _frame(n, 101.0), "BBB": _frame(n, 99.0)}, spy, last_day=pd.Timestamp("2027-01-01")
    )
    tonos = {u["ticker"]: u["tone"] for u in units}
    assert tonos == {"AAA": pytest.approx(1.0), "BBB": pytest.approx(-2.0)}
    assert {u["ticker"]: u["excess"] for u in units} == {
        "AAA": pytest.approx(0.005),
        "BBB": pytest.approx(-0.015),
    }


def test_sin_polaridad_usa_el_nivel_de_la_pestaña():
    n = 12
    rows = [("AAA", "2026-07-01 12:00:00", "positive", None)]
    units = m.build_units(
        rows, {"AAA": _frame(n, 101.0)}, _frame(n, 100.0), last_day=pd.Timestamp("2027-01-01")
    )
    assert units[0]["tone"] == 1.0  # tone_level(None, "positive")


def test_extremos_y_niveles():
    units = [
        {"tone": 2.0, "excess": 0.02, "entry_day": "d1"},
        {"tone": 1.5, "excess": 0.00, "entry_day": "d1"},  # entra en alta (≥ 1,5)
        {"tone": 1.0, "excess": 0.50, "entry_day": "d1"},  # NO entra en alta
        {"tone": -2.0, "excess": -0.01, "entry_day": "d2"},
        {"tone": -0.5, "excess": 0.30, "entry_day": "d2"},
    ]
    assert m.delta_ext(units) == pytest.approx(0.01 - (-0.01))
    niveles = m.por_nivel(units)
    assert niveles[2]["n"] == 2  # 2,0 y 1,5 redondean a +2 hacia afuera
    assert niveles[-1]["n"] == 1  # -0,5 → -1


def test_veredicto_exige_las_cuatro():
    base = {"rho": 0.05, "rho_ci95": [0.01, 0.09], "delta_ext": 0.006, "rho_h1": 0.04, "rho_h2": 0.06}
    assert m.verdict(base)[0]
    assert not m.verdict({**base, "rho_ci95": [-0.01, 0.09]})[0]
    assert not m.verdict({**base, "delta_ext": 0.004})[0]
    assert not m.verdict({**base, "rho_h2": -0.01})[0]
    assert not m.verdict({**base, "rho": -0.01})[0]
