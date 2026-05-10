"""
Tests for the configurable commission + slippage models.
"""
from __future__ import annotations

import pytest

from paper_trading.costs import (
    FlatCommission, PercentCommission, PerShareCommission, TieredCommission,
    ZeroSlippage, PercentSlippage, TickSlippage,
    commission_from_config, slippage_from_config,
)


# ── Commission models ────────────────────────────────────────────────────────

def test_flat_commission():
    c = FlatCommission(fee=5.0)
    assert c.cost(side="BUY", shares=100, price=50) == 5.0
    assert c.cost(side="SELL", shares=1, price=1) == 5.0


def test_percent_commission_with_min_max():
    c = PercentCommission(rate=0.001, min_fee=1.0, max_fee=20.0)
    # Below min — clamped up
    assert c.cost(side="BUY", shares=10, price=50) == 1.0   # raw=0.50, min=1
    # Above min, below max
    assert c.cost(side="BUY", shares=100, price=50) == pytest.approx(5.0)
    # Above max — clamped down
    assert c.cost(side="BUY", shares=100_000, price=50) == 20.0


def test_per_share_commission_ibkr_style():
    c = PerShareCommission(per_share=0.005, min_fee=1.0, max_fee_pct=0.01)
    # Tiny trade — minimum fee applies
    assert c.cost(side="BUY", shares=1, price=50) == 1.0
    # Mid trade: 200 shares * $0.005 = $1.00, but min_fee=$1 too → still $1
    assert c.cost(side="BUY", shares=200, price=50) == 1.0
    # Normal large trade: raw ($50) is well below the 1%-of-notional cap ($5,000)
    cost = c.cost(side="BUY", shares=10_000, price=50)
    assert cost == pytest.approx(10_000 * 0.005)  # = 50.0
    # Penny-stock: raw=$1,000 exceeds 1% cap on $50,000 notional → capped at $500
    cost_capped = c.cost(side="BUY", shares=200_000, price=0.25)
    assert cost_capped == pytest.approx(200_000 * 0.25 * 0.01)  # = 500


def test_tiered_commission_bands():
    c = TieredCommission(bands=[(1_000, 1.0), (10_000, 5.0), (float("inf"), 10.0)])
    assert c.cost(side="BUY", shares=10, price=50) == 1.0       # $500 notional → band 1
    assert c.cost(side="BUY", shares=100, price=50) == 5.0      # $5,000 → band 2
    assert c.cost(side="BUY", shares=1_000, price=50) == 10.0   # $50,000 → band 3


# ── Slippage models ──────────────────────────────────────────────────────────

def test_zero_slippage():
    s = ZeroSlippage()
    assert s.adjust_price(side="BUY", price=100) == 100.0
    assert s.adjust_price(side="SELL", price=100) == 100.0


def test_percent_slippage_directionality():
    s = PercentSlippage(rate=0.001)
    # BUY pays slightly more than the quote (adverse)
    assert s.adjust_price(side="BUY", price=100) == pytest.approx(100.10)
    # SELL receives slightly less
    assert s.adjust_price(side="SELL", price=100) == pytest.approx(99.90)


def test_tick_slippage():
    s = TickSlippage(ticks=2, tick_size=0.01)
    assert s.adjust_price(side="BUY", price=100.00) == pytest.approx(100.02)
    assert s.adjust_price(side="SELL", price=100.00) == pytest.approx(99.98)


# ── Config round-trip ────────────────────────────────────────────────────────

def test_commission_from_config_falls_back_on_unknown_type():
    c = commission_from_config({"type": "BogusModel", "rate": 0.5})
    assert isinstance(c, PercentCommission)


def test_commission_from_config_round_trip():
    src = PercentCommission(rate=0.0015, min_fee=2.0, max_fee=50.0)
    cfg = src.to_dict()
    rebuilt = commission_from_config(cfg)
    assert isinstance(rebuilt, PercentCommission)
    assert rebuilt.rate == 0.0015 and rebuilt.min_fee == 2.0


def test_slippage_from_config_round_trip():
    src = TickSlippage(ticks=3, tick_size=0.05)
    rebuilt = slippage_from_config(src.to_dict())
    assert isinstance(rebuilt, TickSlippage)
    assert rebuilt.ticks == 3
