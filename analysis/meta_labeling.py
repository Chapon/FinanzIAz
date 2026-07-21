"""
Etiquetado triple-barrera y features pooled — **Tarea 9** del backlog.

Pre-registro con todo congelado (etiqueta, features, protocolo, brazos y
kill-criteria): ``docs/meta_labeling_t9_2026-07-21.md``. Este módulo implementa
exactamente lo que ese doc fijó, ni más ni menos.

Qué resuelve
------------
Hoy el ``buy_score`` que elige *qué* nombres entran es la ``ml_probability`` de
``analyze()``: un XGBoost **por ticker**, entrenado dentro del scan, sobre la
etiqueta ``close[t+5] > close[t]``. Val sets de ~40 muestras, gap train/val
99/55, y ``corr(score, fwd5) ≈ −0.08`` (n=27).

Acá se cambia **la pregunta**: dado un BUY primario, *¿toca el take-profit antes
que el stop?* — la misma triple barrera que el engine ya opera. Y se entrena
**pooled** sobre los 41 tickers juntos en vez de 41 modelos con val sets de 40.

Es lógica pura sobre ``list[Bar]`` / ``DataFrame``: sin red, sin DB, sin tocar el
engine. Nada de este módulo está cableado a decisiones — la tarea 9 lo valida
primero (regla 3 de ``CLAUDE.md``: display antes que sizing).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from analysis.exit_replay import Bar, atr_series

# ── Parámetros de la barrera (§3 del pre-registro — CONGELADOS) ──────────────
# Son los valores **vivos** del engine (``AtrParams``), no elegidos por
# performance: el stop 2.0 fue re-confirmado NO-SHIP con poder en A1 (n=4674,
# PBO=0.004) y el TP 4.0 es el que opera hoy. El horizonte 20 es el ``cap_days``
# del harness, que además es el mismo N de la barrera vertical que la tarea 13
# (ENT1) usará para su time stop — se elige una vez y sirve para las dos.
STOP_MULT = 2.0
TP_MULT = 4.0
MAX_DAYS = 20
ATR_PERIOD = 14

# Feature order — fijo, para que el modelo entrenado y el que puntúa vean las
# mismas columnas en el mismo orden aunque un ticker tenga NaNs distintos.
FEATURE_COLUMNS: list[str] = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d",
    "rsi", "rsi_delta5",
    "macd_hist", "macd_hist_chg",
    "bb_position", "bb_width",
    "volume_ratio",
    "volatility_20",
    "price_sma20", "price_sma50",
    "atr_rel",
]


# ── §3 · La etiqueta ────────────────────────────────────────────────────────


def triple_barrier_label(
    bars: list[Bar],
    entry_idx: int,
    atrs: list[float | None],
    *,
    stop_mult: float = STOP_MULT,
    tp_mult: float = TP_MULT,
    max_days: int = MAX_DAYS,
) -> int | None:
    """``1`` si toca el TP antes que el stop; ``0`` si no; ``None`` si no se puede etiquetar.

    Cuatro decisiones del pre-registro, implementadas literalmente:

    1. **Entrada al close** de la barra de la señal — es donde entra
       ``replay_cycle`` y donde entra el engine (scan EOD).
    2. **Las barreras se evalúan sobre el CLOSE**, no sobre High/Low. El engine
       es un scanner de fin de día: no puede actuar sobre un toque intradía que
       revierte antes del cierre. Etiquetar con High/Low mediría una capacidad
       que el sistema no tiene y inflaría la tasa de ``y=1``.
    3. **El trailing no participa**: la barrera es stop duro / TP / tiempo. El
       trailing es política de ejecución (path-dependent) y ensuciaría el target.
       El simulador sí lo usa — el target se mantiene limpio, la evaluación no se
       ablanda.
    4. **Timeout cuenta como 0**: con ``max_positions=5``, un candidato que en 20
       ruedas no llegó a ningún lado es un slot desperdiciado.

    Devuelve ``None`` (muestra descartada, no imputada) cuando el ATR no es
    utilizable o cuando **no hay 20 ruedas completas de futuro**. Etiquetar con
    una ventana truncada mezclaría dos poblaciones distintas.
    """
    n = len(bars)
    if entry_idx < 0 or entry_idx >= n:
        return None
    # La ventana tiene que estar completa: sin esto, las entradas del final de la
    # serie quedarían sistemáticamente sesgadas hacia el timeout (=0).
    if entry_idx + max_days > n - 1:
        return None

    entry = bars[entry_idx][4]
    atr = atrs[entry_idx] if entry_idx < len(atrs) else None
    if atr is None or entry is None:
        return None
    if not math.isfinite(entry) or not math.isfinite(atr) or entry <= 0 or atr <= 0:
        return None

    stop = entry - stop_mult * atr
    tp = entry + tp_mult * atr

    for i in range(entry_idx + 1, entry_idx + max_days + 1):
        close_i = bars[i][4]
        if not math.isfinite(close_i):
            continue
        # Orden stop → TP: un close no puede estar por debajo del stop y por
        # encima del TP a la vez, así que el orden no cambia ningún resultado.
        # Se deja explícito igual para espejar ``atr_exit_decision``.
        if stop > 0 and close_i <= stop:
            return 0
        if close_i >= tp:
            return 1
    return 0  # barrera vertical


# ── §4 · Las features ───────────────────────────────────────────────────────


def _atr_rel(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """ATR(14) / close — la escala de la barrera relativa al precio.

    Es la feature **agregada** por el pre-registro: sin ella el modelo pooled no
    tiene forma de saber que un mismo ``ret_5d`` significa cosas distintas en un
    nombre con 1% de ATR relativo y en uno con 5%, que es justo lo que decide si
    la barrera de 4×ATR es alcanzable en 20 ruedas.
    """
    from analysis.atr import compute_atr_series

    close = df["Close"].squeeze()
    atr = compute_atr_series(df, period)
    if atr is None:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return atr / close.replace(0, np.nan)


def build_pooled_features(df: pd.DataFrame) -> pd.DataFrame:
    """Features PIT comparables entre tickers (§4 del pre-registro).

    Parte de ``ml_signals._build_features`` (ya testeado, PIT por construcción)
    y aplica las **dos correcciones obligatorias para poder poolear**:

    * ``macd_hist`` y ``macd_hist_chg`` se dividen por el close. Vienen en
      **unidades de precio**, así que un histograma de 0.8 es enorme en F (~$12)
      e insignificante en AAPL (~$200). Poolear sin normalizar haría que el
      modelo aprendiera el nivel de precio del ticker, no el momentum.
    * Se agrega ``atr_rel``.

    El resto ya es adimensional (log-retornos, RSI, ratios, vol anualizada).
    Devuelve siempre las columnas de ``FEATURE_COLUMNS`` en ese orden; las que el
    frame no pueda calcular (historia corta) quedan en NaN.
    """
    from analysis.ml_signals import _build_features

    feat = _build_features(df)
    close = df["Close"].squeeze().replace(0, np.nan)

    for col in ("macd_hist", "macd_hist_chg"):
        if col in feat.columns:
            feat[col] = feat[col] / close

    feat["atr_rel"] = _atr_rel(df)

    for col in FEATURE_COLUMNS:
        if col not in feat.columns:
            feat[col] = np.nan
    return feat[FEATURE_COLUMNS]


def momentum_12_1(close: pd.Series, *, long_bars: int = 252, skip_bars: int = 21) -> pd.Series:
    """Momentum 12-1: retorno de los 12 meses previos **excluyendo el último mes**.

    El estándar académico (Jegadeesh-Titman): se saltea el mes más reciente para
    esquivar la reversión de corto plazo. Es el brazo ``F1_mom121`` del
    pre-registro, y **no se barre** — no se prueban 6-1, 9-1 ni 12-2.

    PIT por construcción: en la barra ``t`` solo mira ``t−21`` y ``t−252``.
    """
    c = close.astype(float)
    past = c.shift(long_bars)
    recent = c.shift(skip_bars)
    return (recent / past.replace(0, np.nan)) - 1.0


# ── Armado del dataset ──────────────────────────────────────────────────────


@dataclass
class Sample:
    """Una barra con señal primaria BUY, etiquetada y con sus features."""

    ticker: str
    date: str          # iso10 de la barra de la señal (= fecha de entrada)
    bar_idx: int       # índice en la serie del ticker
    label: int         # 1 = TP antes que stop · 0 = stop primero o timeout
    features: np.ndarray
    buy_score: float | None = None   # ml_probability del artefacto PIT (brazo B1)
    mom121: float | None = None      # momentum 12-1 (brazo F1)


@dataclass
class Dataset:
    samples: list[Sample] = field(default_factory=list)
    n_dropped_no_label: int = 0
    n_dropped_nan_features: int = 0

    @property
    def base_rate(self) -> float:
        """Tasa de ``y=1`` observada. Con TP a 4×ATR y stop a 2×ATR se espera
        que sea minoritaria: el TP está al doble de distancia."""
        if not self.samples:
            return 0.0
        return sum(s.label for s in self.samples) / len(self.samples)


def build_dataset(
    bars_by: dict[str, list[Bar]],
    sigs_by: dict[str, dict],
    frames_by: dict[str, pd.DataFrame],
    *,
    probs_by: dict[str, dict] | None = None,
    warmup: int = 250,
    stop_mult: float = STOP_MULT,
    tp_mult: float = TP_MULT,
    max_days: int = MAX_DAYS,
) -> Dataset:
    """Arma el dataset pooled sobre **todas** las barras con señal primaria BUY.

    Sin el ``spacing`` de las tareas 7 y 8: acá la competencia entre candidatos
    del mismo día por un slot **es** el fenómeno a medir, y espaciar las entradas
    lo borraría (§8 del pre-registro).

    ``sigs_by`` es ``{ticker: {iso10: "BUY"|"SELL"|"HOLD"}}`` y ``probs_by`` es
    ``{ticker: {iso10: ml_probability}}``, los dos del artefacto PIT.
    """
    ds = Dataset()
    for ticker, bars in sorted(bars_by.items()):
        sigs = sigs_by.get(ticker) or {}
        probs = (probs_by or {}).get(ticker) or {}
        df = frames_by.get(ticker)
        if df is None or df.empty:
            continue

        atrs = atr_series(bars, ATR_PERIOD)
        feats = build_pooled_features(df)
        mom = momentum_12_1(df["Close"].squeeze())
        # El frame y la lista de barras comparten fechas, pero ``load_bars_and_signals``
        # descarta barras con OHLC no finito → los índices pueden desalinearse.
        # Se indexa por fecha, que es la única clave común confiable.
        feat_by_date = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
        feat_values = feats.to_numpy(dtype=float)
        mom_values = mom.to_numpy(dtype=float)

        for idx in range(warmup, len(bars)):
            date = bars[idx][0]
            if sigs.get(date) != "BUY":
                continue
            label = triple_barrier_label(
                bars, idx, atrs,
                stop_mult=stop_mult, tp_mult=tp_mult, max_days=max_days,
            )
            if label is None:
                ds.n_dropped_no_label += 1
                continue
            fi = feat_by_date.get(date)
            if fi is None:
                ds.n_dropped_nan_features += 1
                continue
            row = feat_values[fi]
            if not np.all(np.isfinite(row)):
                ds.n_dropped_nan_features += 1
                continue
            prob = probs.get(date)
            m = mom_values[fi]
            ds.samples.append(Sample(
                ticker=ticker, date=date, bar_idx=idx, label=label,
                features=row,
                buy_score=None if prob is None else float(prob),
                mom121=None if not math.isfinite(m) else float(m),
            ))

    ds.samples.sort(key=lambda s: (s.date, s.ticker))
    return ds
