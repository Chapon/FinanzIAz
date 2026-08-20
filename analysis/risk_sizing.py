"""
Sizing por riesgo por nombre — enabler del **bloque 10 + 20** (pre-registro
``docs/sizing_exposure_prereg_t10_t20_2026-07-22.md``).

Provee el peso de riesgo ``m`` (multiplicador sobre el slice equal-weight) que
consume ``portfolio_sim.simulate_portfolio`` vía su hook ``size_weight``. Es
**lógica pura** (stdlib): las barras entran como ``list[Bar]`` y la señal ya
resuelta, así los tests corren offline.

Definiciones CONGELADAS (§4 del pre-registro):
  * ``σ`` = volatilidad **realizada** anualizada de los ``lookback`` (=60) días
    hábiles previos a la entrada, de los log-returns del cache 1d. **Realizada
    simple, NO GARCH** (el GARCH degenera con α+β≈1 — caveat del backlog).
  * ``inverse_vol``: ``m = median_σ / σ`` (``median_σ`` = mediana global de las σ
    del universo en la ventana; centra ``m`` en ~1).
  * ``vol_target``:  ``m = vol_target_annual / σ`` (``vol_target_annual = 0.20``).
  * ``m`` se recorta a ``clamp`` (=[0.25, 2.0]); σ desconocida/≤0 → fallback a la
    mediana global (no dispara ni suprime).
  * ``oracle``: ``m`` monótono en el retorno realizado del ciclo (mira el futuro)
    — SOLO valida que el harness tenga poder para distinguir sizings; no candidato.
"""

from __future__ import annotations

import math
import statistics
from typing import Callable

from analysis.exit_replay import AtrParams, Bar
from analysis.scaleout_replay import CostModel, ScaleOutParams, replay_cycle

# size_weight(ticker, date_iso10) -> m ≥ 0 (multiplicador de riesgo sobre el slice).
SizeWeight = Callable[[str, str], float]

DEFAULT_LOOKBACK = 60         # ruedas de vol realizada (§4)
DEFAULT_VOL_TARGET = 0.20     # objetivo de vol anual por nombre (§4)
DEFAULT_CLAMP = (0.25, 2.0)   # recorte del multiplicador (§4)
_VOL_FALLBACK = 0.20          # cuando no hay ni una σ conocida en todo el universo
TRADING_DAYS = 252


def realized_vol(bars: list[Bar], idx: int, *, lookback: int = DEFAULT_LOOKBACK) -> float | None:
    """Vol realizada anualizada de los ``lookback`` log-returns que TERMINAN en ``idx``.

    Point-in-time: usa sólo closes disponibles al decidir la entrada (hasta ``idx``
    inclusive, el último close conocido EOD). ``None`` si no hay suficientes barras
    o los closes no permiten calcular al menos 2 retornos.
    """
    if idx < lookback or idx >= len(bars):
        return None
    rets: list[float] = []
    for i in range(idx - lookback + 1, idx + 1):
        p0 = bars[i - 1][4]
        p1 = bars[i][4]
        if p0 and p1 and p0 > 0 and p1 > 0:
            rets.append(math.log(p1 / p0))
    if len(rets) < 2:
        return None
    sd = statistics.pstdev(rets)
    if sd <= 0 or not math.isfinite(sd):
        return None
    return sd * math.sqrt(TRADING_DAYS)


def build_sigma_map(
    entries: list[tuple[str, int]],
    bars_by: dict[str, list[Bar]],
    *,
    lookback: int = DEFAULT_LOOKBACK,
) -> dict[tuple[str, str], float]:
    """``(ticker, date_iso10) -> σ`` para cada entrada candidata con σ computable."""
    out: dict[tuple[str, str], float] = {}
    for ticker, idx in entries:
        bars = bars_by.get(ticker)
        if not bars or idx >= len(bars):
            continue
        s = realized_vol(bars, idx, lookback=lookback)
        if s is not None and s > 0:
            out[(ticker, bars[idx][0])] = s
    return out


def precompute_oracle_returns(
    entries: list[tuple[str, int]],
    bars_by: dict[str, list[Bar]],
    sigs_by: dict[str, dict],
    *,
    so_params: ScaleOutParams = ScaleOutParams(),
    atr_p: AtrParams = AtrParams(),
    cap_days: int = 20,
    costs: CostModel = CostModel(),
    eval_mode: str = "close",
    fill_mode: str = "decision",
) -> dict[tuple[str, str], float]:
    """Retorno realizado del ciclo de cada entrada (mira el futuro) para el oráculo.

    Se replaya cada candidato con notional unitario y sin restricción de cartera —
    es un retorno por-nombre independiente de qué entra por slot. SOLO para el brazo
    de validación del harness (nunca se cablea).

    ``fill_mode`` se pasa a ``replay_cycle`` para que el oráculo puntúe con **la
    misma mecánica de fill** que los brazos que valida (Tarea 33): con el legacy,
    el oráculo rankeaba por un retorno que ningún brazo podía cobrar.

    ``eval_mode`` va por el mismo motivo y se agregó por la **Tarea 38** (tarea 44):
    la 26b sumó el eje ``close``/``touch`` a ``replay_cycle`` pero no llegó hasta acá,
    así que un harness que corriera sus brazos en ``touch`` tenía el oráculo
    puntuando al ``close`` — la misma mitad de defecto que arregló la T33, en el otro
    eje. Default ``"close"``: preserva el comportamiento de todo lo publicado.
    """
    out: dict[tuple[str, str], float] = {}
    for ticker, idx in entries:
        bars = bars_by.get(ticker)
        if not bars or idx >= len(bars):
            continue
        cyc = replay_cycle(
            bars, idx, sigs_by.get(ticker) or {},
            params=so_params, atr_p=atr_p, cap_days=cap_days,
            costs=costs, notional=10_000.0, regime="",
            eval_mode=eval_mode, fill_mode=fill_mode,
        )
        if cyc is None or cyc.entry_cost <= 0:
            continue
        out[(ticker, bars[idx][0])] = cyc.total_proceeds / cyc.entry_cost - 1.0
    return out


def make_size_weight(
    mode: str,
    sigma_by_key: dict[tuple[str, str], float],
    *,
    vol_target: float = DEFAULT_VOL_TARGET,
    clamp: tuple[float, float] = DEFAULT_CLAMP,
    oracle_returns: dict[tuple[str, str], float] | None = None,
) -> SizeWeight:
    """Construye el ``size_weight`` de un brazo pre-registrado.

    Modos: ``equal`` (m=1), ``inverse_vol`` (median_σ/σ), ``vol_target``
    (vol_target/σ), ``oracle`` (monótono en el retorno realizado). El recorte
    ``clamp`` acota el multiplicador; σ ausente → mediana global (nunca suprime).
    """
    lo, hi = clamp

    def _clamp(m: float) -> float:
        return max(lo, min(hi, m))

    if mode == "equal":
        return lambda _t, _d: 1.0

    global_median = (
        statistics.median(sigma_by_key.values()) if sigma_by_key else _VOL_FALLBACK
    )

    if mode == "inverse_vol":
        def f(t: str, d: str) -> float:
            s = sigma_by_key.get((t, d)) or global_median
            return _clamp(global_median / s) if s > 0 else 1.0
        return f

    if mode == "vol_target":
        def f(t: str, d: str) -> float:
            s = sigma_by_key.get((t, d)) or global_median
            return _clamp(vol_target / s) if s > 0 else 1.0
        return f

    if mode == "oracle":
        oret = oracle_returns or {}

        def f(t: str, d: str) -> float:
            r = oret.get((t, d))
            if r is None:
                return 1.0
            # monótono en el retorno realizado: r=+0.25 → tope 2.0; r=−0.19 → 0.25.
            return _clamp(1.0 + 4.0 * r)
        return f

    raise ValueError(f"modo de sizing desconocido: {mode}")


# ── métricas de cartera sobre la curva de equity (§3 del pre-registro) ────────
def cagr(curve: list[tuple[str, float]]) -> float:
    """CAGR anualizado por ruedas: (e_fin/e_ini)^(252/n) − 1."""
    if len(curve) < 2:
        return 0.0
    e0 = curve[0][1]
    e1 = curve[-1][1]
    if e0 <= 0:
        return 0.0
    return (e1 / e0) ** (TRADING_DAYS / len(curve)) - 1.0


def daily_returns(curve: list[tuple[str, float]]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(curve)):
        p0 = curve[i - 1][1]
        p1 = curve[i][1]
        if p0 > 0 and math.isfinite(p0) and math.isfinite(p1):
            out.append(p1 / p0 - 1.0)
    return out


def sharpe_annual(curve: list[tuple[str, float]]) -> float | None:
    """Sharpe anualizado de los retornos diarios (rf=0). ``None`` si std=0."""
    rs = daily_returns(curve)
    if len(rs) < 2:
        return None
    sd = statistics.pstdev(rs)
    if sd <= 0 or not math.isfinite(sd):
        return None
    return statistics.fmean(rs) / sd * math.sqrt(TRADING_DAYS)
