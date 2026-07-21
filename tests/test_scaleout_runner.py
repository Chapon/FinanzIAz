"""
Tests de los helpers puros del runner de la Tarea 7
(``scripts/run_scaleout_replay_t7.py``): grilla de entradas, curva compuesta y
resumen/kill-criteria. Todo sintético, sin Parquet ni artefactos de señal.

Pre-registro: docs/scaleout_trailing_t7_2026-07-20.md
"""

from __future__ import annotations

import pytest

from analysis.scaleout_replay import CycleResult, Leg
from scripts.run_scaleout_replay_t7 import (
    ARMS,
    BASELINE_ARM,
    KILL_MAX_DD_RATIO,
    KILL_MIN_DELTA_PTS,
    PRIMARY_ARM,
    build_entries,
    composite_curve,
    summarise,
)


def _d(i: int) -> str:
    return f"2026-03-{i:02d}" if i <= 31 else f"2026-04-{i - 31:02d}"


def _bars(n: int) -> list:
    return [(_d(i + 1), 100.0, 101.0, 99.0, 100.0) for i in range(n)]


# ── Grilla de entradas ───────────────────────────────────────────────────────


def test_build_entries_only_takes_buy_bars():
    bars = _bars(40)
    sigs = {_d(6): "BUY", _d(8): "SELL", _d(10): "HOLD"}
    got = build_entries({"X": bars}, {"X": sigs}, spacing=1, warmup=3)
    assert got == [("X", 5)]


def test_build_entries_respects_spacing_from_last_accepted():
    """El espaciado se cuenta desde la última entrada ACEPTADA (no una grilla fija),
    para que las ventanas de cap no se solapen nunca."""
    bars = _bars(60)
    sigs = {_d(i): "BUY" for i in range(6, 60)}  # BUY todos los días
    got = build_entries({"X": bars}, {"X": sigs}, spacing=20, warmup=3)
    idxs = [i for _, i in got]
    assert all(b - a >= 20 for a, b in zip(idxs, idxs[1:])), idxs


def test_build_entries_is_chronological_across_tickers():
    bars = _bars(40)
    got = build_entries(
        {"A": bars, "B": bars},
        {"A": {_d(20): "BUY"}, "B": {_d(10): "BUY"}},
        spacing=1, warmup=3,
    )
    assert [t for t, _ in got] == ["B", "A"]


def test_build_entries_skips_last_bar():
    """No se puede abrir una posición en la última barra: no hay día siguiente."""
    bars = _bars(10)
    got = build_entries({"X": bars}, {"X": {_d(10): "BUY"}}, spacing=1, warmup=3)
    assert got == []


# ── Curva compuesta ──────────────────────────────────────────────────────────


def _cycle(vals: list[tuple[str, float]], entry_cost: float = 100.0,
           regime: str = "bull_normal") -> CycleResult:
    r = CycleResult(ticker="X", entry_date=vals[0][0], entry_price=1.0,
                    shares=1.0, entry_cost=entry_cost, regime=regime)
    r.daily_value = list(vals)
    r.legs = [Leg(vals[-1][0], 1.0, 1.0, "cap_reached", vals[-1][1])]
    return r


def test_composite_curve_flat_when_positions_flat():
    c = composite_curve([_cycle([(_d(1), 100.0), (_d(2), 100.0), (_d(3), 100.0)])])
    assert [round(v, 9) for _, v in c] == [1.0, 1.0, 1.0]


def test_composite_curve_tracks_a_drawdown():
    c = composite_curve([_cycle([(_d(1), 100.0), (_d(2), 90.0), (_d(3), 95.0)])])
    vals = [v for _, v in c]
    assert vals[1] == pytest.approx(0.9)
    assert vals[2] == pytest.approx(0.95)


def test_composite_curve_averages_across_open_positions():
    a = _cycle([(_d(1), 100.0), (_d(2), 120.0)])
    b = _cycle([(_d(1), 100.0), (_d(2), 80.0)])
    vals = [v for _, v in composite_curve([a, b])]
    assert vals[1] == pytest.approx(1.0)  # +20% y −20% se cancelan


def test_composite_curve_empty():
    assert composite_curve([]) == []


# ── Resumen y kill-criteria ──────────────────────────────────────────────────


def test_summarise_computes_delta_and_flags_pass():
    base = [_cycle([(_d(1), 100.0), (_d(2), 100.0)]) for _ in range(10)]
    # brazo +2% por ciclo ⇒ Δ = +2 pts > umbral 1.5, mismo DD
    arm = [_cycle([(_d(1), 100.0), (_d(2), 102.0)]) for _ in range(10)]
    s = summarise("arm", arm, base)
    assert s["delta_pts"] == pytest.approx(2.0)
    assert s["passes"] is True


def test_summarise_fails_when_delta_below_threshold():
    base = [_cycle([(_d(1), 100.0), (_d(2), 100.0)]) for _ in range(10)]
    arm = [_cycle([(_d(1), 100.0), (_d(2), 101.0)]) for _ in range(10)]  # +1 pt
    s = summarise("arm", arm, base)
    assert s["delta_pts"] == pytest.approx(1.0)
    assert s["passes"] is False


def test_summarise_fails_when_drawdown_blows_up():
    """Δ bueno pero DD > 1.5× ⇒ no pasa (la restricción de riesgo manda)."""
    base = [_cycle([(_d(1), 100.0), (_d(2), 99.0), (_d(3), 100.0)])]
    arm = [_cycle([(_d(1), 100.0), (_d(2), 80.0), (_d(3), 105.0)])]
    s = summarise("arm", arm, base)
    assert s["delta_pts"] > KILL_MIN_DELTA_PTS
    assert s["dd_ratio"] > KILL_MAX_DD_RATIO
    assert s["passes"] is False


def test_summarise_splits_delta_by_regime():
    base = [_cycle([(_d(1), 100.0), (_d(2), 100.0)], regime="bull_normal"),
            _cycle([(_d(1), 100.0), (_d(2), 100.0)], regime="stress_bear_2022")]
    arm = [_cycle([(_d(1), 100.0), (_d(2), 104.0)], regime="bull_normal"),
           _cycle([(_d(1), 100.0), (_d(2), 98.0)], regime="stress_bear_2022")]
    s = summarise("arm", arm, base)
    reg = s["delta_by_regime"]
    assert reg["bull_normal"] == pytest.approx(4.0)
    assert reg["stress_bear_2022"] == pytest.approx(-2.0)


def test_baseline_summary_has_no_verdict():
    base = [_cycle([(_d(1), 100.0), (_d(2), 100.0)])]
    s = summarise(BASELINE_ARM, base, None)
    assert "passes" not in s and "delta_pts" not in s


# ── Integridad del set de brazos pre-registrados ─────────────────────────────


def test_preregistered_arms_are_intact():
    """El pre-registro fija los brazos: que nadie agregue uno post-hoc sin querer."""
    assert set(ARMS) == {
        "B0_baseline_full_exit", "A50_scaleout_50", "B_trail_2.5", "B_trail_3.0",
        "C_A4_levels_rule", "A33_scaleout_33", "A67_scaleout_67",
    }
    assert PRIMARY_ARM in ARMS and BASELINE_ARM in ARMS
    # el baseline tiene que ser el engine de hoy: cierre total, trailing = stop
    params, atr_p = ARMS[BASELINE_ARM]
    assert params.sell_fraction == 1.0
    assert atr_p.effective_trail_mult == atr_p.stop_mult == 2.0


def test_trailing_arms_do_not_move_the_hard_stop():
    """Los brazos B recalibran el trailing, NUNCA el stop inicial (A1 fue NO-SHIP)."""
    for name in ("B_trail_2.5", "B_trail_3.0"):
        _, atr_p = ARMS[name]
        assert atr_p.stop_mult == 2.0
        assert atr_p.effective_trail_mult > 2.0
