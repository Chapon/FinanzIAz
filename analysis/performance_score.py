"""Score mensual de desempeño de la app — tarea 194. **Display-only.**

Responde *«¿cuándo estoy ganando más y cuándo menos?»* con un número por mes, donde
**100 = ganar $4.000 en el mes**. Las definiciones las eligió Chapa el 2026-09-13:

- **Score = 70% plata + 30% calidad**, entre 0 y 100.
- **Plata** = P/L **realizado** del mes (round-trips FIFO cerrados en el mes, neto de
  comisión y slippage) ÷ ``TARGET_MONTHLY_USD``, recortado a [0, 100]. Un mes que pierde
  da 0; uno que pasa del objetivo da 100.
- **Calidad** = % de round-trips cerrados en el mes con P/L > 0.

**Por qué cada mes lleva además el P/L en dólares:** el recorte a [0, 100] iguala un mes que
pierde $200 con uno que pierde $1.700. El score dice *qué tan cerca del objetivo*; el P/L con
signo dice *cuánto*, y los dos juntos responden cuándo se gana más y cuándo menos.

**Lo que NO es:** un criterio de trading. No se cablea a sizing ni a gates (regla 3 de
``CLAUDE.md``), y un mes con score alto no valida ninguna feature — eso lo hace un backtest.

Módulo puro: recibe los round-trips de ``analysis.metrics_panel.pair_round_trips``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

TARGET_MONTHLY_USD = 4_000.0
WEIGHT_MONEY = 0.70
WEIGHT_QUALITY = 0.30


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def score_month(realized_pnl: float, n_round_trips: int, n_wins: int) -> dict[str, float | None]:
    """Las tres cifras de un mes: ``money_pct``, ``quality_pct`` (``None`` sin operaciones) y ``score``.

    Un mes sin round-trips cerrados tiene calidad **indefinida**, no 0%: no hubo decisiones que
    juzgar. Aporta 0 al score —no ganó plata—, pero se muestra como «—» y no como un 0% de aciertos.
    """
    money_pct = _clamp(100.0 * realized_pnl / TARGET_MONTHLY_USD)
    quality_pct = (100.0 * n_wins / n_round_trips) if n_round_trips > 0 else None
    score = WEIGHT_MONEY * money_pct + WEIGHT_QUALITY * (quality_pct or 0.0)
    return {"money_pct": money_pct, "quality_pct": quality_pct, "score": _clamp(score)}


def _meses(desde: str, hasta: str) -> list[str]:
    """``["AAAA-MM", …]`` inclusive en los dos extremos."""
    y, m = int(desde[:4]), int(desde[5:7])
    fy, fm = int(hasta[:4]), int(hasta[5:7])
    out = []
    while (y, m) <= (fy, fm):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def monthly_scores(
    round_trips: list[dict],
    *,
    first_day: str | None,
    today: date,
) -> list[dict[str, Any]]:
    """Un registro por mes, desde el mes de ``first_day`` hasta el de ``today``.

    ``first_day`` es el primer fill de la cuenta: los meses **sin operaciones** entre medio
    aparecen con score 0, porque no operar también es no ganar. El mes de ``today`` va con
    ``in_progress=True`` y se compara contra el objetivo **entero**, sin prorratear.
    Cada round-trip cae en el mes de su **venta** (``sell_day``), que es cuando se realiza.
    """
    if not first_day:
        return []
    hoy = today.isoformat()
    por_mes: dict[str, list[float]] = {}
    for rt in round_trips:
        dia = rt.get("sell_day")
        if dia:
            por_mes.setdefault(dia[:7], []).append(float(rt["pnl"]))

    out = []
    for mes in _meses(first_day[:7], hoy[:7]):
        pnls = por_mes.get(mes, [])
        pnl = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        out.append(
            {
                "month": mes,
                "realized_pnl": pnl,
                "n_round_trips": len(pnls),
                "n_wins": wins,
                **score_month(pnl, len(pnls), wins),
                "in_progress": mes == hoy[:7],
            }
        )
    return out


def performance_score_panel(round_trips: list[dict], orders: list[dict], *, today: date) -> dict[str, Any]:
    """El bloque ``performance_score`` del payload de la pestaña Métricas."""
    dias = [o["filled_at"][:10] for o in orders if o.get("filled_at")]
    months = monthly_scores(round_trips, first_day=min(dias) if dias else None, today=today)
    completos = [m for m in months if not m["in_progress"]]
    return {
        "target_monthly_usd": TARGET_MONTHLY_USD,
        "weight_money": WEIGHT_MONEY,
        "weight_quality": WEIGHT_QUALITY,
        "months": months,
        "current": months[-1] if months else None,
        "best": max(completos, key=lambda m: m["score"]) if completos else None,
        "worst": min(completos, key=lambda m: m["score"]) if completos else None,
        "avg_completed": (sum(m["score"] for m in completos) / len(completos)) if completos else None,
    }
