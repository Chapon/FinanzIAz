"""
Tests para la recalibración de stops ATR (backlog A1).

Cubre el motor ``analysis.exit_replay.replay_atr_recalib`` (re-evalúa un ciclo
ATR desde el día del exit real bajo parámetros alternativos) y la higiene de
datos ``scripts.run_atr_stop_recalib.partition_atr_events`` (excluye precios
corruptos tipo KLAC ~10×). Todo sintético/offline.
"""

from __future__ import annotations

import pytest

from analysis.exit_replay import AtrParams, SellEvent, replay_atr_recalib
from scripts.run_atr_stop_recalib import partition_atr_events


def _d(i: int) -> str:
    return f"2026-03-{i:02d}" if i <= 31 else f"2026-04-{i-31:02d}"


def bars_with_closes(closes, tr: float = 2.0):
    return [(_d(i + 1), c, c + tr / 2, c - tr / 2, c) for i, c in enumerate(closes)]


def make_event(**kw) -> SellEvent:
    # avg_cost = entry = 100 → sin pico previo el trail queda suprimido
    # (hwm no supera entry + 1·ATR), así el stop dispara limpio en los tests.
    defaults = dict(
        order_id=1, ticker="AAA", sell_date=_d(20), sell_price=100.0,
        reason="atr_stop @ 91.0 ≤ 91.0", signal_score=None, shares=10.0,
        avg_cost=100.0, entry_date=_d(17), entry_price=100.0,
        sell_commission=1.0, sell_slippage=1.0,
    )
    defaults.update(kw)
    return SellEvent(**defaults)


P = AtrParams()  # 14 / 2.0 / 4.0 / trail on


# ── replay_atr_recalib ───────────────────────────────────────────────────────


class TestReplayAtrRecalib:
    def test_redispara_el_mismo_dia_bajo_baseline(self):
        # close de D cruza el hard stop (95 - 2·ATR2 = 91) → sale en D mismo
        closes = [100.0] * 30
        closes[19] = 90.0  # D = idx 19 (_d(20))
        bars = bars_with_closes(closes)
        sim = replay_atr_recalib(make_event(), bars, cap_days=20, atr_p=P)
        assert sim is not None
        assert sim.exit_date == _d(20)
        assert sim.exit_reason == "atr_stop"

    def test_stop_mas_laxo_no_dispara_en_D_y_continua(self):
        # baja leve a 95 en D: mult 2.0 dispara (stop ≈95.4) pero mult 3.0 no
        # (stop ≈93.1) → con stop más laxo la posición continúa hasta cap
        closes = [100.0] * 30
        closes[19] = 95.0
        bars = bars_with_closes(closes)
        baseline = replay_atr_recalib(make_event(), bars, cap_days=5, atr_p=P)
        assert baseline.exit_reason == "atr_stop"  # mult 2.0 sí dispara en D
        laxo = replay_atr_recalib(make_event(), bars, cap_days=5,
                                  atr_p=AtrParams(stop_mult=3.0))
        assert laxo.exit_reason == "cap_reached"
        assert laxo.exit_date == _d(25)  # idx 19 + 5

    def test_no_stops_mantiene_hasta_cap(self):
        closes = [100.0] * 30
        closes[19] = 90.0  # caería bajo el stop normal, pero está apagado
        bars = bars_with_closes(closes)
        sim = replay_atr_recalib(
            make_event(), bars, cap_days=5,
            atr_p=AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False))
        assert sim.exit_reason == "cap_reached"
        assert sim.exit_date == _d(25)

    def test_hwm_seedeado_hasta_D_menos_1(self):
        # pico en D-1 (idx 18) → trail = 110 - 2·2 = 106; en D close 100 ≤ 106
        # y hwm 110 > entry+2 → atr_trail dispara EN D (usa el HWM pre-close)
        closes = [100.0] * 30
        closes[18] = 110.0
        bars = bars_with_closes(closes)
        sim = replay_atr_recalib(make_event(), bars, cap_days=20, atr_p=P)
        assert sim.exit_reason == "atr_trail"
        assert sim.exit_date == _d(20)

    def test_fill_modelado_gap_open(self):
        # barra de D con open por debajo del nivel del stop → fill = open (gap),
        # no el nivel (91): espejo de model_exit_fill_price
        bars = bars_with_closes([100.0] * 30)
        bars[19] = (_d(20), 88.0, 92.0, 87.0, 90.0)  # open 88 < stop 91
        sim = replay_atr_recalib(make_event(), bars, cap_days=20, atr_p=P)
        assert sim.exit_reason == "atr_stop"
        assert sim.exit_price == pytest.approx(88.0)

    def test_sell_day_no_en_barras_none(self):
        bars = bars_with_closes([100.0] * 10)
        assert replay_atr_recalib(make_event(sell_date=_d(25)), bars,
                                  cap_days=20, atr_p=P) is None

    def test_sin_barras_none(self):
        assert replay_atr_recalib(make_event(), [], cap_days=20, atr_p=P) is None


# ── partition_atr_events (higiene de datos) ──────────────────────────────────


class TestPartitionAtrEvents:
    def test_excluye_precio_corrupto(self):
        bars = bars_with_closes([100.0] * 30)
        good = make_event(order_id=1, ticker="AAA", sell_price=100.0)
        # fill 10× el close del cache (≈ KLAC) → excluido
        bad = make_event(order_id=2, ticker="BBB", sell_price=1000.0)
        loader = {"AAA": bars, "BBB": bars}.get
        clean, excluded = partition_atr_events([good, bad], loader, contam_tol=0.5)
        assert [e.ticker for e in clean] == ["AAA"]
        assert len(excluded) == 1 and excluded[0][0].ticker == "BBB"
        assert "corrupto" in excluded[0][1]

    def test_ignora_sells_no_atr(self):
        bars = bars_with_closes([100.0] * 30)
        signal = make_event(reason="analyze SELL (0.35)")
        clean, excluded = partition_atr_events([signal], lambda t: bars, contam_tol=0.5)
        assert clean == [] and excluded == []

    def test_sin_barra_del_dia_excluido(self):
        ev = make_event(sell_date=_d(28))  # no está en las barras
        bars = bars_with_closes([100.0] * 20)
        clean, excluded = partition_atr_events([ev], lambda t: bars, contam_tol=0.5)
        assert clean == []
        assert len(excluded) == 1 and "sin barra" in excluded[0][1]
