"""El orden de los candidatos del día, como lo arma el motor vivo (tarea 473).

``simulate_portfolio`` sin ``rank_score`` procesa los candidatos de cada día en orden **alfabético**.
El motor vivo (``generate_trades_analyze_single``, ``paper_trading/strategies.py``) los ordena por
``_default_strength("BUY", ml_probability)``, mayor primero. Con ~56 candidatos por día para 10
lugares, el orden decide quién entra: con el costo del vivo y los gates 5 y 5b, la estrategia da
13,72% de CAGR con el alfabético y 9,75% con el del vivo (tarea 471).

``orden_del_vivo(score_by)`` es el ``rank_score`` del vivo, a partir de la ``ml_probability`` que
guarda el store de señales (``scripts.run_ranking_t21.load_bars_signals_scores``). El desempate del
simulador entre puntajes iguales es alfabético; el del vivo es el de ``list.sort`` sobre
``(score, ticker)`` en reversa, o sea alfabético inverso. Con probabilidades continuas, los empates
son raros (salvo la de 1 cuando falta la probabilidad).

**Supone ``cross_sectional_enabled`` apagado**, como está en la config viva (2026-11-26): prendido,
el vivo mezcla esa fuerza con el percentil de momentum (``analysis.ranking.blended_scores``), y este
orden deja de ser el suyo.
"""

from __future__ import annotations

import math
from collections.abc import Callable

RankScore = Callable[[str, str], float]

ORDEN_ALFABETICO = "alfabetico"
ORDEN_VIVO = "vivo"
ORDENES = (ORDEN_ALFABETICO, ORDEN_VIVO)


def fuerza_del_vivo(ml_probability: float | None) -> float:
    """``_default_strength("BUY", ml_probability)``: la probabilidad topada a [0, 1]; 1 si falta."""
    if ml_probability is not None and math.isfinite(ml_probability):
        return float(max(0.0, min(1.0, ml_probability)))
    return 1.0


def orden_del_vivo(score_by: dict[str, dict[str, float]]) -> RankScore:
    """El ``rank_score`` del vivo sobre el store: ``score_by[ticker][fecha]`` es la ``ml_probability``."""

    def rank(ticker: str, fecha: str) -> float:
        return fuerza_del_vivo((score_by.get(ticker) or {}).get(fecha))

    return rank


def rank_del_orden(nombre: str, score_by: dict[str, dict[str, float]] | None) -> RankScore | None:
    """``None`` para el alfabético (el default del simulador) y ``orden_del_vivo`` para el vivo."""
    if nombre == ORDEN_ALFABETICO:
        return None
    if nombre == ORDEN_VIVO:
        if score_by is None:
            raise ValueError("el orden del vivo necesita el store con la ml_probability (score_by)")
        return orden_del_vivo(score_by)
    raise ValueError(f"orden desconocido: {nombre!r} (esperado uno de {ORDENES})")
