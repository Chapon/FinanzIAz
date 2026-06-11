"""
Tests for Gate 5b (anti-churn v2, T6.5) in paper_trading.engine.

The gate blocks a fresh BUY when the ticker already closed >= N cycles within
the lookback window, *regardless of P/L*. Motivación (auditoría 2026-06-09):
el anti-whipsaw (Gate 5) solo mira ciclos perdedores y por eso no frenó el
churn de KO — 3 ciclos en 7 días, el primero ganador. Solo cuentan SELLs que
dejan la posición en cero: los trims parciales (T09 vol overlay) no son churn.
"""

from __future__ import annotations

from datetime import timedelta

from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.engine import _closed_cycles_count
from paper_trading.models import PaperOrder


def _add_order(session, account_id, ticker, side, fill_price, fill_shares, hours_ago):
    when = utcnow_naive() - timedelta(hours=hours_ago)
    session.add(
        PaperOrder(
            account_id=account_id,
            ticker=ticker,
            side=side,
            target_shares=fill_shares if side == "SELL" else None,
            target_dollars=fill_price * fill_shares if side == "BUY" else None,
            reason=f"test {side}",
            source="analyze_single",
            status="filled",
            created_at=when,
            decided_at=when,
            filled_at=when,
            fill_price=fill_price,
            fill_shares=fill_shares,
            commission_paid=0.0,
            slippage_cost=0.0,
        )
    )


def _add_cycle(session, account_id, ticker, buy_px, sell_px, shares, close_hours_ago):
    """One full BUY→SELL cycle whose SELL filled ``close_hours_ago`` hours ago."""
    _add_order(session, account_id, ticker, "BUY", buy_px, shares, close_hours_ago + 12)
    _add_order(session, account_id, ticker, "SELL", sell_px, shares, close_hours_ago)


# ── _closed_cycles_count ─────────────────────────────────────────────────────


def test_counts_full_cycles_within_window(test_db):
    """Caso KO: 3 ciclos en ~7 días, el primero ganador → cuenta 3."""
    a = create_account(name="C", initial_capital=10_000.0)
    with session_scope() as s:
        _add_cycle(s, a.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24 * 6)  # winner
        _add_cycle(s, a.id, "KO", 65.0, 64.0, 10.0, close_hours_ago=24 * 3)  # loser
        _add_cycle(s, a.id, "KO", 63.0, 63.5, 10.0, close_hours_ago=24 * 1)  # winner

    with session_scope() as s:
        assert _closed_cycles_count(s, a.id, "KO", within_days=10) == 3


def test_old_cycles_fall_out_of_window(test_db):
    """Solo cuentan los SELLs de cierre dentro de la ventana → cooldown expira."""
    a = create_account(name="C", initial_capital=10_000.0)
    with session_scope() as s:
        _add_cycle(s, a.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24 * 15)  # fuera
        _add_cycle(s, a.id, "KO", 65.0, 64.0, 10.0, close_hours_ago=24 * 3)
        _add_cycle(s, a.id, "KO", 63.0, 63.5, 10.0, close_hours_ago=24 * 1)

    with session_scope() as s:
        assert _closed_cycles_count(s, a.id, "KO", within_days=10) == 2


def test_partial_trims_do_not_count(test_db):
    """Un SELL parcial (vol-overlay trim) no cierra ciclo y no suma."""
    a = create_account(name="C", initial_capital=10_000.0)
    with session_scope() as s:
        _add_order(s, a.id, "NVDA", "BUY", 100.0, 10.0, hours_ago=96)
        _add_order(s, a.id, "NVDA", "SELL", 105.0, 4.0, hours_ago=72)  # trim
        _add_order(s, a.id, "NVDA", "SELL", 103.0, 2.0, hours_ago=48)  # trim
        _add_order(s, a.id, "NVDA", "SELL", 104.0, 4.0, hours_ago=24)  # cierra

    with session_scope() as s:
        assert _closed_cycles_count(s, a.id, "NVDA", within_days=10) == 1


def test_open_position_counts_nothing(test_db):
    a = create_account(name="C", initial_capital=10_000.0)
    with session_scope() as s:
        _add_order(s, a.id, "TSLA", "BUY", 300.0, 5.0, hours_ago=48)
        _add_order(s, a.id, "TSLA", "SELL", 310.0, 2.0, hours_ago=24)  # parcial

    with session_scope() as s:
        assert _closed_cycles_count(s, a.id, "TSLA", within_days=10) == 0


def test_fractional_shares_tolerance(test_db):
    """Shares fraccionales con ruido float igual cierran el ciclo."""
    a = create_account(name="C", initial_capital=10_000.0)
    with session_scope() as s:
        _add_order(s, a.id, "AAPL", "BUY", 100.0, 3.3333333333, hours_ago=48)
        _add_order(s, a.id, "AAPL", "SELL", 101.0, 3.3333333333, hours_ago=24)

    with session_scope() as s:
        assert _closed_cycles_count(s, a.id, "AAPL", within_days=10) == 1


def test_within_days_zero_disables(test_db):
    a = create_account(name="C", initial_capital=10_000.0)
    with session_scope() as s:
        _add_cycle(s, a.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24)

    with session_scope() as s:
        assert _closed_cycles_count(s, a.id, "KO", within_days=0) == 0


def test_other_ticker_and_account_isolated(test_db):
    a = create_account(name="C1", initial_capital=10_000.0)
    b = create_account(name="C2", initial_capital=10_000.0)
    with session_scope() as s:
        _add_cycle(s, a.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24)
        _add_cycle(s, b.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24)
        _add_cycle(s, a.id, "PEP", 170.0, 171.0, 5.0, close_hours_ago=24)

    with session_scope() as s:
        assert _closed_cycles_count(s, a.id, "KO", within_days=10) == 1
        assert _closed_cycles_count(s, b.id, "KO", within_days=10) == 1


# ── Gate 5b integración (run_scan) ───────────────────────────────────────────


def _base_settings():
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)  # aislar de Gate 3
    settings.set("paper_whipsaw_lookback_days", 0)  # aislar de Gate 5
    settings.set("paper_churn_max_cycles", 3)
    settings.set("paper_churn_lookback_days", 10)


def _buy_strategy(ticker):
    from paper_trading.strategies import TargetTrade

    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker=ticker,
                side="BUY",
                target_shares=None,
                target_dollars=1_000.0,
                reason="analyze BUY",
                source="analyze_single",
            )
        ]

    return strat


def test_gate_blocks_buy_after_churn(test_db, monkeypatch):
    """3 ciclos cerrados en la ventana (el primero GANADOR) → BUY bloqueado."""
    from paper_trading import engine
    from paper_trading.models import PaperWatchlistItem

    a = create_account(name="C", initial_capital=10_000.0)
    _base_settings()

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="KO"))
        _add_cycle(s, a.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24 * 6)
        _add_cycle(s, a.id, "KO", 65.0, 64.0, 10.0, close_hours_ago=24 * 3)
        _add_cycle(s, a.id, "KO", 63.0, 63.5, 10.0, close_hours_ago=24 * 1)

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("KO"))

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
    )

    assert result is not None
    assert result.filled == 0
    assert result.queued == 0
    assert result.skipped >= 1
    assert any("anti-churn" in w for w in result.warnings)


def test_gate_allows_buy_below_threshold(test_db, monkeypatch):
    """2 ciclos en la ventana (< 3) → BUY pasa."""
    from paper_trading import engine
    from paper_trading.models import PaperWatchlistItem

    a = create_account(name="C", initial_capital=10_000.0, mode="manual")
    _base_settings()

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="KO"))
        _add_cycle(s, a.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24 * 3)
        _add_cycle(s, a.id, "KO", 65.0, 64.0, 10.0, close_hours_ago=24 * 1)

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("KO"))

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("anti-churn" in w for w in result.warnings)


def test_gate_allows_buy_when_cycles_expired(test_db, monkeypatch):
    """3 ciclos pero 2 fuera de la ventana → cooldown expirado, BUY pasa."""
    from paper_trading import engine
    from paper_trading.models import PaperWatchlistItem

    a = create_account(name="C", initial_capital=10_000.0, mode="manual")
    _base_settings()

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="KO"))
        _add_cycle(s, a.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24 * 20)
        _add_cycle(s, a.id, "KO", 65.0, 64.0, 10.0, close_hours_ago=24 * 15)
        _add_cycle(s, a.id, "KO", 63.0, 63.5, 10.0, close_hours_ago=24 * 1)

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("KO"))

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("anti-churn" in w for w in result.warnings)


def test_gate_disabled_with_zero_setting(test_db, monkeypatch):
    """paper_churn_max_cycles=0 apaga el gate aunque haya churn."""
    from paper_trading import engine
    from paper_trading.models import PaperWatchlistItem

    a = create_account(name="C", initial_capital=10_000.0, mode="manual")
    _base_settings()
    settings.set("paper_churn_max_cycles", 0)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="KO"))
        _add_cycle(s, a.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24 * 6)
        _add_cycle(s, a.id, "KO", 65.0, 64.0, 10.0, close_hours_ago=24 * 3)
        _add_cycle(s, a.id, "KO", 63.0, 63.5, 10.0, close_hours_ago=24 * 1)

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy("KO"))

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("anti-churn" in w for w in result.warnings)


def test_gate_does_not_touch_sells(test_db, monkeypatch):
    """El gate es solo de BUYs: un SELL de señal pasa aunque haya churn."""
    from paper_trading import engine
    from paper_trading.models import PaperPosition, PaperWatchlistItem
    from paper_trading.strategies import TargetTrade

    a = create_account(name="C", initial_capital=10_000.0, mode="manual")
    _base_settings()
    # Aislar de Gate 2b (T6.4): score bajo bypassa la edad mínima.
    settings.set("paper_signal_sell_min_age_bdays", 0)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="KO"))
        _add_cycle(s, a.id, "KO", 60.0, 66.0, 10.0, close_hours_ago=24 * 6)
        _add_cycle(s, a.id, "KO", 65.0, 64.0, 10.0, close_hours_ago=24 * 3)
        _add_cycle(s, a.id, "KO", 63.0, 63.5, 10.0, close_hours_ago=24 * 1)
        # Posición abierta para poder vender.
        _add_order(s, a.id, "KO", "BUY", 62.0, 10.0, hours_ago=12)
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="KO",
                shares=10.0,
                avg_cost=62.0,
                opened_at=utcnow_naive() - timedelta(hours=12),
            )
        )

    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker="KO",
                side="SELL",
                target_shares=10.0,
                target_dollars=None,
                reason="analyze SELL",
                source="analyze_single",
            )
        ]

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: strat)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("anti-churn" in w for w in result.warnings)
