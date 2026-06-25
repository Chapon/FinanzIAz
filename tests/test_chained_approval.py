"""
Tests — aprobación encadenada de BUY/SELL en cuenta manual (tarea ② · N2).

Bug: en manual una BUY se sizea contra ``cash + est_proceeds`` (proceeds de
SELLs del mismo scan que todavía no se ejecutaron). Si el usuario aprueba la
BUY antes que la SELL que la financia, ``_fill_trade`` topa el budget en
``acct.cash`` (≈0) → devuelve None → la BUY expiraba por "cash fantasma"
(12 BUYs expiradas, auditoría 2026-06-25).

Fix: ``approve_order`` deja la BUY ``pending`` (no la expira) mientras haya una
SELL pendiente que pueda liberar cash. Aprobar la SELL libera el cash; re-
aprobar la BUY la llena al budget real al precio de aprobación, sin sobre-
apalancar (``_fill_trade`` nunca gasta más que ``acct.cash``).
"""

from __future__ import annotations

from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.engine import approve_order
from paper_trading.models import PaperAccount, PaperOrder, PaperPosition


def _prices(_tickers):
    return {"XOM": 100.0, "NVDA": 100.0}


def _no_earnings(_ticker):
    return None


def _setup_manual_account(*, cash: float):
    """Cuenta manual con cash bajo + posición vendible (XOM) + 1 SELL pendiente
    (XOM, ~$5.000 de proceeds) + 1 BUY pendiente (NVDA, $5.000 sizeada contra
    cash+proceeds que el cash solo no cubre)."""
    settings.set("paper_enforce_market_hours", False)
    settings.set("earnings_blackout_days", 0)
    a = create_account(name="Chain", initial_capital=50_000.0, mode="manual")
    with session_scope() as s:
        acct = s.query(PaperAccount).filter(PaperAccount.id == a.id).first()
        acct.cash = float(cash)
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="XOM",
                shares=50.0,
                avg_cost=100.0,
                opened_at=utcnow_naive(),
                high_water_mark=100.0,
            )
        )
        sell = PaperOrder(
            account_id=a.id, ticker="XOM", side="SELL", target_shares=50.0,
            target_dollars=None, status="pending", reason="analyze SELL (0.30)",
        )
        buy = PaperOrder(
            account_id=a.id, ticker="NVDA", side="BUY", target_shares=None,
            target_dollars=5_000.0, status="pending", reason="analyze BUY (0.72)",
        )
        s.add(sell)
        s.add(buy)
        s.flush()
        return a.id, int(sell.id), int(buy.id)


def test_buy_before_sell_stays_pending_not_expired(test_db):
    """Aprobar la BUY primero, sin cash, NO la expira: queda pending esperando
    la SELL (cash insuficiente ni para 1 acción)."""
    acct_id, sell_id, buy_id = _setup_manual_account(cash=50.0)  # < 1 acción NVDA

    out = approve_order(buy_id, prices_provider=_prices, earnings_provider=_no_earnings)
    assert out is not None
    assert out.status == "pending"
    assert "queda pendiente" in (out.notes or "")

    # No se consumió cash.
    with session_scope() as s:
        acct = s.query(PaperAccount).filter(PaperAccount.id == acct_id).first()
        assert acct.cash == 50.0


def test_chained_flow_sell_then_buy_both_fill(test_db):
    """Flujo completo: aprobar BUY (queda pending) → aprobar SELL (libera cash)
    → re-aprobar BUY (se llena al budget real, sin sobre-apalancar)."""
    acct_id, sell_id, buy_id = _setup_manual_account(cash=50.0)

    # 1) BUY primero → pending.
    out1 = approve_order(buy_id, prices_provider=_prices, earnings_provider=_no_earnings)
    assert out1.status == "pending"

    # 2) SELL libera cash (~50*100 menos fees ≈ $5.000).
    sell = approve_order(sell_id, prices_provider=_prices, earnings_provider=_no_earnings)
    assert sell is not None and sell.status == "filled"
    with session_scope() as s:
        acct = s.query(PaperAccount).filter(PaperAccount.id == acct_id).first()
        cash_after_sell = acct.cash
    assert cash_after_sell > 4_000.0

    # 3) Re-aprobar la BUY → ahora se llena.
    out2 = approve_order(buy_id, prices_provider=_prices, earnings_provider=_no_earnings)
    assert out2 is not None and out2.status == "filled"
    assert out2.fill_shares is not None and out2.fill_shares >= 1

    # Sin sobre-apalancar: el cash nunca queda negativo y el costo de la BUY no
    # excede el cash que había al aprobarla.
    with session_scope() as s:
        acct = s.query(PaperAccount).filter(PaperAccount.id == acct_id).first()
        assert acct.cash >= -1e-6
    assert out2.fill_value is not None and out2.fill_value <= cash_after_sell + 1e-6


def test_buy_without_pending_sell_expires(test_db):
    """Sin SELL pendiente que la financie, una BUY sub-financiada SÍ expira
    (no hay liquidez por venir → no tiene sentido dejarla colgada)."""
    acct_id, sell_id, buy_id = _setup_manual_account(cash=50.0)
    # Rechazamos/eliminamos la SELL pendiente para que no haya financiamiento.
    with session_scope() as s:
        sell = s.query(PaperOrder).filter(PaperOrder.id == sell_id).first()
        sell.status = "rejected"

    out = approve_order(buy_id, prices_provider=_prices, earnings_provider=_no_earnings)
    assert out is not None
    assert out.status == "expired"
    assert "fill rechazado" in (out.notes or "")


def test_funded_buy_still_fills_directly(test_db):
    """Contraprueba: si hay cash de sobra, la BUY se llena directo (el encadenado
    no interfiere con el camino normal)."""
    acct_id, sell_id, buy_id = _setup_manual_account(cash=10_000.0)
    out = approve_order(buy_id, prices_provider=_prices, earnings_provider=_no_earnings)
    assert out is not None and out.status == "filled"
    assert out.fill_shares is not None and out.fill_shares >= 1
