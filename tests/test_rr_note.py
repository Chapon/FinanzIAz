"""Integración: la nota R:R/stop/TP en los BUY (V2, display-only).

El engine estampa en ``PaperOrder.notes`` los niveles de riesgo ex-ante de cada
BUY (stop/TP + R:R) para que la UI de Paper los muestre. Es display-only: no
cambia ninguna decisión ni sizing (regla 3). La matemática pura está en
``test_paper_gates.py`` (entry_risk_levels/format_entry_risk_note).
"""

from __future__ import annotations

import pandas as pd

from config.settings_manager import settings
from database.models import session_scope
from paper_trading.account import create_account
from paper_trading.models import PaperOrder, PaperWatchlistItem


def _history_varying(price: float, n: int = 30) -> pd.DataFrame:
    """OHLCV con rango intradía no nulo → ATR > 0 (High/Low ≠ Close)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    closes = [price + (i % 3) for i in range(n)]  # oscila un poco
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 2.0 for c in closes],
            "Low": [c - 2.0 for c in closes],
            "Close": closes,
            "Volume": [10_000.0] * n,
        },
        index=idx,
    )


def _history_flat(price: float, n: int = 30) -> pd.DataFrame:
    """OHLCV constante → ATR = 0 → sin nota (fail-open)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [price] * n,
            "High": [price] * n,
            "Low": [price] * n,
            "Close": [price] * n,
            "Volume": [10_000.0] * n,
        },
        index=idx,
    )


def _isolate_other_gates() -> None:
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("earnings_blackout_days", 0)
    settings.set("paper_adv_cap_pct", 0.0)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 2.0)
    settings.set("atr_tp_mult", 4.0)
    # Tarea 55 — el MASTER SWITCH, explícito. Estos tests corrían sin ponerlo, o
    # sea con el default `False`, y aun así afirmaban que la nota se estampaba:
    # **codificaban el defecto**. El valor de la cuenta viva es `True`, que es lo
    # que hay que poner para probar el camino donde la nota tiene sentido.
    settings.set("atr_stops_enabled", True)


def _buy_strategy(ticker: str, dollars: float):
    from paper_trading.strategies import TargetTrade

    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker=ticker,
                side="BUY",
                target_shares=None,
                target_dollars=dollars,
                reason="analyze BUY",
                source="analyze_single",
            )
        ]

    return strat


def _run(monkeypatch, account, *, ticker, price, history, buy_dollars):
    from paper_trading import engine

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy(ticker, buy_dollars))
    return engine.run_scan(
        account.id,
        prices_provider=lambda _t: {ticker: price},
        history_provider=lambda _t: history,
        earnings_provider=lambda _t: None,
    )


def test_manual_buy_gets_rr_note(test_db, monkeypatch):
    a = create_account(name="RR", initial_capital=100_000.0, mode="manual")
    _isolate_other_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    result = _run(
        monkeypatch, a, ticker="AAPL", price=100.0, history=_history_varying(100.0), buy_dollars=10_000.0
    )

    assert result is not None and result.queued == 1
    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()
        assert order.notes is not None
        assert "R:R" in order.notes
        assert "stop $" in order.notes and "TP $" in order.notes


def test_auto_buy_fill_gets_rr_note(test_db, monkeypatch):
    a = create_account(name="RRauto", initial_capital=100_000.0, mode="auto")
    _isolate_other_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="MSFT"))

    result = _run(
        monkeypatch, a, ticker="MSFT", price=100.0, history=_history_varying(100.0), buy_dollars=10_000.0
    )

    assert result is not None and result.filled == 1
    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.filled_orders[0]).first()
        assert order.notes is not None and "R:R" in order.notes


def test_flat_history_no_note_failopen(test_db, monkeypatch):
    a = create_account(name="RRflat", initial_capital=100_000.0, mode="manual")
    _isolate_other_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="TSLA"))

    result = _run(
        monkeypatch, a, ticker="TSLA", price=100.0, history=_history_flat(100.0), buy_dollars=10_000.0
    )

    assert result is not None and result.queued == 1
    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()
        assert order.notes is None  # ATR 0 → sin nota, orden creada igual


def test_no_history_no_note_failopen(test_db, monkeypatch):
    from paper_trading import engine

    a = create_account(name="RRnohist", initial_capital=100_000.0, mode="manual")
    _isolate_other_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="NVDA"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("NVDA", 10_000.0))
    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"NVDA": 100.0},
        history_provider=lambda _t: None,
        earnings_provider=lambda _t: None,
    )

    assert result is not None and result.queued == 1
    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()
        assert order.notes is None


# ── El master switch: sin barreras no hay nota (tarea 55) ───────────────────


def test_con_el_master_APAGADO_no_hay_nota(test_db, monkeypatch):
    """**El defecto que arregla la 55.** Con `atr_stops_enabled=False`
    `_atr_exit_trades` devuelve `[]`: no hay stop, ni TP, ni trailing. Estampar
    "stop $X · TP $Y" es dibujar un plan de salida que el motor no tiene.

    Y no es una config exótica: `False` es el **default** del setting."""
    a = create_account(name="RRoff", initial_capital=100_000.0, mode="manual")
    _isolate_other_gates()
    settings.set("atr_stops_enabled", False)
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    result = _run(
        monkeypatch, a, ticker="AAPL", price=100.0, history=_history_varying(100.0), buy_dollars=10_000.0
    )

    assert result is not None and result.queued == 1, "la orden se crea igual (display-only)"
    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()
        assert order.notes is None, f"nota fantasma con el master apagado: {order.notes!r}"


def test_con_el_master_PRENDIDO_la_nota_vuelve(test_db, monkeypatch):
    """El control positivo del de arriba: si el guard nuevo silenciara la nota
    siempre, el test anterior pasaría igual y no probaría nada."""
    a = create_account(name="RRon", initial_capital=100_000.0, mode="manual")
    _isolate_other_gates()
    settings.set("atr_stops_enabled", True)
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    result = _run(
        monkeypatch, a, ticker="AAPL", price=100.0, history=_history_varying(100.0), buy_dollars=10_000.0
    )

    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()
        assert order.notes and "stop $" in order.notes and "TP $" in order.notes


def test_el_TP_tampoco_sobrevive_al_master(test_db, monkeypatch):
    """La diferencia con la 53, escrita. Ahí, apagar **el stop duro** dejaba el TP
    en pie —existe y no cambió— así que la nota se conservaba sin stop ni R:R. Acá
    el master apaga `_atr_exit_trades` **entera**: no queda barrera de ninguna
    clase, y por eso no hay nota en vez de una nota recortada."""
    a = create_account(name="RRtp", initial_capital=100_000.0, mode="manual")
    _isolate_other_gates()
    settings.set("atr_stops_enabled", False)
    settings.set("atr_hard_stop_enabled", True)  # el de la 53, prendido: no alcanza
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    result = _run(
        monkeypatch, a, ticker="AAPL", price=100.0, history=_history_varying(100.0), buy_dollars=10_000.0
    )

    with session_scope() as s:
        order = s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()
        assert order.notes is None
