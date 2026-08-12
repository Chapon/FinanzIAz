"""
Reglas de entrada por pullback — **Tarea 13 (ENT1), brazo (a)**.

Pre-registro con todo congelado (condición, ventana, cancelación, dedup y
kill-criteria): ``docs/ent1_prereg_t13_2026-08-12.md``.

Qué resuelve
------------
Hoy un ``analyze BUY`` se llena **a mercado en el scan siguiente, sin condición de
precio** (``strategies.generate_trades_analyze_single``). El research#2 §B1 propone
el híbrido "el momentum detecta, el pullback entra": la orden espera un retroceso
dentro de una ventana de K días hábiles y, si no llega, **expira sin fillar**.

La ganancia es mecánica, no predictiva: entrando más cerca del stop ATR, el mismo
movimiento adverso cuesta menos R. El costo es que **algunas entradas se pierden**
— por eso el kill-criteria acota la fracción que expira (§5 C6a del pre-registro).

Este módulo es **lógica pura** (stdlib) sobre ``list[Bar]`` + señal PIT como dict:
sin red, sin DB, sin tocar el engine. Transforma una lista de entradas
``(ticker, idx)`` en otra lista ``(ticker, idx_de_fill)`` que ``portfolio_sim``
consume igual, así el brazo se testea sin tocar el simulador.

Detalle que **no** es un detalle: durante la espera el slot **no se ocupa**. La
entrada compite por slot recién el día del fill, y eso es parte del efecto que se
mide (una orden esperando no bloquea a otro candidato).
"""

from __future__ import annotations

from dataclasses import dataclass

from analysis.exit_replay import Bar

# Condiciones de pullback soportadas (§4.1 del pre-registro).
#   "ema20"  → primer close ≤ EMA(20) — la primaria, congelada.
#   "negday" → primer close < close previo — la exploratoria secundaria.
PULLBACK_CONDITIONS = ("ema20", "negday")

EMA_PERIOD = 20
DEFAULT_WINDOW = 5  # K días hábiles


def ema_series(bars: list[Bar], period: int = EMA_PERIOD) -> list[float | None]:
    """EMA de los closes, **point-in-time**: ``out[j]`` sólo usa closes ≤ j.

    Semilla = SMA de las primeras ``period`` barras (convención estándar); antes
    de tener esa ventana completa el valor es ``None`` y la condición de pullback
    no puede evaluarse (la entrada no se filla por falta de dato, no por precio).
    """
    n = len(bars)
    out: list[float | None] = [None] * n
    if period < 1 or n < period:
        return out
    alpha = 2.0 / (period + 1.0)
    seed = sum(b[4] for b in bars[:period]) / period
    out[period - 1] = seed
    prev = seed
    for j in range(period, n):
        prev = alpha * bars[j][4] + (1.0 - alpha) * prev
        out[j] = prev
    return out


def _condition_met(
    bars: list[Bar], j: int, condition: str, ema: list[float | None]
) -> bool:
    if condition == "ema20":
        e = ema[j]
        return e is not None and bars[j][4] <= e
    if condition == "negday":
        return j > 0 and bars[j][4] < bars[j - 1][4]
    raise ValueError(f"condición de pullback desconocida: {condition!r}")


@dataclass
class PullbackOutcome:
    """Cómo se resolvió una espera. ``fill_idx`` es ``None`` salvo en ``filled``."""

    status: str          # "filled" | "expired" | "cancelled"
    fill_idx: int | None
    resolved_idx: int    # última barra que consumió la espera (para el dedup)


def resolve_pullback(
    bars: list[Bar],
    signal_idx: int,
    signals: dict,
    *,
    window: int = DEFAULT_WINDOW,
    condition: str = "ema20",
    ema: list[float | None] | None = None,
) -> PullbackOutcome:
    """Resuelve una espera abierta por la señal BUY de ``signal_idx``.

    Se evalúan los closes de ``signal_idx+1 … signal_idx+window`` en orden:

      1. Si la señal PIT vira a ``SELL`` ese día ⇒ ``cancelled`` (la razón para
         comprar desapareció; comprar igual sería absurdo).
      2. Si se cumple la condición de pullback ⇒ ``filled`` en esa barra.
      3. Agotada la ventana ⇒ ``expired``.

    El fill exige que quede **al menos una barra posterior** (``fill_idx ≤ n-2``),
    porque ``replay_cycle`` necesita futuro para correr el ciclo; una barra sin
    futuro cuenta como ventana agotada, no como fill fantasma.
    """
    if condition not in PULLBACK_CONDITIONS:
        raise ValueError(f"condición de pullback desconocida: {condition!r}")
    n = len(bars)
    if ema is None:
        ema = ema_series(bars)
    last = min(signal_idx + max(0, window), n - 2)
    for j in range(signal_idx + 1, last + 1):
        if signals.get(bars[j][0]) == "SELL":
            return PullbackOutcome("cancelled", None, j)
        if _condition_met(bars, j, condition, ema):
            return PullbackOutcome("filled", j, j)
    return PullbackOutcome("expired", None, min(signal_idx + max(0, window), n - 1))


@dataclass
class PullbackStats:
    """Contabilidad de la transformación (alimenta el sanity §6.2 y el C6a)."""

    n_signals: int = 0      # señales BUY vistas
    n_waits: int = 0        # señales que efectivamente abrieron una espera
    n_filled: int = 0
    n_expired: int = 0
    n_cancelled: int = 0
    n_dup_skipped: int = 0  # BUY del mismo ticker con una espera ya viva

    @property
    def expired_share(self) -> float:
        """Fracción de esperas que agotaron la ventana — el criterio C6a."""
        return self.n_expired / self.n_waits if self.n_waits else 0.0

    @property
    def lost_share(self) -> float:
        """Fracción de esperas que no terminaron en fill (expiradas + canceladas)."""
        return (self.n_expired + self.n_cancelled) / self.n_waits if self.n_waits else 0.0

    @property
    def fill_share(self) -> float:
        return self.n_filled / self.n_waits if self.n_waits else 0.0


def apply_pullback(
    entries: list[tuple[str, int]],
    bars_by: dict[str, list[Bar]],
    sigs_by: dict[str, dict],
    *,
    window: int = DEFAULT_WINDOW,
    condition: str = "ema20",
) -> tuple[list[tuple[str, int]], PullbackStats]:
    """Transforma las entradas ``(ticker, señal_idx)`` en ``(ticker, fill_idx)``.

    Las que expiran o se cancelan **desaparecen** de la lista: son entradas que el
    brazo no toma. El resultado sale ordenado cronológicamente (con desempate
    alfabético), que es lo que ``portfolio_sim`` espera.

    **Dedup (§4.1):** una espera por ticker; mientras una está viva, los BUY
    posteriores del mismo ticker se ignoran. Sin esto, un BUY sostenido varios
    días abriría una espera por día y el brazo tomaría más entradas que el
    baseline, contaminando la comparación.
    """
    stats = PullbackStats()
    out: list[tuple[str, int]] = []
    by_ticker: dict[str, list[int]] = {}
    for ticker, idx in entries:
        by_ticker.setdefault(ticker, []).append(idx)

    for ticker, idxs in by_ticker.items():
        bars = bars_by.get(ticker)
        if not bars:
            continue
        ema = ema_series(bars) if condition == "ema20" else []
        blocked_until = -1
        for idx in sorted(idxs):
            stats.n_signals += 1
            if idx <= blocked_until:
                stats.n_dup_skipped += 1
                continue
            res = resolve_pullback(
                bars, idx, sigs_by.get(ticker) or {},
                window=window, condition=condition, ema=ema,
            )
            stats.n_waits += 1
            blocked_until = res.resolved_idx
            if res.status == "filled" and res.fill_idx is not None:
                stats.n_filled += 1
                out.append((ticker, res.fill_idx))
            elif res.status == "expired":
                stats.n_expired += 1
            else:
                stats.n_cancelled += 1

    out.sort(key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]))
    return out, stats
