"""Tarea 281 — las tarjetas de Portfolio no valúan al costo un precio faltante, y los dividendos
se cuentan lote por lote.

[P-1] (``docs/auditoria_pantalla_resto_2026-10-02.md``): *Valor total*, *Ganancia* y *%* sumaban
una posición sin precio **al costo** —P&L cero— sin decirlo. [P-2]: *«Dividendos cobrados»*
multiplicaba el dividendo por acción desde UNA fecha por la cantidad ACTUAL.

Los casos están elegidos para que la versión vieja dé distinto: con dos tramos (10 + 10) y dos
ex-dates de $1, el cálculo viejo da **$40** (2 × $1 × 20 actuales) y el correcto **$30**.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from database.cartera_real import dividendos_cobrados
from ui.portfolio_tab import totales_cartera

# ── [P-2] dividendos por lote ────────────────────────────────────────────────


def test_dos_tramos_cobran_cada_uno_desde_SU_fecha():
    eventos = [("2026-01-01", 10.0), ("2026-06-01", 10.0)]
    calendario = [("2026-03-01", 1.0), ("2026-09-01", 1.0)]
    assert dividendos_cobrados(eventos, calendario) == pytest.approx(30.0)


def test_comprar_EL_DIA_del_ex_date_no_cobra():
    assert dividendos_cobrados([("2026-03-01", 10.0)], [("2026-03-01", 1.0)]) == 0.0


def test_vender_antes_del_ex_date_no_cobra_lo_vendido():
    eventos = [("2026-01-01", 10.0), ("2026-02-01", -6.0)]
    assert dividendos_cobrados(eventos, [("2026-03-01", 1.0)]) == pytest.approx(4.0)


def test_un_ex_date_anterior_a_la_primera_compra_no_cuenta():
    assert dividendos_cobrados([("2026-05-01", 10.0)], [("2026-03-01", 1.0)]) == 0.0


def test_el_centinela_de_no_paga_no_suma():
    assert dividendos_cobrados([("2026-01-01", 10.0)], [("0000-00-00", 0.0)]) == 0.0


# ── [P-1] las tarjetas ───────────────────────────────────────────────────────


def _pos(ticker, qty, avg):
    return SimpleNamespace(ticker=ticker, quantity=qty, avg_buy_price=avg)


def test_una_posicion_SIN_precio_no_entra_al_valor_ni_a_la_ganancia_y_se_nombra():
    posiciones = [_pos("AAA", 10, 100.0), _pos("BBB", 5, 50.0)]
    precios = {"AAA": {"price": 120.0}}  # BBB sin precio
    t = totales_cartera(posiciones, precios, {}, True)
    assert t["valor"] == pytest.approx(1200.0), "BBB entró al valor (al costo, sin decirlo)"
    assert t["pl_precio"] == pytest.approx(200.0)
    assert t["pl_pct"] == pytest.approx(20.0), "el % tiene que ser sobre el costo de las que tienen precio"
    assert t["sin_precio"] == ["BBB"]
    assert t["invertido"] == pytest.approx(1250.0), "el invertido sigue siendo el de todas"


def test_los_dividendos_son_EFECTIVO_por_posicion_no_por_accion():
    posiciones = [_pos("AAA", 20, 100.0)]
    t = totales_cartera(posiciones, {"AAA": {"price": 100.0}}, {"AAA": 30.0}, True)
    assert t["dividendos"] == pytest.approx(30.0), "se volvió a multiplicar por la cantidad"
    assert totales_cartera(posiciones, {"AAA": {"price": 100.0}}, {"AAA": 30.0}, False)["dividendos"] == 0.0


def test_las_tarjetas_usan_totales_cartera():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "ui" / "portfolio_tab.py").read_text(encoding="utf-8")
    cuerpo = src[src.index("    def _update_cards(self):") :]
    cuerpo = cuerpo[: cuerpo.index("\n    def ", 10)]
    assert "totales_cartera(" in cuerpo
    assert "avg_buy_price" not in cuerpo, "las tarjetas volvieron a hacer cuentas propias"


def test_el_worker_de_dividendos_usa_el_calculo_por_lote():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "ui" / "portfolio_tab.py").read_text(encoding="utf-8")
    assert "dividendos_cobrados(" in src
    assert "get_bulk_dividends(" not in src
