"""
run_scan cancela un aviso de salida ATR pendiente cuando el precio se recupera
y el gatillo ya no aplica (la posición sigue abierta). Si el precio sigue
gatillando, el aviso se mantiene.
"""

from __future__ import annotations

import pandas as pd

from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.engine import run_scan
from paper_trading.models import PaperOrder, PaperPosition


def _flat_df(n: int = 60, close: float = 100.0, pad: float = 0.5) -> pd.DataFrame:
    """OHLCV plano → ATR ≈ pad. Suficientes barras para el período por defecto."""
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": [close] * n,
            "High": [close + pad] * n,
            "Low": [close - pad] * n,
            "Close": [close] * n,
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


def _setup_stop_pending(mode: str = "manual"):
    """Cuenta + posición KO abierta + aviso atr_stop pendiente. Devuelve (acct_id, order_id)."""
    settings.set("atr_stops_enabled", True)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 2.0)
    settings.set("atr_tp_mult", 50.0)  # TP no dispara (50×ATR=50 → TP@150, fuera de alcance; máx permitido)
    settings.set("atr_trail_enabled", False)  # aislar el hard stop
    a = create_account(name="RiskExit", initial_capital=10_000.0, mode=mode)
    with session_scope() as session:
        session.add(
            PaperPosition(
                account_id=a.id,
                ticker="KO",
                shares=10.0,
                avg_cost=100.0,
                high_water_mark=100.0,
                opened_at=utcnow_naive(),
            )
        )
        order = PaperOrder(
            account_id=a.id,
            ticker="KO",
            side="SELL",
            target_shares=10.0,
            reason="atr_stop @ 98.00 ≤ 98.00 (entry 100.00 − 2.0×ATR 1.00)",
            source="atr_stop_gate",
            status="pending",
        )
        session.add(order)
        session.flush()
        oid = order.id
    return a.id, oid


def test_recovered_price_cancels_pending_stop(test_db):
    acct_id, oid = _setup_stop_pending()
    df = _flat_df()
    # Precio 105 > stop 98 → el ATR ya no dispara → el aviso debe cancelarse.
    run_scan(
        acct_id,
        prices_provider=lambda _ts: {"KO": 105.0},
        history_provider=lambda _t: df,
        earnings_provider=lambda _t: None,
    )
    with session_scope() as session:
        o = session.query(PaperOrder).filter(PaperOrder.id == oid).first()
        assert o.status == "expired"
        assert "recuper" in (o.notes or "")


def test_still_triggered_keeps_pending_stop(test_db):
    acct_id, oid = _setup_stop_pending()
    df = _flat_df()
    # Precio 90 ≤ stop 98 → el ATR sigue gatillando → el aviso se mantiene.
    run_scan(
        acct_id,
        prices_provider=lambda _ts: {"KO": 90.0},
        history_provider=lambda _t: df,
        earnings_provider=lambda _t: None,
    )
    with session_scope() as session:
        o = session.query(PaperOrder).filter(PaperOrder.id == oid).first()
        assert o.status == "pending"
