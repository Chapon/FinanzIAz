"""
Simulador de cartera con capital y slots finitos — enabler de la **Tarea 8 (R2)**.

Por qué existe
--------------
El harness de la Tarea 7 le daba **capital ilimitado** a cada entrada, y eso hacía
que cualquier variante que retuviera las posiciones más tiempo se viera
artificialmente bien: al normalizar por ocupación de slot, los cinco brazos de
scale-out pasaban de positivos a negativos
(``docs/scaleout_trailing_t7_2026-07-20.md`` §8.3). Quedó anotado como lección.

Para R2 esa lección no es opcional sino central: el valor entero de un filtro de
régimen **es** cuándo estás en el mercado y cuándo no, o sea una pregunta de
cartera. Medirlo con capital infinito sería medir otra cosa.

Qué modela
----------
  * ``max_positions`` slots. Una entrada que llega sin slot libre **se pierde**
    (no se encola) — igual que el engine vivo.
  * Capital finito: cada entrada toma un slice del cash disponible.
  * El cash liberado por una salida **vuelve a estar disponible** para entradas
    posteriores (es el mecanismo que se está midiendo).
  * Costos de comisión y slippage en las dos puntas.
  * Un **filtro de entrada inyectable** (``entry_filter``) — así el gate de régimen
    (o cualquier otro) se testea sin tocar el simulador.

Qué NO modela (declarado en el pre-registro §9)
------------------------------------------------
  * El ranking por ``buy_score`` entre candidatos del mismo día: se usa orden
    cronológico y, ante empate, orden alfabético estable. Como el ``buy_score`` no
    tiene alpha medido (ref A3), rankear por él agregaría ruido, no realismo.
  * Márgenes, apalancamiento, dividendos.

Es **lógica pura** (stdlib): las barras entran como ``list[Bar]``, la señal como
dict precomputado y el filtro como callable, así los tests corren offline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from analysis.exit_replay import AtrParams, Bar, max_drawdown
from analysis.scaleout_replay import CostModel, ScaleOutParams, replay_cycle

# entry_filter(ticker, date_iso10) -> factor de tamaño en [0, 1].
#   1.0 = entrada normal · 0.0 = entrada suprimida · 0.5 = medio tamaño.
EntryFilter = Callable[[str, str], float]


@dataclass
class Trade:
    """Una posición efectivamente abierta por el simulador."""

    ticker: str
    entry_date: str
    exit_date: str
    invested: float
    proceeds: float
    regime: str
    held_days: int
    exit_reason: str
    size_factor: float = 1.0

    @property
    def pnl(self) -> float:
        return self.proceeds - self.invested

    @property
    def ret(self) -> float:
        return (self.proceeds / self.invested - 1.0) if self.invested > 0 else 0.0


@dataclass
class PortfolioResult:
    initial_capital: float
    final_equity: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    n_offered: int = 0        # entradas candidatas ofrecidas al simulador
    n_taken: int = 0          # efectivamente abiertas
    n_no_slot: int = 0        # rechazadas por falta de slot
    n_filtered: int = 0       # rechazadas por el entry_filter (size 0)
    n_no_cash: int = 0        # rechazadas por falta de cash

    @property
    def total_return_pts(self) -> float:
        if self.initial_capital <= 0:
            return 0.0
        return 100.0 * (self.final_equity / self.initial_capital - 1.0)

    @property
    def max_dd(self) -> float:
        return max_drawdown(self.equity_curve)

    @property
    def exposure_share(self) -> float:
        """Fracción de días con al menos una posición abierta (0-1)."""
        if not self._days_invested_total:
            return 0.0
        return self._days_invested / self._days_invested_total

    _days_invested: int = 0
    _days_invested_total: int = 0


def simulate_portfolio(
    entries: list[tuple[str, int]],
    bars_by: dict[str, list[Bar]],
    sigs_by: dict[str, dict],
    *,
    max_positions: int = 5,
    initial_capital: float = 50_000.0,
    cap_days: int = 20,
    atr_p: AtrParams = AtrParams(),
    so_params: ScaleOutParams = ScaleOutParams(),
    costs: CostModel = CostModel(),
    entry_filter: EntryFilter | None = None,
    regime_of: Callable[[str], str] | None = None,
) -> PortfolioResult:
    """Corre la cartera sobre ``entries`` (ordenadas cronológicamente).

    Cada entrada candidata se acepta solo si (a) el ``entry_filter`` no la suprime,
    (b) hay un slot libre en su fecha y (c) alcanza el cash. El tamaño de la posición
    es ``cash_disponible / slots_libres``, escalado por el factor del filtro.

    El resultado de cada posición se obtiene con ``replay_cycle`` — la misma
    maquinaria de salida ya validada — así el simulador no reimplementa exits.
    """
    res = PortfolioResult(initial_capital=initial_capital, final_equity=initial_capital)
    cash = initial_capital
    # posiciones abiertas: [(exit_date_iso10, proceeds)]
    open_positions: list[tuple[str, float]] = []
    # valor de la cartera por fecha, para la curva de equity
    realized_by_date: dict[str, float] = {}
    all_dates: set[str] = set()

    def _release_until(date_iso10: str) -> None:
        """Cierra las posiciones cuya salida ya ocurrió antes de ``date_iso10``."""
        nonlocal cash
        still: list[tuple[str, float]] = []
        for exit_date, proceeds in open_positions:
            if exit_date < date_iso10:
                cash += proceeds
                realized_by_date[exit_date] = realized_by_date.get(exit_date, 0.0) + proceeds
            else:
                still.append((exit_date, proceeds))
        open_positions[:] = still

    for ticker, idx in entries:
        bars = bars_by.get(ticker)
        if not bars or idx >= len(bars):
            continue
        entry_date = bars[idx][0]
        all_dates.add(entry_date)
        res.n_offered += 1

        _release_until(entry_date)

        size_factor = 1.0 if entry_filter is None else float(entry_filter(ticker, entry_date))
        if size_factor <= 0.0:
            res.n_filtered += 1
            continue

        free_slots = max_positions - len(open_positions)
        if free_slots <= 0:
            res.n_no_slot += 1
            continue

        notional = (cash / free_slots) * min(1.0, size_factor)
        if notional <= 0 or not math.isfinite(notional) or notional > cash:
            res.n_no_cash += 1
            continue

        cyc = replay_cycle(
            bars, idx, sigs_by.get(ticker) or {},
            params=so_params, atr_p=atr_p, cap_days=cap_days,
            costs=costs, notional=notional,
            regime="" if regime_of is None else regime_of(entry_date),
        )
        if cyc is None:
            continue

        cash -= cyc.entry_cost
        proceeds = cyc.total_proceeds
        exit_date = cyc.legs[-1].date if cyc.legs else entry_date
        open_positions.append((exit_date, proceeds))
        all_dates.add(exit_date)
        res.n_taken += 1
        res.trades.append(Trade(
            ticker=ticker, entry_date=entry_date, exit_date=exit_date,
            invested=cyc.entry_cost, proceeds=proceeds,
            regime=cyc.regime, held_days=cyc.held_days,
            exit_reason=cyc.exit_reasons, size_factor=size_factor,
        ))

    # cerrar todo lo que quede
    for _, proceeds in open_positions:
        cash += proceeds
    open_positions.clear()

    res.final_equity = cash
    res.equity_curve = _build_equity_curve(res.trades, initial_capital, bars_by)
    res._days_invested, res._days_invested_total = _exposure(res.trades, res.equity_curve)
    return res


def _build_equity_curve(
    trades: list[Trade], initial_capital: float, bars_by: dict[str, list[Bar]],
) -> list[tuple[str, float]]:
    """Curva de equity diaria: cash + MTM de las posiciones abiertas.

    Se reconstruye a partir de los trades (que ya tienen entrada, salida y montos)
    marcando a mercado con los closes reales de cada ticker.
    """
    if not trades:
        return []
    dates = sorted({d for t in trades for d in (t.entry_date, t.exit_date)})
    if not dates:
        return []
    # índice de closes por ticker para el MTM
    closes: dict[str, dict[str, float]] = {}
    for t in trades:
        if t.ticker in closes:
            continue
        closes[t.ticker] = {b[0]: b[4] for b in (bars_by.get(t.ticker) or [])}

    # calendario completo entre la primera y la última fecha relevante
    cal = sorted({b0 for tk in closes for b0 in closes[tk]
                  if dates[0] <= b0 <= dates[-1]})
    if not cal:
        cal = dates

    curve: list[tuple[str, float]] = []
    for d in cal:
        cash = initial_capital
        mtm = 0.0
        for t in trades:
            if t.entry_date > d:
                continue
            cash -= t.invested
            if t.exit_date <= d:
                cash += t.proceeds
            else:
                # posición abierta: marcar a mercado con el close del día
                px = closes.get(t.ticker, {}).get(d)
                entry_px = closes.get(t.ticker, {}).get(t.entry_date)
                if px and entry_px and entry_px > 0:
                    mtm += t.invested * (px / entry_px)
                else:
                    mtm += t.invested
        curve.append((d, cash + mtm))
    return curve


def _exposure(trades: list[Trade], curve: list[tuple[str, float]]) -> tuple[int, int]:
    """(días con al menos una posición abierta, días totales de la curva)."""
    if not curve:
        return 0, 0
    invested = 0
    for d, _ in curve:
        if any(t.entry_date <= d < t.exit_date for t in trades):
            invested += 1
    return invested, len(curve)
