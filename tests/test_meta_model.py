"""
Tests del meta-modelo pooled walk-forward — **Tarea 9**.

Pre-registro §5: ``docs/meta_labeling_t9_2026-07-21.md``.

Lo que estos tests protegen es **la validez del veredicto**, no una feature: si el
purge o el embargo no funcionan, el AUC sale inflado por solapamiento de
etiquetas y el harness entero mide humo. Es el error clásico que hace que un
backtest de ML se vea espectacular y no sirva para nada.

Todo sintético/offline.

Cubre:
  purge/embargo — se descarta lo que se solapa con el test, contado en RUEDAS
  OOS estricto  — ningún año de entrenamiento recibe predicción
  train limpio  — ninguna muestra de entrenamiento cae en el período de test
  AUC           — separación perfecta, azar, y empates promediados
  percentil     — orden, extremos, None al fondo, caso degenerado
"""

from __future__ import annotations

import numpy as np
import pytest

from analysis.meta_labeling import Dataset, Sample
from analysis.meta_model import (
    EMBARGO_DAYS,
    MIN_TRAIN_YEARS,
    _calendar,
    _split_train,
    cross_sectional_percentile,
    roc_auc,
    walkforward_oof,
)

LABEL_DAYS = 20


# ── Purge + embargo ──────────────────────────────────────────────────────────


def _seq_samples(dates: list[str]) -> list[Sample]:
    return [
        Sample(ticker="T", date=d, bar_idx=i, label=i % 2, features=np.zeros(3, dtype=float))
        for i, d in enumerate(dates)
    ]


def test_purge_drops_samples_whose_label_window_reaches_the_test():
    """Con 100 fechas consecutivas y corte en la 80, las muestras a menos de
    (20 etiqueta + 20 embargo) ruedas del corte se descartan."""
    dates = [f"2020-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(100)]
    dates = sorted(set(dates))
    samples = _seq_samples(dates)
    cal = _calendar(samples)
    cutoff = dates[80]

    train, purged = _split_train(samples, cutoff, cal, label_days=LABEL_DAYS, embargo_days=EMBARGO_DAYS)

    # Se entrena solo con lo que queda a >= 40 ruedas del corte.
    assert all(s.date < cutoff for s in train)
    assert len(train) == 80 - (LABEL_DAYS + EMBARGO_DAYS)
    assert purged == LABEL_DAYS + EMBARGO_DAYS
    assert len(train) + purged == 80


def test_purge_counts_trading_days_not_calendar_days():
    """El calendario se arma con las fechas presentes, no con días corridos.

    Si se contaran días corridos, un fin de semana largo o un feriado dejaría
    entrar muestras contaminadas alrededor de cada corte.
    """
    # 60 fechas salteadas de a 3 días corridos: 40 ruedas son 120 días corridos.
    from datetime import date, timedelta

    dates = [(date(2020, 1, 1) + timedelta(days=3 * i)).isoformat() for i in range(60)]
    samples = _seq_samples(dates)
    cal = _calendar(samples)
    cutoff = dates[50]

    train, purged = _split_train(samples, cutoff, cal, label_days=LABEL_DAYS, embargo_days=EMBARGO_DAYS)
    assert purged == LABEL_DAYS + EMBARGO_DAYS
    assert len(train) == 50 - (LABEL_DAYS + EMBARGO_DAYS)


def test_no_training_sample_is_on_or_after_the_cutoff():
    dates = [f"2021-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(60)]
    dates = sorted(set(dates))
    samples = _seq_samples(dates)
    train, _ = _split_train(
        samples, dates[30], _calendar(samples), label_days=LABEL_DAYS, embargo_days=EMBARGO_DAYS
    )
    assert all(s.date < dates[30] for s in train)


def test_cutoff_absent_from_the_calendar_still_purges():
    """El 1 de enero nunca es rueda: el corte tiene que resolverse a la primera
    fecha posterior en vez de romper o dejar pasar todo."""
    dates = [f"2020-06-{d:02d}" for d in range(1, 29)] + [f"2021-06-{d:02d}" for d in range(1, 29)]
    samples = _seq_samples(dates)
    train, purged = _split_train(samples, "2021-01-01", _calendar(samples), label_days=2, embargo_days=1)
    assert all(s.date < "2021-01-01" for s in train)
    assert purged == 3


# ── Walk-forward OOS ─────────────────────────────────────────────────────────


def _yearly_dataset(n_years: int = 7, per_year: int = 200, seed: int = 3) -> Dataset:
    """Dataset sintético con señal real, para que el modelo pueda entrenar."""
    rng = np.random.default_rng(seed)
    ds = Dataset()
    for y in range(2015, 2015 + n_years):
        for k in range(per_year):
            x = rng.normal(size=4)
            # etiqueta con dependencia real de la primera feature + ruido
            p = 1.0 / (1.0 + np.exp(-(1.5 * x[0])))
            label = int(rng.random() < p)
            month = 1 + (k * 12) // per_year
            day = 1 + (k % 27)
            ds.samples.append(
                Sample(
                    ticker=f"T{k % 5}",
                    date=f"{y}-{month:02d}-{day:02d}",
                    bar_idx=k,
                    label=label,
                    features=x,
                )
            )
    ds.samples.sort(key=lambda s: (s.date, s.ticker))
    return ds


def test_only_out_of_sample_years_get_predictions():
    """Los primeros ``MIN_TRAIN_YEARS`` años se usan SOLO para entrenar: si
    recibieran predicción, el harness estaría leyendo in-sample como si fuera OOS.
    """
    ds = _yearly_dataset(n_years=7)
    oof = walkforward_oof(ds)

    years = sorted({int(s.date[:4]) for s in ds.samples})
    train_only = set(years[:MIN_TRAIN_YEARS])
    scored_years = {int(d[:4]) for _, d in oof.proba}

    assert scored_years, "el walk-forward no produjo ninguna predicción"
    assert not (scored_years & train_only)
    assert scored_years == set(years[MIN_TRAIN_YEARS:])


def test_every_scored_sample_appears_exactly_once():
    ds = _yearly_dataset(n_years=6)
    oof = walkforward_oof(ds)
    expected = {(s.ticker, s.date) for s in ds.samples if int(s.date[:4]) in {f.test_year for f in oof.folds}}
    assert set(oof.proba) == expected


def test_probabilities_are_in_range():
    ds = _yearly_dataset(n_years=6)
    oof = walkforward_oof(ds)
    assert all(0.0 <= p <= 1.0 for p in oof.proba.values())


def test_train_window_expands_across_folds():
    ds = _yearly_dataset(n_years=7)
    oof = walkforward_oof(ds)
    sizes = [f.n_train for f in oof.folds]
    assert sizes == sorted(sizes), "la ventana de entrenamiento no expande"


def test_too_few_years_yields_no_folds():
    """Sin años suficientes no se inventa un fold: se devuelve vacío."""
    ds = _yearly_dataset(n_years=MIN_TRAIN_YEARS)
    oof = walkforward_oof(ds)
    assert oof.folds == []
    assert oof.proba == {}


def test_empty_dataset_is_handled():
    oof = walkforward_oof(Dataset())
    assert oof.proba == {}
    assert oof.folds == []


# ── AUC ──────────────────────────────────────────────────────────────────────


def test_auc_perfect_separation():
    assert roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)


def test_auc_inverted_separation():
    assert roc_auc([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(0.0)


def test_auc_all_tied_is_one_half():
    """Todos los scores iguales ⇒ 0.5 exacto (empates promediados)."""
    assert roc_auc([0, 1, 0, 1], [0.5] * 4) == pytest.approx(0.5)


def test_auc_single_class_is_none():
    assert roc_auc([1, 1, 1], [0.1, 0.5, 0.9]) is None
    assert roc_auc([0, 0, 0], [0.1, 0.5, 0.9]) is None


# ── Percentil cross-sectional (brazo F1) ─────────────────────────────────────


def test_percentile_orders_and_reserves_zero_for_missing():
    """Los presentes ocupan (0, 1]; el 0.0 queda libre para los ausentes."""
    pct = cross_sectional_percentile({"A": 0.1, "B": 0.5, "C": 0.9})
    assert pct["C"] > pct["B"] > pct["A"] > 0.0
    assert pct["C"] == pytest.approx(1.0)


def test_percentile_sends_missing_values_strictly_below_the_worst():
    """Un candidato sin momentum va al fondo, y **estrictamente** por debajo del
    peor candidato con dato: si empataran, el desempate alfabético del simulador
    podría meter al que no tiene dato por delante. La ausencia de dato no puede
    valer lo mismo que un dato malo.
    """
    pct = cross_sectional_percentile({"A": None, "B": 0.5, "C": 0.9})
    assert pct["A"] == 0.0
    assert pct["C"] > pct["B"] > pct["A"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_percentile_treats_non_finite_as_missing(bad):
    pct = cross_sectional_percentile({"A": bad, "B": 0.5})
    assert pct["A"] == 0.0


def test_percentile_single_candidate():
    assert cross_sectional_percentile({"A": 0.3}) == {"A": 1.0}


def test_percentile_all_missing():
    assert cross_sectional_percentile({"A": None, "B": None}) == {"A": 0.0, "B": 0.0}
