"""
Tests for the configurable commission + slippage models.
"""

from __future__ import annotations

import pytest

from paper_trading.costs import (
    FINRA_TAF_MAX,
    FINRA_TAF_PER_SHARE,
    SEC_FEE_RATE,
    FlatCommission,
    IBKRProCommission,
    PercentCommission,
    PercentSlippage,
    PerShareCommission,
    TickSlippage,
    TieredCommission,
    ZeroSlippage,
    commission_from_config,
    make_ibkr_pro_fixed,
    make_ibkr_pro_tiered,
    slippage_from_config,
)

# ── Commission models ────────────────────────────────────────────────────────


def test_flat_commission():
    c = FlatCommission(fee=5.0)
    assert c.cost(side="BUY", shares=100, price=50) == 5.0
    assert c.cost(side="SELL", shares=1, price=1) == 5.0


def test_percent_commission_with_min_max():
    c = PercentCommission(rate=0.001, min_fee=1.0, max_fee=20.0)
    # Below min — clamped up
    assert c.cost(side="BUY", shares=10, price=50) == 1.0  # raw=0.50, min=1
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
    assert c.cost(side="BUY", shares=10, price=50) == 1.0  # $500 notional → band 1
    assert c.cost(side="BUY", shares=100, price=50) == 5.0  # $5,000 → band 2
    assert c.cost(side="BUY", shares=1_000, price=50) == 10.0  # $50,000 → band 3


# ── IBKR Pro models ─────────────────────────────────────────────────────────


def test_ibkr_tiered_small_buy_hits_minimum():
    """50 shares × $0.0035 = $0.175 → bumped up to $0.35 minimum."""
    c = make_ibkr_pro_tiered()
    cost = c.cost(side="BUY", shares=50, price=100.0)
    # BUY: no SEC, no FINRA TAF. CAT and exchange fees apply.
    expected = 0.35 + 50 * 0.003 + 50 * 0.000035
    assert cost == pytest.approx(expected, rel=1e-6)


def test_ibkr_tiered_large_buy_uses_per_share_not_min():
    """1000 shares × $0.0035 = $3.50, well above $0.35 floor."""
    c = make_ibkr_pro_tiered()
    cost = c.cost(side="BUY", shares=1_000, price=100.0)
    expected = 3.50 + 1_000 * 0.003 + 1_000 * 0.000035
    assert cost == pytest.approx(expected, rel=1e-6)


def test_ibkr_tiered_penny_stock_caps_at_1_percent():
    """200k shares at $0.25 → raw IBKR = $700, but 1% cap = $500."""
    c = make_ibkr_pro_tiered()
    notional = 200_000 * 0.25  # $50,000
    cost = c.cost(side="BUY", shares=200_000, price=0.25)
    # IBKR is capped at 1% of notional. Exchange + CAT still apply on top.
    ibkr_cap = notional * 0.01
    expected = ibkr_cap + 200_000 * 0.003 + 200_000 * 0.000035
    assert cost == pytest.approx(expected, rel=1e-6)


def test_ibkr_tiered_sell_adds_sec_and_finra_taf():
    """SELLs add SEC §31 fee + FINRA TAF on top of buy-side costs."""
    c = make_ibkr_pro_tiered()
    notional = 1_000 * 100.0
    cost = c.cost(side="SELL", shares=1_000, price=100.0)
    ibkr = 1_000 * 0.0035
    exchange = 1_000 * 0.003
    cat = 1_000 * 0.000035
    sec = notional * SEC_FEE_RATE
    finra = min(1_000 * FINRA_TAF_PER_SHARE, FINRA_TAF_MAX)
    assert cost == pytest.approx(ibkr + exchange + cat + sec + finra, rel=1e-6)


def test_ibkr_tiered_finra_taf_caps_at_max_per_trade():
    """200k shares sold → FINRA TAF would be $33.20 raw but caps at $8.30."""
    c = make_ibkr_pro_tiered()
    cost = c.cost(side="SELL", shares=200_000, price=10.0)
    # We just need the FINRA component to honour the cap; assert the totals
    # break down by re-computing.
    bd = c.breakdown(side="SELL", shares=200_000, price=10.0)
    assert bd["finra_taf"] == pytest.approx(FINRA_TAF_MAX)
    # And the total equals the sum of components.
    assert cost == pytest.approx(
        bd["ibkr"] + bd["exchange"] + bd["cat"] + bd["sec"] + bd["finra_taf"], rel=1e-6
    )


def test_ibkr_fixed_no_exchange_fee():
    """Fixed bundles exchange/clearing into per_share — no separate venue fee."""
    c = make_ibkr_pro_fixed()
    cost = c.cost(side="BUY", shares=1_000, price=100.0)
    # 1000 × $0.005 = $5.00 (well above $1 min, well under 1% cap)
    # No exchange fee. CAT still applies.
    expected = 5.0 + 1_000 * 0.000035
    assert cost == pytest.approx(expected, rel=1e-6)


def test_ibkr_fixed_tiny_order_hits_dollar_minimum():
    """5 shares × $0.005 = $0.025 → clamped up to $1.00."""
    c = make_ibkr_pro_fixed()
    cost = c.cost(side="BUY", shares=5, price=100.0)
    expected = 1.00 + 5 * 0.000035  # min + CAT
    assert cost == pytest.approx(expected, rel=1e-6)


def test_ibkr_pro_breakdown_components_sum_to_total():
    """The breakdown helper must be internally consistent with cost()."""
    c = IBKRProCommission(per_share=0.0035, min_fee=0.35, exchange_fee_per_share=0.003)
    bd = c.breakdown(side="SELL", shares=500, price=50.0)
    component_sum = bd["ibkr"] + bd["exchange"] + bd["cat"] + bd["sec"] + bd["finra_taf"]
    assert bd["total"] == pytest.approx(component_sum, rel=1e-9)
    assert c.cost(side="SELL", shares=500, price=50.0) == pytest.approx(bd["total"])


def test_ibkr_pro_regulatory_can_be_disabled():
    """When include_regulatory=False, only IBKR + exchange apply."""
    c = IBKRProCommission(
        per_share=0.0035,
        min_fee=0.35,
        exchange_fee_per_share=0.003,
        include_regulatory=False,
    )
    cost = c.cost(side="SELL", shares=1_000, price=100.0)
    expected = 1_000 * 0.0035 + 1_000 * 0.003
    assert cost == pytest.approx(expected, rel=1e-6)


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
