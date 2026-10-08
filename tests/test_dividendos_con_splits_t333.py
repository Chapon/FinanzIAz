"""Tarea 333 — El cobro de dividendos multiplicaba fills CRUDOS por montos AJUSTADOS.

El defecto (latente, salió verificando la 331): ``acreditar_dividendos`` contaba las acciones con
``PaperOrder.fill_shares`` tal cual, y el calendario viene **ajustado** por los splits posteriores.
La 262 ajusta la posición por un split, no los fills: para un ex-date posterior a un 10:1, una
posición comprada antes cobraba **1/10**. El panel (``_dividendos_devengados``) hacía la misma
cuenta y tenía el mismo defecto; ahora los dos usan ``acciones_al_ex_date_con_splits``.

Los casos están elegidos para que la versión con y sin splits **difieran** (×10), y para que un
ex-date anterior al split no cambie: ése ya se cobró, sobre el calendario de antes del split.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from database.models import DividendCalendarCache, session_scope, utcnow_naive
from paper_trading.dividends import acciones_al_ex_date_con_splits, acreditar_dividendos, creditos_pendientes
from paper_trading.models import PaperAccount, PaperOrder, PaperSpinoffAdjustment, PaperSplitAdjustment

SPLIT = "2026-06-10"
FILLS = [("NVDA", "BUY", 10.0, "2026-06-01 21:00:00")]
CAL = {"NVDA": [("2026-06-05", 0.4), ("2026-06-20", 0.04)]}  # el 06-05 ya cobrado antes del split


def test_un_ex_date_posterior_al_split_cobra_las_acciones_de_hoy():
    pend = creditos_pendientes(FILLS, CAL, set(), "2026-06-15", "2026-06-30", {"NVDA": [(SPLIT, 10.0)]})
    assert pend == [("NVDA", "2026-06-20", 100.0, 0.04)]  # 10 × 10 × $0,04 = $4, no $0,40


def test_un_ex_date_anterior_al_split_cobra_lo_mismo_que_antes():
    con = creditos_pendientes(FILLS, CAL, set(), "2026-06-01", "2026-06-09", {"NVDA": [(SPLIT, 10.0)]})
    sin = creditos_pendientes(FILLS, CAL, set(), "2026-06-01", "2026-06-09")
    assert con == sin == [("NVDA", "2026-06-05", 10.0, 0.4)]


def test_lo_comprado_el_dia_del_split_o_despues_ya_esta_en_la_escala_nueva():
    eventos = [("2026-06-01", 10.0), (SPLIT, 5.0), ("2026-06-12", 7.0), ("2026-06-15", -20.0)]
    # 10 × 10 + 5 + 7 − 20 = 92
    assert acciones_al_ex_date_con_splits(eventos, "2026-06-20", [(SPLIT, 10.0)]) == pytest.approx(92.0)


# ── Contra la DB: el motor y el panel ────────────────────────────────────────


def _cuenta_con_split(spinoff: bool = False) -> int:
    with session_scope() as s:
        a = PaperAccount(name="Sintetica333", initial_capital=10_000.0, cash=10_000.0)
        s.add(a)
        s.flush()
        s.add(
            PaperOrder(
                account_id=a.id,
                ticker="NVDA",
                side="BUY",
                status="filled",
                fill_shares=10.0,
                fill_price=100.0,
                filled_at=datetime(2026, 6, 1, 21),
            )
        )
        comunes = dict(
            account_id=a.id,
            ticker="NVDA",
            ex_date=SPLIT,
            avg_cost_before=100.0,
            hwm_before=None,
            hwm_after=None,
        )
        if spinoff:
            # Un reverse 1:2 dentro de un spin-off (la forma de HON 2026): 10 acciones → 5.
            s.add(
                PaperSpinoffAdjustment(
                    **comunes,
                    child_ticker="X",
                    q=0.5,
                    r=1.0,
                    parent_price=100.0,
                    child_price=10.0,
                    shares_at_ex=10.0,
                    share_ratio=0.5,
                    shares_before=10.0,
                    shares_after=5.0,
                    avg_cost_after=200.0,
                    cash=0.0,
                )
            )
        else:
            s.add(
                PaperSplitAdjustment(
                    **comunes, ratio=10.0, shares_before=10.0, shares_after=100.0, avg_cost_after=10.0
                )
            )
        s.add(
            DividendCalendarCache(ticker="NVDA", ex_date="2026-06-20", amount=0.04, fetched_at=utcnow_naive())
        )
        return a.id


def _acreditar(acct_id: int) -> list[dict]:
    with session_scope() as s:
        acct = s.query(PaperAccount).filter(PaperAccount.id == acct_id).one()
        return acreditar_dividendos(s, acct, "2026-06-15", "2026-06-30")


def test_el_motor_cobra_con_el_split_del_ledger(test_db):
    (c,) = _acreditar(_cuenta_con_split())
    assert c["shares"] == pytest.approx(100.0)
    assert c["cash"] == pytest.approx(4.0)


def test_el_motor_cobra_con_el_share_ratio_del_spinoff(test_db):
    (c,) = _acreditar(_cuenta_con_split(spinoff=True))
    assert c["shares"] == pytest.approx(5.0)


def test_el_panel_devenga_lo_mismo_que_el_motor():
    import analysis.metrics_panel as mp

    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_orders (id INTEGER PRIMARY KEY, account_id INT, ticker TEXT, side TEXT, "
        "fill_shares REAL, status TEXT, filled_at TEXT)"
    )
    con.execute(
        "CREATE TABLE dividend_calendar_cache (id INTEGER PRIMARY KEY, ticker TEXT, ex_date TEXT, amount REAL)"
    )
    con.execute(
        "CREATE TABLE paper_split_adjustments (account_id INT, ticker TEXT, ex_date TEXT, ratio REAL)"
    )
    con.execute(
        "INSERT INTO paper_orders (account_id, ticker, side, fill_shares, status, filled_at) "
        "VALUES (2,'NVDA','BUY',10,'filled','2026-06-01 21:00:00')"
    )
    con.execute(
        "INSERT INTO dividend_calendar_cache (ticker, ex_date, amount) VALUES ('NVDA','2026-06-20',0.04)"
    )
    con.execute(f"INSERT INTO paper_split_adjustments VALUES (2,'NVDA','{SPLIT}',10.0)")
    devengado, _ = mp._dividendos_devengados(con, 2, "2026-06-15", "2026-06-30")
    assert devengado == pytest.approx(4.0)  # sin el split: $0,40
