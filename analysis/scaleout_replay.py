"""
Replay de scale-out parcial + trailing del remanente — backlog **Tarea 7**.

Pre-registro (kill-criteria congelados ANTES de correr):
``docs/scaleout_trailing_t7_2026-07-20.md``.

Qué mide
--------
Hoy un ``analyze SELL`` cierra el **100%** de la posición
(``strategies.generate_trades_analyze_single``). Acá se simula, desde una entrada
point-in-time, qué habría pasado vendiendo solo una **fracción** en el flip y
dejando correr el remanente bajo el trailing ATR — más la variante de jerarquía
nivel-vs-señal (gap A4) y el sweep del múltiplo del trailing (research#2 §C1).

Diseño
------
Todo es **lógica pura** (stdlib): las barras entran como ``list[Bar]`` y la señal
PIT como un ``dict[iso10, str]`` precomputado (ver
``scripts/precompute_pit_signals.py``), así los tests corren offline con datos
sintéticos y el replay es determinista y reproducible.

Reusa el motor ATR ya validado de ``analysis.exit_replay`` (``atr_series``,
``atr_exit``, ``_atr_trigger_level``, ``_exit_fill_price``) — no se reimplementa
la mecánica de salida, solo se la aplica a una posición que puede cerrarse en
**dos tramos**.

Contrafactual (congelado en el doc §3)
--------------------------------------
1. La fracción vendida sale al **close de la barra del flip**, con costos completos.
2. El remanente sigue bajo la maquinaria ATR real: stop desde el ``avg_cost``
   **original**, trailing desde el HWM (que **no se resetea** en el scale-out), TP;
   fills gap/touch.
3. Cap de ``cap_days`` días hábiles; al cap el remanente sale al close.
4. El cash liberado **no se reinvierte** (ni en el baseline, que libera el 100%).
5. El scale-out paga **un fill de salida extra** — la fricción no se le perdona.
6. Gate 2b vigente en todos los brazos: un SELL de señal con edad < 3 días hábiles
   se difiere salvo score < ``bypass_score``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable

from analysis.exit_replay import (
    AtrParams,
    Bar,
    _atr_trigger_level,
    _exit_fill_price,
    atr_exit,
    atr_series,
)

# Señal PIT: {iso10: "BUY"|"SELL"|"HOLD"}. Fechas ausentes ⇒ sin señal ese día.
SignalSeries = dict

# ``stop_filter(bars, i) -> bool``: ¿se le permite al **stop duro** disparar en la
# barra ``i``? Sirve para los brazos oráculo de la Tarea 26 (STOP-CAL), que gatean
# el stop con información del futuro para validar la sensibilidad del harness.
# ``None`` (default) ⇒ el stop dispara siempre que toque, o sea el comportamiento
# de T7/T23/T13/T21 sin cambio alguno.
StopFilter = Callable[[list[Bar], int], bool]

# Múltiplo que pone el nivel del stop en negativo ⇒ el guard ``> 0`` lo apaga.
_NO_STOP = 1e9


@dataclass(frozen=True)
class CostModel:
    """Comisión + slippage como fracción del notional (espejo de la cuenta viva)."""

    commission: float = 0.001   # 0.1%
    slippage: float = 0.0005    # 0.05%

    def sell_proceeds(self, shares: float, price: float) -> float:
        """Efectivo neto de vender ``shares`` a ``price`` (costos descontados)."""
        gross = shares * price
        return gross - gross * (self.commission + self.slippage)

    def buy_cost(self, shares: float, price: float) -> float:
        """Costo total de comprar ``shares`` a ``price`` (costos incluidos)."""
        gross = shares * price
        return gross + gross * (self.commission + self.slippage)


@dataclass(frozen=True)
class ScaleOutParams:
    """Parámetros de un brazo del pre-registro."""

    # Fracción vendida en el flip de señal:
    #   1.0 → cierra entero = comportamiento actual (baseline B0)
    #   0.5 → scale-out del 50% (brazo A₅₀)
    #   0.0 → la señal NO vende: solo salen stop / TP / cap. Es la jerarquía
    #         nivel-vs-señal del gap A4 ("los niveles mandan") en su forma
    #         separable — ver la nota de abajo.
    sell_fraction: float = 1.0
    # Gate 2b — histéresis del engine vivo (T6.4).
    min_age_bdays: int = 3
    bypass_score: float = 0.25


@dataclass
class Leg:
    """Un tramo de salida (el parcial del flip, o el cierre del remanente)."""

    date: str
    price: float
    shares: float
    reason: str
    proceeds: float


@dataclass
class CycleResult:
    """Resultado de un ciclo completo bajo un brazo."""

    ticker: str
    entry_date: str
    entry_price: float
    shares: float
    entry_cost: float = 0.0   # lo que costó abrir, con costos
    regime: str = ""
    legs: list[Leg] = field(default_factory=list)
    # Curva diaria de valor de la posición (MTM + cash ya realizado), para el DD
    # compuesto. [(iso10, valor_total)] incluyendo el día de entrada.
    daily_value: list[tuple[str, float]] = field(default_factory=list)
    # Excursiones sobre el capital invertido inicial.
    mae: float = 0.0   # max adverse excursion (fracción negativa o 0)
    mfe: float = 0.0   # max favourable excursion (fracción positiva o 0)

    @property
    def total_proceeds(self) -> float:
        return sum(l.proceeds for l in self.legs)

    @property
    def ret(self) -> float:
        """Retorno neto sobre el capital invertido (fracción)."""
        if self.entry_cost <= 0:
            return 0.0
        return self.total_proceeds / self.entry_cost - 1.0

    @property
    def exit_reasons(self) -> str:
        return "+".join(l.reason for l in self.legs)

    @property
    def held_days(self) -> int:
        return len(self.daily_value) - 1 if self.daily_value else 0


def _fired_barrier(bar: Bar, *, avg_cost: float, hwm: float, atr_value: float,
                   p: AtrParams, eval_mode: str) -> str | None:
    """Qué barrera ATR dispara en ``bar``, según **contra qué precio se decide**.

    * ``"close"`` — contra el close, que es lo que hicieron T7/T23/T13/T21/T26.
    * ``"touch"`` — contra los extremos: ``low`` para las barreras de abajo (stop y
      trailing) y ``high`` para el take-profit.

    **Empate dentro de la misma barra:** si el mínimo perforó el stop y el máximo
    perforó el TP, gana el **stop**. El OHLC no dice cuál pasó primero, así que se
    congela la convención **adversa** (pre-registro 26b §3). Evaluar primero contra
    el ``low`` produce exactamente eso, y de paso preserva el orden interno del
    engine (stop → trail → TP).
    """
    _, _open, high, low, close = bar
    if eval_mode == "close":
        return atr_exit(current_price=close, avg_cost=avg_cost,
                        high_water_mark=hwm, atr_value=atr_value, p=p)

    down = atr_exit(current_price=low, avg_cost=avg_cost,
                    high_water_mark=hwm, atr_value=atr_value, p=p)
    if down is not None:
        return down
    # Las barreras de abajo ya quedaron descartadas contra el ``low`` (y ``low`` es
    # el precio más adverso de la barra), así que acá sólo puede aparecer el TP.
    up = atr_exit(current_price=high, avg_cost=avg_cost,
                  high_water_mark=hwm, atr_value=atr_value, p=p)
    return up if up == "atr_tp" else None


def _barrier_fill_price(bar: Bar, fired: str, level: float | None, *,
                        eval_mode: str, fill_mode: str) -> float:
    """A qué precio se llena la barrera que disparó en ``bar``.

    ``fill_mode``:

    * ``"decision"`` (default desde la Tarea 33) — el fill es el precio que **tomó
      la decisión**: el nivel (o el open si abrió con gap) cuando se decide al
      toque, y el **close** cuando se decide al close.
    * ``"resting"`` (legacy) — siempre el modelo gap/toque de ``_exit_fill_price``:
      espejo de ``gates.model_exit_fill_price``, o sea una **orden en reposo** en
      el nivel. Es lo que corrieron T7/T23/T13/T21/T26; se conserva para
      reproducir esas corridas, no para escribir harness nuevos.

    **Por qué ``"resting"`` es incoherente en modo ``close`` (Tarea 26b):** una
    orden en reposo en el nivel se habría ejecutado *intradía*, cuando el ``low``
    lo tocó — que es la regla ``touch``, no la ``close``. No se puede tener la
    orden en reposo y a la vez salir sólo cuando el close confirma: son reglas
    mutuamente excluyentes. Como al disparar al close vale ``low ≤ close ≤ nivel``,
    el fill legacy devuelve **siempre** el nivel, un precio mejor que el close y
    tocado *antes* de existir la información que decidió — look-ahead.
    Con ``"decision"`` el close-mode llena al close, que es además la convención
    que el harness ya usa para todas las otras salidas decididas al close (flip de
    señal y cap).

    **Bajo ``eval_mode="touch"`` los dos modos coinciden** y no es una casualidad:
    ahí el precio que decide *es* el nivel (o el open si la barra abrió con gap),
    así que el modelo de orden en reposo y el precio de la decisión son el mismo
    número. El flag sólo muerde en modo ``close``.
    """
    if fill_mode == "resting" or eval_mode == "touch":
        return _exit_fill_price(fired, level, bar)
    return bar[4]


def _idx_of(bars: list[Bar], date_iso10: str) -> int:
    for i, b in enumerate(bars):
        if b[0] >= date_iso10:
            return i
    return len(bars)


def replay_cycle(
    bars: list[Bar],
    entry_idx: int,
    signals: SignalSeries,
    *,
    params: ScaleOutParams,
    atr_p: AtrParams,
    cap_days: int = 20,
    costs: CostModel = CostModel(),
    notional: float = 10_000.0,
    scores: dict | None = None,
    regime: str = "",
    time_stop_days: int | None = None,
    stop_filter: StopFilter | None = None,
    eval_mode: str = "close",
    fill_mode: str = "decision",
) -> CycleResult | None:
    """Simula un ciclo desde ``entry_idx`` (entrada al close) bajo un brazo.

    La posición se abre con ``notional`` dólares. Cada día, en el orden del engine:

      1. Se evalúa el **ATR** con el HWM *previo* al close (stop → trail → TP).
         Si dispara, cierra **todo** lo que quede (los niveles siempre son totales).
      2. Si no disparó y hay un **flip a SELL** en la señal PIT (y pasa el Gate 2b),
         se vende la fracción; si ya se había vendido el parcial, el siguiente flip
         cierra el resto (no se vende una fracción de la fracción indefinidamente).
      2b. **Time stop** (ENT1 brazo b, opcional): exactamente en la barra
         ``time_stop_days`` desde la entrada, si liquidar al close no recupera el
         costo de entrada (P/L ≤ 0 **neto de costos**) se cierra el remanente.
      3. Al ``cap_days`` se cierra lo que quede al close.
      4. Recién ahí se actualiza el HWM con el close del día.

    ``time_stop_days=None`` (default) ⇒ el paso 2b no existe y el comportamiento es
    idéntico al de T7/T23 — este parámetro no puede cambiar sus resultados.

    ``stop_filter=None`` (default) ⇒ ídem para el paso 1: el stop duro dispara
    siempre que toque. Cuando se pasa, gatea **sólo** al ``atr_stop`` (Tarea 26).

    ``eval_mode`` (Tarea 26b) — **contra qué precio se decide** la barrera del paso 1:

    * ``"close"`` (default) ⇒ dispara si el **close** cruzó el nivel. Es lo que
      midieron T7/T23/T13/T21/T26, así que el default no cambia ningún resultado.
    * ``"touch"`` ⇒ dispara si el **extremo** de la barra lo cruzó (``low`` para
      stop/trailing, ``high`` para el TP). Es la cota superior de frecuencia de
      disparo del engine vivo, que decide contra el precio corriente intradía.

    Los dos **acotan** al engine (que samplea cada ~15 min), ninguno lo reproduce —
    ver ``analysis/harness_config.py`` y el pre-registro de la 26b.

    ``fill_mode`` (Tarea 26b, **default invertido por la Tarea 33**) — a **qué
    precio** se llena esa barrera; ver ``_barrier_fill_price``. ``"decision"``
    (default) ⇒ el precio que tomó la decisión, el único coherente cuando se decide
    al close. ``"resting"`` ⇒ el modelo gap/toque de siempre: en modo ``close`` es
    **look-ahead** (llena en el nivel, mejor que el close y tocado antes de que
    existiera la información que decidió) y por eso dejó de ser el default; se
    conserva sólo para reproducir T7/T23/T13/T21/T26.

    Devuelve ``None`` si no hay barras suficientes.
    """
    if eval_mode not in ("close", "touch"):
        raise ValueError(f"eval_mode inválido: {eval_mode!r} (esperado 'close' o 'touch')")
    if fill_mode not in ("resting", "decision"):
        raise ValueError(
            f"fill_mode inválido: {fill_mode!r} (esperado 'resting' o 'decision')")
    n = len(bars)
    if not bars or entry_idx >= n - 1:
        return None

    entry_price = bars[entry_idx][4]
    if not math.isfinite(entry_price) or entry_price <= 0:
        return None

    shares = notional / entry_price
    entry_cost = costs.buy_cost(shares, entry_price)
    avg_cost = entry_cost / shares  # costo por share incluyendo fees (como el engine)

    atrs = atr_series(bars, atr_p.period)
    res = CycleResult(
        ticker="", entry_date=bars[entry_idx][0], entry_price=entry_price,
        shares=shares, entry_cost=entry_cost, regime=regime,
    )
    res.daily_value.append((bars[entry_idx][0], entry_cost))

    hwm = entry_price
    remaining = shares
    realized_cash = 0.0
    scaled_out = False  # ya se ejecutó el tramo parcial
    last_idx = min(entry_idx + cap_days, n - 1)

    for i in range(entry_idx + 1, last_idx + 1):
        date_i, _, _, _, close_i = bars[i]
        a = atrs[i]

        # ── 1. Niveles ATR (siempre cierran el remanente entero) ──────────────
        fired = None
        p_eff = atr_p
        if a is not None:
            fired = _fired_barrier(bars[i], avg_cost=avg_cost, hwm=hwm,
                                   atr_value=a, p=atr_p, eval_mode=eval_mode)
            if (fired == "atr_stop" and stop_filter is not None
                    and not stop_filter(bars, i)):
                # Stop suprimido en esta barra (brazos oráculo de la T26). Se
                # re-evalúa la misma barra con el stop apagado y el trailing
                # **pineado en su múltiplo efectivo**: sin ese pin, apagar el
                # stop apagaría también al trail, que por default comparte
                # múltiplo con él (espejo de ``gates.py``). Así el filtro toca
                # una sola barrera, que es lo que el pre-registro congeló.
                p_eff = replace(atr_p, stop_mult=_NO_STOP,
                                trail_mult=atr_p.effective_trail_mult)
                fired = _fired_barrier(bars[i], avg_cost=avg_cost, hwm=hwm,
                                       atr_value=a, p=p_eff, eval_mode=eval_mode)
        if fired is not None:
            level = _atr_trigger_level(fired, avg_cost=avg_cost, hwm=hwm,
                                       atr_value=a, p=p_eff)
            px = _barrier_fill_price(bars[i], fired, level,
                                     eval_mode=eval_mode, fill_mode=fill_mode)
            proceeds = costs.sell_proceeds(remaining, px)
            res.legs.append(Leg(date_i, px, remaining, fired, proceeds))
            realized_cash += proceeds
            remaining = 0.0
            res.daily_value.append((date_i, realized_cash))
            break

        # ── 2. Flip de señal ──────────────────────────────────────────────────
        sig = signals.get(date_i)
        if sig == "SELL" and _passes_hysteresis(
            bars, entry_idx, i, scores, date_i, params
        ):
            frac = _fraction_to_sell(params, scaled_out)
            if frac > 0:
                sell_shares = remaining * frac
                proceeds = costs.sell_proceeds(sell_shares, close_i)
                reason = "signal_full" if frac >= 1.0 else "signal_partial"
                res.legs.append(Leg(date_i, close_i, sell_shares, reason, proceeds))
                realized_cash += proceeds
                remaining -= sell_shares
                scaled_out = True
                if remaining <= 1e-9:
                    res.daily_value.append((date_i, realized_cash))
                    break

        # ── 2b. Time stop (ENT1 brazo b) ──────────────────────────────────────
        # Chequeo de **una sola vez** en la barra N (no rolling): si a los N días
        # la posición no avanzó, el slot se libera. La condición se evalúa sobre
        # el P/L neto real —lo que quedaría si liquidara al close, contra lo que
        # costó abrir— no sobre el precio, así los costos de las dos puntas
        # cuentan igual que en el resto del harness.
        if (
            time_stop_days is not None
            and remaining > 0
            and (i - entry_idx) == time_stop_days
        ):
            net_if_closed = realized_cash + costs.sell_proceeds(remaining, close_i)
            if net_if_closed <= entry_cost:
                proceeds = costs.sell_proceeds(remaining, close_i)
                res.legs.append(Leg(date_i, close_i, remaining, "time_stop", proceeds))
                realized_cash += proceeds
                remaining = 0.0
                res.daily_value.append((date_i, realized_cash))
                break

        # ── 3. Cap ────────────────────────────────────────────────────────────
        if i == last_idx and remaining > 0:
            proceeds = costs.sell_proceeds(remaining, close_i)
            res.legs.append(Leg(date_i, close_i, remaining, "cap_reached", proceeds))
            realized_cash += proceeds
            remaining = 0.0
            res.daily_value.append((date_i, realized_cash))
            break

        # valor del día = cash realizado + MTM de lo que queda
        res.daily_value.append((date_i, realized_cash + remaining * close_i))

        # ── 4. Recién ahora se actualiza el HWM ───────────────────────────────
        hwm = max(hwm, close_i)

    # excursiones sobre el capital invertido
    if res.daily_value and entry_cost > 0:
        vals = [v for _, v in res.daily_value]
        res.mfe = max(0.0, max(vals) / entry_cost - 1.0)
        res.mae = min(0.0, min(vals) / entry_cost - 1.0)
    return res


def _passes_hysteresis(
    bars: list[Bar], entry_idx: int, i: int,
    scores: dict | None, date_i: str, params: ScaleOutParams,
) -> bool:
    """Gate 2b del engine vivo (T6.4): el SELL de señal espera ``min_age_bdays``
    días hábiles salvo que el score sea < ``bypass_score`` (convicción alta de salir).
    """
    age = i - entry_idx
    if age >= params.min_age_bdays:
        return True
    if scores is not None:
        sc = scores.get(date_i)
        if sc is not None and sc < params.bypass_score:
            return True
    return False


def _fraction_to_sell(params: ScaleOutParams, scaled_out: bool) -> float:
    """Fracción del remanente a vender ante un flip de señal.

    * Baseline (``sell_fraction=1.0``) ⇒ siempre 1.0 (cierra entero).
    * Scale-out ⇒ ``sell_fraction`` la primera vez; el **segundo** flip cierra el
      resto (si no, una posición en SELL crónico se iría vendiendo por mitades
      eternamente, que no es la política que se quiere testear).
    * ``sell_fraction=0.0`` ⇒ la señal nunca vende: mandan los niveles (gap A4).

    **Por qué no hay una regla explícita de "en los extremos manda el nivel":**
    se implementó y resultó *inalcanzable*. ``replay_cycle`` evalúa los niveles ATR
    **antes** que la señal y un stop/TP siempre cierra el remanente entero, así que
    para cuando la señal se evalúa el precio ya está, por construcción, dentro de la
    banda ``(stop, TP)``. La cláusula nunca se ejecutaba. La forma separable —y la
    que el gap A4 realmente propone— es que la señal **no preempte** al nivel, o sea
    ``sell_fraction`` chica (0.0 en el extremo).
    """
    if params.sell_fraction >= 1.0:
        return 1.0
    if scaled_out:
        return 1.0  # segundo flip ⇒ cierra el remanente
    return max(0.0, min(1.0, params.sell_fraction))
