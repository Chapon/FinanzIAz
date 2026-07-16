"""
Regresión del incidente 2026-07-13: "database is locked" durante el scan.

``run_scan`` corre dentro de UNA transacción; desde el primer flush de
escritura (fills, o autoflush de los updates de HWM) la conexión retiene el
write lock de SQLite hasta el commit. Si dentro de esa ventana el loop de
gates hace llamadas de red (earnings del Gate 6, history del Gate 3b), la
ventana se estira a decenas de segundos y las escrituras concurrentes
(harvest, price_cache, earnings_cache — esta última desde el MISMO thread,
auto-bloqueo) mueren tras el busy_timeout de 30s.

El fix prefetchea earnings/history de todos los trades candidatos ANTES del
primer fill. Estos tests fijan ese orden: providers primero, fills después.
"""

from __future__ import annotations

from datetime import timedelta

from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.models import PaperWatchlistItem
from paper_trading.strategies import TargetTrade


def _two_buy_strategy(t1: str, t2: str):
    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker=t,
                side="BUY",
                target_shares=None,
                target_dollars=1_000.0,
                reason="analyze BUY",
                source="analyze_single",
            )
            for t in (t1, t2)
        ]

    return strat


def _relax_gates():
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("paper_min_holding_minutes", 0)
    settings.set("paper_signal_sell_min_age_bdays", 0)
    settings.set("earnings_blackout_days", 2)


def test_providers_run_before_first_fill(test_db, monkeypatch):
    """Toda la red (earnings + history de BUYs) ocurre antes del primer fill.

    Con el orden viejo (lookup dentro del loop) la secuencia era
    earnings(T1) → fill(T1) → earnings(T2) → ... y el lock de escritura
    quedaba abierto durante la llamada de red de T2.
    """
    from paper_trading import engine

    a = create_account(name="LockWin", initial_capital=50_000.0, mode="auto")
    _relax_gates()

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))
        s.add(PaperWatchlistItem(account_id=a.id, ticker="MSFT"))

    events: list[tuple[str, str]] = []

    def earnings_provider(ticker):
        events.append(("earnings", ticker))
        return utcnow_naive() + timedelta(days=30)  # lejos → no bloquea

    def history_provider(ticker):
        events.append(("history", ticker))
        return None  # fail-open en ADV cap / nota R:R

    real_fill = engine._fill_trade

    def spy_fill(session, acct, trade, **kwargs):
        events.append(("fill", trade.ticker))
        return real_fill(session, acct, trade, **kwargs)

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _two_buy_strategy("AAPL", "MSFT"))
    monkeypatch.setattr(engine, "_fill_trade", spy_fill)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0, "MSFT": 200.0},
        history_provider=history_provider,
        earnings_provider=earnings_provider,
    )

    assert result is not None
    assert result.filled == 2

    fill_idxs = [i for i, (kind, _) in enumerate(events) if kind == "fill"]
    earnings_idxs = [i for i, (kind, _) in enumerate(events) if kind == "earnings"]
    assert fill_idxs, "esperaba fills registrados"
    assert earnings_idxs, "esperaba lookups de earnings registrados"

    first_fill = min(fill_idxs)
    # Ningún lookup de earnings después del primer fill (= dentro de la
    # ventana de lock). Esto es exactamente lo que rompía el 2026-07-13.
    assert max(earnings_idxs) < first_fill, f"earnings dentro de la ventana de lock: {events}"

    # El primer history de CADA ticker BUY también precede al primer fill
    # (después el loop pega al memo, no al provider). Nota: history posteriores
    # al fill existen y son legítimos (_estimate_book_sigma post-commit).
    for t in ("AAPL", "MSFT"):
        first_hist = next(i for i, e in enumerate(events) if e == ("history", t))
        assert first_hist < first_fill, f"history({t}) dentro de la ventana de lock: {events}"

    # Y el gate sigue usando el memo: exactamente un lookup de earnings por ticker.
    assert sorted(t for k, t in events if k == "earnings") == ["AAPL", "MSFT"]


def test_prefetch_skipped_when_market_blocked(test_db, monkeypatch):
    """Mercado cerrado → no se prefetchea nada (no gastar red para no operar)."""
    from paper_trading import engine

    a = create_account(name="LockWin2", initial_capital=50_000.0, mode="auto")
    _relax_gates()
    settings.set("paper_enforce_market_hours", True)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    calls: list[str] = []

    def earnings_provider(ticker):
        calls.append(ticker)
        return None

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _two_buy_strategy("AAPL", "MSFT"))
    monkeypatch.setattr(engine, "_is_market_open_safe", lambda: False)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0, "MSFT": 200.0},
        history_provider=lambda _t: None,
        earnings_provider=earnings_provider,
    )

    assert result is not None
    assert result.filled == 0
    assert result.skipped == 2
    assert calls == []
