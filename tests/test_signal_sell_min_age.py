"""
Tests para paper_trading.gates.signal_sell_min_age_block — T6.4 hysteresis.

Contrato (validado en T6.1, docs/exit_replay_t61_2026-06-10.md): SELLs de
señal con score ≥ bypass esperan ``min_age_bdays`` días hábiles; score bajo
(convicción alta de venta) ejecuta directo; exits de riesgo nunca se tocan.

Fechas reales usadas para el conteo de días hábiles:
    jue 2026-06-04 → lun 2026-06-08 = 2 días hábiles (jue, vie)
    jue 2026-06-04 → mar 2026-06-09 = 3 días hábiles (jue, vie, lun)
"""

from __future__ import annotations

from datetime import datetime

from paper_trading.gates import signal_sell_min_age_block

THU = datetime(2026, 6, 4, 15, 30)
FRI = datetime(2026, 6, 5, 15, 30)
MON = datetime(2026, 6, 8, 15, 30)
TUE = datetime(2026, 6, 9, 15, 30)

BASE = dict(
    reason="analyze SELL (0.35)",
    signal_score=0.35,
    opened_at=THU,
    min_age_bdays=3,
    bypass_score=0.25,
)


def _block(**overrides):
    kw = {**BASE, **overrides}
    return signal_sell_min_age_block(**kw)


class TestBlocking:
    def test_young_grey_zone_sell_blocked(self):
        msg = _block(scan_at=MON)  # 2 días hábiles < 3
        assert msg is not None
        assert "T6.4" in msg and "2 días hábiles" in msg

    def test_old_enough_passes(self):
        assert _block(scan_at=TUE) is None  # 3 días hábiles = min

    def test_same_day_blocked(self):
        msg = _block(scan_at=THU)  # 0 días hábiles
        assert msg is not None and "0 días hábiles" in msg

    def test_weekend_does_not_count(self):
        # vie → lun: 1 día hábil (el viernes); el finde no suma
        msg = _block(opened_at=FRI, scan_at=MON)
        assert msg is not None and "1 días hábiles" in msg


class TestBypasses:
    def test_gate_off(self):
        assert _block(scan_at=MON, min_age_bdays=0) is None

    def test_low_score_executes_directly(self):
        # convicción alta de venta (score < bypass) no espera
        assert _block(scan_at=MON, signal_score=0.20, reason="analyze SELL (0.20)") is None

    def test_score_exactly_at_bypass_waits(self):
        assert _block(scan_at=MON, signal_score=0.25) is not None

    def test_bypass_zero_means_everyone_waits(self):
        assert _block(scan_at=MON, signal_score=0.01, bypass_score=0.0) is not None

    def test_none_score_passes(self):
        # rebalanceos / housekeeping van sin score → no aplica
        assert _block(scan_at=MON, signal_score=None) is None

    def test_atr_reason_passes(self):
        assert _block(scan_at=MON, reason="atr_stop @ 90.00 ≤ 92.00", signal_score=1.0) is None

    def test_atr_trail_reason_passes(self):
        assert _block(scan_at=MON, reason="atr_trail @ 95.0 ≤ 96.0", signal_score=1.0) is None

    def test_vol_trim_reason_passes(self):
        assert _block(scan_at=MON, reason="vol_trim σ 0.32 > target 0.25", signal_score=1.0) is None

    def test_no_position_opened_at_passes(self):
        assert _block(scan_at=MON, opened_at=None) is None


class TestMessage:
    def test_message_carries_context(self):
        msg = _block(scan_at=MON, signal_score=0.42, reason="analyze SELL (0.42)")
        assert "0.42" in msg and "min 3" in msg and "bypass 0.25" in msg


# ── Integration: run_scan + Gate 2b ──────────────────────────────────────────


def _engine_setup(test_db, monkeypatch, *, score: float, opened_days_ago: int):
    """Cuenta + posición de edad controlada + estrategia que emite un SELL
    de señal con ``score``. Devuelve el resultado del scan."""
    from datetime import timedelta

    from config.settings_manager import settings
    from database.models import session_scope, utcnow_naive
    from paper_trading import engine
    from paper_trading.account import create_account
    from paper_trading.models import PaperPosition, PaperWatchlistItem
    from paper_trading.strategies import TargetTrade

    settings.set("atr_stops_enabled", False)
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_min_holding_minutes", 0)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("earnings_blackout_days", 0)
    settings.set("paper_signal_sell_min_age_bdays", 3)
    settings.set("paper_signal_sell_bypass_score", 0.25)

    a = create_account(name="T64", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker="AAPL",
                shares=10.0,
                avg_cost=100.0,
                opened_at=utcnow_naive() - timedelta(days=opened_days_ago),
                high_water_mark=100.0,
            )
        )
        s.add(PaperWatchlistItem(account_id=a.id, ticker="AAPL"))

    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker="AAPL",
                side="SELL",
                target_shares=10.0,
                target_dollars=None,
                reason=f"analyze SELL ({score:.2f})",
                source="analyze_single",
                signal_score=score,
            )
        ]

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: strat)
    return engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 105.0},
        history_provider=lambda _t: None,
    )


def test_run_scan_blocks_young_grey_zone_sell(test_db, monkeypatch):
    result = _engine_setup(test_db, monkeypatch, score=0.40, opened_days_ago=0)
    assert result is not None
    assert result.filled == 0 and result.skipped >= 1
    assert any("T6.4" in w for w in result.warnings)


def test_run_scan_allows_low_score_sell_immediately(test_db, monkeypatch):
    result = _engine_setup(test_db, monkeypatch, score=0.20, opened_days_ago=0)
    assert result is not None
    assert result.filled == 1
    assert not any("T6.4" in w for w in result.warnings)


def test_run_scan_allows_aged_grey_zone_sell(test_db, monkeypatch):
    # 7 días calendario ≥ 3 días hábiles siempre (peor caso: 5 hábiles)
    result = _engine_setup(test_db, monkeypatch, score=0.40, opened_days_ago=7)
    assert result is not None
    assert result.filled == 1
    assert not any("T6.4" in w for w in result.warnings)
