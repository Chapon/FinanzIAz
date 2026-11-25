"""El Gate 6 del motor (blackout de earnings) como filtro de entrada del simulador (tarea 458).

En vivo, el motor frena una compra si hay un balance a ±``earnings_blackout_days`` días **corridos**
de la fecha del scan (``paper_trading.gates.is_within_earnings_blackout``, ±2 en la cuenta 2). La 96
lo dio por no modelable porque no había fechas de balance a 10 años; Yahoo las tiene desde 2014
(``scripts/bajar_fechas_balance_t458.py``).

``filtro_de_balances`` devuelve un ``EntryFilter`` de ``simulate_portfolio``: 0 en la ventana de un
balance (la entrada se suprime, como el ``continue`` del Gate 6), 1 fuera. ``componer`` lo multiplica
por otro filtro (el del régimen), porque en vivo los dos corren sobre la misma compra.

**Lo que no replica, dicho:** el motor mira **la próxima** fecha del calendario de Yahoo, cacheada,
y una fecha pasada sigue ahí un par de días; acá se usan todas las fechas conocidas, o sea el gate
ideal. Un ticker sin fechas no se bloquea nunca, como en vivo (*fail-open*). Y en vivo el pick
frenado se queda con su lugar en el scan, mientras que el simulador se lo da al siguiente (tarea
471).
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Callable
from datetime import date
from pathlib import Path

from analysis.harness_config import LIVE_EARNINGS_BLACKOUT_DAYS

ALMACEN = Path("data") / "earnings_dates" / "fechas_balance.json"

EntryFilter = Callable[[str, str], float]


def cargar_fechas(path: str | Path = ALMACEN) -> tuple[dict[str, list[str]], dict]:
    """(fechas por ticker, metadatos del almacén). Las fechas son ``YYYY-MM-DD``, ordenadas."""
    blob = json.loads(Path(path).read_bytes().decode("utf-8"))
    fechas = {t: sorted(f) for t, f in blob["fechas"].items()}
    meta = {k: v for k, v in blob.items() if k != "fechas"}
    return fechas, meta


def filtro_de_balances(fechas: dict[str, list[str]], dias: int = LIVE_EARNINGS_BLACKOUT_DAYS) -> EntryFilter:
    """0.0 si ``fecha`` está a ±``dias`` corridos de un balance del ticker, 1.0 si no.

    Es ``is_within_earnings_blackout`` sobre todas las fechas conocidas: ``|balance − fecha| ≤ dias``
    en días calendario. Con ``dias <= 0`` el gate está apagado, como en vivo.
    """
    ordinales = {t: [date.fromisoformat(d).toordinal() for d in fs] for t, fs in fechas.items()}

    def filtro(ticker: str, fecha: str) -> float:
        if dias <= 0:
            return 1.0
        o = ordinales.get(ticker)
        if not o:
            return 1.0
        d = date.fromisoformat(fecha).toordinal()
        k = bisect_left(o, d - dias)
        return 0.0 if k < len(o) and o[k] <= d + dias else 1.0

    return filtro


def componer(*filtros: EntryFilter | None) -> EntryFilter | None:
    """El producto de los filtros que no son ``None`` (``None`` si no queda ninguno)."""
    activos = [f for f in filtros if f is not None]
    if not activos:
        return None
    if len(activos) == 1:
        return activos[0]

    def compuesto(ticker: str, fecha: str) -> float:
        g = 1.0
        for f in activos:
            g *= float(f(ticker, fecha))
            if g <= 0.0:
                return 0.0
        return g

    return compuesto
