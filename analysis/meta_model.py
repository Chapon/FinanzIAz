"""
Meta-modelo pooled con walk-forward purgado — **Tarea 9** del backlog.

Pre-registro §5 (protocolo de entrenamiento, CONGELADO):
``docs/meta_labeling_t9_2026-07-21.md``.

El punto entero
---------------
El modelo vivo entrena **un XGBoost por ticker dentro del scan**, con val sets de
~40 muestras. Eso produce el ``val_acc std >8%`` y el gap train/val 99/55 que el
log tira en casi todos los tickers: no es un bug, es lo que pasa cuando se
estiman 120 árboles con 40 muestras de validación. Acá se entrena **un solo
modelo sobre los 41 tickers juntos**, que es el fix estructural.

Lo que hace honesto al resultado
--------------------------------
Cada barra la puntúa el fold que **no la vio**, y de cada ventana de
entrenamiento se sacan las muestras cuya etiqueta se solapa con el test
(**purge**) más un **embargo** posterior. Sin eso, el solapamiento de ventanas de
20 ruedas filtra futuro y el AUC sale inflado — es el error clásico que hace que
un backtest de ML se vea espectacular y no sirva para nada.

Sin red, sin DB, sin tocar el engine.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

from analysis.meta_labeling import MAX_DAYS, Dataset, Sample

log = logging.getLogger(__name__)

# §5 — congelados.
MIN_TRAIN_YEARS = 4      # el primer año de test es el quinto de la muestra
EMBARGO_DAYS = 20        # ruedas de embargo después del corte (López de Prado)
MIN_CALIB_SAMPLES = 100  # bajo esto se usa el modelo crudo (igual que ml_signals)
CALIB_FRACTION = 0.20    # cola del train reservada para la isotónica


@dataclass
class FoldReport:
    """Trazabilidad de un fold — para poder auditar por qué dio lo que dio."""

    test_year: int
    n_train: int
    n_purged: int
    n_calib: int
    n_test: int
    train_base_rate: float
    test_base_rate: float
    calibrated: bool
    auc: float | None = None


@dataclass
class OOFResult:
    """Predicciones out-of-sample + el detalle de cómo se produjeron."""

    # {(ticker, date_iso10): P(TP antes que stop)}
    proba: dict[tuple[str, str], float] = field(default_factory=dict)
    folds: list[FoldReport] = field(default_factory=list)
    n_skipped_folds: int = 0

    @property
    def auc(self) -> float | None:
        """AUC agregada sobre todos los folds (ponderada por n de test)."""
        pairs = [(f.auc, f.n_test) for f in self.folds if f.auc is not None]
        if not pairs:
            return None
        tot = sum(n for _, n in pairs)
        return sum(a * n for a, n in pairs) / tot if tot else None


def roc_auc(y: list[int], p: list[float]) -> float | None:
    """AUC por el estadístico de Mann-Whitney, con empates promediados.

    Implementada acá (en vez de importar sklearn) para que el módulo se pueda
    testear sin depender de la versión de sklearn instalada, y porque el cálculo
    por rangos es exacto y de tres líneas.
    """
    pos = [pi for yi, pi in zip(y, p) if yi == 1]
    neg = [pi for yi, pi in zip(y, p) if yi == 0]
    if not pos or not neg:
        return None
    order = sorted(range(len(p)), key=lambda i: p[i])
    ranks = [0.0] * len(p)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and p[order[j + 1]] == p[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # rangos 1-based, empates promediados
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    sum_pos = sum(r for r, yi in zip(ranks, y) if yi == 1)
    n_pos, n_neg = len(pos), len(neg)
    return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _calendar(samples: list[Sample]) -> dict[str, int]:
    """{fecha iso10: posición en el calendario común}.

    El purge y el embargo se cuentan en **ruedas**, no en días corridos: 20 días
    hábiles son 28 corridos en el caso feliz y más si hay feriados, y aproximarlo
    dejaría entrar muestras contaminadas alrededor de cada fin de año.
    """
    dates = sorted({s.date for s in samples})
    return {d: i for i, d in enumerate(dates)}


def _split_train(
    samples: list[Sample],
    cutoff_date: str,
    cal: dict[str, int],
    *,
    label_days: int,
    embargo_days: int,
) -> tuple[list[Sample], int]:
    """Muestras entrenables antes de ``cutoff_date``, ya purgadas.

    Se descarta toda muestra cuya **ventana de etiqueta** (``label_days`` ruedas)
    llegue a menos de ``embargo_days`` del corte. Devuelve ``(train, n_purged)``.
    """
    cut = cal.get(cutoff_date)
    if cut is None:
        # El corte puede caer en un día sin ninguna señal BUY: se usa la primera
        # fecha del calendario que lo alcanza.
        later = [i for d, i in cal.items() if d >= cutoff_date]
        cut = min(later) if later else len(cal)
    horizon = label_days + embargo_days
    train, purged = [], 0
    for s in samples:
        if s.date >= cutoff_date:
            continue
        pos = cal.get(s.date)
        if pos is None or pos + horizon >= cut:
            purged += 1
            continue
        train.append(s)
    return train, purged


def _fit_predict(
    train: list[Sample], test: list[Sample]
) -> tuple[list[float] | None, bool, int]:
    """Entrena sobre ``train`` y puntúa ``test``. ``(proba, calibrada, n_calib)``.

    Arquitectura: exactamente ``ml_signals._make_raw_xgb()`` — **sin tunear
    ningún hiperparámetro**. Usar la misma arquitectura que el baseline aísla la
    variable bajo estudio (la pregunta nueva + el pooling); tunear sería un sweep
    sobre la misma muestra y encarecería el DSR de todos los brazos.
    """
    from analysis.ml_signals import _build_calibrator, _make_raw_xgb

    X = np.asarray([s.features for s in train], dtype=float)
    y = np.asarray([s.label for s in train], dtype=int)
    Xt = np.asarray([s.features for s in test], dtype=float)
    if X.size == 0 or Xt.size == 0 or len(set(y.tolist())) < 2:
        return None, False, 0

    # Cola temporal reservada para la isotónica. ``train`` ya viene ordenado por
    # fecha, así que el corte es cronológico. Entre el ajuste y la calibración se
    # deja el mismo hueco de purge que contra el test: la ventana de etiqueta de
    # las últimas muestras de ajuste se solapa con las primeras de calibración.
    n = len(train)
    n_calib = int(n * CALIB_FRACTION)
    gap = MAX_DAYS + EMBARGO_DAYS
    n_fit = max(0, n - n_calib - gap)

    use_calib = n_calib >= MIN_CALIB_SAMPLES and n_fit >= MIN_CALIB_SAMPLES
    if use_calib:
        X_fit, y_fit = X[:n_fit], y[:n_fit]
        X_cal, y_cal = X[n - n_calib:], y[n - n_calib:]
        use_calib = len(set(y_fit.tolist())) >= 2 and len(set(y_cal.tolist())) >= 2
    if not use_calib:
        X_fit, y_fit = X, y

    model = _make_raw_xgb()
    model.fit(X_fit, y_fit)

    if use_calib:
        try:
            calibrated = _build_calibrator(model, "prefit")
            calibrated.fit(X_cal, y_cal)
            return [float(v) for v in calibrated.predict_proba(Xt)[:, 1]], True, len(X_cal)
        except Exception as exc:  # la isotónica puede fallar con clases degeneradas
            log.debug("calibración isotónica falló (%s) — se usa el modelo crudo", exc)

    return [float(v) for v in model.predict_proba(Xt)[:, 1]], False, 0


def walkforward_oof(
    dataset: Dataset,
    *,
    min_train_years: int = MIN_TRAIN_YEARS,
    label_days: int = MAX_DAYS,
    embargo_days: int = EMBARGO_DAYS,
) -> OOFResult:
    """Predicciones estrictamente out-of-sample, año calendario por año calendario.

    Protocolo (§5, congelado): ventana de entrenamiento **expandiendo** — para el
    año ``Y`` se entrena con todo lo anterior a ``Y-01-01`` (purgado y con
    embargo) y se puntúa ``Y``. El primer año de test es el ``min_train_years+1``
    de la muestra. **Sin re-entrenamiento intra-año** y sin ninguna decisión
    tomada mirando el resultado del test.
    """
    res = OOFResult()
    samples = sorted(dataset.samples, key=lambda s: (s.date, s.ticker))
    if not samples:
        return res

    cal = _calendar(samples)
    years = sorted({int(s.date[:4]) for s in samples})
    if len(years) <= min_train_years:
        log.warning("solo %d años en la muestra: no alcanza para %d de entrenamiento",
                    len(years), min_train_years)
        return res

    for test_year in years[min_train_years:]:
        cutoff = f"{test_year}-01-01"
        test = [s for s in samples if int(s.date[:4]) == test_year]
        train, n_purged = _split_train(
            samples, cutoff, cal, label_days=label_days, embargo_days=embargo_days,
        )
        if not train or not test:
            res.n_skipped_folds += 1
            continue

        proba, calibrated, n_calib = _fit_predict(train, test)
        if proba is None:
            res.n_skipped_folds += 1
            continue

        for s, p in zip(test, proba):
            res.proba[(s.ticker, s.date)] = p

        auc = roc_auc([s.label for s in test], proba)
        res.folds.append(FoldReport(
            test_year=test_year,
            n_train=len(train), n_purged=n_purged, n_calib=n_calib, n_test=len(test),
            train_base_rate=sum(s.label for s in train) / len(train),
            test_base_rate=sum(s.label for s in test) / len(test),
            calibrated=calibrated, auc=auc,
        ))

    return res


def cross_sectional_percentile(values: dict[str, float | None]) -> dict[str, float]:
    """Percentil dentro del día. Presentes en ``(0, 1]``; ausentes en ``0.0``.

    Lo usa el brazo ``F1_mom121``: el momentum crudo no es comparable entre
    nombres con volatilidades distintas, y lo que decide un ranking es la
    posición relativa del día, no el nivel.

    El ``0.0`` queda **reservado para los ausentes** (``None`` o no finito) y los
    presentes arrancan en ``1/n``. Con la fórmula ingenua ``rank/(n−1)`` el peor
    candidato *con* dato empataba en 0.0 con los que no tienen dato, y el
    desempate alfabético del simulador podía meter a un candidato sin momentum
    por delante de uno con el peor momentum del día. La ausencia de dato no puede
    valer lo mismo que un dato malo.
    """
    present = {k: v for k, v in values.items() if v is not None and math.isfinite(v)}
    out = {k: 0.0 for k in values}
    if not present:
        return out
    ordered = sorted(present.items(), key=lambda kv: kv[1])
    n = len(ordered)
    for rank, (k, _) in enumerate(ordered):
        out[k] = (rank + 1) / n
    return out
