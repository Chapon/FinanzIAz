"""
Puntaje de calidad del negocio — **tarea 384**, display-only.

Lo que *Buffettology* y *El arte de invertir* llaman calidad, llevado a números que salen de los
fundamentals point-in-time de EDGAR (tarea 382), y lo que la literatura midió aparte (Novy-Marx
2013: la rentabilidad bruta; Asness, Frazzini y Pedersen 2014: *quality minus junk*). Cuatro patas:

- **roe:** el ROE medio de hasta 10 años **menos su desvío**. Premia el retorno alto y parejo; un
  año excepcional no alcanza.
- **rentab_bruta:** ganancia bruta sobre activos del último año (Novy-Marx). No existe para
  bancos, eléctricas, REITs y transporte: la pata queda vacía y no cuenta (la 382 lo midió).
- **deuda:** años de ganancia neta que hacen falta para pagar la deuda de largo plazo. Menos es
  mejor. Sin ganancia positiva no hay pata.
- **regularidad:** la fracción de años en que la **ganancia neta** creció. Se usa la ganancia y no
  el EPS porque no cambia con los splits.

Cada pata se pasa a percentil dentro de la población que se le dé (el universo), y el puntaje es
el promedio de las patas presentes, de 0 a 100, con un mínimo de dos. Todo con lo que se conocía
**antes** de la fecha.

**No entra en ninguna decisión** (regla 3). Su poder predictivo se mide con
``scripts/measure_calidad_t384.py`` antes de que nada lo use.
"""

from __future__ import annotations

from itertools import pairwise
from statistics import mean, pstdev

PATAS = ("roe", "rentab_bruta", "deuda", "regularidad")
MAYOR_ES_MEJOR = {"roe": True, "rentab_bruta": True, "deuda": False, "regularidad": True}
ANIOS = 10
MIN_ANIOS = 3
MIN_PATAS = 2


def _ultimos(serie: list[tuple[str, float]], n: int = ANIOS) -> list[tuple[str, float]]:
    return serie[-n:]


def patas_de(fund, fecha: str) -> dict[str, float | None]:
    """Las cuatro patas de un ticker con lo conocido antes de ``fecha``. Pura salvo por ``fund``."""
    out: dict[str, float | None] = dict.fromkeys(PATAS)
    if fund is None:
        return out
    ganancia = dict(_ultimos(fund.serie("ganancia_neta", fecha)))
    patrimonio = dict(fund.serie("patrimonio", fecha))

    roes = [ganancia[e] / patrimonio[e] for e in ganancia if patrimonio.get(e, 0) > 0]
    if len(roes) >= MIN_ANIOS:
        out["roe"] = mean(roes) - pstdev(roes)

    activos = dict(fund.serie("activos", fecha))
    bruta = fund.serie("ganancia_bruta", fecha)
    if bruta and activos.get(bruta[-1][0], 0) > 0:
        out["rentab_bruta"] = bruta[-1][1] / activos[bruta[-1][0]]

    serie_g = sorted(ganancia.items())
    deuda = fund.serie("deuda_lp", fecha)
    if deuda and serie_g and serie_g[-1][1] > 0:
        out["deuda"] = deuda[-1][1] / serie_g[-1][1]

    if len(serie_g) >= MIN_ANIOS + 1:
        pasos = list(pairwise(serie_g))
        out["regularidad"] = sum(1 for (_, a), (_, b) in pasos if b > a) / len(pasos)
    return out


def _percentiles(valores: dict[str, float], mayor_es_mejor: bool) -> dict[str, float]:
    """Percentil (0 a 100) de cada valor dentro de la población; los empates, al promedio."""
    if not valores:
        return {}
    orden = sorted(valores.values())
    n = len(orden)
    out = {}
    for t, v in valores.items():
        debajo = sum(1 for x in orden if x < v)
        iguales = sum(1 for x in orden if x == v)
        p = (debajo + (iguales - 1) / 2) / (n - 1) * 100 if n > 1 else 50.0
        out[t] = p if mayor_es_mejor else 100.0 - p
    return out


def puntajes(patas_por_ticker: dict[str, dict[str, float | None]]) -> dict[str, dict]:
    """El puntaje de cada ticker dentro de la población: ``{t: {"puntaje", "percentiles", "patas"}}``.

    ``puntaje`` es ``None`` si el ticker tiene menos de ``MIN_PATAS`` patas.
    """
    pct_por_pata = {
        p: _percentiles(
            {t: v[p] for t, v in patas_por_ticker.items() if v.get(p) is not None}, MAYOR_ES_MEJOR[p]
        )
        for p in PATAS
    }
    out = {}
    for t, patas in patas_por_ticker.items():
        pcts = {p: pct_por_pata[p][t] for p in PATAS if t in pct_por_pata[p]}
        out[t] = {
            "puntaje": mean(pcts.values()) if len(pcts) >= MIN_PATAS else None,
            "percentiles": pcts,
            "patas": patas,
        }
    return out
