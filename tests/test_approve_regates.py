"""
Tests T7.2 (M4 del code review): ``approve_order`` re-aplica Gate 1 (market
hours) y Gate 6 (earnings blackout) al momento de aprobar.

Contrato:
- Orden bloqueada NO se consume: queda ``pending`` con el motivo en notes.
- ``override_gates=True`` saltea los re-gates (aprobación humana explícita).
- Semántica de Gate 6 idéntica a run_scan: BUYs siempre, SELLs solo con
  ``earnings_blackout_block_sells=True``, exits ATR-forzados pasan, fail-open
  si el provider explota.
- ``reconcile_account`` barre además las órdenes en limbo ``approved``
  (pre-fix) más viejas que el cutoff.
"""

from __future__ import annotations

from datetime import timedelta

from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.engine import _approval_gate_block, approve_order, reconcile_account
from paper_trading.models import PaperOrder


def _order(**kw) -> PaperOrder:
    base = dict(
        account_id=1,
        ticker="AAPL",
        side="BUY",
        target_dollars=500.0,
        status="pending",
        reason="analyze BUY (0.72)",
    )
    base.update(kw)
    return PaperOrder(**base)


def _earnings_tomorrow(_ticker: str):
    return utcnow_naive() + timedelta(days=1)


def _no_earnings(_ticker: str):
    return None


# ── Unit: _approval_gate_block ────────────────────────────────────────────────


class TestGate1MarketHours:
    def test_market_closed_blocks(self, monkeypatch):
        from paper_trading import engine

        monkeypatch.setattr(engine, "_is_market_open_safe", lambda: False)
        reason = _approval_gate_block(_order(), _no_earnings)
        assert reason is not None and "mercado cerrado" in reason

    def test_market_closed_but_enforce_off_passes(self, monkeypatch):
        from paper_trading import engine

        monkeypatch.setattr(engine, "_is_market_open_safe", lambda: False)
        settings.set("paper_enforce_market_hours", False)
        assert _approval_gate_block(_order(), _no_earnings) is None

    def test_market_open_passes(self, monkeypatch):
        from paper_trading import engine

        monkeypatch.setattr(engine, "_is_market_open_safe", lambda: True)
        assert _approval_gate_block(_order(), _no_earnings) is None


class TestGate6EarningsBlackout:
    def setup_method(self):
        settings.set("paper_enforce_market_hours", False)  # aislar Gate 1

    def test_buy_within_blackout_blocked(self):
        reason = _approval_gate_block(_order(), _earnings_tomorrow)
        assert reason is not None and "earnings" in reason

    def test_buy_no_earnings_passes(self):
        assert _approval_gate_block(_order(), _no_earnings) is None

    def test_buy_far_earnings_passes(self):
        far = lambda _t: utcnow_naive() + timedelta(days=30)
        assert _approval_gate_block(_order(), far) is None

    def test_sell_passes_by_default(self):
        # T08 default: SELLs de señal no se bloquean por blackout.
        o = _order(side="SELL", target_shares=3.0, target_dollars=None)
        assert _approval_gate_block(o, _earnings_tomorrow) is None

    def test_sell_blocked_with_legacy_flag(self):
        settings.set("earnings_blackout_block_sells", True)
        o = _order(side="SELL", target_shares=3.0, target_dollars=None)
        reason = _approval_gate_block(o, _earnings_tomorrow)
        assert reason is not None and "earnings" in reason

    def test_atr_forced_exit_bypasses(self):
        settings.set("earnings_blackout_block_sells", True)
        o = _order(side="SELL", target_shares=3.0, target_dollars=None, reason="atr_stop_loss")
        assert _approval_gate_block(o, _earnings_tomorrow) is None

    def test_provider_failure_fails_open(self):
        def boom(_t):
            raise RuntimeError("calendar API down")

        assert _approval_gate_block(_order(), boom) is None

    def test_blackout_days_zero_disables(self):
        settings.set("earnings_blackout_days", 0)
        assert _approval_gate_block(_order(), _earnings_tomorrow) is None


# ── Integración: approve_order ────────────────────────────────────────────────


def _prices(_tickers):
    return {"AAPL": 100.0}


class TestApproveOrderRegates:
    def _pending_buy(self, account_id: int) -> int:
        with session_scope() as session:
            o = _order(account_id=account_id)
            session.add(o)
            session.flush()
            return int(o.id)

    def test_blocked_order_stays_pending(self, test_db, monkeypatch):
        from paper_trading import engine

        monkeypatch.setattr(engine, "_is_market_open_safe", lambda: False)
        a = create_account(name="Regate", initial_capital=10_000.0)
        oid = self._pending_buy(a.id)

        out = approve_order(oid, prices_provider=_prices, earnings_provider=_no_earnings)
        assert out is not None
        assert out.status == "pending"
        assert "bloqueada por re-gate" in (out.notes or "")
        assert "mercado cerrado" in (out.notes or "")

        # No se consumió: cash intacto y se puede reintentar.
        with session_scope() as session:
            from paper_trading.models import PaperAccount

            acct = session.query(PaperAccount).filter(PaperAccount.id == a.id).first()
            assert acct.cash == 10_000.0

    def test_override_fills_blocked_order(self, test_db, monkeypatch):
        from paper_trading import engine

        monkeypatch.setattr(engine, "_is_market_open_safe", lambda: False)
        a = create_account(name="Regate", initial_capital=10_000.0)
        oid = self._pending_buy(a.id)

        blocked = approve_order(oid, prices_provider=_prices, earnings_provider=_no_earnings)
        assert blocked.status == "pending"

        filled = approve_order(
            oid,
            prices_provider=_prices,
            earnings_provider=_no_earnings,
            override_gates=True,
        )
        assert filled is not None and filled.status == "filled"
        assert filled.fill_shares and filled.fill_shares >= 1

    def test_earnings_blackout_blocks_buy_at_approval(self, test_db):
        settings.set("paper_enforce_market_hours", False)
        a = create_account(name="Regate", initial_capital=10_000.0)
        oid = self._pending_buy(a.id)

        out = approve_order(oid, prices_provider=_prices, earnings_provider=_earnings_tomorrow)
        assert out.status == "pending"
        assert "earnings" in (out.notes or "")

    def test_clean_order_fills_normally(self, test_db):
        settings.set("paper_enforce_market_hours", False)
        a = create_account(name="Regate", initial_capital=10_000.0)
        oid = self._pending_buy(a.id)

        out = approve_order(oid, prices_provider=_prices, earnings_provider=_no_earnings)
        assert out is not None and out.status == "filled"


# ── Integración: reconcile barre el limbo "approved" ──────────────────────────


def test_reconcile_expires_approved_limbo(test_db):
    a = create_account(name="Limbo", initial_capital=10_000.0)
    old = utcnow_naive() - timedelta(hours=48)
    with session_scope() as session:
        session.add(_order(account_id=a.id, status="approved", created_at=old, ticker="KO"))
        session.add(_order(account_id=a.id, status="approved", ticker="MSFT"))  # fresca

    n = reconcile_account(a.id, expire_pending_after_hours=24)
    assert n == 1

    with session_scope() as session:
        rows = session.query(PaperOrder).filter(PaperOrder.account_id == a.id).all()
        by_ticker = {r.ticker: r for r in rows}
    assert by_ticker["KO"].status == "expired"
    assert "approved-limbo" in (by_ticker["KO"].notes or "")
    assert by_ticker["MSFT"].status == "approved"  # dentro del cutoff, no se toca
