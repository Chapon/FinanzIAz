"""
Tests de la decisión pura del screen de universo (E1b).

``screen_candidate`` excluye SOLO ante evidencia positiva de iliquidez o
fragilidad; cualquier dato ausente conserva el nombre (fail open — la mitad del
kill-criteria: "sin sacar nombres buenos"). Cubre las dos patas, el orden
(liquidez primero), y que ``UniverseThresholds.from_settings`` lea los flags.
"""

from __future__ import annotations

from config.settings_manager import settings
from data.edgar_fundamentals import FundamentalFacts
from paper_trading.universe import (
    REASON_ADV,
    REASON_FRAGILE,
    UniverseThresholds,
    screen_candidate,
    screen_enabled,
)


def _facts(net_income=(), revenue_latest=None, ticker="T"):
    ni = tuple((f"{2023 - i}-12-31", v) for i, v in enumerate(net_income))
    rev = () if revenue_latest is None else (("2023-12-31", revenue_latest),)
    return FundamentalFacts(ticker=ticker, net_income_annual=ni, revenue_annual=rev)


def _thr(**kw) -> UniverseThresholds:
    base = dict(
        min_adv_dollars=0.0, fundamentals_enabled=True, min_negative_years=2, revenue_floor=10_000_000.0
    )
    base.update(kw)
    return UniverseThresholds(**base)


# ── Liquidity leg ─────────────────────────────────────────────────────────────


def test_adv_floor_excludes_illiquid():
    v = screen_candidate(
        "ILLQ", adv_dollars=1_000_000, facts=None, thresholds=_thr(min_adv_dollars=5_000_000)
    )
    assert v.excluded and v.reason == REASON_ADV


def test_adv_floor_keeps_liquid():
    v = screen_candidate(
        "LIQ", adv_dollars=50_000_000, facts=None, thresholds=_thr(min_adv_dollars=5_000_000)
    )
    assert v.included


def test_adv_missing_fails_open():
    # ADV desconocido no alcanza para excluir; sin facts tampoco → incluido.
    v = screen_candidate("NOADV", adv_dollars=None, facts=None, thresholds=_thr(min_adv_dollars=5_000_000))
    assert v.included


def test_adv_floor_disabled_when_zero():
    v = screen_candidate("ANY", adv_dollars=1.0, facts=None, thresholds=_thr(min_adv_dollars=0.0))
    assert v.included


# ── Fundamentals leg ──────────────────────────────────────────────────────────


def test_fragile_pre_revenue_biotech_excluded():
    facts = _facts(net_income=(-50_000_000, -40_000_000), revenue_latest=2_000_000)
    v = screen_candidate("MLTX", adv_dollars=None, facts=facts, thresholds=_thr())
    assert v.excluded and v.reason == REASON_FRAGILE


def test_profitable_name_kept():
    facts = _facts(net_income=(100_000_000, 90_000_000), revenue_latest=5_000_000)
    v = screen_candidate("AAPL", adv_dollars=None, facts=facts, thresholds=_thr())
    assert v.included


def test_unprofitable_but_revenue_generating_kept():
    # Pérdidas sostenidas pero revenue real (arriba del piso) → NO es pre-revenue.
    facts = _facts(net_income=(-50_000_000, -40_000_000), revenue_latest=500_000_000)
    v = screen_candidate("GROWTH", adv_dollars=None, facts=facts, thresholds=_thr())
    assert v.included


def test_insufficient_negative_years_fails_open():
    facts = _facts(net_income=(-50_000_000,), revenue_latest=2_000_000)  # solo 1 año
    v = screen_candidate("YOUNG", adv_dollars=None, facts=facts, thresholds=_thr(min_negative_years=2))
    assert v.included


def test_one_positive_year_in_window_kept():
    facts = _facts(net_income=(-50_000_000, 30_000_000), revenue_latest=2_000_000)
    v = screen_candidate("MIXED", adv_dollars=None, facts=facts, thresholds=_thr())
    assert v.included


def test_missing_revenue_with_sustained_losses_excluded():
    # Un biotech clínico pre-revenue NO reporta concepto de revenue en EDGAR
    # (revenue_latest=None). Con pérdidas sostenidas, la ausencia de revenue ES
    # la señal → excluido (validado con MLTX real 2026-07-02).
    facts = _facts(net_income=(-50_000_000, -40_000_000), revenue_latest=None)
    v = screen_candidate("NOREV", adv_dollars=None, facts=facts, thresholds=_thr())
    assert v.excluded and v.reason == REASON_FRAGILE


def test_missing_revenue_without_sustained_losses_kept():
    # Sin la evidencia positiva (pérdidas sostenidas), revenue ausente NO excluye.
    facts = _facts(net_income=(10_000_000, -40_000_000), revenue_latest=None)
    v = screen_candidate("OK", adv_dollars=None, facts=facts, thresholds=_thr())
    assert v.included


def test_fundamentals_leg_disabled():
    facts = _facts(net_income=(-50_000_000, -40_000_000), revenue_latest=2_000_000)
    v = screen_candidate("MLTX", adv_dollars=None, facts=facts, thresholds=_thr(fundamentals_enabled=False))
    assert v.included


def test_no_facts_fails_open():
    v = screen_candidate("UNKNOWN", adv_dollars=None, facts=None, thresholds=_thr())
    assert v.included


# ── Ordering: liquidity wins ──────────────────────────────────────────────────


def test_liquidity_reason_wins_over_fundamentals():
    facts = _facts(net_income=(-50_000_000, -40_000_000), revenue_latest=2_000_000)
    v = screen_candidate("BOTH", adv_dollars=1_000, facts=facts, thresholds=_thr(min_adv_dollars=5_000_000))
    assert v.excluded and v.reason == REASON_ADV


# ── Settings wiring ───────────────────────────────────────────────────────────


def test_from_settings_reads_flags():
    settings.set("paper_universe_min_adv_dollars", 7_500_000.0)
    settings.set("paper_universe_fundamentals_enabled", False)
    settings.set("paper_universe_min_negative_years", 3)
    settings.set("paper_universe_revenue_floor_dollars", 25_000_000.0)
    t = UniverseThresholds.from_settings()
    assert t.min_adv_dollars == 7_500_000.0
    assert t.fundamentals_enabled is False
    assert t.min_negative_years == 3
    assert t.revenue_floor == 25_000_000.0


def test_screen_enabled_defaults_off_and_reads_master():
    assert screen_enabled() is False
    settings.set("paper_universe_screen_enabled", True)
    assert screen_enabled() is True
