"""
Detector de anomalía precio/volumen — enabler de la **Tarea 11, Brazo B**.

Pre-registro CONGELADO (kill-criteria ANTES de codear):
``docs/anomaly_signal_prereg_t11b_2026-07-23.md``.

Qué detecta (§2 del pre-registro, forma congelada — sin sweep)
-------------------------------------------------------------
Sobre las barras diarias de un ticker + su serie de **volumen** alineada, la barra
``i`` (con ``i >= warmup``) dispara una anomalía si se cumplen **las dos**:

  1. **Salto de precio positivo:** ``close[i] - close[i-1] >= k * ATR14[i]``
     — un movimiento diario al alza de al menos ``k`` ATRs. Long-only: solo el
     lado positivo (la simetría short queda fuera de alcance, ref backlog).
  2. **Volumen anómalo:** ``volume[i] >= m * ADV20[i]``, con
     ``ADV20[i] = media(volume[i-20 : i])`` (las 20 ruedas **estrictamente
     anteriores** a ``i`` — el nivel *normal* previo, no incluye a la propia
     barra del evento).

**Entrada:** al close del día hábil **siguiente** (``entry_idx = i + 1``).
Point-in-time estricto: la anomalía queda determinada por datos hasta el close de
``i`` (el scan EOD), y la orden se llena en la rueda siguiente — exactamente cómo
actuaría el engine vivo (scan post-close → fill al próximo close).

**Refractario:** tras una anomalía aceptada en un ticker, se saltean las
siguientes en ese mismo ticker por ``refractory`` ruedas — evita clustering
degenerado y espeja el "no reabrir mientras está en cartera" del engine.

Por qué el ``AND`` ret+volumen (caveat de datos): el volumen de yfinance puede no
estar ajustado por splits → un split infla el volumen. Pero la condición (1) exige
además un salto de **precio** de ``k·ATR``, y los splits **sí** están ajustados en
precio → un split (volumen alto, precio sin salto) **no** dispara. El ``AND``
protege contra ese artefacto por diseño.

Módulo **puro** (stdlib): las barras entran como ``list[Bar]`` y el volumen como
``list[float]`` alineado, reusando el ATR de Wilder ya validado
(``analysis.exit_replay.atr_series``). Los tests corren offline. No decide nada por
sí solo (regla 3): solo emite candidatos; quién los consume vive en el harness (y,
si pasa el kill-criteria, en el engine detrás de un flag default OFF).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from analysis.exit_replay import Bar, atr_series

ATR_PERIOD = 14
ADV_WINDOW = 20
DEFAULT_REFRACTORY = 20  # = cap_days del harness


@dataclass(frozen=True)
class AnomalyParams:
    """Par umbral (lo único que barre la grilla del harness) + forma congelada."""

    k: float = 2.0  # umbral de retorno en unidades de ATR14
    m: float = 2.0  # múltiplo de volumen sobre ADV20
    atr_period: int = ATR_PERIOD  # congelado
    adv_window: int = ADV_WINDOW  # congelado
    refractory: int = DEFAULT_REFRACTORY  # congelado (= cap_days)


def _finite_pos(x: float | None) -> bool:
    return x is not None and math.isfinite(x) and x > 0


def detect_anomalies(
    bars: list[Bar],
    volumes: list[float],
    params: AnomalyParams = AnomalyParams(),
    *,
    warmup: int = 250,
) -> list[int]:
    """Índices de barra ``i`` donde dispara una anomalía (point-in-time).

    Devuelve el índice del **evento** ``i`` (NO el ``entry_idx = i+1``); la
    resolución de la entrada la hace ``build_anomaly_entries`` para dejar el
    detector agnóstico del pipeline.

    Fail-safe (nunca mira ``i+1`` ni posterior, nunca rompe por falta de datos):
    requiere ``ATR14[i]`` válido, ``adv_window`` volúmenes previos válidos, y
    ``i >= warmup``. Los ``i`` dentro del refractario del último disparo se saltean.
    """
    n = len(bars)
    if n == 0 or len(volumes) != n:
        return []
    atr = atr_series(bars, params.atr_period)
    out: list[int] = []
    last_fire = -(10**9)
    start = max(warmup, params.adv_window, params.atr_period + 1, 1)
    for i in range(start, n):
        if i - last_fire < params.refractory:
            continue
        a = atr[i]
        if not _finite_pos(a):
            continue
        c_i = bars[i][4]
        c_prev = bars[i - 1][4]
        if not (_finite_pos(c_i) and _finite_pos(c_prev)):
            continue
        # (1) salto de precio positivo >= k·ATR
        if (c_i - c_prev) < params.k * a:
            continue
        # (2) volumen anómalo vs ADV20 (ventana estrictamente anterior a i)
        window = volumes[i - params.adv_window : i]
        if len(window) < params.adv_window:
            continue
        if any((v is None or not math.isfinite(v) or v < 0) for v in window):
            continue
        adv = sum(window) / params.adv_window
        v_i = volumes[i]
        if adv <= 0 or v_i is None or not math.isfinite(v_i) or v_i < 0:
            continue
        if v_i < params.m * adv:
            continue
        out.append(i)
        last_fire = i
    return out


def build_anomaly_entries(
    bars_by: dict[str, list[Bar]],
    vol_by: dict[str, list[float]],
    params: AnomalyParams = AnomalyParams(),
    *,
    warmup: int = 250,
) -> list[tuple[str, int]]:
    """Entradas ``(ticker, entry_idx = i+1)`` para ``simulate_portfolio``.

    Descarta la anomalía cuya barra de fill (``i+1``) no deje al menos una rueda
    posterior (la maquinaria de salida necesita días siguientes). Orden
    cronológico por fecha de entrada, desempate alfabético por ticker (determinista).
    """
    out: list[tuple[str, int]] = []
    for t, bars in bars_by.items():
        vols = vol_by.get(t)
        if not vols or len(vols) != len(bars):
            continue
        for i in detect_anomalies(bars, vols, params, warmup=warmup):
            entry_idx = i + 1
            if entry_idx >= len(bars) - 1:  # sin rueda posterior al fill → no operable
                continue
            out.append((t, entry_idx))
    out.sort(key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]))
    return out
