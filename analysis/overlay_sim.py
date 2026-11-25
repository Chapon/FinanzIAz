"""El overlay de σ de cartera del motor, para el simulador del harness (tarea 457).

En vivo, ``_apply_vol_overlay_to_buys`` (``paper_trading/strategies.py``) achica **todas** las
compras de un scan cuando la σ anualizada del libro que va a quedar —lo tenido que no se vende
en ese scan, a mercado, más las compras, antes del régimen— pasa del objetivo
(``vol_target_portfolio_annual``, 12%). La 94 lo dejó declarado como desvío y nadie lo midió.

Este módulo es la otra punta del hook ``vol_overlay`` de ``simulate_portfolio``: recibe el
libro del día que arma el simulador y devuelve el factor, con **las mismas funciones** que usa
el motor (``returns_frame`` y ``apply_portfolio_vol_overlay`` de ``analysis/portfolio_risk.py``,
``compute_vol_overlay`` de ``paper_trading/gates.py``). La paridad con el motor está fijada en
``tests/test_vol_overlay_t457.py``.

**Punto en el tiempo:** la historia de cada ticker llega hasta el cierre de la fecha del
scan, inclusive, que es la barra con que el simulador decide y compra.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable

import pandas as pd

from analysis.exit_replay import Bar
from analysis.harness_config import LIVE_VOL_TARGET_ANNUAL
from analysis.portfolio_risk import apply_portfolio_vol_overlay, returns_frame

Historia = Callable[[str], "pd.DataFrame | None"]


def factor_overlay_del_dia(
    tenidas: dict[str, float],
    compras: dict[str, float],
    valor_cartera: float,
    historia: Historia,
    objetivo: float,
):
    """El ``VolOverlayResult`` del motor para un libro: ``tenidas`` y ``compras`` en dólares,
    ``valor_cartera`` = caja + todo lo abierto a mercado, ``historia(ticker)`` = sus cierres.

    Es ``_apply_vol_overlay_to_buys`` sin el estado del motor: los mismos cortes (objetivo
    ≤ 0, cartera sin valor o ninguna compra ⇒ factor 1), los mismos pesos (dólares sobre el
    valor de la cartera, y una compra pisa a una tenencia del mismo ticker) y la misma σ.
    """
    from paper_trading.gates import VolOverlayResult, compute_vol_overlay

    if objetivo <= 0 or valor_cartera <= 0 or not compras:
        return VolOverlayResult(factor=1.0, sigma=None, scaled_weights={})
    held_w = {t: v / valor_cartera for t, v in tenidas.items()}
    pick_w = {t: d / valor_cartera for t, d in compras.items()}
    combined = {**held_w, **pick_w}
    ret_df = returns_frame(list(combined.keys()), historia)
    return compute_vol_overlay(combined, ret_df, objetivo, apply_fn=apply_portfolio_vol_overlay)


class OverlayDeVolatilidad:
    """El hook ``vol_overlay`` de ``simulate_portfolio`` con el overlay del motor.

    Guarda la σ de cada día en ``sigmas`` para el reporte; el factor queda en el
    ``PortfolioResult`` (``overlay_por_dia``), que es lo que sobrevive al cache.
    """

    def __init__(self, bars_by: dict[str, list[Bar]], *, objetivo: float = LIVE_VOL_TARGET_ANNUAL):
        self.objetivo = float(objetivo)
        self._fechas = {t: [b[0] for b in bars] for t, bars in bars_by.items() if bars}
        self._cierres = {
            t: pd.Series([float(b[4]) for b in bars_by[t]], index=fechas, dtype="float64")
            for t, fechas in self._fechas.items()
        }
        self.sigmas: dict[str, float | None] = {}

    def historia_hasta(self, fecha: str) -> Historia:
        """Los cierres de cada ticker hasta ``fecha`` inclusive, como los ve el motor ese día."""

        def historia(ticker: str) -> pd.DataFrame | None:
            fechas = self._fechas.get(ticker)
            if not fechas:
                return None
            k = bisect_right(fechas, fecha)
            if k == 0:
                return None
            return pd.DataFrame({"Close": self._cierres[ticker].iloc[:k]})

        return historia

    def __call__(
        self, fecha: str, tenidas: dict[str, float], compras: dict[str, float], valor_cartera: float
    ) -> float:
        r = factor_overlay_del_dia(tenidas, compras, valor_cartera, self.historia_hasta(fecha), self.objetivo)
        self.sigmas[fecha] = r.sigma
        return r.factor
