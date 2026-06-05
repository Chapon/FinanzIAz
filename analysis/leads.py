"""
Lead scoring para el scanner masivo de recomendaciones de analistas.

Toma la respuesta de ``data.yahoo_finance.get_analyst_data`` (un dict con
``recommendations`` y ``price_targets``) y produce métricas comparables entre
tickers:

  - ``score``: promedio ponderado del MES MÁS RECIENTE (sBuy=+2, buy=+1,
    hold=0, sell=-1, sSell=-2). Range teórico [-2, +2].
  - ``total_analysts``: total de analistas del mes más reciente.
  - ``pct_strong_buy``, ``pct_buy``, ``pct_hold``, ``pct_sell``,
    ``pct_strong_sell``: porcentajes del mes más reciente.
  - ``verdict``: label en español derivada del score.
  - ``upside_pct``: implícito vs precio actual usando el mean target (puede
    ser ``None`` si Yahoo no devolvió targets o precio).

La función ``filter_leads`` aplica los thresholds ``min_score`` y
``min_analysts`` que la UI puede ajustar.
"""

from __future__ import annotations

from dataclasses import dataclass

BUCKET_WEIGHTS = {"strongBuy": 2, "buy": 1, "hold": 0, "sell": -1, "strongSell": -2}
BUCKET_KEYS = ("strongBuy", "buy", "hold", "sell", "strongSell")


@dataclass
class LeadRow:
    ticker: str
    score: float
    total_analysts: int
    pct_strong_buy: float
    pct_buy: float
    pct_hold: float
    pct_sell: float
    pct_strong_sell: float
    verdict: str
    price: float | None
    mean_target: float | None
    upside_pct: float | None


def compute_lead_score(analyst: dict, ticker: str) -> LeadRow | None:
    """Construye una ``LeadRow`` desde la respuesta de ``get_analyst_data``.

    Devuelve ``None`` si no hay recomendaciones (sin score, no aporta al ranking).
    Price targets son opcionales — si faltan, el campo upside queda en ``None``.
    """
    recs = (analyst or {}).get("recommendations") or []
    if not recs:
        return None

    latest = recs[-1]  # 0m (mes actual) — recs viene cronológico
    total = max(int(latest.get("total", 0)), 0)
    if total == 0:
        return None

    counts = {b: int(latest.get(b, 0)) for b in BUCKET_KEYS}
    score = sum(BUCKET_WEIGHTS[b] * counts[b] for b in BUCKET_KEYS) / total

    targets = (analyst or {}).get("price_targets") or {}
    price = targets.get("current")
    mean_target = targets.get("mean")
    upside = None
    if price is not None and mean_target is not None and price > 0:
        upside = (mean_target / price - 1) * 100

    return LeadRow(
        ticker=ticker.upper(),
        score=score,
        total_analysts=total,
        pct_strong_buy=counts["strongBuy"] / total * 100,
        pct_buy=counts["buy"] / total * 100,
        pct_hold=counts["hold"] / total * 100,
        pct_sell=counts["sell"] / total * 100,
        pct_strong_sell=counts["strongSell"] / total * 100,
        verdict=_score_to_verdict(score),
        price=price,
        mean_target=mean_target,
        upside_pct=upside,
    )


def _score_to_verdict(score: float) -> str:
    if score >= 1.5:
        return "Compra fuerte"
    if score >= 0.5:
        return "Compra"
    if score >= -0.5:
        return "Mantener"
    if score >= -1.5:
        return "Venta"
    return "Venta fuerte"


def filter_leads(
    rows: list[LeadRow],
    min_score: float = 1.0,
    min_analysts: int = 5,
) -> list[LeadRow]:
    """Filtra y ordena por score descendente (mejores leads primero).

    Defaults:
      - ``min_score=1.0`` → "Compra" o mejor
      - ``min_analysts=5`` → filtra penny stocks / sin cobertura amplia
    """
    filtered = [r for r in rows if r.score >= min_score and r.total_analysts >= min_analysts]
    filtered.sort(key=lambda r: (r.score, r.total_analysts), reverse=True)
    return filtered
