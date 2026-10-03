"""Consenso de analistas point-in-time, en una escala comparable (tarea 279).

Para qué existe
---------------
``analyst_estimate_snapshots`` guarda cada día lo que devuelve Yahoo **tal cual**: sin ajustar
por split y en la moneda de reporte de la empresa. Medido el 2026-10-02
(``docs/auditoria_datos_2026-10-02.md`` [D-2]):

* **KLAC**, 2026-06-11 → 06-12: EPS ``0q`` 9,95 → 0,995 y precio objetivo 1.869 → 190,5 el mismo
  día — su split 10:1. Una *revisión* medida a través de eso da **−90%**, y es el split.
* **TSM**: el revenue de consenso viene en **TWD** (7,3 billones ``+1y``), con el EPS por ADR en USD.

Hoy nadie decide con esa tabla. Su consumidor es **T-CAT-5b** (el consenso del día antes de cada
earnings, y la idea de revisiones de estimaciones), bloqueado por datos. Esto deja hecha la parte
que su pre-registro tiene que usar para no medir splits ni monedas.

Qué hace
--------
* ``ajustar_por_split`` lleva una serie a la escala **más reciente**: cada valor **por acción**
  (``eps``, ``price_target``) se divide por el producto de los splits con ex-date **posterior** a
  su fecha. ``revenue`` y ``rec_mean`` no dependen de la cantidad de acciones y no se tocan.
* ``revision`` es el cambio **relativo** de la serie ajustada, dentro de un mismo ticker: como es
  un cociente, la moneda se cancela (el caso TSM).

Puro: los splits llegan como parámetro (``data.yahoo_finance.get_split_events``).
"""

from __future__ import annotations

# Las métricas de `analyst_estimate_snapshots` que son POR ACCIÓN y cambian de escala con un split.
METRICAS_POR_ACCION = frozenset({"eps", "price_target"})


def ajustar_por_split(
    valores: list[tuple[str, float]], splits: list[tuple[str, float]], metrica: str
) -> list[tuple[str, float]]:
    """``[(fecha 'YYYY-MM-DD', valor)]`` en la escala del último split. Puro.

    Un valor de fecha ``d`` se divide por el producto de los ``ratio`` con ``ex_date > d``: un
    snapshot del **mismo** día del ex-date ya viene en la escala nueva (la misma convención que el
    ajuste de posiciones de la 262).
    """
    if metrica not in METRICAS_POR_ACCION:
        return list(valores)
    salida = []
    for fecha, valor in valores:
        factor = 1.0
        for ex, ratio in splits:
            if ex > fecha and ratio and ratio > 0:
                factor *= float(ratio)
        salida.append((fecha, float(valor) / factor))
    return salida


def revision(valores: list[tuple[str, float]], splits: list[tuple[str, float]], metrica: str) -> float | None:
    """Cambio relativo de la serie (último / primero − 1), ya en una escala comparable.

    ``None`` si no hay dos valores o el primero es 0 (no hay base para un cambio relativo).
    """
    serie = sorted(ajustar_por_split(valores, splits, metrica))
    if len(serie) < 2 or serie[0][1] == 0:
        return None
    return serie[-1][1] / serie[0][1] - 1.0
