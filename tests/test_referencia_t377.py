"""Tarea 377 — la curva de referencia que no elige nada (``paper_trading/referencia.py``).

Los casos están elegidos para que la versión correcta y la defectuosa **den distinto**: con un
solo ticker, o con precios que no se mueven después del rebalanceo, mantener y rebalancear
coinciden y el test no fijaría nada.
"""

from __future__ import annotations

import os
from datetime import date, datetime

import pytest

from paper_trading.referencia import curva_sin_elegir, dia_de_alta, referencia_de_cuenta

D = date


def _cierres():
    # A se duplica en enero y vuelve en febrero; B no se mueve. El 2026-02-02 es el primer día
    # de un mes nuevo: ahí se rebalancea.
    return {
        "A": [(D(2026, 1, 29), 10.0), (D(2026, 1, 30), 20.0), (D(2026, 2, 2), 20.0), (D(2026, 2, 3), 10.0)],
        "B": [(D(2026, 1, 29), 10.0), (D(2026, 1, 30), 10.0), (D(2026, 2, 2), 10.0), (D(2026, 2, 3), 10.0)],
    }


def test_rebalancear_y_mantener_dan_distinto_y_cada_uno_da_lo_calculado_a_mano():
    # A mano: 5 acciones de cada uno a 10. El 30/01 vale 5·20 + 5·10 = 150. El 02/02 se lleva a
    # 75 y 75: 3,75 de A y 7,5 de B. El 03/02 A vuelve a 10: 37,5 + 75 = 112,5.
    r = curva_sin_elegir(_cierres(), 100.0, D(2026, 1, 29))
    assert r.serie == [
        (D(2026, 1, 29), pytest.approx(100.0)),
        (D(2026, 1, 30), pytest.approx(150.0)),
        (D(2026, 2, 2), pytest.approx(150.0)),
        (D(2026, 2, 3), pytest.approx(112.5)),
    ]
    # Sin rebalancear, las 5 y 5 del principio: 50 + 50 = 100.
    m = curva_sin_elegir(_cierres(), 100.0, D(2026, 1, 29), rebalancear=False)
    assert m.serie[-1][1] == pytest.approx(100.0)
    assert r.n == 2 and r.costos == 0.0


def test_el_costo_se_descuenta_en_la_compra_y_en_cada_rebalanceo():
    def uno_por_ciento(side, acciones, precio):
        return 0.01 * acciones * precio

    r = curva_sin_elegir(_cierres(), 100.0, D(2026, 1, 29), uno_por_ciento)
    # Compra: 1% de 100 = 1 ⇒ 99 netos, 4,95 acciones de cada uno.
    assert r.serie[0][1] == pytest.approx(99.0)
    # 30/01: 4,95·20 + 4,95·10 = 148,5. El 02/02 se mueven 24,75 en cada pata ⇒ 0,495 de costo.
    assert r.serie[1][1] == pytest.approx(148.5)
    assert r.serie[2][1] == pytest.approx(148.5 - 0.495)
    assert r.costos == pytest.approx(1.0 + 0.495)


def test_arranca_con_el_ultimo_cierre_del_dia_del_alta_aunque_sea_feriado():
    # La cuenta 2 se dio de alta el 19/06/2026 (Juneteenth, sin cierres) y compró a los del 18.
    cierres = {
        "A": [(D(2026, 6, 18), 10.0), (D(2026, 6, 22), 11.0)],
        "B": [(D(2026, 6, 18), 10.0), (D(2026, 6, 22), 10.0)],
    }
    r = curva_sin_elegir(cierres, 100.0, D(2026, 6, 19))
    assert r.serie[0] == (D(2026, 6, 18), pytest.approx(100.0))
    assert r.serie[-1][1] == pytest.approx(105.0)


def test_un_ticker_sin_precio_el_dia_de_arranque_queda_afuera_y_nombrado():
    cierres = _cierres() | {"NUEVO": [(D(2026, 2, 2), 50.0), (D(2026, 2, 3), 60.0)], "VACIO": []}
    r = curva_sin_elegir(cierres, 100.0, D(2026, 1, 29))
    assert r.sin_historia == ["NUEVO", "VACIO"]
    assert r.n == 2
    assert r.serie[-1][1] == pytest.approx(112.5)  # lo mismo que sin ellos


def test_uno_que_dejo_de_cotizar_se_mantiene_quieto_y_no_corta_la_curva_de_los_demas():
    dias = [D(2026, 3, d) for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)]
    cierres = {
        "VIVO": [(d, 10.0 + i) for i, d in enumerate(dias)],
        "MUERTO": [(d, 10.0) for d in dias[:2]],  # último cierre el 03/03, 8 ruedas antes
    }
    r = curva_sin_elegir(cierres, 100.0, D(2026, 3, 2), rebalancear=False)
    assert r.quietos == [("MUERTO", D(2026, 3, 3))]
    assert r.serie[-1][0] == D(2026, 3, 13)
    # 5 de VIVO a 19 + 5 de MUERTO a su último 10 = 145.
    assert r.serie[-1][1] == pytest.approx(145.0)


def test_un_atraso_corto_no_lo_da_por_muerto_y_la_curva_termina_donde_llegan_todos():
    cierres = {
        "A": [(D(2026, 3, 2), 10.0), (D(2026, 3, 3), 10.0), (D(2026, 3, 4), 12.0)],
        "B": [(D(2026, 3, 2), 10.0), (D(2026, 3, 3), 10.0)],  # un día atrás: el cache, no la bolsa
    }
    r = curva_sin_elegir(cierres, 100.0, D(2026, 3, 2))
    assert r.quietos == []
    assert r.serie[-1][0] == D(2026, 3, 3)


def test_el_dia_de_alta_es_el_de_nueva_york():
    # 2026-06-20 01:40 UTC es el 19/06 a las 21:40 en Nueva York.
    assert dia_de_alta(datetime(2026, 6, 20, 1, 40)) == D(2026, 6, 19)


def test_la_referencia_de_una_cuenta_usa_su_watchlist_su_capital_y_los_costos_del_motor(test_db):
    from database.models import session_scope
    from paper_trading.account import add_watchlist_tickers, create_account
    from paper_trading.models import PaperAccount

    acct = create_account(name="Ref", initial_capital=1_000.0, slippage=0.01)
    add_watchlist_tickers(acct.id, ["A", "B"])
    with session_scope() as s:
        s.get(PaperAccount, acct.id).created_at = datetime(2026, 1, 29, 18, 0)
    r = referencia_de_cuenta(acct.id, cierres=_cierres() | {"OTRO": _cierres()["A"]})
    assert r.n == 2  # OTRO no está en la watchlist
    # Slippage 1% más la comisión del plan activo (IBKR: mínimo $1 por fill) en cada compra.
    assert r.serie[0][1] < 1_000.0 - 10.0
    assert r.costos > 10.0


# ── Home ─────────────────────────────────────────────────────────────────────

REF = "Universo de Sim Segundo, sin elegir"


@pytest.fixture
def home(test_db, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    import database.cartera_real as cr
    from database.models import session_scope
    from paper_trading.account import add_watchlist_tickers
    from paper_trading.models import PaperAccount, PaperEquitySnapshot

    global _APP
    _APP = QApplication.instance() or QApplication([])  # referencia viva (la lección de la 323)
    with session_scope() as s:
        viva = PaperAccount(
            name="Sim Segundo", initial_capital=100.0, is_active=True, created_at=datetime(2026, 1, 29, 18, 0)
        )
        s.add(viva)
        s.flush()
        for ts, eq in ((datetime(2026, 1, 30, 18), 101.0), (datetime(2026, 2, 3, 18), 103.0)):
            s.add(
                PaperEquitySnapshot(
                    account_id=viva.id, snapshot_at=ts, cash=1.0, positions_value=eq - 1, total_equity=eq
                )
            )
        vid = viva.id
    add_watchlist_tickers(vid, ["A", "B"])
    monkeypatch.setattr(cr, "cierres_del_cache", lambda ts: {t: _cierres()[t] for t in ts if t in _cierres()})
    from ui.home_tab import HomeTab

    h = HomeTab()
    h.vid = vid
    yield h
    h.hero_chart.cleanup()
    h.deleteLater()


def _lineas(home):
    return {ln.get_label(): ln for ln in home.hero_chart.ax.lines}


def _vista(home, clave):
    home.vista_combo.setCurrentIndex(home.vista_combo.findData(clave))


def test_home_pinta_la_referencia_punteada_al_lado_de_la_cuenta(home):
    for cb in home.cuenta_checks.values():
        cb.setChecked(False)
    home.cuenta_checks[home.vid].setChecked(True)
    esperada = referencia_de_cuenta(home.vid)
    assert len(esperada.serie) == 4  # el caso del primer test, con los costos del motor

    lineas = _lineas(home)
    assert set(lineas) == {REF, "Paper · Sim Segundo"}
    assert lineas[REF].get_linestyle() == "--"
    assert [float(y) for y in lineas[REF].get_ydata()] == pytest.approx([v for _, v in esperada.serie])
    assert "Punteada: los 2 de la watchlist" in home.hero_sub.text()

    _vista(home, "ganancia")
    ys = [float(y) for y in _lineas(home)[REF].get_ydata()]
    assert ys == pytest.approx([v - 100.0 for _, v in esperada.serie])

    _vista(home, "invertido")
    assert REF not in _lineas(home)


def test_con_varias_tildadas_la_referencia_va_con_su_cuenta(home):
    for cb in home.cuenta_checks.values():
        cb.setChecked(True)
    lineas = _lineas(home)
    assert REF in lineas
    assert lineas[REF].get_color() == lineas["Sim Segundo"].get_color()
    assert REF in home.hero_sub.text()


def test_con_varias_tildadas_en_invertido_no_hay_referencia(home):
    # «Invertido» de una paper son las posiciones a mercado: el universo sin elegir no tiene par ahí.
    for cb in home.cuenta_checks.values():
        cb.setChecked(True)
    _vista(home, "invertido")
    assert REF not in _lineas(home)
    assert "Punteada" not in home.hero_sub.text()
