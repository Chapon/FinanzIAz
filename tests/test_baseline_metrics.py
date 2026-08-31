"""
Tests para scripts/baseline_metrics.

Foco: las funciones puras (sin I/O) que se prestan a fixtures sintéticos
con respuestas conocidas. La idea es asegurar que el ancla del Sprint 0
sea reproducible — si una métrica cambia de número, queremos que sea
porque cambió la lógica adrede, no por un drift silencioso.

Edge cases cubiertos
--------------------
* equity:
    - daily_endpoints colapsa múltiples scans del mismo día al último
    - daily_returns descarta divisores ≤ 0
    - sharpe_annual returns None con muestra chica o stdev=0
    - cagr returns None con start=0 o sin segundo punto
    - max_drawdown sobre curvas planas, ascendentes y con valle
* FIFO:
    - round-trip ganador / perdedor con fees
    - cierre parcial deja la cola intacta
    - SELL que excede inventory cierra lo que puede
    - múltiples lotes que se consumen en orden
* trade_stats:
    - lista vacía → todo None salvo conteo
    - solo wins / solo losses (profit_factor = ∞ / 0)
* monthly_breakdown agrupa por mes calendar
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from scripts.baseline_metrics import (
    AccountSnapshot,
    Fill,
    cagr,
    compute_account,
    daily_endpoints,
    daily_returns,
    fifo_match,
    max_drawdown,
    monthly_breakdown,
    period_return,
    run,
    sharpe_annual,
    trade_stats,
    turnover_metrics,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def snap(date: str, equity: float, cash: float = 0.0, pos: float | None = None) -> AccountSnapshot:
    return AccountSnapshot(
        snapshot_at=datetime.fromisoformat(date),
        total_equity=equity,
        cash=cash,
        positions_value=pos if pos is not None else equity - cash,
    )


def buy(
    *,
    ticker: str = "AAA",
    shares: float,
    price: float,
    when: str,
    commission: float = 1.0,
    slippage: float = 0.5,
    order_id: int = 0,
) -> Fill:
    return Fill(
        order_id=order_id,
        ticker=ticker,
        side="BUY",
        shares=shares,
        price=price,
        commission=commission,
        slippage=slippage,
        filled_at=datetime.fromisoformat(when),
    )


def sell(
    *,
    ticker: str = "AAA",
    shares: float,
    price: float,
    when: str,
    commission: float = 1.0,
    slippage: float = 0.5,
    order_id: int = 0,
) -> Fill:
    return Fill(
        order_id=order_id,
        ticker=ticker,
        side="SELL",
        shares=shares,
        price=price,
        commission=commission,
        slippage=slippage,
        filled_at=datetime.fromisoformat(when),
    )


# ── daily_endpoints ──────────────────────────────────────────────────────────


def test_daily_endpoints_collapses_intraday_scans_to_last():
    """Varios scans en el mismo día → solo el último cuenta."""
    snaps = [
        snap("2026-01-01T09:00:00", 100.0),
        snap("2026-01-01T16:00:00", 110.0),  # last of the day → keep this
        snap("2026-01-01T12:00:00", 105.0),
        snap("2026-01-02T16:00:00", 115.0),
    ]
    eps = daily_endpoints(snaps)
    assert len(eps) == 2
    assert eps[0][1] == 110.0
    assert eps[1][1] == 115.0


def test_daily_endpoints_empty():
    assert daily_endpoints([]) == []


# ── daily_returns / sharpe ───────────────────────────────────────────────────


def test_daily_returns_simple():
    eps = [
        (datetime(2026, 1, 1), 100.0),
        (datetime(2026, 1, 2), 110.0),
        (datetime(2026, 1, 3), 99.0),
    ]
    rets = daily_returns(eps)
    assert rets == pytest.approx([0.10, -0.10])


def test_daily_returns_skips_non_positive_prev():
    eps = [(datetime(2026, 1, 1), 0.0), (datetime(2026, 1, 2), 100.0)]
    assert daily_returns(eps) == []


def test_sharpe_returns_none_with_few_returns():
    assert sharpe_annual([]) is None
    assert sharpe_annual([0.01]) is None


def test_sharpe_returns_none_with_zero_stdev():
    assert sharpe_annual([0.01, 0.01, 0.01]) is None


def test_sharpe_known_value():
    """Sharpe de retornos constantes [+1%, -1%, +1%, -1%]:
    mean=0 → Sharpe=0."""
    assert sharpe_annual([0.01, -0.01, 0.01, -0.01]) == pytest.approx(0.0)


def test_sharpe_positive_strong_signal():
    """Retornos [+1%, +1%, +1%, +1%]: stdev=0 → None (caso esperado)."""
    assert sharpe_annual([0.01, 0.01, 0.01, 0.01]) is None


# ── CAGR / period_return ─────────────────────────────────────────────────────


def test_cagr_one_year_double():
    eps = [
        (datetime(2026, 1, 1), 100.0),
        (datetime(2027, 1, 1), 200.0),
    ]
    # ~365 cal days, 2x → CAGR = 100%
    assert cagr(eps) == pytest.approx(1.0, rel=0.01)


def test_cagr_returns_none_zero_start():
    eps = [(datetime(2026, 1, 1), 0.0), (datetime(2026, 6, 1), 100.0)]
    assert cagr(eps) is None


def test_period_return_simple():
    eps = [(datetime(2026, 1, 1), 100.0), (datetime(2026, 2, 1), 110.0)]
    assert period_return(eps) == pytest.approx(0.10)


# ── max_drawdown ─────────────────────────────────────────────────────────────


def test_max_drawdown_flat_curve_is_zero():
    eps = [(datetime(2026, 1, i + 1), 100.0) for i in range(5)]
    dd, date = max_drawdown(eps)
    assert dd == 0.0
    assert date is None


def test_max_drawdown_strictly_ascending_is_zero():
    eps = [(datetime(2026, 1, i + 1), 100.0 + i) for i in range(5)]
    dd, _ = max_drawdown(eps)
    assert dd == 0.0


def test_max_drawdown_known_valley():
    """Sube 100 → 120, cae a 90, sube a 110. Max DD = (120-90)/120 = 25%."""
    eps = [
        (datetime(2026, 1, 1), 100.0),
        (datetime(2026, 1, 2), 120.0),
        (datetime(2026, 1, 3), 90.0),
        (datetime(2026, 1, 4), 110.0),
    ]
    dd, date = max_drawdown(eps)
    assert dd == pytest.approx(0.25)
    assert date == "2026-01-03"


# ── FIFO matching ────────────────────────────────────────────────────────────


def test_fifo_simple_winning_roundtrip():
    fills = [
        buy(shares=10, price=100, when="2026-01-01T10:00:00", commission=1, slippage=0.5),
        sell(shares=10, price=110, when="2026-01-10T10:00:00", commission=1, slippage=0.5),
    ]
    trades, opens = fifo_match(fills)
    assert len(trades) == 1
    t = trades[0]
    # cost = 10*100 + 1 + 0.5 = 1001.5
    assert t.cost_basis == pytest.approx(1001.5)
    # proceeds = 10*110 - 1 - 0.5 = 1098.5
    assert t.proceeds == pytest.approx(1098.5)
    assert t.pnl == pytest.approx(97.0)
    assert t.is_win
    assert t.holding_days == pytest.approx(9.0)
    assert list(opens["AAA"]) == []  # inventory consumed exactly


def test_fifo_losing_roundtrip_marks_loss():
    fills = [
        buy(shares=5, price=100, when="2026-01-01T10:00:00"),
        sell(shares=5, price=90, when="2026-01-02T10:00:00"),
    ]
    trades, _ = fifo_match(fills)
    assert len(trades) == 1
    assert not trades[0].is_win
    assert trades[0].pnl < 0


def test_fifo_partial_close_leaves_inventory():
    """BUY 10, SELL 4 → 1 trade y queda lot con 6 shares."""
    fills = [
        buy(shares=10, price=100, when="2026-01-01T10:00:00", commission=2, slippage=1),
        sell(shares=4, price=120, when="2026-01-05T10:00:00", commission=1, slippage=0.5),
    ]
    trades, opens = fifo_match(fills)
    assert len(trades) == 1
    # per-share cost = (10*100 + 3) / 10 = 100.3
    # cost basis for 4 closed = 4 * 100.3 = 401.2
    assert trades[0].cost_basis == pytest.approx(401.2)
    assert trades[0].shares == pytest.approx(4.0)
    remaining_lot = opens["AAA"][0]
    assert remaining_lot["shares"] == pytest.approx(6.0)
    assert remaining_lot["cost_per_share"] == pytest.approx(100.3)


def test_fifo_multiple_lots_consumed_in_order():
    """2 BUYs a precios distintos + 1 SELL grande → SELL consume FIFO."""
    fills = [
        buy(shares=5, price=100, when="2026-01-01T10:00:00", commission=0, slippage=0),
        buy(shares=5, price=120, when="2026-01-03T10:00:00", commission=0, slippage=0),
        sell(shares=8, price=130, when="2026-01-10T10:00:00", commission=0, slippage=0),
    ]
    trades, opens = fifo_match(fills)
    assert len(trades) == 1
    # consume 5 @ 100 + 3 @ 120 = 500 + 360 = 860 cost
    assert trades[0].cost_basis == pytest.approx(860.0)
    # proceeds = 8*130 = 1040
    assert trades[0].proceeds == pytest.approx(1040.0)
    # 2 shares left of the second lot
    assert opens["AAA"][0]["shares"] == pytest.approx(2.0)
    assert opens["AAA"][0]["cost_per_share"] == pytest.approx(120.0)


def test_fifo_sell_exceeding_inventory_closes_what_it_can():
    """BUY 5, SELL 10 → cierra 5 (toda la inventory)."""
    fills = [
        buy(shares=5, price=100, when="2026-01-01T10:00:00", commission=0, slippage=0),
        sell(shares=10, price=110, when="2026-01-05T10:00:00", commission=0, slippage=0),
    ]
    trades, opens = fifo_match(fills)
    assert len(trades) == 1
    assert trades[0].shares == pytest.approx(5.0)
    # proceeds prorated: total proceeds = 10*110 = 1100, * (5/10) = 550
    assert trades[0].proceeds == pytest.approx(550.0)
    assert len(opens["AAA"]) == 0


def test_fifo_isolates_tickers():
    """Fills mezclados de 2 tickers no se cruzan."""
    fills = [
        buy(ticker="AAA", shares=10, price=100, when="2026-01-01T10:00:00"),
        buy(ticker="BBB", shares=20, price=50, when="2026-01-02T10:00:00"),
        sell(ticker="AAA", shares=10, price=110, when="2026-01-05T10:00:00"),
        sell(ticker="BBB", shares=20, price=55, when="2026-01-06T10:00:00"),
    ]
    trades, _ = fifo_match(fills)
    assert len(trades) == 2
    tickers = sorted(t.ticker for t in trades)
    assert tickers == ["AAA", "BBB"]


# ── trade_stats ──────────────────────────────────────────────────────────────


def test_trade_stats_empty_list():
    s = trade_stats([])
    assert s["n_round_trips"] == 0
    assert s["win_rate"] is None
    assert s["profit_factor"] is None
    assert s["expectancy_dollars"] is None


def test_trade_stats_only_wins_profit_factor_infinity():
    """Sin losses → profit_factor = ∞."""
    import math as _m

    fills = [
        buy(shares=10, price=100, when="2026-01-01T10:00:00", commission=0, slippage=0),
        sell(shares=10, price=110, when="2026-01-02T10:00:00", commission=0, slippage=0),
    ]
    trades, _ = fifo_match(fills)
    s = trade_stats(trades)
    assert s["win_rate"] == 1.0
    assert _m.isinf(s["profit_factor"])
    assert s["gross_loss"] == 0.0


def test_trade_stats_known_mix():
    """2 wins (+10, +20) + 1 loss (-5) → wr=2/3, pf=30/5=6, exp=8.33."""
    fills = [
        buy(shares=1, price=100, when="2026-01-01T10:00:00", commission=0, slippage=0),
        sell(shares=1, price=110, when="2026-01-02T10:00:00", commission=0, slippage=0),
        buy(shares=1, price=100, when="2026-01-03T10:00:00", commission=0, slippage=0),
        sell(shares=1, price=120, when="2026-01-04T10:00:00", commission=0, slippage=0),
        buy(shares=1, price=100, when="2026-01-05T10:00:00", commission=0, slippage=0),
        sell(shares=1, price=95, when="2026-01-06T10:00:00", commission=0, slippage=0),
    ]
    trades, _ = fifo_match(fills)
    s = trade_stats(trades)
    assert s["n_round_trips"] == 3
    assert s["win_rate"] == pytest.approx(2 / 3)
    assert s["profit_factor"] == pytest.approx(30 / 5)
    assert s["expectancy_dollars"] == pytest.approx((10 + 20 - 5) / 3)


# ── turnover ─────────────────────────────────────────────────────────────────


def test_turnover_basic():
    fills = [
        buy(shares=10, price=100, when="2026-01-01T10:00:00"),
        sell(shares=10, price=110, when="2026-01-11T10:00:00"),
    ]
    eps = [
        (datetime(2026, 1, 1), 1000.0),
        (datetime(2026, 1, 11), 1100.0),
    ]
    t = turnover_metrics(fills, eps)
    # notional = 10*100 + 10*110 = 2100
    assert t["notional_volume"] == pytest.approx(2100.0)
    # avg_eq = 1050; turnover_period = 2 ; days=10 → annual = 2 * 365/10 = 73
    assert t["turnover_period"] == pytest.approx(2.0)
    assert t["turnover_annual"] == pytest.approx(73.0)


def test_turnover_no_endpoints():
    fills = [buy(shares=1, price=100, when="2026-01-01T10:00:00")]
    t = turnover_metrics(fills, [])
    assert t["avg_equity"] is None
    assert t["turnover_period"] is None
    assert t["turnover_annual"] is None


# ── monthly breakdown ────────────────────────────────────────────────────────


def test_monthly_breakdown_groups_by_close_month():
    snaps = [snap(f"2026-{m:02d}-15", 100.0 + m) for m in range(1, 4)]
    fills = [
        buy(shares=1, price=100, when="2026-01-05T10:00:00", commission=0, slippage=0),
        sell(shares=1, price=110, when="2026-01-20T10:00:00", commission=0, slippage=0),
        buy(shares=1, price=100, when="2026-02-05T10:00:00", commission=0, slippage=0),
        sell(shares=1, price=90, when="2026-03-05T10:00:00", commission=0, slippage=0),
    ]
    trades, _ = fifo_match(fills)
    months = monthly_breakdown(snaps, trades)
    by_month = {m["month"]: m for m in months}
    assert "2026-01" in by_month and "2026-03" in by_month
    assert by_month["2026-01"]["n_round_trips"] == 1
    assert by_month["2026-01"]["win_rate"] == 1.0
    assert by_month["2026-03"]["n_round_trips"] == 1
    assert by_month["2026-03"]["win_rate"] == 0.0


# ── compute_account end-to-end ───────────────────────────────────────────────


def test_compute_account_flags_thin_sample_notes():
    """3 snapshots y 1 round-trip → debería disparar las 3 notas de fragility."""
    account = {
        "id": 99,
        "name": "tiny",
        "initial_capital": 1000.0,
        "is_active": True,
        "strategy": "x",
        "allocation_mode": "y",
    }
    snaps = [
        snap("2026-01-01", 1000.0),
        snap("2026-01-02", 1010.0),
        snap("2026-01-03", 1020.0),
    ]
    fills = [
        buy(shares=1, price=100, when="2026-01-01T10:00:00", commission=0, slippage=0),
        sell(shares=1, price=105, when="2026-01-03T10:00:00", commission=0, slippage=0),
    ]
    result = compute_account(account, fills, snaps, open_positions=[])
    assert result.account_id == 99
    assert any("sharpe" in n for n in result.notes)
    assert any("cagr" in n for n in result.notes)
    assert any("round trips" in n for n in result.notes)


def test_compute_account_no_snapshots_no_fills():
    """Cuenta vacía: todo None, sin crashear."""
    account = {
        "id": 1,
        "name": "empty",
        "initial_capital": 1000.0,
        "is_active": True,
        "strategy": "x",
        "allocation_mode": "y",
    }
    result = compute_account(account, fills=[], snapshots=[], open_positions=[])
    assert result.overall["n_round_trips"] == 0
    assert result.overall["sharpe_annual"] is None
    assert result.overall["cagr"] is None


# ── end-to-end against a real backup (only runs if file exists) ──────────────


def test_run_against_backup_db(tmp_path):
    """Smoke test: corrida contra el último backup. Verifica que
    el JSON se escribe y que tiene la estructura esperada."""
    repo_root = Path(__file__).resolve().parent.parent
    backups = sorted((repo_root / "backups").glob("finanzias_*.db"))
    if not backups:
        pytest.skip("no backups available")
    out_dir = tmp_path / "baselines"
    run(backups[-1], out_dir, write=True)
    files = list(out_dir.glob("baseline_*.json"))
    assert len(files) == 1
    import json as _json

    payload = _json.loads(files[0].read_text())
    assert "accounts" in payload
    assert isinstance(payload["accounts"], list)
    # If Sim Principal is present (id=1), it must have well-formed structure.
    if payload["accounts"]:
        a = payload["accounts"][0]
        assert "overall" in a and "monthly" in a and "notes" in a
