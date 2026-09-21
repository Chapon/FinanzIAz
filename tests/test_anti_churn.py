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


# Gate 6 (earnings blackout) DECLARADO, no fallando abierto por accidente (tarea 213).
#
# Estos tests inyectan `prices_provider` e `history_provider` pero no éste, y el default
# sale a Yahoo de verdad: `yf.Ticker(...).calendar`, en un thread del pool del scan — por
# eso no aparecía en ningún traceback. Lo destapó la bitácora del cortafuegos de la **209**
# (el exit code no lo veía: el gate tolera el fallo y el test pasaba igual).
#
# Va una fecha **lejana** y no `None` a propósito: `None` deja pasar por el fail-open, o
# sea por la rama de "no sé", y entonces el test no distingue "el gate miró y no bloqueó"
# de "el gate no tenía dato". Con +90 días contra un blackout de ±2, el gate **corre** y
# deja pasar por el motivo que está escrito acá.
class _EarningsLejos:
    """Provider de earnings que deja pasar el Gate 6 **y registra a quien se le pregunto**.

    ``consultado`` es lo que vuelve **load-bearing** a la inyeccion: sin el, sacar el
    ``earnings_provider=`` de un ``run_scan`` deja el test igual de verde -- el default
    sale a Yahoo, el gate tolera el fallo y nadie se entera. Asi fue como el defecto de
    la tarea 213 sobrevivio sin que ninguna corrida lo delatara. Mutacion: sacar el
    ``append`` pone en rojo los cuatro tests de este archivo.

    **La fecha lejana, en cambio, NO esta probada, y conviene decirlo.** La idea era que
    +90 dias contra un blackout de +-2 hace que el gate **corra** y deje pasar por el
    motivo escrito, en vez de por el fail-open de "no se" que da ``None``. Eso es cierto
    del engine, pero **ningun test de aca lo distingue**: con ``None`` el gate tampoco
    bloquea y ``consultado`` se llena igual, asi que la mutacion "devolver ``None``" sale
    **verde**. Y no se puede cerrar sin tocar el engine, que hoy no registra en ningun
    lado "el gate evaluo y dejo pasar". Queda como eleccion de **legibilidad** -- se lee
    que fecha se le dio al gate -- y no como propiedad fijada. Que Gate 6 **si** bloquea
    con una fecha adentro de la ventana lo cubren los tests del blackout (T08), no estos.
    """

    def __init__(self):
        self.consultado: list[str] = []

    def __call__(self, ticker):
        self.consultado.append(ticker)
        return utcnow_naive() + timedelta(days=90)


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

    earnings = _EarningsLejos()
    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
        earnings_provider=earnings,
    )

    assert result is not None
    assert result.filled == 0
    assert result.queued == 0
    assert result.skipped >= 1
    assert any("anti-churn" in w for w in result.warnings)
    assert earnings.consultado == ["KO"], (
        "el Gate 6 no llego a consultar el provider inyectado: si esto falla, el scan "
        "volvio a resolver earnings por el default, que sale a Yahoo (tarea 213)."
    )
    # Tarea 215 — aca el Gate 6 NO corre, y eso tambien vale declararlo: un gate previo
    # (anti-churn / anti-whipsaw) bloqueo y el loop hizo `continue` antes de llegar. El
    # spy de arriba SI se llena, porque lo consulta el **prefetch** de `run_scan`, que
    # corre antes del loop de gates para no dejar red adentro de la ventana de escritura.
    # Los dos juntos dicen algo que ninguno dice solo: se pidio el dato, y el gate que
    # bloqueo fue otro.
    assert result.earnings_gate == {}, (
        "si el Gate 6 evaluo algo, este BUY llego mas lejos de lo que el test cree: "
        f"lo tenia que frenar un gate anterior. {result.earnings_gate}"
    )


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

    earnings = _EarningsLejos()
    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
        earnings_provider=earnings,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("anti-churn" in w for w in result.warnings)
    assert earnings.consultado == ["KO"], (
        "el Gate 6 no llego a consultar el provider inyectado: si esto falla, el scan "
        "volvio a resolver earnings por el default, que sale a Yahoo (tarea 213)."
    )
    # Tarea 215 — y esto es lo que la 213 NO podia escribir. Alla el engine no
    # registraba "el gate evaluo y dejo pasar", asi que cambiar la fecha lejana por
    # `None` no rompia nada y la eleccion quedaba como preferencia de legibilidad. Con
    # el contador, la fecha pasa a estar FIJADA: el gate corrio, tenia el dato, y dejo
    # pasar por eso y no por el fail-open de "no se".
    assert result.earnings_gate.get("evaluado") == 1, (
        "el Gate 6 tiene que haber evaluado con FECHA CONOCIDA; si dice `sin_dato`, el "
        f"provider dejo de devolver la fecha lejana (tarea 215): {result.earnings_gate}"
    )


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

    earnings = _EarningsLejos()
    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
        earnings_provider=earnings,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("anti-churn" in w for w in result.warnings)
    assert earnings.consultado == ["KO"], (
        "el Gate 6 no llego a consultar el provider inyectado: si esto falla, el scan "
        "volvio a resolver earnings por el default, que sale a Yahoo (tarea 213)."
    )
    # Tarea 215 — y esto es lo que la 213 NO podia escribir. Alla el engine no
    # registraba "el gate evaluo y dejo pasar", asi que cambiar la fecha lejana por
    # `None` no rompia nada y la eleccion quedaba como preferencia de legibilidad. Con
    # el contador, la fecha pasa a estar FIJADA: el gate corrio, tenia el dato, y dejo
    # pasar por eso y no por el fail-open de "no se".
    assert result.earnings_gate.get("evaluado") == 1, (
        "el Gate 6 tiene que haber evaluado con FECHA CONOCIDA; si dice `sin_dato`, el "
        f"provider dejo de devolver la fecha lejana (tarea 215): {result.earnings_gate}"
    )


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

    earnings = _EarningsLejos()
    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
        earnings_provider=earnings,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("anti-churn" in w for w in result.warnings)
    assert earnings.consultado == ["KO"], (
        "el Gate 6 no llego a consultar el provider inyectado: si esto falla, el scan "
        "volvio a resolver earnings por el default, que sale a Yahoo (tarea 213)."
    )
    # Tarea 215 — y esto es lo que la 213 NO podia escribir. Alla el engine no
    # registraba "el gate evaluo y dejo pasar", asi que cambiar la fecha lejana por
    # `None` no rompia nada y la eleccion quedaba como preferencia de legibilidad. Con
    # el contador, la fecha pasa a estar FIJADA: el gate corrio, tenia el dato, y dejo
    # pasar por eso y no por el fail-open de "no se".
    assert result.earnings_gate.get("evaluado") == 1, (
        "el Gate 6 tiene que haber evaluado con FECHA CONOCIDA; si dice `sin_dato`, el "
        f"provider dejo de devolver la fecha lejana (tarea 215): {result.earnings_gate}"
    )


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

    earnings = _EarningsLejos()
    result = engine.run_scan(
        a.id,
        prices_provider=lambda _tickers: {"KO": 63.0},
        history_provider=lambda _t: None,
        earnings_provider=earnings,
    )

    assert result is not None
    assert result.queued == 1
    assert not any("anti-churn" in w for w in result.warnings)
    assert earnings.consultado == [], (
        "Gate 6 no toca SELLs con earnings_blackout_block_sells=False — si esto falla, "
        "el blackout empezo a mirar ventas y hay que decidirlo, no descubrirlo."
    )
    assert result.earnings_gate == {}, (
        "y no hay nada que contar: el gate ni siquiera se evaluo para un SELL "
        f"(tarea 215): {result.earnings_gate}"
    )
