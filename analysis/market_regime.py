"""
Detector de régimen de mercado para el gate de BUYs — **Tarea 8 (R2)**.

Pre-registro: ``docs/market_regime_gate_r2_2026-07-20.md`` §3, congelado antes de
codear.

Definición (CONGELADA, sin sweep)
---------------------------------
**risk-off ≡ ``SPY.close < SMA200(SPY.close)``** evaluado con el close de **D−1**
respecto de la barra de entrada.

  * SMA **simple** de 200 ruedas. Elegida por ser la definición canónica de la
    industria, **no** por performance sobre estos datos. Cero parámetros ajustados.
  * **Point-in-time estricto:** usar el close de D sería mirar el futuro — la
    decisión de comprar se toma con la información disponible *antes* de la barra.
  * **Fail-open:** sin 200 barras previas, o con el dato faltante, se devuelve
    risk-**on**. Un filtro de riesgo que se rompe no puede frenar la operatoria.

El módulo es **puro** (stdlib): las barras entran como ``list[Bar]``, así los tests
corren offline y el detector es reusable por el engine sin arrastrar dependencias.

Este módulo **no decide nada por sí solo** — solo describe el estado del mercado.
Quién lo consulta y qué hace con eso vive en el gate (y hoy, en el harness).
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from analysis.exit_replay import Bar

SMA_WINDOW = 200          # congelado (§3 del pre-registro)
CONFIRM_DAYS_DEFAULT = 5  # solo para la variante R2c; valor fijado, no barrido


@dataclass(frozen=True)
class RegimeSeries:
    """Serie precomputada de risk-off por fecha, para consultas O(log n).

    ``risk_off[i]`` corresponde a ``dates[i]`` y responde: *al cierre de ese día,
    ¿SPY estaba por debajo de su SMA200?*
    """

    dates: list[str]
    risk_off: list[bool]
    # Racha de días consecutivos en risk-off al cierre de cada fecha (para R2c).
    streak: list[int]

    def is_risk_off(self, date_iso10: str, *, confirm_days: int = 1) -> bool:
        """¿El día **anterior** a ``date_iso10`` estaba en risk-off (confirmado)?

        Point-in-time: busca la última fecha **estrictamente menor** que la pedida.
        Fail-open (False = risk-on) si no hay historia previa suficiente.
        """
        i = bisect.bisect_left(self.dates, date_iso10) - 1
        if i < 0 or i >= len(self.risk_off):
            return False
        if not self.risk_off[i]:
            return False
        return self.streak[i] >= max(1, confirm_days)


def build_regime_series(spy_bars: list[Bar], *, window: int = SMA_WINDOW) -> RegimeSeries:
    """Precomputa risk-off + racha por fecha desde las barras de SPY.

    Antes de tener ``window`` closes válidos, la SMA no existe → risk-**on**
    (fail-open), nunca se bloquea por falta de datos.
    """
    dates: list[str] = []
    flags: list[bool] = []
    streaks: list[int] = []
    closes: list[float] = []
    running = 0.0
    streak = 0

    for d, _o, _h, _l, c in spy_bars:
        dates.append(d)
        if c is None or not math.isfinite(c) or c <= 0:
            # dato roto: no rompe la serie, se trata como risk-on y no corta racha
            flags.append(False)
            streaks.append(0)
            streak = 0
            continue
        closes.append(c)
        running += c
        if len(closes) > window:
            running -= closes[-window - 1]
        if len(closes) < window:
            flags.append(False)   # fail-open mientras no haya SMA
            streaks.append(0)
            streak = 0
            continue
        sma = running / window
        off = c < sma
        flags.append(off)
        streak = streak + 1 if off else 0
        streaks.append(streak)

    return RegimeSeries(dates=dates, risk_off=flags, streak=streaks)


def make_entry_filter(
    series: RegimeSeries, *, mode: str, confirm_days: int = CONFIRM_DAYS_DEFAULT,
    factor: float = 0.5,
):
    """Construye el ``entry_filter`` del simulador para un brazo pre-registrado.

    Modos (§4 del pre-registro de R2, ampliado por el bloque 10+20):
      * ``"off"``   — baseline: nunca filtra (factor 1.0 siempre).
      * ``"hard"``  — R2a: en risk-off no se abren BUYs (factor 0.0).
      * ``"half"``  — R2b: en risk-off los BUYs entran con medio tamaño (0.5).
      * ``"scale"`` — R2b generalizado (bloque 20): en risk-off el tamaño se escala
        por ``factor`` ∈ (0,1] — el sweep pre-registrado 0.25 / 0.50 / 0.75.
      * ``"confirm"`` — R2c: como ``hard`` pero exige ``confirm_days`` ruedas
        consecutivas bajo la SMA200.

    El filtro **solo** afecta entradas nuevas: el simulador no lo consulta jamás
    para salir (invariante §2 del pre-registro, verificado por test).
    """
    if mode == "off":
        return lambda _ticker, _date: 1.0
    if mode == "hard":
        return lambda _ticker, date: 0.0 if series.is_risk_off(date) else 1.0
    if mode == "half":
        return lambda _ticker, date: 0.5 if series.is_risk_off(date) else 1.0
    if mode == "scale":
        f = float(factor)
        return lambda _ticker, date: f if series.is_risk_off(date) else 1.0
    if mode == "confirm":
        return lambda _ticker, date: (
            0.0 if series.is_risk_off(date, confirm_days=confirm_days) else 1.0
        )
    raise ValueError(f"modo de régimen desconocido: {mode}")
