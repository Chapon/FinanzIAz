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
  * Un **ranking inyectable** (``rank_score``) entre los candidatos que compiten
    por el mismo slot el mismo día, y la regla de que **un ticker no se reabre
    mientras está en cartera** (agregados por la Tarea 9 — ver abajo).

Qué NO modela
-------------
  * Márgenes, apalancamiento, dividendos.

Extensiones de la Tarea 9 (declaradas en su pre-registro §7 antes de escribirlas)
--------------------------------------------------------------------------------
R2 declaró como "no modelado" el ranking entre candidatos del mismo día: usaba
orden cronológico con desempate alfabético. Para la **Tarea 9** ese orden dejó de
ser un detalle y pasó a ser *la variable bajo estudio* — con ``max_positions=5``
y 41 tickers hay días con más candidatos que slots, y quién entra lo decide el
ranking. Por eso:

  * ``rank_score`` ordena los candidatos **dentro de cada día** (score más alto
    primero, desempate alfabético para que siga siendo determinista). Sin él, el
    comportamiento es exactamente el de R2 = el brazo ``B0_neutral``.
  * ``allow_reentry_while_open=False`` (default) saltea un ticker que ya está en
    cartera, como hace el engine (``strategies.py``: ``if t in held_tickers and t
    not in forced_exits: continue``). R2 no lo necesitaba porque corría con
    ``spacing=20`` y el solapamiento era raro; sin espaciado deja de serlo.

**Las dos extensiones cambian los números absolutos** respecto de los publicados
por R2 (CAGR 18.98% / DD 21.6%): esos números son de otra población y no sirven
como referencia para la Tarea 9, que re-corre su propio baseline.

Es **lógica pura** (stdlib): las barras entran como ``list[Bar]``, la señal como
dict precomputado y el filtro como callable, así los tests corren offline.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date

from analysis.exit_replay import AtrParams, Bar, max_drawdown
from analysis.harness_config import (
    LIVE_CHURN_LOOKBACK_DAYS,
    LIVE_CHURN_MAX_CYCLES,
    LIVE_WHIPSAW_LOOKBACK_DAYS,
    LIVE_WHIPSAW_MIN_LOSS_PCT,
)
from analysis.scaleout_replay import CostModel, ScaleOutParams, StopFilter, replay_cycle

# entry_filter(ticker, date_iso10) -> factor de tamaño en [0, 1].
#   1.0 = entrada normal · 0.0 = entrada suprimida · 0.5 = medio tamaño.
EntryFilter = Callable[[str, str], float]

# rank_score(ticker, date_iso10) -> conviccion; mayor entra primero.
RankScore = Callable[[str, str], float]

# size_weight(ticker, date_iso10) -> m ≥ 0, multiplicador de riesgo POR NOMBRE
# sobre el slice equal-weight (bloque 10). Cuando se pasa, el tamaño deja de estar
# capeado a 1.0 (un nombre de baja σ puede pesar más que el slice), pero se topa a
# ``max_weight`` de la equity para que no concentre. None ⇒ comportamiento actual.
SizeWeight = Callable[[str, str], float]

# cap_days_of(ticker, date_iso10) -> tope de tenencia EN RUEDAS de esa posicion.
# Enabler de la Tarea 51 (EVENT-TIMESTOP): permite que el tope dependa de la
# posicion —p.ej. corto solo para las entradas que ademas son evento— sin tocar
# `replay_cycle`, que ya recibe `cap_days` posicion por posicion. None => el
# `cap_days` global de siempre, asi que ningun harness previo cambia.
#
# Ojo con la distincion que la tarea 57 tuvo que declarar: esto es el **cap duro**
# (cierra a todos al llegar a N, ganadores incluidos), NO el `time_stop_days` de la
# T13 (que dispara una sola vez en la barra N y solo si esta en perdida).
CapDaysOf = Callable[[str, str], int]

# trail_min_excess_of(ticker, date_iso10) -> umbral de ARMADO del trailing (en
# ATRs) de esa posicion. Enabler de la Tarea 54 (TRAIL-ARM): el trailing esta
# suprimido hasta que el HWM supere `entry + umbral x ATR`, y esta tarea pregunta
# si ese umbral (1.0 en vivo) esta bien puesto. Que dependa de la posicion es lo
# que permite el CONTROL igualado en tasa: bajarlo solo para un subconjunto
# aleatorio, a la misma frecuencia que el candidato. None => el `atr_p` global de
# siempre, asi que ningun harness previo cambia.
#
# Ojo: aca **0.0 es un valor valido** (trailing siempre armado), a diferencia del
# `cap_days_of`, donde 0 no tiene sentido y se cae al global.
TrailMinExcessOf = Callable[[str, str], float]


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
    n_already_open: int = 0   # rechazadas por tener ya el ticker en cartera
    n_gate5_blocked: int = 0  # rechazadas por Gate 5 vivo (anti-whipsaw), T34
    n_gate5b_blocked: int = 0 # rechazadas por Gate 5b vivo (anti-churn), T34

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
    rank_score: RankScore | None = None,
    size_weight: SizeWeight | None = None,
    max_weight: float = 0.25,
    allow_reentry_while_open: bool = False,
    regime_of: Callable[[str], str] | None = None,
    time_stop_days: int | None = None,
    cap_days_of: CapDaysOf | None = None,
    trail_min_excess_of: TrailMinExcessOf | None = None,
    stop_filter: StopFilter | None = None,
    eval_mode: str = "close",
    fill_mode: str = "decision",
    live_gates: bool = False,
) -> PortfolioResult:
    """Corre la cartera sobre ``entries`` (ordenadas cronológicamente).

    Cada entrada candidata se acepta solo si (a) el ticker no está ya en cartera,
    (b) el ``entry_filter`` no la suprime, (c) hay un slot libre en su fecha y
    (d) alcanza el cash. El tamaño de la posición es ``cash_disponible /
    slots_libres``, escalado por el factor del filtro.

    Los candidatos **del mismo día** se procesan en el orden que dicta
    ``rank_score`` (mayor primero); sin él, en orden alfabético. Ese orden es lo
    único que decide quién se queda con el último slot de un día con más
    candidatos que lugar.

    El resultado de cada posición se obtiene con ``replay_cycle`` — la misma
    maquinaria de salida ya validada — así el simulador no reimplementa exits.

    ``time_stop_days`` (ENT1 brazo b, Tarea 13) se pasa tal cual a ``replay_cycle``:
    ``None`` ⇒ sin time stop, que es el comportamiento de todas las tareas previas.

    ``cap_days_of`` (EVENT-TIMESTOP, Tarea 51) resuelve el **cap duro por posición**
    a partir de ``(ticker, fecha_de_entrada)``; ``None`` ⇒ el ``cap_days`` global de
    siempre. Es lo que permite preguntar si un tope de tenencia corto sirve para
    **todas** las posiciones o **sólo** para las que entraron con un evento, sin que
    el simulador tenga que saber qué es un evento. **No confundirlo con
    ``time_stop_days``** (tarea 57): el cap cierra a todos al llegar a N —ganadores
    incluidos— y el time stop dispara una sola vez y sólo en pérdida.
    ``trail_min_excess_of`` (TRAIL-ARM, Tarea 54) resuelve el **umbral de armado
    del trailing por posición**, en ATRs sobre la entrada; ``None`` ⇒ el
    ``atr_p.trail_min_excess_atrs`` global. Es lo que permite el **control igualado
    en tasa**: bajarle el umbral a un subconjunto aleatorio de posiciones, a la
    misma frecuencia que el candidato, sin que el simulador sepa qué es un
    control. **``0.0`` es válido** (trailing siempre armado) — a diferencia del
    ``cap_days_of``, donde un 0 no tiene sentido y se cae al global.

    Ídem ``stop_filter`` (brazos oráculo de STOP-CAL, Tarea 26): ``None`` ⇒ el stop
    duro dispara siempre que toque. Y ``eval_mode`` (STOP-PRICE, Tarea 26b):
    ``"close"`` ⇒ la barrera se decide contra el close, como en todas las tareas
    previas; ``"touch"`` la decide contra los extremos de la barra.

    ``fill_mode`` (26b; **default invertido a ``"decision"`` por la Tarea 33**) ⇒ a
    qué precio se llena esa barrera. El legacy ``"resting"`` es look-ahead en modo
    ``close`` y sólo se conserva para reproducir T7/T23/T13/T21/T26 — ver
    ``scaleout_replay._barrier_fill_price``.

    ``live_gates`` (**Tarea 34**, el *sexto* desvío) ⇒ modela los dos gates de
    re-entrada del engine vivo, que este simulador no tenía:

      * **Gate 5 (anti-whipsaw)** — si el **último** ciclo cerrado del ticker dentro
        de ``LIVE_WHIPSAW_LOOKBACK_DAYS`` cerró con pérdida mayor al umbral, el
        re-BUY se bloquea. Con el valor vivo (``0.0``) **cualquier** pérdida bloquea.
      * **Gate 5b (anti-churn)** — ``LIVE_CHURN_MAX_CYCLES`` o más ciclos cerrados
        dentro de ``LIVE_CHURN_LOOKBACK_DAYS`` bloquean, sin mirar el P/L.

    Default **``False``** ⇒ cero cambio para todo lo publicado (T7, R2, T9, T10/T20,
    T11b, T12, T23, T13, T21, T26, T26b), igual que hizo la 26b con ``eval_mode``.

    **Sin look-ahead, por construcción:** el historial se alimenta desde
    ``_release_until``, o sea **sólo** con ciclos cuya salida ocurrió *estrictamente
    antes* de la fecha del candidato. Un ciclo que cierra el mismo día que la entrada
    —o después— no puede bloquearla, aunque el simulador ya conozca su desenlace.
    Y el candidato bloqueado hace ``continue``, así que **el slot se le ofrece al
    siguiente**, igual que en vivo.
    """
    res = PortfolioResult(initial_capital=initial_capital, final_equity=initial_capital)
    cash = initial_capital
    # posiciones abiertas: [(exit_date_iso10, proceeds, ticker, entry_cost)]
    # entry_cost se guarda para topar el sizing por nombre a max_weight de la equity.
    open_positions: list[tuple[str, float, str, float]] = []
    # valor de la cartera por fecha, para la curva de equity
    realized_by_date: dict[str, float] = {}
    all_dates: set[str] = set()

    # Historial de ciclos CERRADOS por ticker: [(exit_date_iso10, ret)], en orden.
    # Sólo lo alimenta ``_release_until``, y sólo con salidas estrictamente anteriores
    # a la fecha que se está procesando ⇒ los gates del T34 no pueden ver el futuro.
    closed_by_ticker: dict[str, list[tuple[str, float]]] = {}
    _ord_cache: dict[str, int] = {}

    def _ord(date_iso10: str) -> int:
        """iso10 → día ordinal, cacheado (se llama millones de veces)."""
        o = _ord_cache.get(date_iso10)
        if o is None:
            o = date.fromisoformat(date_iso10).toordinal()
            _ord_cache[date_iso10] = o
        return o

    def _release_until(date_iso10: str) -> None:
        """Cierra las posiciones cuya salida ya ocurrió antes de ``date_iso10``."""
        nonlocal cash
        still: list[tuple[str, float, str, float]] = []
        closing: list[tuple[str, str, float]] = []
        for exit_date, proceeds, tk, ec in open_positions:
            if exit_date < date_iso10:
                cash += proceeds
                realized_by_date[exit_date] = realized_by_date.get(exit_date, 0.0) + proceeds
                if live_gates:
                    closing.append((exit_date, tk, (proceeds / ec - 1.0) if ec > 0 else 0.0))
            else:
                still.append((exit_date, proceeds, tk, ec))
        open_positions[:] = still
        # ``open_positions`` está en orden de APERTURA, no de salida. Con
        # ``allow_reentry_while_open=True`` un ticker puede tener dos ciclos abiertos
        # que cierran fuera de ese orden, y los dos gates leen el historial con
        # ``reversed()`` asumiendo que el último elemento es el cierre **más
        # reciente**. Ordenar acá mantiene esa invariante. (Entre llamadas ya es
        # monótono: cada una libera exits ≥ los de la anterior.)
        for exit_date, tk, ret in sorted(closing):
            closed_by_ticker.setdefault(tk, []).append((exit_date, ret))

    def _gate5_blocks(ticker: str, entry_date: str) -> bool:
        """Gate 5 vivo (anti-whipsaw, ``engine.py:993``): el **último** ciclo cerrado
        dentro de la ventana cerró con pérdida ⇒ bloquea el re-BUY.

        Espeja la semántica del engine: si el último cierre del ticker quedó **fuera**
        de la ventana, ``_last_closed_cycle_pnl_pct`` devuelve ``None`` y no bloquea —
        o sea que mira el más reciente *dentro* de la ventana, no el más reciente a secas.
        """
        hist = closed_by_ticker.get(ticker)
        if not hist:
            return False
        cutoff = _ord(entry_date) - LIVE_WHIPSAW_LOOKBACK_DAYS
        for exit_date, ret in reversed(hist):
            if _ord(exit_date) < cutoff:
                return False
            return ret * 100.0 < -LIVE_WHIPSAW_MIN_LOSS_PCT
        return False

    def _gate5b_blocks(ticker: str, entry_date: str) -> bool:
        """Gate 5b vivo (anti-churn, ``engine.py:1013``): ``LIVE_CHURN_MAX_CYCLES`` o
        más ciclos cerrados dentro de la ventana ⇒ bloquea, sin mirar el P/L."""
        hist = closed_by_ticker.get(ticker)
        if not hist:
            return False
        cutoff = _ord(entry_date) - LIVE_CHURN_LOOKBACK_DAYS
        n = 0
        for exit_date, _ in reversed(hist):
            if _ord(exit_date) < cutoff:
                break
            n += 1
            if n >= LIVE_CHURN_MAX_CYCLES:
                return True
        return False

    # Agrupadas por fecha: los candidatos de un mismo día compiten entre sí por el
    # slot, y el ranking es lo que resuelve esa competencia.
    by_date: dict[str, list[tuple[str, int]]] = {}
    for ticker, idx in entries:
        bars = bars_by.get(ticker)
        if not bars or idx >= len(bars):
            continue
        by_date.setdefault(bars[idx][0], []).append((ticker, idx))

    for entry_date in sorted(by_date):
        all_dates.add(entry_date)
        _release_until(entry_date)

        day = by_date[entry_date]
        if rank_score is None:
            day = sorted(day, key=lambda ti: ti[0])
        else:
            # Desempate alfabético para que el orden sea determinista aun cuando
            # dos candidatos empaten en score (pasa seguido con scores discretos).
            day = sorted(day, key=lambda ti: (-float(rank_score(ti[0], entry_date)), ti[0]))

        for ticker, idx in day:
            bars = bars_by[ticker]
            res.n_offered += 1

            if not allow_reentry_while_open and any(tk == ticker for _, _, tk, _ in open_positions):
                res.n_already_open += 1
                continue

            # Gates de re-entrada del engine vivo (T34). Como en producción, el
            # candidato bloqueado se saltea y **el slot queda para el siguiente**.
            if live_gates:
                if _gate5_blocks(ticker, entry_date):
                    res.n_gate5_blocked += 1
                    continue
                if _gate5b_blocks(ticker, entry_date):
                    res.n_gate5b_blocked += 1
                    continue

            # g = factor de régimen (mercado); m = peso de riesgo (nombre).
            g = 1.0 if entry_filter is None else float(entry_filter(ticker, entry_date))
            if g <= 0.0:
                res.n_filtered += 1
                continue

            free_slots = max_positions - len(open_positions)
            if free_slots <= 0:
                res.n_no_slot += 1
                continue

            base = cash / free_slots
            if size_weight is None:
                # Comportamiento histórico (R2): el factor de régimen se capea a 1.0
                # y no hay peso por nombre ni tope de concentración.
                size_factor = g
                notional = base * min(1.0, g)
            else:
                m = float(size_weight(ticker, entry_date))
                if not math.isfinite(m) or m <= 0.0:
                    m = 1.0  # sizing desconocido → equal-weight, nunca suprime
                size_factor = m * g
                notional = base * m * g
                # Tope por nombre: nunca más de max_weight de la equity (cash + costo
                # de lo abierto) — evita que una σ diminuta concentre la cartera.
                equity_proxy = cash + sum(ec for _, _, _, ec in open_positions)
                notional = min(notional, max_weight * equity_proxy)
            # Se invierte lo que hay: si el target supera el cash disponible se
            # recorta (no se rechaza — rechazar dejaría cash ocioso Y perdería la
            # entrada). Para el path R2 esto es no-op (notional ≤ base ≤ cash).
            notional = min(notional, cash)
            if notional <= 0 or not math.isfinite(notional):
                res.n_no_cash += 1
                continue

            # Tarea 51: el tope puede depender de la posicion. Un valor no finito
            # o <= 0 seria un cap sin sentido, asi que se cae al global.
            cap_i = cap_days
            if cap_days_of is not None:
                cand = cap_days_of(ticker, entry_date)
                if isinstance(cand, (int, float)) and cand >= 1:
                    cap_i = int(cand)

            # Tarea 54: el umbral de ARMADO del trailing puede depender de la
            # posicion. Un valor no finito o negativo no es un umbral, asi que se
            # cae al global; **0.0 si es valido** (trailing armado desde la
            # entrada), que es justo el brazo extremo de la grilla.
            atr_i = atr_p
            if trail_min_excess_of is not None:
                cand = trail_min_excess_of(ticker, entry_date)
                if (isinstance(cand, (int, float)) and not isinstance(cand, bool)
                        and math.isfinite(cand) and cand >= 0
                        and float(cand) != atr_p.trail_min_excess_atrs):
                    atr_i = replace(atr_p, trail_min_excess_atrs=float(cand))

            cyc = replay_cycle(
                bars, idx, sigs_by.get(ticker) or {},
                params=so_params, atr_p=atr_i, cap_days=cap_i,
                costs=costs, notional=notional,
                regime="" if regime_of is None else regime_of(entry_date),
                time_stop_days=time_stop_days, stop_filter=stop_filter,
                eval_mode=eval_mode, fill_mode=fill_mode,
            )
            if cyc is None:
                continue

            cash -= cyc.entry_cost
            proceeds = cyc.total_proceeds
            exit_date = cyc.legs[-1].date if cyc.legs else entry_date
            open_positions.append((exit_date, proceeds, ticker, cyc.entry_cost))
            all_dates.add(exit_date)
            res.n_taken += 1
            res.trades.append(Trade(
                ticker=ticker, entry_date=entry_date, exit_date=exit_date,
                invested=cyc.entry_cost, proceeds=proceeds,
                regime=cyc.regime, held_days=cyc.held_days,
                exit_reason=cyc.exit_reasons, size_factor=size_factor,
            ))

    # cerrar todo lo que quede
    for _, proceeds, _tk, _ec in open_positions:
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
