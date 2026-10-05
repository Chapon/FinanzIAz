"""Tarea 309 — la curva de Home no se corta por un ticker que ya se vendió.

El defecto (``docs/auditoria_tanda_2026-10-05.md`` [B-1]): ``valor_diario`` terminaba la serie en
el último cierre del ticker más atrasado de **toda** la historia de la cartera, vendidos incluidos.
Un ticker vendido que no está en el universo del scan deja de refrescarse, así que la primera
venta congelaba el gráfico en esa fecha.
"""

from __future__ import annotations

from datetime import date, timedelta

from database.cartera_real import valor_diario

COMPRA = date(2026, 4, 14)


def _cierres(desde: date, hasta: date, precio: float) -> list[tuple[date, float]]:
    out, d = [], desde
    while d <= hasta:
        if d.weekday() < 5:
            out.append((d, precio))
        d += timedelta(days=1)
    return out


def test_un_ticker_VENDIDO_con_el_cache_viejo_no_corta_la_serie():
    cierres = {
        "A": _cierres(date(2026, 4, 1), date(2026, 10, 2), 100.0),
        "B": _cierres(date(2026, 4, 1), date(2026, 6, 5), 50.0),  # vendida el 01/06; cache al 05/06
    }
    eventos = [(COMPRA, "A", 10.0), (COMPRA, "B", 10.0), (date(2026, 6, 1), "B", -10.0)]
    serie, sin = valor_diario(eventos, cierres)
    assert serie[-1] == (date(2026, 10, 2), 1000.0) and sin == []
    # Y mientras B estaba, valía: la serie no se la olvida.
    assert dict(serie)[date(2026, 5, 29)] == 1500.0


def test_un_ticker_EN_CARTERA_atrasado_sigue_cortando():
    """La regla de la 305 sigue en pie para lo que está en cartera: no se congela a nadie."""
    cierres = {
        "A": _cierres(date(2026, 4, 1), date(2026, 10, 2), 100.0),
        "C": _cierres(date(2026, 4, 1), date(2026, 9, 15), 20.0),
    }
    serie, _ = valor_diario([(COMPRA, "A", 1.0), (COMPRA, "C", 1.0)], cierres)
    assert serie[-1][0] == date(2026, 9, 15)


def test_si_se_vendio_TODO_llega_al_ultimo_cierre_que_haya():
    """Dos vendidos con caches que terminan en fechas distintas: el corte es el más nuevo."""
    cierres = {
        "A": _cierres(date(2026, 4, 1), date(2026, 10, 2), 100.0),
        "B": _cierres(date(2026, 4, 1), date(2026, 6, 5), 50.0),
    }
    eventos = [
        (COMPRA, "A", 5.0),
        (COMPRA, "B", 5.0),
        (date(2026, 6, 1), "B", -5.0),
        (date(2026, 7, 1), "A", -5.0),
    ]
    serie, _ = valor_diario(eventos, cierres)
    assert serie[-1] == (date(2026, 10, 2), 0.0)
