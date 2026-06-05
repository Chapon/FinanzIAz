"""
Tests para scripts/dashboard_data — funciones de alpha decay (T06).

Cubre:
  _decay_signal:
    - insuficientes meses → "insufficient_data"
    - pendiente claramente negativa → "decaying"
    - pendiente claramente positiva → "improving"
    - pendiente plana / cerca de cero → "stable"
    - usa solo los últimos 4 meses (ignora historial largo)
    - Sharpe None filtrado correctamente
    - slope devuelto correctamente (OLS exacto en caso lineal)

  _monthly_perf:
    - wrapper delega correctamente en monthly_breakdown
    - retorna lista ordenada con las claves esperadas
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

# dashboard_data importa desde scripts.baseline_metrics, así que aseguramos que
# el path del repo esté en sys.path antes de importar.
from scripts.dashboard_data import _decay_signal, _monthly_perf
from scripts.baseline_metrics import AccountSnapshot, Fill


# ── Helpers para construir monthly dicts sintéticos ──────────────────────────

def _month(month_str: str, sharpe: float | None, period_return: float = 0.0) -> dict:
    return {
        "month": month_str,
        "n_trading_days": 20,
        "period_return": period_return,
        "sharpe_annual": sharpe,
        "max_drawdown": 0.01,
        "max_dd_date": None,
        "n_round_trips": 5,
        "win_rate": 0.6,
        "profit_factor": 1.5,
        "expectancy_dollars": 50.0,
    }


# ── _decay_signal ─────────────────────────────────────────────────────────────

class TestDecaySignal:

    def test_insufficient_data_empty(self):
        result = _decay_signal([])
        assert result["status"] == "insufficient_data"
        assert result["slope"] is None
        assert result["n_months"] == 0

    def test_insufficient_data_one_month(self):
        result = _decay_signal([_month("2026-05", 1.5)])
        assert result["status"] == "insufficient_data"
        assert result["n_months"] == 1

    def test_insufficient_data_two_months(self):
        monthly = [_month("2026-04", 1.5), _month("2026-05", 1.2)]
        result = _decay_signal(monthly)
        assert result["status"] == "insufficient_data"
        assert result["n_months"] == 2

    def test_decaying_clear_negative_slope(self):
        # Sharpe cae 0.5 por mes: slope ≈ -0.5 << threshold -0.10
        monthly = [
            _month("2026-03", 2.5),
            _month("2026-04", 2.0),
            _month("2026-05", 1.5),
        ]
        result = _decay_signal(monthly)
        assert result["status"] == "decaying"
        assert result["slope"] is not None
        assert result["slope"] < -0.10

    def test_improving_clear_positive_slope(self):
        # Sharpe sube 0.5 por mes
        monthly = [
            _month("2026-03", 1.0),
            _month("2026-04", 1.5),
            _month("2026-05", 2.0),
        ]
        result = _decay_signal(monthly)
        assert result["status"] == "improving"
        assert result["slope"] > 0.10

    def test_stable_flat(self):
        # Sharpe constante → slope = 0
        monthly = [
            _month("2026-03", 1.5),
            _month("2026-04", 1.5),
            _month("2026-05", 1.5),
        ]
        result = _decay_signal(monthly)
        assert result["status"] == "stable"
        assert result["slope"] == pytest.approx(0.0, abs=1e-9)

    def test_stable_near_zero_slope(self):
        # Pequeña oscilación dentro del threshold
        monthly = [
            _month("2026-03", 1.50),
            _month("2026-04", 1.55),
            _month("2026-05", 1.48),
        ]
        result = _decay_signal(monthly)
        assert result["status"] == "stable"
        assert abs(result["slope"]) < 0.10

    def test_uses_last_4_months_not_older(self):
        # Los primeros 3 meses son crecientes pero los últimos 4 caen fuerte.
        # El resultado debe clasificarse como "decaying".
        monthly = [
            _month("2026-01", 1.0),
            _month("2026-02", 1.5),
            _month("2026-03", 2.0),  # punto máximo
            _month("2026-04", 2.0),
            _month("2026-05", 1.5),
            _month("2026-06", 1.0),
        ]
        result = _decay_signal(monthly)
        # Últimos 4: 2.0, 2.0, 1.5, 1.0  → pendiente negativa
        assert result["status"] == "decaying"
        assert len(result["recent_sharpes"]) == 4
        assert result["recent_sharpes"][0][0] == "2026-03"

    def test_none_sharpe_filtered(self):
        # El mes con sharpe=None no cuenta como punto válido
        monthly = [
            _month("2026-03", None),
            _month("2026-04", 1.5),
            _month("2026-05", None),
            _month("2026-06", 1.2),
        ]
        result = _decay_signal(monthly)
        # Solo 2 puntos válidos → insufficient_data
        assert result["status"] == "insufficient_data"
        assert result["n_months"] == 2

    def test_slope_exact_linear(self):
        # Con 3 puntos perfectamente lineales con pendiente -0.5:
        #   xs = [0, 1, 2], ys = [2.0, 1.5, 1.0]
        # OLS slope = cov(x,y) / var(x) = ( (-1)(0.5) + (0)(-0.5+0.5=0) ... ) → -0.5
        monthly = [
            _month("2026-04", 2.0),
            _month("2026-05", 1.5),
            _month("2026-06", 1.0),
        ]
        result = _decay_signal(monthly)
        assert result["slope"] == pytest.approx(-0.5, abs=1e-6)

    def test_n_months_reflects_valid_count(self):
        monthly = [
            _month("2026-03", 1.0),
            _month("2026-04", 1.2),
            _month("2026-05", 1.4),
            _month("2026-06", None),  # descartado
        ]
        result = _decay_signal(monthly)
        assert result["n_months"] == 3

    def test_recent_sharpes_structure(self):
        monthly = [
            _month("2026-04", 1.0),
            _month("2026-05", 1.5),
            _month("2026-06", 2.0),
        ]
        result = _decay_signal(monthly)
        assert isinstance(result["recent_sharpes"], list)
        for item in result["recent_sharpes"]:
            assert len(item) == 2  # [month_str, value]
            assert isinstance(item[0], str)
            assert isinstance(item[1], float)


# ── _monthly_perf ─────────────────────────────────────────────────────────────

def _make_snapshots(n_days: int, start_equity: float = 50_000.0) -> list[AccountSnapshot]:
    base = datetime(2026, 4, 1, 12, 0, 0)
    snaps = []
    equity = start_equity
    for i in range(n_days):
        snaps.append(AccountSnapshot(
            snapshot_at=base + timedelta(days=i),
            total_equity=equity + i * 10.0,
            cash=5_000.0,
            positions_value=equity + i * 10.0 - 5_000.0,
        ))
    return snaps


def _make_fills(n: int = 4) -> list[Fill]:
    """Synthetic matched BUY+SELL pairs across two months."""
    fills = []
    base_buy = datetime(2026, 4, 5, 10, 0, 0)
    base_sell = datetime(2026, 5, 5, 10, 0, 0)
    for i in range(n):
        fills.append(Fill(
            order_id=i * 2,
            ticker=f"TKR{i}",
            side="BUY",
            shares=10.0,
            price=100.0 + i,
            commission=0.1,
            slippage=0.05,
            filled_at=base_buy + timedelta(days=i),
        ))
        fills.append(Fill(
            order_id=i * 2 + 1,
            ticker=f"TKR{i}",
            side="SELL",
            shares=10.0,
            price=110.0 + i,
            commission=0.1,
            slippage=0.05,
            filled_at=base_sell + timedelta(days=i),
        ))
    return fills


class TestMonthlyPerf:

    def test_returns_list(self):
        snaps = _make_snapshots(60)
        fills = _make_fills(4)
        result = _monthly_perf(snaps, fills)
        assert isinstance(result, list)

    def test_has_expected_keys(self):
        snaps = _make_snapshots(60)
        fills = _make_fills(2)
        result = _monthly_perf(snaps, fills)
        assert len(result) > 0
        row = result[0]
        for key in ("month", "n_trading_days", "period_return", "sharpe_annual",
                    "max_drawdown", "n_round_trips"):
            assert key in row, f"Missing key: {key}"

    def test_ordered_chronologically(self):
        snaps = _make_snapshots(90)
        fills = _make_fills(2)
        result = _monthly_perf(snaps, fills)
        months = [r["month"] for r in result]
        assert months == sorted(months)

    def test_empty_snapshots(self):
        result = _monthly_perf([], [])
        assert result == []
