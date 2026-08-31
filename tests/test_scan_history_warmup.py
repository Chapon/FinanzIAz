"""Tests for the batched OHLCV warm-up at the top of ``run_scan``.

El scan calienta la cache de históricos en UNA descarga por lotes
(``get_historical_data_batch``) antes de que las llamadas per-ticker de
``history_provider`` corran, para reutilizar un único crumb de Yahoo y reducir
los 401 "Invalid Crumb". El warm-up:
  - corre sólo con el provider por defecto (si se inyecta uno, p.ej. en tests,
    NO debe tocar la red);
  - es best-effort (si la descarga falla, el scan sigue con el fetch per-ticker).
"""

from __future__ import annotations

import pandas as pd

from config.settings_manager import settings
from database.models import session_scope
from paper_trading.account import create_account
from paper_trading.models import PaperWatchlistItem


def _isolate_gates() -> None:
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("earnings_blackout_days", 0)


def _no_trades_strategy(account, watchlist, positions, prices, history_provider):
    return []


def _history(n: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [100.0] * n,
            "High": [100.0] * n,
            "Low": [100.0] * n,
            "Close": [100.0] * n,
            "Volume": [10_000.0] * n,
        },
        index=idx,
    )


def test_warmup_batches_full_universe_with_default_provider(test_db, monkeypatch):
    """Sin history_provider inyectado → run_scan llama get_historical_data_batch
    UNA vez con el set completo de tickers (watchlist ∪ posiciones ∪ SPY).

    SPY se suma SOLO para cachear el benchmark de Métricas (V1); no entra al
    universo de decisiones (precios/gates usan ``tickers`` sin SPY)."""
    import data.yahoo_finance as yfmod
    from paper_trading import engine

    a = create_account(name="WARM", initial_capital=100_000.0, mode="manual")
    _isolate_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))
        s.add(PaperWatchlistItem(account_id=a.id, ticker="MSFT"))

    calls: list[list[str]] = []

    def _spy_batch(tickers, period="1y", interval="1d", **kw):
        calls.append(list(tickers))
        return {t.upper(): None for t in tickers}

    monkeypatch.setattr(yfmod, "get_historical_data_batch", _spy_batch)
    # red per-ticker neutralizada por si algo cae al provider por defecto
    monkeypatch.setattr(yfmod, "get_historical_data", lambda *a, **k: None)
    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _no_trades_strategy)

    engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0, "MSFT": 100.0},
        earnings_provider=lambda _t: None,
        # history_provider OMITIDO a propósito → usa el default → dispara warm-up
    )

    assert len(calls) == 1
    assert calls[0] == ["AAPL", "MSFT", "SPY"]  # ordenado, universo completo + SPY (benchmark V1)


def test_warmup_skipped_when_history_provider_injected(test_db, monkeypatch):
    """Con history_provider inyectado (tests) el warm-up NO debe tocar la red."""
    import data.yahoo_finance as yfmod
    from paper_trading import engine

    a = create_account(name="WARM2", initial_capital=100_000.0, mode="manual")
    _isolate_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    calls: list[list[str]] = []
    monkeypatch.setattr(
        yfmod,
        "get_historical_data_batch",
        lambda tickers, **kw: calls.append(list(tickers)) or {},
    )
    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _no_trades_strategy)

    engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        history_provider=lambda _t: _history(),
        earnings_provider=lambda _t: None,
    )

    assert calls == []  # warm-up no ejecutado


def test_warmup_failure_is_swallowed(test_db, monkeypatch):
    """Si la descarga batch revienta, el scan sigue (best-effort)."""
    import data.yahoo_finance as yfmod
    from paper_trading import engine

    a = create_account(name="WARM3", initial_capital=100_000.0, mode="manual")
    _isolate_gates()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    def _boom(*a, **k):
        raise RuntimeError("crumb storm")

    monkeypatch.setattr(yfmod, "get_historical_data_batch", _boom)
    monkeypatch.setattr(yfmod, "get_historical_data", lambda *a, **k: None)
    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _no_trades_strategy)

    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 100.0},
        earnings_provider=lambda _t: None,
    )

    assert result is not None  # el scan no se cae por el warm-up


# ── fallback per-ticker de SPY (tarea 22, BENCH-STALE, pata a) ────────────────
# SPY entra al warm-up SOLO para el benchmark (V1) y NO a ``tickers``, así que es
# el único símbolo sin re-fetch per-ticker. Si el batch lo saltea (throttle/401)
# su fila queda stale y el benchmark se congela → se le da su propio fallback.
def test_spy_fallback_fetched_when_batch_skips_it(monkeypatch):
    import data.yahoo_finance as yfmod
    from paper_trading import engine

    singles: list[str] = []
    monkeypatch.setattr(
        yfmod,
        "get_historical_data_batch",
        lambda tickers, **kw: {t.upper(): None for t in tickers},  # todo None (throttle)
    )
    monkeypatch.setattr(yfmod, "get_historical_data", lambda ticker, **kw: singles.append(ticker))

    engine._warm_up_history_cache(["AAPL", "MSFT"])
    assert singles == ["SPY"]  # sólo SPY recibe el re-fetch per-ticker


def test_spy_fallback_skipped_when_batch_returns_it(monkeypatch):
    import data.yahoo_finance as yfmod
    from paper_trading import engine

    singles: list[str] = []
    monkeypatch.setattr(
        yfmod,
        "get_historical_data_batch",
        lambda tickers, **kw: {t.upper(): (None if t.upper() != "SPY" else object()) for t in tickers},
    )
    monkeypatch.setattr(yfmod, "get_historical_data", lambda ticker, **kw: singles.append(ticker))

    engine._warm_up_history_cache(["AAPL"])
    assert singles == []  # SPY vino en el batch → un solo request, sin refetch


def test_spy_fallback_fetched_when_batch_raises(monkeypatch):
    import data.yahoo_finance as yfmod
    from paper_trading import engine

    singles: list[str] = []

    def _boom(*a, **k):
        raise RuntimeError("crumb storm")

    monkeypatch.setattr(yfmod, "get_historical_data_batch", _boom)
    monkeypatch.setattr(yfmod, "get_historical_data", lambda ticker, **kw: singles.append(ticker))

    engine._warm_up_history_cache(["AAPL"])
    assert singles == ["SPY"]  # aun con el batch caído, el benchmark recibe fallback
