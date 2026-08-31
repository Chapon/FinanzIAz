"""
Tests offline del harness scripts/run_risk_exit_autofill_replay.py (tarea ① N3/A2).

Sintético/offline: barras a mano, sin DB ni red. Cubre la lógica pura del
contrafactual "pending expira" — clasificación de risk-exits y el ride al cap
con ATR neutralizado (el stop nunca dispara en la sim → mide la cola de DD).
"""

from __future__ import annotations

from analysis.exit_replay import SellEvent, replay_event
from scripts.run_risk_exit_autofill_replay import _NO_ATR, is_risk_exit


def _d(i: int) -> str:
    return f"2026-03-{i:02d}" if i <= 31 else f"2026-04-{i - 31:02d}"


def _bars(closes: list[float], tr: float = 2.0) -> list:
    return [(_d(i + 1), c, c + tr / 2, c - tr / 2, c) for i, c in enumerate(closes)]


def _risk_event(**kw) -> SellEvent:
    defaults = dict(
        order_id=1,
        ticker="AAA",
        sell_date=_d(10),
        sell_price=90.0,
        reason="atr_stop @ 90 ≤ 92 (entry 100 − 2.0×ATR 4)",
        signal_score=1.0,
        shares=10.0,
        avg_cost=100.0,
        entry_date=_d(3),
        entry_price=100.0,
        sell_commission=1.0,
        sell_slippage=1.0,
    )
    defaults.update(kw)
    return SellEvent(**defaults)


# ── Clasificación de risk-exits ───────────────────────────────────────────────


def test_is_risk_exit_classifier():
    assert is_risk_exit("atr_stop @ ...")
    assert is_risk_exit("atr_trail @ ...")
    assert is_risk_exit("atr_tp @ ...")
    assert is_risk_exit("vol_trim σ=0.21>0.12")
    assert not is_risk_exit("analyze SELL (0.30)")
    assert not is_risk_exit(None)
    assert not is_risk_exit("")


# ── Contrafactual "pending expira": ride al cap, ATR neutralizado ──────────────


def test_expire_rides_to_cap_no_atr_fire():
    """Con _NO_ATR ningún stop dispara en la sim → la posición ride al cap aunque
    el precio se desplome (modela el stop que nunca se ejecuta por expiry)."""
    # Cae de 90 (día del sell) a 70 y se queda: sin _NO_ATR un atr_stop dispararía.
    closes = [90.0] + [70.0] * 25
    bars = _bars(closes)  # día del sell = _d(1)=2026-03-01; reindexamos abajo
    ev = _risk_event(sell_date=bars[0][0], entry_date=bars[0][0])
    sim = replay_event(ev, bars, scheduled_exit_idx=None, cap_days=20, atr_p=_NO_ATR)
    assert sim is not None
    assert sim.exit_reason == "cap_reached"
    # Salió 20 días hábiles después del sell, no antes.
    assert sim.exit_date == bars[20][0]


def test_expire_worst_excursion_is_negative_on_drop():
    """La peor excursión diaria (MTM vs el fill del stop) es negativa cuando el
    precio cae por debajo del precio del stop — esa es la cola que el auto-fill
    evita."""
    closes = [90.0] + [60.0] * 25  # cae $30 bajo el fill del stop (90)
    bars = _bars(closes)
    ev = _risk_event(sell_date=bars[0][0], entry_date=bars[0][0], sell_price=90.0, shares=10.0)
    sim = replay_event(ev, bars, scheduled_exit_idx=None, cap_days=20, atr_p=_NO_ATR)
    assert sim is not None
    worst = min(d for _, d in sim.daily_delta)
    # 10 shares * (60 - 90) = -300.
    assert worst < 0.0
    assert abs(worst - (-300.0)) < 1e-6


def test_expire_neutral_when_price_flat():
    """Si el precio no se mueve, expira y auto-fill dan el mismo P/L (Δ=0) y sin
    excursión adversa — el auto-fill no inventa beneficio de la nada."""
    closes = [90.0] * 25
    bars = _bars(closes)
    ev = _risk_event(sell_date=bars[0][0], entry_date=bars[0][0], sell_price=90.0)
    sim = replay_event(ev, bars, scheduled_exit_idx=None, cap_days=20, atr_p=_NO_ATR)
    assert sim is not None
    # pnl_sim (sale al close del cap = 90) ≈ pnl_real (salió al stop = 90).
    assert abs(sim.pnl_delta) < 1e-6
    assert min(d for _, d in sim.daily_delta) == 0.0
