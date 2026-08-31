"""
Inyección de ruina — enabler de la **Tarea 37** (STOP-VALUE).

Por qué existe
--------------
El universo del harness son **127 sobrevivientes**: la watchlist viva en 2026 con
diez años de historia. Por construcción ninguno quebró, ninguno fue deslistado,
ninguno fue a cero. Ese es **el ambiente más benévolo posible para no tener stop**,
y el brazo que apaga el stop duro es el que más lo explota de toda la serie (T34 §3).

No se puede corregir con los datos que hay, así que se lo **acota**: se inyecta
ruina sintética a una tasa **medida dentro del propio universo** y se mide si el
candidato sigue ganándole al baseline. La cota se vuelve criterio (**C9** del
pre-registro ``docs/stop_value_prereg_t37_2026-08-19.md`` §3).

El principio de diseño
----------------------
**Se modifican los DATOS, no el motor.** Las series salen de acá una sola vez por
``(rate, depth, shape, seed)`` y **todos los brazos ven exactamente el mismo
mundo**, así la comparación sigue siendo pareada. ``bars_digest`` existe para
verificarlo (sanity §7.6).

Las **señales PIT no se regeneran**: el evento es, por construcción, invisible
para ``analyze()``. Es realista para fraude/quiebra y es **conservador para el
candidato**, porque le saca al flip de señal —su barrera dominante— la posibilidad
de reaccionar.

Forma del evento
----------------
Con hazard ``rate/252`` por rueda, cada ticker puede entrar en un **evento
terminal** en una fecha sorteada. Desde el cierre de esa barra el precio cae
**linealmente en log** hasta ``−depth`` a lo largo de ``span`` ruedas, y después
queda **plano** (o=h=l=c) hasta el final de la serie: un nombre que dejó de
cotizar no vuelve a hacer precio.

* ``shape="gradual"`` (span=20) **es la que decide**. Es la **más favorable al
  stop duro**: le da veinte barras para dispararse.
* ``shape="gap"`` (span=1) se reporta como **sensibilidad**, no decide. Una caída
  de una sola barra rigearía el test a favor del candidato, porque ahí ninguna
  barrera salva nada.

Lógica pura: stdlib, sin I/O, sin red, determinista por semilla.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

from analysis.exit_replay import Bar

# Ruedas por año — el mismo denominador que usa el resto del harness.
TRADING_DAYS = 252

# §3 del pre-registro: las dos formas, con su span en ruedas.
SHAPE_SPANS: dict[str, int] = {"gradual": 20, "gap": 1}
DECIDING_SHAPE = "gradual"

# Semilla base congelada + las tres corridas (+0/+1/+2). El criterio se aplica a
# la PEOR de las tres, no al promedio.
BASE_SEED = 20260819
N_SEEDS = 3


@dataclass(frozen=True)
class RuinEvent:
    """Un evento terminal inyectado en un ticker."""

    ticker: str
    start_idx: int
    start_date: str
    anchor_close: float
    terminal_close: float
    span: int
    n_bars_after: int  # barras de la serie que quedan desde start_idx

    @property
    def completes(self) -> bool:
        """¿La serie tiene largo para que la caída llegue a ``−depth``?"""
        return self.n_bars_after > self.span


def seeds(base: int = BASE_SEED, n: int = N_SEEDS) -> tuple[int, ...]:
    """Las ``n`` semillas congeladas: ``base+0``, ``base+1``, …"""
    return tuple(base + i for i in range(n))


def _rng(seed: int, ticker: str) -> random.Random:
    """RNG por ``(semilla, ticker)``.

    Derivar del **nombre** y no de un contador hace que el sorteo **no dependa
    del orden de iteración** del diccionario: el mismo ticker recibe el mismo
    evento aunque el universo cambie de tamaño o de orden. Es lo que permite
    comparar barridos entre sí.
    """
    return random.Random(f"t37-ruin|{seed}|{ticker}")


def _draw_start(rng: random.Random, n_bars: int, rate: float) -> int | None:
    """Primera barra donde dispara el hazard ``rate/252``, o ``None``.

    Se sortea barra a barra (en vez de una geométrica cerrada) porque es la
    lectura literal de *"hazard por rueda"* y no depende de convenciones de
    truncado. Con ``rate=0`` no se consume ninguna extracción: la serie tiene que
    volver **idéntica**, no equivalente.
    """
    if rate <= 0.0 or n_bars <= 1:
        return None
    p = rate / TRADING_DAYS
    if p <= 0.0:
        return None
    for i in range(n_bars):
        if rng.random() < p:
            return i
    return None


def _decline_factor(j: int, depth: float, span: int) -> float:
    """Multiplicador log-lineal de la caída en la rueda ``j`` desde el evento.

    ``j=0`` ⇒ 1.0 (la barra del evento no se toca) y ``j=span`` ⇒ ``1−depth``
    **exacto**, que es lo que el test del §11.4 verifica.
    """
    if j <= 0:
        return 1.0
    if j >= span:
        return 1.0 - depth
    return math.exp(math.log(1.0 - depth) * (j / span))


def _apply_event(
    bars: list[Bar], start_idx: int, depth: float, span: int
) -> tuple[list[Bar], RuinEvent | None]:
    """Devuelve la serie con el evento aplicado desde ``start_idx``."""
    n = len(bars)
    if not (0 <= start_idx < n):
        return bars, None
    anchor_close = bars[start_idx][4]
    if not math.isfinite(anchor_close) or anchor_close <= 0:
        return bars, None

    terminal = anchor_close * (1.0 - depth)
    out: list[Bar] = list(bars[: start_idx + 1])

    for j in range(1, n - start_idx):
        idx = start_idx + j
        date, o, h, lo, c = bars[idx]
        if j >= span:
            # Plano: dejó de hacer precio. Una barra sin rango.
            out.append((date, terminal, terminal, terminal, terminal))
            continue
        target_close = anchor_close * _decline_factor(j, depth, span)
        # Se escala la barra ENTERA por el ratio con su close original, así se
        # preserva la forma intradía (el rango relativo) y el close cae justo
        # sobre el camino log-lineal.
        if not math.isfinite(c) or c <= 0:
            out.append((date, target_close, target_close, target_close, target_close))
            continue
        k = target_close / c
        out.append((date, o * k, h * k, lo * k, c * k))

    ev = RuinEvent(
        ticker="",
        start_idx=start_idx,
        start_date=bars[start_idx][0],
        anchor_close=anchor_close,
        terminal_close=terminal,
        span=span,
        n_bars_after=n - start_idx,
    )
    return out, ev


def inject_ruin(
    bars_by: dict[str, list[Bar]],
    *,
    rate: float,
    depth: float,
    shape: str = DECIDING_SHAPE,
    seed: int = BASE_SEED,
) -> tuple[dict[str, list[Bar]], list[RuinEvent]]:
    """Inyecta eventos terminales en ``bars_by``. **Puro y determinista.**

    ``rate`` es anual (0.026 = 2,6%/año) y ``depth`` es la caída objetivo
    (0.50 = −50%). Devuelve ``(bars_modificadas, eventos)``.

    Con ``rate=0`` devuelve **los mismos objetos lista** —no copias— así que la
    identidad es verificable con ``is`` además de con hash. Los tickers sin
    evento tampoco se copian.
    """
    if shape not in SHAPE_SPANS:
        raise ValueError(f"shape desconocida: {shape!r} (esperaba {sorted(SHAPE_SPANS)})")
    if not (0.0 < depth < 1.0):
        raise ValueError(f"depth fuera de (0,1): {depth!r}")
    if rate < 0.0:
        raise ValueError(f"rate negativa: {rate!r}")

    span = SHAPE_SPANS[shape]
    out: dict[str, list[Bar]] = {}
    events: list[RuinEvent] = []

    for ticker in sorted(bars_by):  # orden estable, aunque el RNG no dependa
        bars = bars_by[ticker]
        if not bars or rate <= 0.0:
            out[ticker] = bars
            continue
        start = _draw_start(_rng(seed, ticker), len(bars), rate)
        if start is None:
            out[ticker] = bars
            continue
        new_bars, ev = _apply_event(bars, start, depth, span)
        out[ticker] = new_bars
        if ev is not None:
            events.append(
                RuinEvent(
                    ticker=ticker,
                    start_idx=ev.start_idx,
                    start_date=ev.start_date,
                    anchor_close=ev.anchor_close,
                    terminal_close=ev.terminal_close,
                    span=ev.span,
                    n_bars_after=ev.n_bars_after,
                )
            )
    return out, events


def bars_digest(bars_by: dict[str, list[Bar]]) -> str:
    """SHA-256 del universo entero de barras — sanity §7.6.

    Dos brazos que corren sobre el mismo mundo tienen que dar el **mismo**
    digest. Los floats se serializan con ``repr`` (round-trip exacto en CPython),
    así que el digest distingue diferencias que un redondeo taparía.
    """
    h = hashlib.sha256()
    for ticker in sorted(bars_by):
        h.update(ticker.encode("utf-8"))
        h.update(b"\x1f")
        for date, o, hi, lo, c in bars_by[ticker]:
            h.update(f"{date}|{o!r}|{hi!r}|{lo!r}|{c!r}\x1e".encode())
        h.update(b"\x1d")
    return h.hexdigest()


def event_summary(events: list[RuinEvent], n_tickers: int, total_ticker_years: float | None = None) -> dict:
    """Descriptivo del barrido: cuántos eventos, en cuántos nombres, y la tasa."""
    completed = [e for e in events if e.completes]
    out = {
        "n_events": len(events),
        "n_completed": len(completed),
        "n_tickers_hit": len({e.ticker for e in events}),
        "n_tickers": n_tickers,
        "share_tickers_hit": (len({e.ticker for e in events}) / n_tickers if n_tickers else 0.0),
    }
    if total_ticker_years:
        out["events_per_ticker_year"] = len(events) / total_ticker_years
    return out


def ticker_years(bars_by: dict[str, list[Bar]]) -> float:
    """Ticker-años del universo, para reportar la tasa efectiva del barrido."""
    return sum(len(b) for b in bars_by.values()) / TRADING_DAYS
