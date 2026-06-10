"""
Exit replay harness — T6.1 (roadmap v3, Sprint 6 Exit Quality).

Replay de los ciclos cerrados reales con variantes de política de exit, para
medir cuánto del alpha regalado por los SELLs tempranos se recupera con cada
política. Caso de negocio: la auditoría 2026-06-09 mostró que los SELLs por
señal cortan posiciones a 1-3 días y el precio sigue subiendo después
(mediana fwd5 post-SELL positiva en todas las eras).

Contrafáctico (decidido con Chapa 2026-06-10): al saltear/deferir un SELL de
señal, la posición sigue bajo el **ATR trail real del engine** (misma lógica
de ``paper_trading.gates.atr_exit_decision``, mismo orden stop → trail → tp,
mismo seeding de high-water mark) hasta que dispare, llegue el exit
programado de la variante, o se alcance el cap de 20 días hábiles. Los exits
ATR reales (``atr_*``) no se modifican: las variantes solo tocan SELLs cuyo
reason empieza con ``analyze``.

Limitación documentada: no existe trail de señales scan-a-scan (ningún SELL
quedó ``expired``), así que la variante (a) "confirmación en 2 scans" se
aproxima como *delay de 1 día hábil asumiendo que la señal persiste*. Es el
peor caso para la variante: si la señal desaparecía al día siguiente, el
resultado real solo puede ser mejor que el simulado aquí.

Todo el módulo es lógica pura (stdlib): los precios entran por un
``bar_loader`` inyectable, así los tests corren offline con barras sintéticas.
El runner CLI vive en ``scripts/run_exit_replay_t61.py``.

Kill criteria (upfront, roadmap v3): se shipea la variante que mejore el P/L
total ≥ +2 puntos (% sobre capital inicial) sobre el real sin aumentar el max
DD del equity ajustado más de 1.5× el real. Si ninguna pasa, se documenta y
no se shipea nada.
"""

from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass, field
from typing import Callable, Iterable

# ── Datos de entrada ─────────────────────────────────────────────────────────

# bar_loader(ticker) -> list[Bar] ordenada asc, o None si no hay data.
# Bar = (date_iso10, open, high, low, close)
Bar = tuple[str, float, float, float, float]
BarLoader = Callable[[str], "list[Bar] | None"]


@dataclass(frozen=True)
class SellEvent:
    """Un SELL filled real con el contexto de su ciclo (FIFO)."""

    order_id: int
    ticker: str
    sell_date: str          # iso10 del fill
    sell_price: float       # fill_price real
    reason: str
    signal_score: float | None
    shares: float
    avg_cost: float         # costo por share del lote consumido (incl. fees BUY)
    entry_date: str         # iso10 del BUY más viejo consumido
    entry_price: float      # fill_price del primer BUY (seed del HWM)
    sell_commission: float = 0.0
    sell_slippage: float = 0.0

    @property
    def is_signal_sell(self) -> bool:
        return bool(self.reason) and self.reason.startswith("analyze")

    @property
    def pnl_real(self) -> float:
        return (self.sell_price * self.shares
                - self.sell_commission - self.sell_slippage
                - self.avg_cost * self.shares)


@dataclass(frozen=True)
class AtrParams:
    """Espejo de los settings del engine (defaults = defaults del engine)."""

    period: int = 14
    stop_mult: float = 2.0
    tp_mult: float = 4.0
    trail_enabled: bool = True
    trail_min_excess_atrs: float = 1.0


@dataclass
class SimExit:
    """Resultado de replay de un SellEvent bajo una variante."""

    event: SellEvent
    modified: bool                  # False ⇒ pasa igual que el real
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl_sim: float = 0.0
    # path diario de MTM delta vs real: [(date, delta_dollars)] mientras la
    # posición sigue abierta en la sim pero cerrada en el real.
    daily_delta: list[tuple[str, float]] = field(default_factory=list)

    @property
    def pnl_delta(self) -> float:
        return self.pnl_sim - self.event.pnl_real


# ── ATR Wilder (espejo stdlib de analysis.atr.compute_atr_series) ────────────


def atr_series(bars: list[Bar], period: int = 14) -> list[float | None]:
    """ATR de Wilder por barra. None hasta tener ``period`` TRs (índice < period).

    Misma semántica que ``analysis.atr.compute_atr_series``: seed = SMA de
    TR_1..TR_n en el índice ``period``, después recursión de Wilder.
    """
    n = len(bars)
    if n <= period:
        return [None] * n
    tr: list[float] = [0.0] * n
    for i in range(1, n):
        _, _, hi, lo, _ = bars[i]
        prev_close = bars[i - 1][4]
        tr[i] = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
    out: list[float | None] = [None] * n
    seed = sum(tr[1 : period + 1]) / period
    if not math.isfinite(seed):
        return out
    out[period] = seed
    for i in range(period + 1, n):
        out[i] = ((period - 1) * out[i - 1] + tr[i]) / period  # type: ignore[operator]
    return out


# ── Decisión de exit ATR (espejo de paper_trading.gates.atr_exit_decision) ───


def atr_exit(
    *,
    current_price: float,
    avg_cost: float,
    high_water_mark: float | None,
    atr_value: float,
    p: AtrParams,
) -> str | None:
    """Versión stdlib de ``gates.atr_exit_decision``. Devuelve el reason o None.

    Mismo orden de evaluación: hard stop → trail → take-profit; trail
    suprimido hasta que el HWM supere el entry por ≥ trail_min_excess_atrs×ATR.
    """
    vals = [current_price, avg_cost, atr_value]
    if not all(math.isfinite(v) for v in vals):
        return None
    if current_price <= 0 or avg_cost <= 0 or atr_value <= 0:
        return None
    hwm = float(high_water_mark) if high_water_mark is not None else avg_cost

    stop_level = avg_cost - p.stop_mult * atr_value
    if stop_level > 0 and current_price <= stop_level:
        return "atr_stop"

    trail_level = hwm - p.stop_mult * atr_value
    if (
        p.trail_enabled
        and trail_level > 0
        and current_price <= trail_level
        and hwm > avg_cost + p.trail_min_excess_atrs * atr_value
    ):
        return "atr_trail"

    tp_level = avg_cost + p.tp_mult * atr_value
    if tp_level > 0 and current_price >= tp_level:
        return "atr_tp"

    return None


# ── Replay de un ciclo ───────────────────────────────────────────────────────


def _idx_on_or_after(bars: list[Bar], date_iso10: str) -> int:
    dates = [b[0] for b in bars]
    return bisect.bisect_left(dates, date_iso10)


def replay_event(
    ev: SellEvent,
    bars: list[Bar],
    *,
    scheduled_exit_idx: int | None,
    cap_days: int,
    atr_p: AtrParams,
) -> SimExit | None:
    """Simula mantener la posición desde el día siguiente al SELL real.

    ``scheduled_exit_idx``: índice de barra (absoluto en ``bars``) donde la
    variante ejecuta el SELL diferido (asumiendo señal persistente); None ⇒
    sin exit programado (variante umbral), rige solo ATR + cap.

    Orden intradía espejado del engine: cada día primero se evalúa el ATR con
    el HWM *antes* de actualizar (ATR gana sobre el SELL programado del mismo
    día), después se actualiza el HWM con el close.

    Devuelve None si no hay barras suficientes (ticker sin cache o SELL más
    reciente que la última barra disponible).
    """
    if not bars:
        return None
    d_idx = _idx_on_or_after(bars, ev.sell_date)
    if d_idx >= len(bars) or bars[d_idx][0] != ev.sell_date:
        # el día del fill tiene que existir como barra
        return None
    if d_idx + 1 >= len(bars):
        return None  # SELL demasiado reciente: no hay día siguiente todavía

    atrs = atr_series(bars, atr_p.period)

    # HWM al cierre del día del SELL real: seed = entry fill, actualizado con
    # los closes desde el entry hasta D inclusive (el engine ya pasó por esos
    # scans sin disparar ATR — el exit real fue por señal).
    e_idx = _idx_on_or_after(bars, ev.entry_date)
    hwm = ev.entry_price
    for i in range(e_idx, d_idx + 1):
        hwm = max(hwm, bars[i][4])

    last_idx = min(d_idx + cap_days, len(bars) - 1)
    exit_idx: int | None = None
    exit_reason = ""
    deltas: list[tuple[str, float]] = []

    for i in range(d_idx + 1, last_idx + 1):
        date_i, _, _, _, close_i = bars[i]
        a = atrs[i]
        fired = None
        if a is not None:
            fired = atr_exit(
                current_price=close_i,
                avg_cost=ev.avg_cost,
                high_water_mark=hwm,
                atr_value=a,
                p=atr_p,
            )
        if fired is not None:
            exit_idx, exit_reason = i, fired
        elif scheduled_exit_idx is not None and i >= scheduled_exit_idx:
            exit_idx, exit_reason = i, "deferred_signal_sell"
        elif i == last_idx:
            exit_idx, exit_reason = i, "cap_reached"

        # MTM delta diario vs el real (que ya está en cash a sell_price)
        deltas.append((date_i, (close_i - ev.sell_price) * ev.shares))

        if exit_idx is not None:
            break
        hwm = max(hwm, close_i)

    assert exit_idx is not None  # last_idx siempre cierra
    exit_price = bars[exit_idx][4]
    pnl_sim = (exit_price * ev.shares
               - ev.sell_commission - ev.sell_slippage
               - ev.avg_cost * ev.shares)
    return SimExit(
        event=ev,
        modified=True,
        exit_date=bars[exit_idx][0],
        exit_price=exit_price,
        exit_reason=exit_reason,
        pnl_sim=pnl_sim,
        daily_delta=deltas,
    )


# ── Variantes ────────────────────────────────────────────────────────────────


def _business_age_days(bars: list[Bar], entry_date: str, asof_idx: int) -> int:
    """Edad de la posición en barras (días hábiles) al índice ``asof_idx``."""
    e_idx = _idx_on_or_after(bars, entry_date)
    return max(0, asof_idx - e_idx)


def simulate_variant(
    events: Iterable[SellEvent],
    bar_loader: BarLoader,
    variant: str,
    *,
    cap_days: int = 20,
    atr_p: AtrParams = AtrParams(),
    sell_threshold: float = 0.25,
    min_holding_days: int = 2,
) -> list[SimExit]:
    """Corre una variante sobre todos los SellEvents.

    Variantes:
      * ``confirm_next_scan`` — (a) el SELL de señal ejecuta al scan siguiente
        (D+1, asumiendo señal persistente); ATR puede ganar ese día.
      * ``score_threshold``   — (b) SELLs de señal con score ≥ ``sell_threshold``
        se saltean; la posición queda bajo ATR + cap. SELLs con score <
        threshold (o sin score) ejecutan igual que el real.
      * ``min_holding``       — (c) SELLs de señal con edad < ``min_holding_days``
        días hábiles se difieren hasta cumplir la edad; ATR puede ganar antes.

    Los SELLs no-señal (``atr_*``, trims, etc.) pasan sin modificar siempre.
    Eventos modificables sin barras suficientes pasan sin modificar (quedan
    contados en ``ReplayReport.n_skipped_no_data``).
    """
    out: list[SimExit] = []
    for ev in events:
        if not ev.is_signal_sell:
            out.append(_passthrough(ev))
            continue

        bars = bar_loader(ev.ticker)
        sim: SimExit | None = None

        if variant == "confirm_next_scan":
            if bars:
                d_idx = _idx_on_or_after(bars, ev.sell_date)
                sim = replay_event(ev, bars, scheduled_exit_idx=d_idx + 1,
                                   cap_days=cap_days, atr_p=atr_p)
        elif variant == "score_threshold":
            if ev.signal_score is not None and ev.signal_score >= sell_threshold:
                if bars:
                    sim = replay_event(ev, bars, scheduled_exit_idx=None,
                                       cap_days=cap_days, atr_p=atr_p)
            else:
                out.append(_passthrough(ev))
                continue
        elif variant == "min_holding":
            if bars:
                d_idx = _idx_on_or_after(bars, ev.sell_date)
                age = _business_age_days(bars, ev.entry_date, d_idx)
                if age >= min_holding_days:
                    out.append(_passthrough(ev))
                    continue
                e_idx = _idx_on_or_after(bars, ev.entry_date)
                sim = replay_event(ev, bars,
                                   scheduled_exit_idx=e_idx + min_holding_days,
                                   cap_days=cap_days, atr_p=atr_p)
        else:
            raise ValueError(f"variante desconocida: {variant}")

        if sim is None:
            ps = _passthrough(ev)
            ps.exit_reason = "no_data"
            out.append(ps)
        else:
            out.append(sim)
    return out


def _passthrough(ev: SellEvent) -> SimExit:
    return SimExit(
        event=ev, modified=False,
        exit_date=ev.sell_date, exit_price=ev.sell_price,
        exit_reason=ev.reason, pnl_sim=ev.pnl_real,
    )


# ── Métricas agregadas ───────────────────────────────────────────────────────


@dataclass
class ReplayReport:
    variant: str
    n_events: int
    n_modified: int
    n_skipped_no_data: int
    pnl_real_total: float
    pnl_sim_total: float
    pnl_delta_total: float
    pnl_delta_pts: float            # delta como % del capital inicial
    max_dd_real: float              # fracción positiva (0.06 = 6%)
    max_dd_sim: float
    dd_ratio: float                 # max_dd_sim / max_dd_real
    median_extra_return: float | None   # mediana de (exit_sim/sell_real - 1) en modificados
    capture_ratio_median: float | None  # mediana de capturado / rally máximo 20d
    passes_kill_criteria: bool
    exits_by_reason: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


def max_drawdown(curve: list[tuple[str, float]]) -> float:
    """Max drawdown (fracción positiva) de una curva [(date, equity)] asc."""
    peak = -math.inf
    dd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, 1.0 - v / peak)
    return dd


def adjusted_equity_curve(
    real_curve: list[tuple[str, float]],
    sims: list[SimExit],
) -> list[tuple[str, float]]:
    """Equity real + suma de los MTM deltas diarios de los ciclos extendidos.

    Para fechas posteriores al último snapshot real, no extrapola: los deltas
    fuera de rango se ignoran (el cap de 20 días mantiene esto acotado).
    Después del exit simulado de cada ciclo, el delta queda congelado en el
    delta realizado (pnl_sim - pnl_real) hasta el final de la curva.
    """
    if not real_curve:
        return []
    dates = [d for d, _ in real_curve]
    deltas = [0.0] * len(real_curve)
    for s in sims:
        if not s.modified or not s.daily_delta:
            continue
        # mientras está abierta: MTM delta del día
        last_pos = None
        for d, delta in s.daily_delta:
            pos = bisect.bisect_left(dates, d)
            if pos < len(dates) and dates[pos][:10] >= d:
                # aplicar al primer snapshot en/después de d
                deltas[pos] += delta
                last_pos = pos
        # después del exit: delta realizado congelado
        realized = s.pnl_delta
        if last_pos is not None:
            for i in range(last_pos + 1, len(dates)):
                deltas[i] += realized
    # los deltas son por-día (no acumulados): el MTM de cada día reemplaza al
    # anterior mientras la posición está abierta. Arriba ya se aplicó cada
    # delta solo a su día, y el realizado a los días posteriores; sumar ambos
    # da la curva ajustada por día.
    return [(d, v + deltas[i]) for i, (d, v) in enumerate(real_curve)]


def build_report(
    variant: str,
    sims: list[SimExit],
    real_curve: list[tuple[str, float]],
    *,
    initial_capital: float,
    bar_loader: BarLoader,
    rally_horizon: int = 20,
) -> ReplayReport:
    pnl_real = sum(s.event.pnl_real for s in sims)
    pnl_sim = sum(s.pnl_sim for s in sims)
    delta = pnl_sim - pnl_real
    delta_pts = 100.0 * delta / initial_capital if initial_capital > 0 else 0.0

    modified = [s for s in sims if s.modified]
    skipped = sum(1 for s in sims if not s.modified and s.exit_reason == "no_data")

    extra_returns = [
        s.exit_price / s.event.sell_price - 1.0
        for s in modified if s.event.sell_price > 0
    ]

    # capture ratio: cuánto del rally máximo a 20d post-SELL se retuvo
    captures: list[float] = []
    for s in modified:
        bars = bar_loader(s.event.ticker)
        if not bars:
            continue
        d_idx = _idx_on_or_after(bars, s.event.sell_date)
        peak = max(
            (b[4] for b in bars[d_idx + 1 : d_idx + 1 + rally_horizon]),
            default=None,
        )
        if peak is None or peak <= s.event.sell_price:
            continue  # no hubo rally: no aplica
        captures.append(
            (s.exit_price - s.event.sell_price) / (peak - s.event.sell_price)
        )

    dd_real = max_drawdown(real_curve)
    adj = adjusted_equity_curve(real_curve, sims)
    dd_sim = max_drawdown(adj)
    dd_ratio = (dd_sim / dd_real) if dd_real > 0 else (1.0 if dd_sim == 0 else math.inf)

    reasons: dict[str, int] = {}
    for s in modified:
        reasons[s.exit_reason] = reasons.get(s.exit_reason, 0) + 1

    return ReplayReport(
        variant=variant,
        n_events=len(sims),
        n_modified=len(modified),
        n_skipped_no_data=skipped,
        pnl_real_total=pnl_real,
        pnl_sim_total=pnl_sim,
        pnl_delta_total=delta,
        pnl_delta_pts=delta_pts,
        max_dd_real=dd_real,
        max_dd_sim=dd_sim,
        dd_ratio=dd_ratio,
        median_extra_return=(statistics.median(extra_returns) if extra_returns else None),
        capture_ratio_median=(statistics.median(captures) if captures else None),
        passes_kill_criteria=(delta_pts >= 2.0 and dd_ratio <= 1.5),
        exits_by_reason=reasons,
    )
