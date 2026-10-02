"""Tarea 266 — la caja y las posiciones se cuadran contra las órdenes en cada scan.

El defecto (``docs/auditoria_cuentas_2026-10-02.md`` [G-2]): ``reconcile_account`` sólo expiraba
pendientes; nada verificaba que la caja fuera capital + ventas − compras − comisiones +
dividendos, ni que las acciones fueran las de los fills. Medido el 2026-10-02 (las dos cuentas
cuadran al centavo); este guard avisa si deja de pasar.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from paper_trading.cuadre import descuadres

D1 = datetime(2026, 9, 1, 15, 0)
D2 = datetime(2026, 9, 20, 15, 0)


# ── La función pura ──────────────────────────────────────────────────────────


def test_una_cuenta_sana_cuadra():
    fills = [("AAA", "BUY", 10, 100.0, 1.0, D1), ("AAA", "SELL", 4, 110.0, 1.0, D2)]
    caja = 10_000 - (1000 + 1) + (440 - 1)
    assert descuadres(10_000, caja, fills, 0.0, {}, {"AAA": 6}) == []


def test_una_venta_que_no_entro_a_la_caja_DESCUADRA():
    fills = [("AAA", "BUY", 10, 100.0, 0.0, D1), ("AAA", "SELL", 4, 110.0, 0.0, D2)]
    pr = descuadres(10_000, 10_000 - 1000, fills, 0.0, {}, {"AAA": 6})
    assert len(pr) == 1 and "caja" in pr[0]


def test_acciones_de_mas_en_la_posicion_DESCUADRAN():
    pr = descuadres(10_000, 9_000, [("AAA", "BUY", 10, 100.0, 0.0, D1)], 0.0, {}, {"AAA": 12})
    assert pr == ["AAA: la posición tiene 12 acciones y las órdenes dan 10"]


def test_los_dividendos_entran_a_la_caja():
    assert descuadres(10_000, 9_025, [("AAA", "BUY", 10, 100.0, 0.0, D1)], 25.0, {}, {"AAA": 10}) == []


def test_un_split_del_ledger_cuadra_y_uno_sin_ledger_no():
    """Desde la 262 las acciones de una posición que atravesó un split no son la suma de sus fills."""
    fills = [("AAA", "BUY", 10, 100.0, 0.0, D1)]
    assert descuadres(10_000, 9_000, fills, 0.0, {("AAA", "2026-09-10"): 2.0}, {"AAA": 20}) == []
    assert descuadres(10_000, 9_000, fills, 0.0, {}, {"AAA": 20}) != []


def test_un_centavo_por_fill_de_tolerancia():
    fills = [("AAA", "BUY", 1, 100.0, 0.0, D1)] * 3
    assert descuadres(10_000, 9_700.02, fills, 0.0, {}, {"AAA": 3}) == []
    assert descuadres(10_000, 9_700.05, fills, 0.0, {}, {"AAA": 3}) != []


# ── Contra la DB ─────────────────────────────────────────────────────────────


def _cuenta_con(test_db, *, caja: float, anulada: bool = False):
    from database.models import session_scope
    from paper_trading.account import create_account
    from paper_trading.models import PaperAccount, PaperOrder, PaperPosition

    acct = create_account(name="Cuadre", initial_capital=10_000.0)
    with session_scope() as s:
        s.query(PaperAccount).filter(PaperAccount.id == acct.id).one().cash = caja
        s.add(
            PaperOrder(
                account_id=acct.id,
                ticker="AAA",
                side="BUY",
                status="filled",
                fill_shares=10.0,
                fill_price=100.0,
                commission_paid=1.0,
                filled_at=D1,
            )
        )
        if anulada:
            # Las KLAC de E5: ejecutadas y después anuladas, con la caja revertida.
            s.add(
                PaperOrder(
                    account_id=acct.id,
                    ticker="KLAC",
                    side="BUY",
                    status="voided",
                    fill_shares=2.0,
                    fill_price=1942.70,
                    commission_paid=1.0,
                    filled_at=D1,
                )
            )
        s.add(PaperPosition(account_id=acct.id, ticker="AAA", shares=10.0, avg_cost=100.1))
    return acct.id


def test_una_orden_ANULADA_no_cuenta(test_db):
    from paper_trading.cuadre import cuadrar_cuenta

    aid = _cuenta_con(test_db, caja=10_000 - 1001, anulada=True)
    assert cuadrar_cuenta(aid) == []


def test_un_ERROR_no_se_lee_como_que_cuadra(test_db, monkeypatch):
    """La primera versión devolvía `[]` ante un error: con la DB sin migrar, decía «cuadra»."""
    from paper_trading import cuadre

    aid = _cuenta_con(test_db, caja=10_000 - 1001)

    def explota(*a, **k):
        raise RuntimeError("no such table: paper_split_adjustments")

    monkeypatch.setattr(cuadre, "descuadres", explota)
    assert cuadre.cuadrar_cuenta(aid) is None
    assert cuadre.chequear_y_avisar(aid, "Cuadre") == ["no se pudo cuadrar la cuenta (ver el log)"]


# ── El aviso ─────────────────────────────────────────────────────────────────


@pytest.fixture
def slack(monkeypatch):
    from paper_trading import cuadre

    enviados: list[str] = []
    monkeypatch.setattr(cuadre, "_notifier", lambda t: enviados.append(t) or True)
    monkeypatch.setattr(cuadre, "_avisado", {})
    return enviados


def test_un_descuadre_avisa_UNA_vez_y_se_rearma_al_cuadrar(test_db, slack):
    from database.models import session_scope
    from paper_trading.cuadre import chequear_y_avisar
    from paper_trading.models import PaperAccount

    aid = _cuenta_con(test_db, caja=5_000.0)  # no cuadra
    w1 = chequear_y_avisar(aid, "Cuadre")
    chequear_y_avisar(aid, "Cuadre")
    assert len(slack) == 1 and "no cuadra" in slack[0]
    assert w1 and w1[0].startswith("no cuadra: caja")

    with session_scope() as s:
        s.query(PaperAccount).filter(PaperAccount.id == aid).one().cash = 10_000 - 1001
    assert chequear_y_avisar(aid, "Cuadre") == []
    with session_scope() as s:
        # El MISMO descuadre que antes: sólo avisa de nuevo si cuadrar rearmó el aviso (con
        # uno distinto avisaría igual por la firma nueva, y el test no distinguiría).
        s.query(PaperAccount).filter(PaperAccount.id == aid).one().cash = 5_000.0
    chequear_y_avisar(aid, "Cuadre")
    assert len(slack) == 2, "el mismo descuadre, después de haber cuadrado, vuelve a avisar"


def test_el_aviso_respeta_el_switch_de_salud(test_db, slack):
    from config.settings_manager import settings
    from paper_trading.cuadre import chequear_y_avisar

    settings.set("slack_data_outage_enabled", False)
    aid = _cuenta_con(test_db, caja=5_000.0)
    assert chequear_y_avisar(aid, "Cuadre")
    assert slack == []


def test_run_scan_reporta_el_descuadre(test_db, monkeypatch):
    """El cable: el scan corre el cuadre y lo reporta en sus warnings."""
    from paper_trading import cuadre, engine
    from paper_trading.account import create_account

    llamadas = []
    monkeypatch.setattr(
        cuadre, "chequear_y_avisar", lambda aid, nombre: llamadas.append(aid) or ["no cuadra: prueba"]
    )
    acct = create_account(name="Scan", initial_capital=1_000.0)
    result = engine.run_scan(acct.id, prices_provider=lambda _t: {}, history_provider=lambda _t: None)
    assert llamadas == [acct.id]
    assert "no cuadra: prueba" in result.warnings
