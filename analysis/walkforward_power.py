"""
Walk-forward power harness — backlog E4 (poder estadístico, enabler transversal).

Motiva: los harness de A1 (stops ATR) y la Tarea 3 (buy_score) sólo replayean los
42 round-trips reales de la cuenta viva → n=6 salidas ATR limpias y n=27 pares
score↔fwd5. Con esas muestras las decisiones están **sub-potenciadas** (ver
``docs/effectiveness_deep_analysis_2026-06-30.md`` §6). E4 genera el poder
estadístico faltante: un **sampler point-in-time** sobre el cache 10y que emite
cientos de entradas sintéticas no-solapadas, etiquetadas por régimen (incluyendo
ventanas de stress 2018Q4 / COVID 2020 / bear 2022), de las que salen:

  1. **A1 potenciado** — por cada entrada, replay stop-vs-no-stop reusando el
     motor ATR puro de ``analysis.exit_replay``. Δret por régimen con n>>6.
  2. **Tarea 3 potenciado** — corr(score, fwd) pooled + IC cross-sectional, con
     n>>27.
  3. **Power analysis** — N necesario para 80% de potencia (Fisher-z para corr,
     d de Cohen para el Δret pareado) y la potencia lograda con el N generado.

**Enabler puro:** este módulo NO cambia decisiones de trading; sólo mide poder.
La re-decisión de A1 y la Tarea 3 son tareas propias con estos datos.

Todo acá es **lógica pura** (stdlib + numpy, SIN red): las barras entran por un
``bar_loader`` inyectable y el buy_score por un ``score_fn`` inyectable, así los
tests corren offline. El runner CLI (con ``analyze()`` PIT + red) vive en
``scripts/run_walkforward_power.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from statistics import NormalDist
from typing import Callable

import numpy as np

from analysis.exit_replay import (
    AtrParams,
    Bar,
    BarLoader,
    _atr_trigger_level,
    _exit_fill_price,
    atr_exit,
    atr_series,
)

# ── Regímenes de mercado (rangos de fecha, tag por barra) ────────────────────

# score_fn(ticker, bars_hasta_t)  ->  buy_score en [0,1] (o None si no computable).
# ``bars_hasta_t`` incluye la barra de entrada (índice t) y NADA posterior (PIT).
ScoreFn = Callable[[str, "list[Bar]"], "float | None"]


@dataclass(frozen=True)
class Regime:
    name: str
    start: str  # iso10 inclusive
    end: str    # iso10 inclusive


# Ventanas de stress históricas (drawdown real) para evaluar guardrails fuera del
# régimen de rebote que domina la cuenta viva. Todo lo que no cae acá = bull_normal.
STRESS_REGIMES: list[Regime] = [
    Regime("stress_2018q4", "2018-10-01", "2018-12-31"),
    Regime("stress_covid_2020", "2020-02-15", "2020-04-30"),
    Regime("stress_bear_2022", "2022-01-01", "2022-10-31"),
]

BULL_NORMAL = "bull_normal"


def regime_for_date(date_iso10: str, regimes: list[Regime] = STRESS_REGIMES) -> str:
    """Tag de régimen para una fecha iso10. Primer rango que la contiene, o bull_normal."""
    for r in regimes:
        if r.start <= date_iso10 <= r.end:
            return r.name
    return BULL_NORMAL


def regime_window_returns(
    pairs: "list[tuple[str, float]]",
    regimes: list[Regime] = STRESS_REGIMES,
) -> dict[str, float]:
    """Retorno **compuesto de la cartera** durante los días de cada régimen.

    ``pairs`` son ``(fecha_iso10, retorno_diario_de_equity)`` — la serie de la
    curva de equity, no de los trades. Los días sin posición abierta entran con
    su retorno real (0 si la cartera está toda en cash), que es justamente el
    punto.

    **Por qué no se mide por trade** (regla congelada en el pre-registro de la
    T38 §4 y reusada por la T39 C5): un brazo que deja de operar en el bear
    tiene ~cero trades ahí, así que el Δ del retorno *por trade* es vacío y el
    brazo **pasaría el criterio sin hacer nada**. A nivel cartera, "no operar"
    se **premia** si evita la caída y se **castiga** si el costo es perderse la
    recuperación.

    Devuelve ``{nombre_de_régimen: retorno}`` con una entrada por régimen de
    ``regimes`` más ``bull_normal``; los regímenes sin días en la muestra dan
    ``0.0``.
    """
    growth: dict[str, float] = {BULL_NORMAL: 1.0}
    for r in regimes:
        growth[r.name] = 1.0
    for date_iso10, ret in pairs:
        growth[regime_for_date(date_iso10, regimes)] *= 1.0 + float(ret)
    return {name: g - 1.0 for name, g in growth.items()}


# ── Muestra de entrada sintética ─────────────────────────────────────────────


@dataclass
class EntrySample:
    """Una entrada candidata en la grilla PIT.

    ``score`` lo completa el runner con ``analyze().ml_probability`` (caro); el
    sampler puro lo deja en None. ``fwd5``/``fwd20`` son retornos por-share
    (close-a-close) desde la entrada; None si no hay barras suficientes adelante.

    ``label_end`` es la fecha iso10 en la que se cierra la ventana de etiquetado
    (``fwd_long`` barras después de la entrada); el CPCV lo usa para purgar
    solapamientos de etiqueta entre train y test (López de Prado). None si la
    ventana se sale del rango.
    """

    ticker: str
    entry_date: str      # iso10
    entry_idx: int       # índice en las barras de ese ticker
    entry_price: float   # close en la entrada
    regime: str
    fwd5: float | None
    fwd20: float | None
    score: float | None = None
    label_end: str | None = None


def build_entry_grid(
    bars: list[Bar],
    ticker: str,
    *,
    spacing: int = 20,
    warmup: int = 250,
    fwd_short: int = 5,
    fwd_long: int = 20,
    regimes: list[Regime] = STRESS_REGIMES,
) -> list[EntrySample]:
    """Grilla de entradas no-solapadas para un ticker.

    Arranca en ``warmup`` (≥200 para que ``analyze()``/SMA200/XGBoost sean válidos
    y A1+T3 compartan la misma grilla) y avanza de a ``spacing`` barras. Para que
    las ventanas forward de entradas consecutivas del mismo ticker NO se solapen
    (independencia temporal), pedí ``spacing >= fwd_long``; con spacing menor las
    muestras quedan autocorrelacionadas y el N pooled sobreestima el poder.
    """
    n = len(bars)
    out: list[EntrySample] = []
    if n == 0:
        return out
    start = max(warmup, 0)
    for idx in range(start, n, max(1, spacing)):
        entry_price = bars[idx][4]
        if entry_price is None or not math.isfinite(entry_price) or entry_price <= 0:
            continue

        def _fwd(h: int) -> float | None:
            j = idx + h
            if j >= n:
                return None
            fut = bars[j][4]
            if fut is None or not math.isfinite(fut) or fut <= 0:
                return None
            return fut / entry_price - 1.0

        label_end_idx = idx + fwd_long
        label_end = bars[label_end_idx][0] if label_end_idx < n else None
        out.append(
            EntrySample(
                ticker=ticker,
                entry_date=bars[idx][0],
                entry_idx=idx,
                entry_price=entry_price,
                regime=regime_for_date(bars[idx][0], regimes),
                fwd5=_fwd(fwd_short),
                fwd20=_fwd(fwd_long),
                label_end=label_end,
            )
        )
    return out


def sample_universe(
    data: dict[str, list[Bar]],
    *,
    spacing: int = 20,
    warmup: int = 250,
    fwd_short: int = 5,
    fwd_long: int = 20,
    regimes: list[Regime] = STRESS_REGIMES,
) -> list[EntrySample]:
    """Construye la grilla de entradas sobre todo el universo (concatenada)."""
    out: list[EntrySample] = []
    for ticker, bars in data.items():
        out.extend(
            build_entry_grid(
                bars, ticker, spacing=spacing, warmup=warmup,
                fwd_short=fwd_short, fwd_long=fwd_long, regimes=regimes,
            )
        )
    return out


# ── A1: replay stop-vs-no-stop desde una entrada sintética ───────────────────


@dataclass
class StopReplayOutcome:
    entry: EntrySample
    ret_with_stops: float        # retorno por-share bajo el ATR baseline
    ret_no_stops: float          # retorno por-share manteniendo hasta cap sin stops
    exit_reason_with_stops: str
    exit_days_with_stops: int    # barras desde la entrada hasta el exit con stops

    @property
    def delta(self) -> float:
        """no_stops − with_stops. Positivo ⇒ sacar los stops ayudó (framing A1)."""
        return self.ret_no_stops - self.ret_with_stops


# Params "sin stops": stop/trail/tp desactivados ⇒ siempre llega al cap.
_NO_STOPS = AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False)


def replay_from_entry(
    bars: list[Bar],
    entry_idx: int,
    *,
    cap_days: int,
    atr_p: AtrParams,
) -> tuple[int, float, str] | None:
    """Mantiene una posición nueva desde ``entry_idx`` (entrada al close) hasta
    que dispare un exit ATR o se alcance ``cap_days``. Devuelve
    ``(exit_idx, exit_price, exit_reason)`` o None si no hay barra posterior.

    Mismo orden intradía que el engine y ``exit_replay.replay_atr_recalib``: cada
    día se evalúa el ATR con el HWM *previo* al close, después se actualiza el HWM.
    El HWM se seedea en el entry (avg_cost = close de entrada) y la primera
    evaluación es el día siguiente (la posición recién abrió en ``entry_idx``).
    Los exits ATR llenan con el modelo gap/touch; el cap llena al close.
    """
    n = len(bars)
    if entry_idx >= n - 1:
        return None  # sin día siguiente
    avg_cost = bars[entry_idx][4]
    if avg_cost is None or not math.isfinite(avg_cost) or avg_cost <= 0:
        return None

    atrs = atr_series(bars, atr_p.period)
    hwm = avg_cost
    last_idx = min(entry_idx + cap_days, n - 1)

    for i in range(entry_idx + 1, last_idx + 1):
        close_i = bars[i][4]
        a = atrs[i]
        fired = None
        if a is not None:
            fired = atr_exit(
                current_price=close_i,
                avg_cost=avg_cost,
                high_water_mark=hwm,
                atr_value=a,
                p=atr_p,
            )
        if fired is not None:
            level = _atr_trigger_level(
                fired, avg_cost=avg_cost, hwm=hwm, atr_value=a, p=atr_p
            )
            return (i, _exit_fill_price(fired, level, bars[i]), fired)
        if i == last_idx:
            return (i, close_i, "cap_reached")
        hwm = max(hwm, close_i)

    # inalcanzable (last_idx siempre cierra), pero cerramos por las dudas
    return (last_idx, bars[last_idx][4], "cap_reached")


def replay_stop_vs_nostop(
    entries: list[EntrySample],
    bar_loader: BarLoader,
    *,
    cap_days: int = 20,
    atr_p: AtrParams = AtrParams(),
) -> list[StopReplayOutcome]:
    """Por cada entrada, retorno por-share bajo el ATR baseline vs mantener hasta
    cap sin stops. Entradas sin barra posterior se saltean (no aportan muestra)."""
    out: list[StopReplayOutcome] = []
    for e in entries:
        bars = bar_loader(e.ticker)
        if not bars:
            continue
        with_stops = replay_from_entry(bars, e.entry_idx, cap_days=cap_days, atr_p=atr_p)
        no_stops = replay_from_entry(bars, e.entry_idx, cap_days=cap_days, atr_p=_NO_STOPS)
        if with_stops is None or no_stops is None:
            continue
        exit_idx_ws, exit_px_ws, reason_ws = with_stops
        _, exit_px_ns, _ = no_stops
        out.append(
            StopReplayOutcome(
                entry=e,
                ret_with_stops=exit_px_ws / e.entry_price - 1.0,
                ret_no_stops=exit_px_ns / e.entry_price - 1.0,
                exit_reason_with_stops=reason_ws,
                exit_days_with_stops=exit_idx_ws - e.entry_idx,
            )
        )
    return out


# ── Estadística de correlación (Tarea 3) ─────────────────────────────────────


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson r; None si n<3 o alguna serie es constante (corr indefinida)."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    a = np.asarray(xs, dtype=float)
    b = np.asarray(ys, dtype=float)
    if a.std() == 0 or b.std() == 0:
        return None
    r = float(np.corrcoef(a, b)[0, 1])
    return r if math.isfinite(r) else None


def _pairs(entries: list[EntrySample], horizon: str) -> tuple[list[float], list[float]]:
    """Pares (score, fwd) válidos (ambos no-None) para el horizonte pedido."""
    xs: list[float] = []
    ys: list[float] = []
    for e in entries:
        fwd = e.fwd5 if horizon == "fwd5" else e.fwd20
        if e.score is None or fwd is None:
            continue
        xs.append(float(e.score))
        ys.append(float(fwd))
    return xs, ys


@dataclass
class CorrResult:
    horizon: str
    n: int
    corr: float | None
    # |ρ| detectable con este n a 80% de potencia (α=0.05, dos colas)
    detectable_rho: float


def pooled_correlation(entries: list[EntrySample], horizon: str = "fwd5") -> CorrResult:
    xs, ys = _pairs(entries, horizon)
    return CorrResult(
        horizon=horizon,
        n=len(xs),
        corr=pearson(xs, ys),
        detectable_rho=detectable_correlation(len(xs)),
    )


@dataclass
class ICResult:
    """Information Coefficient cross-sectional: corr(score, fwd) por fecha,
    promediado sobre fechas. Una obs por fecha ⇒ robusto al clustering temporal."""

    horizon: str
    n_dates: int
    mean_ic: float | None
    std_ic: float | None
    t_stat: float | None       # mean_ic / (std_ic / sqrt(n_dates))
    per_date_ic: list[float] = field(default_factory=list)


def cross_sectional_ic(
    entries: list[EntrySample], *, horizon: str = "fwd5", min_names: int = 5
) -> ICResult:
    """Agrupa por ``entry_date`` y corre corr(score, fwd) entre nombres en cada
    fecha con ≥ ``min_names`` observaciones; devuelve el IC medio y su t-stat."""
    by_date: dict[str, list[EntrySample]] = {}
    for e in entries:
        by_date.setdefault(e.entry_date, []).append(e)

    ics: list[float] = []
    for _date, group in sorted(by_date.items()):
        xs, ys = _pairs(group, horizon)
        if len(xs) < min_names:
            continue
        r = pearson(xs, ys)
        if r is not None:
            ics.append(r)

    if not ics:
        return ICResult(horizon=horizon, n_dates=0, mean_ic=None, std_ic=None, t_stat=None)
    arr = np.asarray(ics, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    t = (mean / (std / math.sqrt(len(arr)))) if std > 0 else None
    return ICResult(
        horizon=horizon, n_dates=len(ics), mean_ic=mean, std_ic=std,
        t_stat=t, per_date_ic=ics,
    )


# ── Power analysis (Fisher-z para corr, d de Cohen para el Δret pareado) ─────


def _z(p: float) -> float:
    return NormalDist().inv_cdf(p)


def n_for_correlation(rho: float, *, alpha: float = 0.05, power: float = 0.80) -> float:
    """N para detectar |ρ| a la potencia dada (α dos colas), vía Fisher-z."""
    if rho == 0:
        return math.inf
    c = math.atanh(min(abs(rho), 0.999999))
    z = _z(1 - alpha / 2) + _z(power)
    return math.ceil((z / c) ** 2 + 3)


def detectable_correlation(n: int, *, alpha: float = 0.05, power: float = 0.80) -> float:
    """|ρ| más chico detectable con ``n`` muestras a la potencia dada (Fisher-z)."""
    if n <= 3:
        return 1.0
    z = _z(1 - alpha / 2) + _z(power)
    return float(math.tanh(z / math.sqrt(n - 3)))


def cohens_d_paired(deltas: list[float]) -> float | None:
    """d = mean(Δ) / std(Δ) (efecto estandarizado del test pareado)."""
    if len(deltas) < 2:
        return None
    arr = np.asarray(deltas, dtype=float)
    sd = float(arr.std(ddof=1))
    if sd == 0:
        return None
    return float(arr.mean()) / sd


def n_for_mean_effect(d: float, *, alpha: float = 0.05, power: float = 0.80) -> float:
    """N para detectar un efecto estandarizado ``d`` (test pareado, aprox normal)."""
    if d == 0:
        return math.inf
    z = _z(1 - alpha / 2) + _z(power)
    return math.ceil((z / abs(d)) ** 2)


def achieved_power_mean(d: float, n: int, *, alpha: float = 0.05) -> float:
    """Potencia lograda para un test pareado dado el efecto ``d`` y ``n``."""
    if n < 2 or d == 0:
        return 0.0
    z_a = _z(1 - alpha / 2)
    ncp = abs(d) * math.sqrt(n)
    nd = NormalDist()
    return float(1 - nd.cdf(z_a - ncp) + nd.cdf(-z_a - ncp))


# ── Agregados por régimen (para el doc) ──────────────────────────────────────


@dataclass
class RegimeStopStats:
    regime: str
    n: int
    mean_ret_with_stops: float | None
    mean_ret_no_stops: float | None
    mean_delta: float | None       # no_stops − with_stops
    d: float | None                # Cohen del Δ pareado
    achieved_power: float | None   # potencia del test pareado con este n
    loo_worst_delta: float | None  # mean_delta sacando el ticker de ±mayor aporte


def _mean(xs: list[float]) -> float | None:
    return float(np.mean(xs)) if xs else None


def stop_stats_by_regime(
    outcomes: list[StopReplayOutcome],
) -> dict[str, RegimeStopStats]:
    """Estadística A1 por régimen: retornos medios stop/no-stop, Δ, d y potencia.

    ``loo_worst_delta`` = el mean_delta recomputado sacando **todas** las
    muestras del ticker que más aporta al Δ agregado (leave-one-ticker-out), para
    chequear que el efecto no cuelgue de un solo nombre (misma higiene que A1).
    """
    by_reg: dict[str, list[StopReplayOutcome]] = {"all": list(outcomes)}
    for o in outcomes:
        by_reg.setdefault(o.entry.regime, []).append(o)

    stats: dict[str, RegimeStopStats] = {}
    for regime, group in by_reg.items():
        deltas = [o.delta for o in group]
        d = cohens_d_paired(deltas)
        stats[regime] = RegimeStopStats(
            regime=regime,
            n=len(group),
            mean_ret_with_stops=_mean([o.ret_with_stops for o in group]),
            mean_ret_no_stops=_mean([o.ret_no_stops for o in group]),
            mean_delta=_mean(deltas),
            d=d,
            achieved_power=(achieved_power_mean(d, len(group)) if d is not None else None),
            loo_worst_delta=_leave_one_ticker_out_delta(group),
        )
    return stats


def _leave_one_ticker_out_delta(group: list[StopReplayOutcome]) -> float | None:
    """mean_delta sacando el ticker cuya suma de |Δ| es mayor."""
    if not group:
        return None
    contrib: dict[str, float] = {}
    for o in group:
        contrib[o.entry.ticker] = contrib.get(o.entry.ticker, 0.0) + abs(o.delta)
    if not contrib:
        return None
    worst = max(contrib, key=lambda k: contrib[k])
    kept = [o.delta for o in group if o.entry.ticker != worst]
    return _mean(kept)


# ── CPCV (combinatorial purged CV) + DSR/PBO — ampliación E4 ──────────────────
#
# Motiva (research de predicción §7): la grilla por spacing da UNA estimación
# puntual del efecto; CPCV la vuelve una *distribución* sobre múltiples
# particiones train/test purgadas del mismo cache — más caminos independientes y
# menor probabilidad de backtest overfitting que un walk-forward simple. DSR/PBO
# son la defensa contra "la mejora que pasa es el mejor de N intentos por azar":
# PBO mide si el mejor config in-sample aguanta out-of-sample; DSR deflacta el
# Sharpe del ganador por el número de variantes probadas. Todo puro (numpy+stdlib).


def _iso_to_ord(d: str) -> int:
    return date.fromisoformat(d).toordinal()


def _merge_intervals(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Une [start,end] solapados/adyacentes en intervalos disjuntos ordenados."""
    if not spans:
        return []
    ordered = sorted(spans)
    merged = [ordered[0]]
    for s, e in ordered[1:]:
        ms, me = merged[-1]
        if s <= me:
            merged[-1] = (ms, max(me, e))
        else:
            merged.append((s, e))
    return merged


@dataclass(frozen=True)
class CPCVSplit:
    test_groups: tuple[int, ...]   # grupos temporales que forman el test
    train_idx: tuple[int, ...]     # posiciones (en la lista original) del train purgado
    test_idx: tuple[int, ...]      # posiciones del test


def entry_intervals(entries: list[EntrySample]) -> list[tuple[str, str]]:
    """Intervalo de etiqueta [entry_date, label_end] por entrada; si falta
    label_end se usa entry_date (ventana degenerada = punto)."""
    return [(e.entry_date, e.label_end or e.entry_date) for e in entries]


def cpcv_splits(
    intervals: list[tuple[str, str]],
    *,
    n_groups: int = 6,
    k_test: int = 2,
    embargo_days: int = 5,
) -> list[CPCVSplit]:
    """Combinatorial Purged CV (López de Prado). Ordena los samples por fecha de
    inicio, los reparte en ``n_groups`` bloques temporales contiguos, y por cada
    combinación de ``k_test`` grupos como test devuelve (train, test) con el train
    **purgado** (se sacan los samples cuya etiqueta [start,end] solapa la de algún
    test) y con **embargo** (el end del test se extiende ``embargo_days`` a la
    derecha antes de purgar, matando autocorrelación serial). Produce
    C(n_groups, k_test) splits; los índices son posiciones en ``intervals``.
    """
    n = len(intervals)
    if n == 0 or n_groups < 2 or not (1 <= k_test < n_groups) or n < n_groups:
        return []
    starts = [_iso_to_ord(s) for s, _ in intervals]
    ends = [_iso_to_ord(en) for _, en in intervals]
    order = sorted(range(n), key=lambda i: (starts[i], ends[i]))

    groups: list[list[int]] = []
    base, extra = divmod(n, n_groups)
    pos = 0
    for g in range(n_groups):
        size = base + (1 if g < extra else 0)
        groups.append(order[pos:pos + size])
        pos += size

    splits: list[CPCVSplit] = []
    all_idx = set(range(n))
    for combo in combinations(range(n_groups), k_test):
        test_idx = [i for g in combo for i in groups[g]]
        test_set = set(test_idx)
        merged = _merge_intervals([(starts[i], ends[i] + embargo_days) for i in test_idx])
        train_idx = [
            i for i in (all_idx - test_set)
            if not any(starts[i] <= me and ms <= ends[i] for ms, me in merged)
        ]
        splits.append(CPCVSplit(
            test_groups=combo,
            train_idx=tuple(sorted(train_idx)),
            test_idx=tuple(sorted(test_idx)),
        ))
    return splits


# ── Distribución del efecto A1 sobre los test sets de CPCV ────────────────────


@dataclass
class CPCVEffectResult:
    regime: str
    n_paths: int
    mean_delta: float | None       # promedio de los Δ medios por path
    std_delta: float | None        # dispersión entre paths (robustez temporal)
    frac_positive: float | None    # fracción de paths con Δ medio > 0
    per_path_delta: list[float] = field(default_factory=list)


def cpcv_effect_distribution(
    outcomes: list[StopReplayOutcome],
    *,
    regime: str = "all",
    n_groups: int = 6,
    k_test: int = 2,
    embargo_days: int = 5,
) -> CPCVEffectResult:
    """Distribución del Δ (no_stops − with_stops) sobre los test sets de CPCV,
    filtrando por régimen (o 'all'). Cada test set aporta un Δ medio; se reporta
    la dispersión y la fracción de paths con Δ>0 — un efecto real es estable a
    través de los bloques temporales, uno espurio cambia de signo."""
    filt = [o for o in outcomes if regime == "all" or o.entry.regime == regime]
    if len(filt) < n_groups:
        return CPCVEffectResult(regime, 0, None, None, None, [])
    intervals = entry_intervals([o.entry for o in filt])
    splits = cpcv_splits(intervals, n_groups=n_groups, k_test=k_test,
                         embargo_days=embargo_days)
    per_path: list[float] = []
    for sp in splits:
        m = _mean([filt[i].delta for i in sp.test_idx])
        if m is not None:
            per_path.append(m)
    if not per_path:
        return CPCVEffectResult(regime, 0, None, None, None, [])
    arr = np.asarray(per_path, dtype=float)
    return CPCVEffectResult(
        regime=regime,
        n_paths=len(per_path),
        mean_delta=float(arr.mean()),
        std_delta=float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        frac_positive=float(np.mean(arr > 0)),
        per_path_delta=per_path,
    )


# ── PBO vía CSCV (Bailey & López de Prado) ───────────────────────────────────


def _sharpe(xs: "list[float] | np.ndarray") -> float:
    """Sharpe por-observación (mean/std, SIN anualizar). std 0 ⇒ devuelve la media
    (config degenerado sin dispersión)."""
    a = np.asarray(xs, dtype=float)
    if a.size < 2:
        return 0.0
    sd = float(a.std(ddof=1))
    return float(a.mean() / sd) if sd > 0 else float(a.mean())


@dataclass
class PBOResult:
    n_configs: int
    n_splits: int
    n_combos: int
    pbo: float                                  # P(mejor-IS por debajo de la mediana OOS)
    mean_logit: float | None = None
    best_is_counts: dict[str, int] = field(default_factory=dict)


def pbo_cscv(perf_matrix: dict[str, "list[float]"], *, n_splits: int = 10) -> PBOResult:
    """Probability of Backtest Overfitting vía CSCV (Bailey & López de Prado 2017).

    ``perf_matrix`` = {config: serie de performance por-observación} (todas del
    mismo largo T, alineadas por observación). Parte las T obs en ``n_splits``
    bloques contiguos y, por cada forma de elegir n_splits/2 como in-sample (resto
    out-of-sample), toma el config con mejor Sharpe IS y mide su rango relativo
    OOS. PBO = fracción de combinaciones donde ese config quedó **por debajo de la
    mediana** OOS (logit λ ≤ 0). PBO ≈ 0.5 ⇒ selección puro ruido; PBO baja ⇒ el
    ganador aguanta fuera de muestra.
    """
    configs = list(perf_matrix.keys())
    N = len(configs)
    if N < 2:
        return PBOResult(N, 0, 0, float("nan"))
    T = len(perf_matrix[configs[0]])
    if any(len(perf_matrix[c]) != T for c in configs) or n_splits < 2 or T < n_splits:
        return PBOResult(N, n_splits, 0, float("nan"))
    if n_splits % 2:
        n_splits -= 1
    mat = {c: np.asarray(perf_matrix[c], dtype=float) for c in configs}
    bounds = np.linspace(0, T, n_splits + 1).astype(int)
    blocks = [np.arange(bounds[g], bounds[g + 1]) for g in range(n_splits)]

    logits: list[float] = []
    best_counts = {c: 0 for c in configs}
    for is_groups in combinations(range(n_splits), n_splits // 2):
        is_set = set(is_groups)
        is_idx = np.concatenate([blocks[g] for g in is_groups])
        oos_idx = np.concatenate([blocks[g] for g in range(n_splits) if g not in is_set])
        is_perf = {c: _sharpe(mat[c][is_idx]) for c in configs}
        oos_perf = {c: _sharpe(mat[c][oos_idx]) for c in configs}
        best = max(configs, key=lambda c: is_perf[c])
        best_counts[best] += 1
        worse = sum(1 for c in configs if oos_perf[c] < oos_perf[best])
        omega = min(max((worse + 0.5) / N, 1e-6), 1 - 1e-6)
        logits.append(math.log(omega / (1 - omega)))

    if not logits:
        return PBOResult(N, n_splits, 0, float("nan"), best_is_counts=best_counts)
    pbo = float(np.mean([1.0 if x <= 0 else 0.0 for x in logits]))
    return PBOResult(N, n_splits, len(logits), pbo,
                     mean_logit=float(np.mean(logits)), best_is_counts=best_counts)


# ── Deflated Sharpe Ratio (Bailey & López de Prado 2014) ─────────────────────


def _skew_kurt(xs: "list[float] | np.ndarray") -> tuple[float, float]:
    """Skew (γ3) y kurtosis de Pearson (γ4, normal=3) poblacionales."""
    a = np.asarray(xs, dtype=float)
    if a.size < 3:
        return 0.0, 3.0
    m = a.mean()
    s = a.std(ddof=0)
    if s == 0:
        return 0.0, 3.0
    z = (a - m) / s
    return float(np.mean(z ** 3)), float(np.mean(z ** 4))


@dataclass
class DSRResult:
    observed_sharpe: float           # por-observación (sin anualizar)
    n_trials: int
    n_obs: int
    expected_max_sharpe: float       # SR0: máximo esperado bajo el nulo
    deflated_sharpe: float           # P(SR verdadero > 0) tras deflactar
    prob_positive_raw: float         # PSR contra 0 sin deflactar (referencia)


def deflated_sharpe_ratio(
    trial_sharpes: "list[float]",
    *,
    n_obs: int,
    selected: float | None = None,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> DSRResult:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014).

    ``trial_sharpes`` = Sharpe por-observación (mean/std, SIN anualizar) de cada
    variante probada; ``selected`` = el Sharpe a defender (por defecto el máximo).
    Deflacta el umbral por el máximo esperado bajo el nulo dado el número de
    intentos y su dispersión, y devuelve P(Sharpe verdadero > 0). ``skew``/
    ``kurtosis`` son los momentos de los retornos del config elegido (corrigen el
    denominador del PSR).
    """
    N = len(trial_sharpes)
    sr = selected if selected is not None else (max(trial_sharpes) if trial_sharpes else 0.0)
    Z = NormalDist()
    gamma = 0.5772156649015329  # Euler-Mascheroni

    if N >= 2:
        var_trials = float(np.var(np.asarray(trial_sharpes, dtype=float), ddof=1))
        sr0 = math.sqrt(max(var_trials, 0.0)) * (
            (1 - gamma) * Z.inv_cdf(1 - 1.0 / N)
            + gamma * Z.inv_cdf(1 - 1.0 / (N * math.e))
        )
    else:
        sr0 = 0.0  # sin múltiples intentos no hay nada que deflactar

    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurtosis - 1) / 4.0 * sr ** 2))
    scale = math.sqrt(max(n_obs - 1, 0))
    deflated = float(Z.cdf((sr - sr0) * scale / denom)) if n_obs >= 2 else float("nan")
    raw = float(Z.cdf(sr * scale / denom)) if n_obs >= 2 else float("nan")
    return DSRResult(
        observed_sharpe=sr, n_trials=N, n_obs=n_obs,
        expected_max_sharpe=sr0, deflated_sharpe=deflated, prob_positive_raw=raw,
    )


# ── Block-bootstrap pareado (Tarea 13 / ENT1 §5 C5) ──────────────────────────


@dataclass
class PairedBootstrapResult:
    """Distribución bootstrapeada de ΔCAGR (candidato − baseline)."""

    observed: float          # ΔCAGR puntual sobre la serie completa
    mean: float              # media de los resamples
    ci_low: float            # percentil 2.5
    ci_high: float           # percentil 97.5
    p_value: float           # fracción de resamples con Δ ≤ 0 (unilateral)
    n_obs: int
    block: int
    n_resamples: int


def _compound_cagr(rets: "np.ndarray", periods: int = 252) -> float:
    """CAGR anualizado por composición de retornos diarios."""
    if rets.size == 0:
        return 0.0
    growth = float(np.prod(1.0 + rets))
    if growth <= 0:
        return -1.0
    return growth ** (periods / rets.size) - 1.0


def paired_block_bootstrap(
    base_rets: "list[float]",
    cand_rets: "list[float]",
    *,
    block: int = 20,
    n_resamples: int = 2000,
    seed: int = 12345,
    periods: int = 252,
) -> PairedBootstrapResult:
    """Bootstrap de bloques móviles **pareado** sobre Δ(retorno diario de equity).

    Por qué éste y no PBO/CSCV (congelado en el pre-registro §5 C5): CSCV responde
    *"¿el mejor de muchos candidatos generaliza?"*, que **no es la pregunta** cuando
    se refina **una** regla contra su propio baseline — con pocos brazos colineales
    es un estimador grueso, que es exactamente cómo murió T23 (``PBO=0.889``) y lo
    que su veredicto dejó anotado como idea derivada.

    Mecánica: las dos series entran **alineadas por fecha** (mismo largo T). Cada
    resample arma una secuencia de índices concatenando bloques contiguos de
    ``block`` días tomados al azar (bloques móviles: preservan autocorrelación y el
    efecto cascada de path que T23 midió) y **aplica la misma secuencia a las dos
    series** — de ahí lo pareado: el ruido de mercado común se cancela y lo que
    queda es el efecto de la regla. Se compone el CAGR de cada una y se guarda la
    diferencia.

    El gate es ``ci_low > 0``: el percentil 2.5 del ΔCAGR bootstrapeado tiene que
    seguir siendo positivo. Determinista por ``seed``.
    """
    a = np.asarray(base_rets, dtype=float)
    b = np.asarray(cand_rets, dtype=float)
    T = min(a.size, b.size)
    block = max(1, min(int(block), T))
    if T < 2 or n_resamples < 1:
        return PairedBootstrapResult(0.0, 0.0, 0.0, 0.0, float("nan"), T, block, 0)
    a, b = a[:T], b[:T]

    observed = _compound_cagr(b, periods) - _compound_cagr(a, periods)
    n_blocks = int(math.ceil(T / block))
    max_start = T - block  # inclusive
    rng = np.random.default_rng(seed)

    deltas = np.empty(n_resamples, dtype=float)
    for k in range(n_resamples):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:T]
        deltas[k] = _compound_cagr(b[idx], periods) - _compound_cagr(a[idx], periods)

    return PairedBootstrapResult(
        observed=observed,
        mean=float(deltas.mean()),
        ci_low=float(np.percentile(deltas, 2.5)),
        ci_high=float(np.percentile(deltas, 97.5)),
        p_value=float(np.mean(deltas <= 0.0)),
        n_obs=T,
        block=block,
        n_resamples=n_resamples,
    )


# ── A1 con variantes de stop-mult: matriz de retornos por config ─────────────

# Variantes del eje "cuán apretado es el stop/trail" para el PBO/DSR de A1.
# Loosear stop_mult afloja también el trailing (usa el mismo mult) — es el eje que
# A1 re-evalúa. NO es el stop inicial 2×ATR aislado (eso fue A1 puntual, NO-SHIP).
A1_VARIANTS: dict[str, AtrParams] = {
    "no_stops": _NO_STOPS,
    "loose_3.0": AtrParams(stop_mult=3.0),
    "loose_2.5": AtrParams(stop_mult=2.5),
    "baseline_2.0": AtrParams(),
}


def per_entry_returns_by_config(
    entries: list[EntrySample],
    bar_loader: BarLoader,
    configs: dict[str, AtrParams],
    *,
    cap_days: int = 20,
) -> tuple[list[EntrySample], dict[str, list[float]]]:
    """Retorno por-share de cada entrada bajo cada config nombrada. Sólo incluye
    entradas donde TODAS las configs producen un exit (alineadas por índice), para
    que la matriz de performance sea rectangular (requisito de PBO/DSR)."""
    used: list[EntrySample] = []
    cols: dict[str, list[float]] = {name: [] for name in configs}
    for e in entries:
        bars = bar_loader(e.ticker)
        if not bars:
            continue
        rets: dict[str, float] = {}
        ok = True
        for name, p in configs.items():
            res = replay_from_entry(bars, e.entry_idx, cap_days=cap_days, atr_p=p)
            if res is None:
                ok = False
                break
            rets[name] = res[1] / e.entry_price - 1.0
        if not ok:
            continue
        used.append(e)
        for name in configs:
            cols[name].append(rets[name])
    return used, cols
