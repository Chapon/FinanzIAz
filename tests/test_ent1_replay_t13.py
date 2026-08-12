"""
Tests offline de las micro-reglas de entrada/salida — Tarea 13 (ENT1).
Pre-registro: ``docs/ent1_prereg_t13_2026-08-12.md``.

Todo sintético: barras a mano, señal PIT como dict, sin Parquet, sin red, sin DB.

Cubre:
  analysis/entry_rules
    ema_series           — semilla SMA, point-in-time estricto (out[j] ignora j+1..)
    resolve_pullback     — fill al primer toque, expiración, cancelación por SELL,
                           y que no se filla sin barra futura (replay_cycle la exige)
    apply_pullback       — dedup de una espera por ticker, contabilidad, orden
    condición negday     — el brazo exploratorio
  analysis/scaleout_replay (hook del brazo b)
    time stop            — dispara en la barra N con P/L ≤ 0; NO dispara con P/L > 0;
                           es one-shot (no re-chequea después de N)
    no-op                — time_stop_days=None no cambia nada (regresión T7/T23)
  analysis/walkforward_power
    paired_block_bootstrap — series idénticas ⇒ el gate NO pasa; candidato
                           estrictamente mejor ⇒ ci_low > 0; determinismo por seed
  scripts/run_ent1_replay_t13
    evaluate_arm         — el AND de los criterios, y el C6 distinto por brazo
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from analysis.entry_rules import (
    DEFAULT_WINDOW,
    apply_pullback,
    ema_series,
    resolve_pullback,
)
from analysis.scaleout_replay import CostModel, ScaleOutParams, replay_cycle
from analysis.exit_replay import AtrParams
from analysis.walkforward_power import paired_block_bootstrap
from scripts.run_ent1_replay_t13 import TIME_STOP_N, evaluate_arm


# ── Helpers ──────────────────────────────────────────────────────────────────

_D0 = date(2026, 1, 5)


def _d(i: int) -> str:
    """Calendario sintético sin límite de mes (los tests comparan strings)."""
    return (_D0 + timedelta(days=i)).isoformat()


def _bars(closes: list[float], tr: float = 2.0) -> list:
    return [(_d(i), c, c + tr / 2, c - tr / 2, c) for i, c in enumerate(closes)]


def flat(n: int, close: float = 100.0, tr: float = 2.0) -> list:
    return _bars([close] * n, tr)


# ── ema_series ───────────────────────────────────────────────────────────────


def test_ema_seed_is_sma_and_warmup_is_none():
    bars = _bars([10.0, 20.0, 30.0, 40.0])
    ema = ema_series(bars, period=3)
    assert ema[0] is None and ema[1] is None
    assert ema[2] == pytest.approx(20.0)          # SMA(10,20,30)
    alpha = 2.0 / 4.0
    assert ema[3] == pytest.approx(alpha * 40.0 + (1 - alpha) * 20.0)


def test_ema_is_point_in_time():
    """``out[j]`` no puede depender de barras posteriores — si dependiera, el brazo
    (a) estaría mirando el futuro para decidir la entrada."""
    closes = [100.0, 102.0, 98.0, 105.0, 95.0, 110.0, 90.0, 101.0]
    full = ema_series(_bars(closes), period=3)
    for k in range(3, len(closes) + 1):
        assert ema_series(_bars(closes[:k]), period=3) == full[:k]


def test_ema_shorter_than_period_is_all_none():
    assert ema_series(_bars([1.0, 2.0]), period=20) == [None, None]


# ── resolve_pullback ─────────────────────────────────────────────────────────


def _ema_stub(n: int, value: float) -> list:
    return [value] * n


def test_pullback_fills_at_first_touch():
    # close cae por debajo de la EMA (=100) recién en la barra 3.
    bars = _bars([101.0, 102.0, 103.0, 99.0, 98.0, 97.0, 96.0])
    out = resolve_pullback(bars, 0, {}, window=5, condition="ema20",
                           ema=_ema_stub(len(bars), 100.0))
    assert out.status == "filled" and out.fill_idx == 3


def test_pullback_expires_when_no_touch_in_window():
    bars = _bars([101.0] + [110.0] * 8)
    out = resolve_pullback(bars, 0, {}, window=3, condition="ema20",
                           ema=_ema_stub(len(bars), 100.0))
    assert out.status == "expired" and out.fill_idx is None


def test_pullback_cancelled_by_sell_flip():
    """Si la señal vira a SELL dentro de la ventana, la espera se cancela: comprar
    igual sería comprar algo que el sistema ya quiere vender."""
    bars = _bars([101.0, 102.0, 99.0, 98.0, 97.0])
    sigs = {bars[1][0]: "SELL"}
    out = resolve_pullback(bars, 0, sigs, window=4, condition="ema20",
                           ema=_ema_stub(len(bars), 100.0))
    assert out.status == "cancelled" and out.fill_idx is None


def test_pullback_needs_a_future_bar():
    """El toque en la última barra no es un fill: ``replay_cycle`` necesita futuro."""
    bars = _bars([101.0, 102.0, 99.0])   # el toque cae en n-1
    out = resolve_pullback(bars, 0, {}, window=5, condition="ema20",
                           ema=_ema_stub(len(bars), 100.0))
    assert out.status == "expired"


def test_pullback_negday_condition():
    bars = _bars([100.0, 101.0, 102.0, 101.5, 103.0])
    out = resolve_pullback(bars, 0, {}, window=5, condition="negday")
    assert out.status == "filled" and out.fill_idx == 3


def test_pullback_unknown_condition_raises():
    with pytest.raises(ValueError):
        resolve_pullback(_bars([1.0, 2.0, 3.0]), 0, {}, condition="nope")


# ── apply_pullback ───────────────────────────────────────────────────────────


def test_apply_pullback_dedups_one_wait_per_ticker():
    """Un BUY sostenido varios días abriría una espera por día; sin dedup el brazo
    tomaría más entradas que el baseline y la comparación quedaría contaminada."""
    bars = _bars([100.0, 101.0, 102.0, 103.0, 104.0, 99.0, 98.0, 97.0])
    bars_by = {"AAA": bars}
    sigs_by = {"AAA": {}}
    entries = [("AAA", 1), ("AAA", 2), ("AAA", 3)]
    out, stats = apply_pullback(entries, bars_by, sigs_by, window=5, condition="negday")
    assert stats.n_signals == 3
    assert stats.n_waits == 1          # sólo la más vieja abrió espera
    assert stats.n_dup_skipped == 2
    assert out == [("AAA", 5)]         # primer día de retorno negativo


def test_apply_pullback_accounting_and_order():
    bars_a = _bars([100.0, 101.0, 99.0, 98.0, 97.0, 96.0])
    bars_b = _bars([50.0] + [60.0] * 5)          # nunca retrocede → expira
    bars_by = {"AAA": bars_a, "BBB": bars_b}
    sigs_by = {"AAA": {}, "BBB": {}}
    out, stats = apply_pullback([("AAA", 0), ("BBB", 0)], bars_by, sigs_by,
                                window=3, condition="negday")
    assert stats.n_waits == 2
    assert stats.n_filled == 1 and stats.n_expired == 1
    assert stats.expired_share == pytest.approx(0.5)
    assert stats.fill_share == pytest.approx(0.5)
    assert out == [("AAA", 2)]
    # el resultado sale ordenado por fecha (lo que portfolio_sim espera)
    assert out == sorted(out, key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]))


def test_apply_pullback_default_window_is_five():
    assert DEFAULT_WINDOW == 5


# ── Time stop (brazo b) ──────────────────────────────────────────────────────

_SO = ScaleOutParams()
_COSTS = CostModel()


def _cycle(bars, *, time_stop_days=None, cap_days=40):
    return replay_cycle(bars, 0, {}, params=_SO, atr_p=AtrParams(),
                        cap_days=cap_days, costs=_COSTS, notional=10_000.0,
                        time_stop_days=time_stop_days)


def test_time_stop_fires_at_bar_n_when_flat():
    """Precio plano: ningún nivel ATR dispara, y a los N días el P/L neto es
    negativo (los costos de las dos puntas) → el slot se libera."""
    cyc = _cycle(flat(40), time_stop_days=TIME_STOP_N)
    assert cyc is not None
    assert cyc.exit_reasons == "time_stop"
    assert cyc.legs[-1].date == flat(40)[TIME_STOP_N][0]


def test_time_stop_does_not_fire_when_position_advanced():
    """Con P/L > 0 en la barra N la posición sigue: es lo que protege a los runners
    que arrancan tarde (T7: 4 trades de 12–27 días hicieron el 69% de la ganancia)."""
    closes = [100.0 + 0.05 * i for i in range(40)]     # +1.95 en 39 ruedas
    cyc = _cycle(_bars(closes), time_stop_days=TIME_STOP_N)
    assert cyc is not None
    assert "time_stop" not in cyc.exit_reasons


def test_time_stop_is_one_shot_not_rolling():
    """Positivo en la barra N y negativo después ⇒ NO se cierra: la regla se evalúa
    una sola vez (la variante rolling está declarada fuera de alcance en el §4.2)."""
    closes = [100.0 + 0.05 * i for i in range(TIME_STOP_N + 1)]     # +1.0 al día N
    closes += [101.0 - 0.15 * i for i in range(1, 20)]              # cae bajo el costo
    bars = _bars(closes)
    cyc = _cycle(bars, time_stop_days=TIME_STOP_N, cap_days=len(closes) - 1)
    assert cyc is not None
    assert "time_stop" not in cyc.exit_reasons
    assert cyc.held_days > TIME_STOP_N


def test_time_stop_none_is_a_no_op():
    """Regresión: el parámetro nuevo no puede alterar los resultados de T7/T23."""
    bars = flat(40)
    base = _cycle(bars)
    assert base is not None
    assert base.exit_reasons == "cap_reached"
    explicit_none = _cycle(bars, time_stop_days=None)
    assert explicit_none is not None
    assert explicit_none.exit_reasons == base.exit_reasons
    assert explicit_none.total_proceeds == pytest.approx(base.total_proceeds)


def test_time_stop_uses_net_pnl_not_raw_price():
    """En un precio apenas por encima de la entrada pero por debajo del break-even
    con costos, el time stop SÍ dispara: la condición mira el P/L neto."""
    # +0.1% de precio contra ~0.3% de fricción round-trip.
    closes = [100.0] + [100.1] * 40
    cyc = _cycle(_bars(closes), time_stop_days=TIME_STOP_N)
    assert cyc is not None
    assert cyc.exit_reasons == "time_stop"


# ── Block-bootstrap pareado ──────────────────────────────────────────────────


def _wiggle(n: int, seed: int = 7) -> list[float]:
    import random
    rnd = random.Random(seed)
    return [rnd.gauss(0.0004, 0.01) for _ in range(n)]


def test_bootstrap_identical_series_does_not_pass_the_gate():
    r = _wiggle(500)
    out = paired_block_bootstrap(r, r, block=20, n_resamples=200, seed=1)
    assert out.observed == pytest.approx(0.0, abs=1e-12)
    assert out.ci_low <= 0.0 <= out.ci_high
    assert not (out.ci_low > 0.0)          # el gate C5 NO pasa


def test_bootstrap_strictly_better_candidate_passes():
    base = _wiggle(500)
    cand = [x + 0.0008 for x in base]      # mejor todos los días
    out = paired_block_bootstrap(base, cand, block=20, n_resamples=300, seed=1)
    assert out.observed > 0
    assert out.ci_low > 0.0
    assert out.p_value < 0.05


def test_bootstrap_is_deterministic_by_seed():
    base, cand = _wiggle(300), _wiggle(300, seed=8)
    a = paired_block_bootstrap(base, cand, block=20, n_resamples=100, seed=42)
    b = paired_block_bootstrap(base, cand, block=20, n_resamples=100, seed=42)
    assert (a.ci_low, a.ci_high, a.p_value) == (b.ci_low, b.ci_high, b.p_value)


def test_bootstrap_degenerate_input():
    out = paired_block_bootstrap([0.01], [0.02], block=20, n_resamples=100)
    assert out.n_resamples == 0


# ── evaluate_arm (kill-criteria §5) ──────────────────────────────────────────

_REGIMES = ["bull_normal", "stress_2018q4", "covid_2020", "bear_2022"]


class _Boot:
    def __init__(self, ci_low: float):
        self.ci_low = ci_low


class _Stats:
    def __init__(self, expired_share: float):
        self.expired_share = expired_share


def _summary(cagr=0.10, sharpe=1.0, dd=0.20, winner=5.0, p95=0.12):
    return {"cagr": cagr, "sharpe": sharpe, "max_dd": dd, "p5_trade": -0.07,
            "p95_trade": p95, "winner_mean_pts": winner, "accounting_ok": True}


def _regimes(delta=0.0):
    return {r: {"n": 10, "mean_ret_pts": 1.0 + delta} for r in _REGIMES}


def test_evaluate_arm_ships_when_everything_passes():
    summaries = {"BASE": _summary(), "B_timestop": _summary(cagr=0.11)}
    regimes = {"BASE": _regimes(), "B_timestop": _regimes()}
    v = evaluate_arm("B_timestop", summaries, regimes, _Boot(0.001), None)
    assert v["ship"] is True


def test_evaluate_arm_blocked_by_bootstrap_gate():
    """C5 es el gate anti-overfit: con el IC95% cruzando cero no se shipea aunque
    el ΔCAGR puntual sea bueno."""
    summaries = {"BASE": _summary(), "B_timestop": _summary(cagr=0.13)}
    regimes = {"BASE": _regimes(), "B_timestop": _regimes()}
    v = evaluate_arm("B_timestop", summaries, regimes, _Boot(-0.002), None)
    assert v["c1_cagr"] is True and v["c5_bootstrap"] is False and v["ship"] is False


def test_evaluate_arm_blocked_by_regime_robustness():
    summaries = {"BASE": _summary(), "B_timestop": _summary(cagr=0.12)}
    regimes = {"BASE": _regimes(), "B_timestop": _regimes()}
    regimes["B_timestop"]["bear_2022"]["mean_ret_pts"] -= 0.4
    v = evaluate_arm("B_timestop", summaries, regimes, _Boot(0.001), None)
    assert v["c4_regime"] is False and v["ship"] is False


def test_evaluate_arm_c6_is_expiry_for_a_and_right_tail_for_b():
    summaries = {"BASE": _summary(),
                 "A_pullback": _summary(cagr=0.12),
                 "B_timestop": _summary(cagr=0.12, winner=4.0)}
    regimes = {n: _regimes() for n in summaries}
    # (a) — demasiadas entradas perdidas por expiración
    va = evaluate_arm("A_pullback", summaries, regimes, _Boot(0.001), _Stats(0.35))
    assert va["c6_specific"] is False and va["ship"] is False
    assert evaluate_arm("A_pullback", summaries, regimes, _Boot(0.001),
                        _Stats(0.10))["ship"] is True
    # (b) — el time stop recortó la cola derecha (ganadores 5.0 → 4.0 pts)
    vb = evaluate_arm("B_timestop", summaries, regimes, _Boot(0.001), None)
    assert vb["c6_specific"] is False and vb["ship"] is False
