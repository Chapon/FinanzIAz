"""Tests offline para el harness del cap de exposición por nombre (E1a).

Cubre ``scripts.run_exposure_cap_replay.replay_exposure_cap`` (FIFO por lote +
escalado lineal del P/L de las compras sobre-cap) y ``summarize``. Todo
sintético, sin DB ni red. Ver `docs/exposure_cap_e1a_2026-07-01.md`.
"""

from __future__ import annotations

import pytest

from scripts.run_exposure_cap_replay import replay_exposure_cap, summarize


def _o(ticker, side, price, shares, when):
    return {"ticker": ticker, "side": side, "fill_price": price,
            "fill_shares": shares, "filled_at": when}


def test_no_cap_is_identity():
    # cap_pct=0 → el P/L capado es idéntico al actual.
    orders = [
        _o("AAA", "BUY", 100.0, 10, "2026-01-01"),
        _o("AAA", "SELL", 120.0, 10, "2026-01-05"),
    ]
    res = replay_exposure_cap(orders, 0.0, init_capital=10_000)
    assert res["actual_pnl"]["AAA"] == pytest.approx(200.0)
    assert res["capped_pnl"]["AAA"] == pytest.approx(200.0)


def test_over_cap_buy_scales_pnl_linearly():
    # book=100 al comprar (todo cash); compra 1 sh @100 = 100% del book.
    # cap 50% → scale = 0.5 → el P/L realizado se parte a la mitad.
    orders = [
        _o("AAA", "BUY", 100.0, 1, "2026-01-01"),
        _o("AAA", "SELL", 120.0, 1, "2026-01-05"),
    ]
    res = replay_exposure_cap(orders, 0.50, init_capital=100)
    assert res["max_pct"]["AAA"] == pytest.approx(1.0)
    assert res["actual_pnl"]["AAA"] == pytest.approx(20.0)
    assert res["capped_pnl"]["AAA"] == pytest.approx(10.0)  # 20 * 0.5


def test_under_cap_buy_untouched():
    # book=1000, compra de 100 (10% del book) < cap 50% → sin recorte.
    orders = [
        _o("AAA", "BUY", 100.0, 1, "2026-01-01"),
        _o("AAA", "SELL", 120.0, 1, "2026-01-05"),
    ]
    res = replay_exposure_cap(orders, 0.50, init_capital=1000)
    assert res["capped_pnl"]["AAA"] == pytest.approx(res["actual_pnl"]["AAA"])


def test_fifo_two_lots_scaled_independently():
    # Dos lotes: el 1ro a 100% del book (capado), el 2do más chico.
    # init=100: BUY1 1@100 (book=100 → 100%, scale .5 con cap .5).
    # Tras BUY1 cash=0, shares=1. BUY2 1@100: book = 0 + 1*100 = 100,
    # notional=100 → 100% → también capado a .5.
    orders = [
        _o("AAA", "BUY", 100.0, 1, "2026-01-01"),
        _o("AAA", "BUY", 100.0, 1, "2026-01-02"),
        _o("AAA", "SELL", 110.0, 2, "2026-01-05"),
    ]
    res = replay_exposure_cap(orders, 0.50, init_capital=100)
    # gross actual = (110-100)*2 = 20 ; capado = 20 * 0.5 = 10
    assert res["actual_pnl"]["AAA"] == pytest.approx(20.0)
    assert res["capped_pnl"]["AAA"] == pytest.approx(10.0)


def test_summarize_aggregates_worst_and_big_winners():
    res = {
        "actual_pnl": {"MLTX": -2000.0, "MU": 1000.0, "TSLA": 500.0,
                       "AAPL": 500.0, "TJX": 500.0, "XYZ": 100.0},
        "capped_pnl": {"MLTX": -1000.0, "MU": 800.0, "TSLA": 500.0,
                       "AAPL": 400.0, "TJX": 500.0, "XYZ": 100.0},
        "max_pct": {},
    }
    s = summarize(res)
    assert s["worst_actual"] == pytest.approx(-2000.0)
    assert s["worst_reduction"] == pytest.approx(0.5)  # -2000 → -1000
    assert s["big_actual"] == pytest.approx(2500.0)   # 1000+500+500+500
    assert s["big_capped"] == pytest.approx(2200.0)   # 800+500+400+500
    assert s["big_retained"] == pytest.approx(2200.0 / 2500.0)
    assert s["delta_total"] == pytest.approx(s["total_capped"] - s["total_actual"])
