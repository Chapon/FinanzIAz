"""
Valuación de una empresa con sus fundamentals point-in-time — **tarea 383**, display-only.

Tres miradas sobre el precio, cada una de un libro (``docs/libros_inversion_analisis_2026-10-21.md``):

- **Graham:** el número de Graham, √(22,5 · EPS · valor libro por acción), y el margen de
  seguridad del precio contra él. Es el techo que Graham le ponía al inversor defensivo: un PE de
  15 por un precio sobre valor libro de 1,5.
- **Buffettology:** el EPS de hoy crecido 10 años a su ritmo histórico (con tope), por el PE
  histórico mediano de la propia empresa, da un precio dentro de 10 años. De ahí salen el
  **retorno anual esperado** al precio de hoy y el **precio máximo** para esperar un 15% anual.
  No suma dividendos: es el precio solo, y lo dice.
- **Lynch:** el PEG (PE dividido por el crecimiento del EPS en %) y una categoría automática por
  crecimiento y estabilidad del EPS.

**No entra en ninguna decisión** (regla 3): ni sizing, ni gates, ni ranking. Un test lo verifica.

Todo es puro: recibe los fundamentals (``data.fundamentos_pit.Fundamentos``), los cierres y el
precio, y devuelve ``None`` en cada número que no se puede calcular con honestidad (EPS ≤ 0,
crecimiento sin base positiva, menos de 3 años de PE). Una empresa **extranjera** (la 382) no se
valúa: su EPS no está en la misma moneda o la misma unidad que el precio del ADR.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from statistics import median

from data.fundamentos_pit import es_vigente

ANIOS_PROYECCION = 10
TOPE_CRECIMIENTO = 0.15  # Buffettology no proyecta crecimientos de dos dígitos altos por 10 años
OBJETIVO_ANUAL = 0.15  # el retorno que Buffett pedía para comprar
ANIOS_CRECIMIENTO = 5  # ventana del crecimiento del EPS para el PEG y la categoría de Lynch
MIN_ANIOS_PE = 3
LENTO, FIRME = 0.06, 0.15  # fronteras de Lynch (él hablaba de 2-4%, 10-12% y 20-25%)


def numero_graham(eps: float | None, valor_libro_x_accion: float | None) -> float | None:
    if eps is None or valor_libro_x_accion is None or eps <= 0 or valor_libro_x_accion <= 0:
        return None
    return math.sqrt(22.5 * eps * valor_libro_x_accion)


def margen_de_seguridad(precio: float | None, valor: float | None) -> float | None:
    """Cuánto por debajo del valor está el precio, como fracción del valor. Negativo si está arriba."""
    if precio is None or valor is None or valor <= 0:
        return None
    return (valor - precio) / valor


def crecimiento_anual(serie: list[tuple[str, float]], anios: int) -> tuple[float | None, int]:
    """Crecimiento compuesto entre el valor de hace ``anios`` y el último, y los años que usó.

    Con menos historia usa la que hay (mínimo 3 años). ``None`` si alguno de los dos extremos
    no es positivo: no hay crecimiento compuesto entre una pérdida y una ganancia.
    """
    if len(serie) < 4:
        return None, 0
    tramo = serie[-(anios + 1) :]
    n = len(tramo) - 1
    ini, fin = tramo[0][1], tramo[-1][1]
    if ini <= 0 or fin <= 0:
        return None, n
    return (fin / ini) ** (1 / n) - 1, n


def _cierre_al(cierres: list[tuple[str, float]], fecha: str) -> float | None:
    previos = [c for d, c in cierres if d <= fecha]
    return previos[-1] if previos else None


def pe_historico(
    eps_serie: list[tuple[str, float]], cierres: list[tuple[str, float]]
) -> tuple[float | None, int]:
    """Mediana del PE al cierre de cada año fiscal con EPS positivo, y cuántos años entraron."""
    pes = []
    for fin, eps in eps_serie:
        if eps <= 0:
            continue
        precio = _cierre_al(cierres, fin)
        if precio:
            pes.append(precio / eps)
    if len(pes) < MIN_ANIOS_PE:
        return None, len(pes)
    return median(pes), len(pes)


def categoria_lynch(eps_serie: list[tuple[str, float]]) -> tuple[str | None, str]:
    """La categoría de Lynch por el EPS de los últimos años, y por qué."""
    ultimos = [v for _, v in eps_serie[-(ANIOS_CRECIMIENTO + 1) :]]
    if len(ultimos) < 4:
        return None, "menos de 4 años de EPS"
    if ultimos[-1] > 0 and any(v <= 0 for v in ultimos[:-1]):
        return "recuperación", "volvió a ganar después de perder"
    variaciones = [b / a - 1 for a, b in pairwise(ultimos) if a > 0]
    if any(v < -0.25 for v in variaciones) and any(v > 0.25 for v in variaciones):
        return "cíclica", "el EPS cayó y subió más de 25% en años distintos"
    g, n = crecimiento_anual(eps_serie, ANIOS_CRECIMIENTO)
    if g is None:
        return None, "sin crecimiento calculable"
    if g < LENTO:
        return "crecimiento lento", f"EPS +{g:.0%} anual en {n} años"
    if g < FIRME:
        return "firme", f"EPS +{g:.0%} anual en {n} años"
    return "crecimiento rápido", f"EPS +{g:.0%} anual en {n} años"


@dataclass
class Valuacion:
    precio: float
    eps: float | None = None
    valor_libro_x_accion: float | None = None
    numero_graham: float | None = None
    margen_graham: float | None = None
    crecimiento: float | None = None  # del EPS, compuesto anual
    anios_crecimiento: int = 0
    pe_historico: float | None = None
    anios_pe: int = 0
    precio_en_10: float | None = None
    retorno_anual: float | None = None
    precio_max_objetivo: float | None = None
    peg: float | None = None
    categoria: str | None = None
    motivo_categoria: str = ""
    fin_ultimo_anio: str | None = None
    avisos: list[str] = field(default_factory=list)
    # El puntaje de calidad de la tarea 384 dentro del universo: {"puntaje", "percentiles", "n"}.
    calidad: dict | None = None


def valuar(
    fund,
    precio: float | None,
    cierres: list[tuple[str, float]],
    fecha: str,
    splits: list[tuple[str, float]] | None = None,
) -> Valuacion | None:
    """La valuación con lo que se conocía antes de ``fecha``. ``None`` si no hay con qué.

    ``cierres`` tienen que estar ajustados por splits y **no** por dividendos
    (``get_cierres_sin_ajuste_por_dividendos``), y ``splits`` lleva el EPS y las acciones de EDGAR
    a esa misma base: precio y ganancia en la misma unidad.
    """
    if fund is None or precio is None or precio <= 0:
        return None
    if fund.extranjera:
        return None
    eps_serie = fund.serie("eps_diluido", fecha, splits)
    if not eps_serie:
        return None
    v = Valuacion(precio=precio)
    v.fin_ultimo_anio, v.eps = eps_serie[-1]
    ganancia = fund.serie("ganancia_neta", fecha)
    if ganancia and not es_vigente(v.fin_ultimo_anio, ganancia):
        # Tarea 390: el EPS de EXC y HAL termina en 2021 y la tarjeta lo mostraba como el de hoy.
        v.avisos.append(f"el EPS termina en {v.fin_ultimo_anio[:4]} y la ganancia en {ganancia[-1][0][:4]}")
    patrimonio = fund.serie("patrimonio", fecha)
    acciones = fund.serie("acciones_diluidas", fecha, splits)
    if patrimonio and acciones and acciones[-1][1] > 0:
        v.valor_libro_x_accion = patrimonio[-1][1] / acciones[-1][1]
        if patrimonio[-1][0] != acciones[-1][0]:
            v.avisos.append("patrimonio y acciones de cierres distintos")
    v.numero_graham = numero_graham(v.eps, v.valor_libro_x_accion)
    v.margen_graham = margen_de_seguridad(precio, v.numero_graham)

    v.crecimiento, v.anios_crecimiento = crecimiento_anual(eps_serie, ANIOS_PROYECCION)
    v.pe_historico, v.anios_pe = pe_historico(eps_serie, cierres)
    if v.eps and v.eps > 0 and v.crecimiento is not None and v.pe_historico:
        g = min(v.crecimiento, TOPE_CRECIMIENTO)
        if v.crecimiento > TOPE_CRECIMIENTO:
            v.avisos.append(f"crecimiento topeado en {TOPE_CRECIMIENTO:.0%}")
        v.precio_en_10 = v.eps * (1 + g) ** ANIOS_PROYECCION * v.pe_historico
        v.retorno_anual = (v.precio_en_10 / precio) ** (1 / ANIOS_PROYECCION) - 1
        v.precio_max_objetivo = v.precio_en_10 / (1 + OBJETIVO_ANUAL) ** ANIOS_PROYECCION

    g5, _ = crecimiento_anual(eps_serie, ANIOS_CRECIMIENTO)
    if v.eps and v.eps > 0 and g5 and g5 > 0:
        v.peg = (precio / v.eps) / (g5 * 100)
    v.categoria, v.motivo_categoria = categoria_lynch(eps_serie)
    return v
