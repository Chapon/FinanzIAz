"""Tarea 305 — Home grafica el valor de mercado por rueda, no un punto.

*«El home solo grafica 1 día»* (Chapa, 2026-10-04): la curva era el capital invertido neto, que
en «Mis Acciones» —siete compras, todas del 2026-04-14— es un solo día. Los casos usan una
cartera comprada en UN día, que es justo donde la serie vieja y la nueva difieren.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from database.cartera_real import resumen_home, valor_diario

D0 = date(2026, 4, 14)


def _ruedas(desde: date, n: int, precio0: float, paso: float = 1.0) -> list[tuple[date, float]]:
    return [(desde + timedelta(days=i), precio0 + paso * i) for i in range(n)]


def test_una_cartera_comprada_en_un_dia_da_UNA_RUEDA_POR_DIA():
    serie, sin = valor_diario([(D0, "AAA", 10.0)], {"AAA": _ruedas(D0, 30, 100.0)})
    assert len(serie) == 30 and sin == []
    assert serie[0] == (D0, 10 * 100.0)
    assert serie[-1] == (D0 + timedelta(days=29), 10 * 129.0)


def test_cada_rueda_usa_las_acciones_que_HABIA_ese_dia():
    eventos = [(D0, "AAA", 10.0), (D0 + timedelta(days=2), "AAA", -4.0), (D0 + timedelta(days=3), "BBB", 5.0)]
    cierres = {"AAA": _ruedas(D0, 5, 100.0, 0.0), "BBB": _ruedas(D0, 5, 20.0, 0.0)}
    serie, _ = valor_diario(eventos, cierres)
    assert [v for _, v in serie] == [1000.0, 1000.0, 600.0, 700.0, 700.0]


def test_antes_de_la_primera_compra_no_hay_ruedas():
    serie, _ = valor_diario([(D0 + timedelta(days=3), "AAA", 1.0)], {"AAA": _ruedas(D0, 6, 10.0)})
    assert serie[0][0] == D0 + timedelta(days=3)


def test_un_ticker_SIN_HISTORIA_se_dice_y_no_se_valua_en_cero():
    serie, sin = valor_diario([(D0, "AAA", 1.0), (D0, "ZZZ", 1.0)], {"AAA": _ruedas(D0, 3, 10.0, 0.0)})
    assert sin == ["ZZZ"]
    assert [v for _, v in serie] == [10.0, 10.0, 10.0]


def test_la_serie_TERMINA_donde_termina_el_ticker_mas_corto_en_vez_de_congelarlo():
    cierres = {"AAA": _ruedas(D0, 10, 10.0), "BBB": _ruedas(D0, 6, 10.0)}
    serie, _ = valor_diario([(D0, "AAA", 1.0), (D0, "BBB", 1.0)], cierres)
    assert serie[-1][0] == D0 + timedelta(days=5)


def test_una_rueda_que_le_falta_a_un_ticker_toma_su_cierre_anterior():
    cierres = {
        "AAA": [(D0, 10.0), (D0 + timedelta(days=1), 11.0), (D0 + timedelta(days=2), 12.0)],
        "BBB": [(D0, 5.0), (D0 + timedelta(days=2), 7.0)],
    }
    serie, _ = valor_diario([(D0, "AAA", 1.0), (D0, "BBB", 1.0)], cierres)
    assert [v for _, v in serie] == [15.0, 16.0, 19.0]


def test_sin_eventos_o_sin_ninguna_historia_queda_vacia():
    assert valor_diario([], {}) == ([], [])
    assert valor_diario([(D0, "ZZZ", 1.0)], {}) == ([], ["ZZZ"])


# ── resumen_home y la pantalla, con la DB de test ────────────────────────────


@pytest.fixture
def qapp():
    """La QApplication con referencia viva: si se descarta, Qt aborta el proceso (exit 127)."""
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def mis_acciones(test_db):
    from database.models import Portfolio, Position, Transaction, session_scope

    with session_scope() as s:
        pf = Portfolio(name="Mis Acciones")
        s.add(pf)
        s.flush()
        pos = Position(portfolio_id=pf.id, ticker="AAA", quantity=10, avg_buy_price=100.0)
        s.add(pos)
        s.flush()
        s.add(
            Transaction(
                position_id=pos.id,
                transaction_type="BUY",
                quantity=10,
                price=100.0,
                date=datetime(2026, 4, 14, 12),
            )
        )


def test_resumen_home_trae_el_valor_diario(mis_acciones):
    from database.models import session_scope

    with session_scope() as s:
        r = resumen_home(s, cierres=lambda ts: {"AAA": _ruedas(D0, 20, 100.0)})
    assert len(r["valor_diario"]) == 20 and len(r["invertido_neto"]) == 1


def test_home_grafica_el_valor_y_dice_hasta_cuando(mis_acciones, qapp, monkeypatch):
    import database.cartera_real as cr
    from ui.home_tab import HomeTab

    monkeypatch.setattr(cr, "cierres_del_cache", lambda ts: {"AAA": _ruedas(D0, 20, 100.0)})
    home = HomeTab()
    try:
        assert "valor de mercado, hasta el 03/05" in home.hero_title.text()
    finally:
        home.hero_chart.cleanup()


def test_home_sin_cierres_vuelve_al_invertido_neto_Y_LO_DICE(mis_acciones, qapp, monkeypatch):
    import database.cartera_real as cr
    from ui.home_tab import HomeTab

    monkeypatch.setattr(cr, "cierres_del_cache", lambda ts: {})
    home = HomeTab()
    try:
        assert "invertido neto (sin cierres en el cache)" in home.hero_title.text()
    finally:
        home.hero_chart.cleanup()
