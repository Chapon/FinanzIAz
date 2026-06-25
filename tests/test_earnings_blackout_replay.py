"""Tests offline del harness de earnings blackout (sin red, sin DB).

Solo ejercita las funciones puras: clasificación near-earnings, resumen y
contrafactual. Las fechas de earnings se inyectan a mano.
"""
from __future__ import annotations

from datetime import date

from scripts.run_earnings_blackout_replay import (
    classify_round_trips,
    counterfactual_delta,
    is_near_earnings,
    run,
    summarize,
)


def _rt(ticker, buy_day, pnl, pnl_pct, shares=10.0, buy_price=100.0):
    return {
        "ticker": ticker,
        "buy_day": buy_day,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "shares": shares,
        "buy_price": buy_price,
    }


def test_is_near_earnings_dentro_y_fuera():
    earnings = [date(2026, 5, 10)]
    assert is_near_earnings(date(2026, 5, 11), earnings, 2) is True   # +1 día
    assert is_near_earnings(date(2026, 5, 8), earnings, 2) is True    # −2 días
    assert is_near_earnings(date(2026, 5, 14), earnings, 2) is False  # +4 días
    assert is_near_earnings(None, earnings, 2) is False
    assert is_near_earnings(date(2026, 5, 10), [], 2) is False


def test_is_near_earnings_acepta_strings():
    assert is_near_earnings("2026-05-11", ["2026-05-10"], 2) is True
    assert is_near_earnings("2026-05-11 09:30:00", ["2026-05-10"], 1) is True


def test_classify_separa_por_ticker():
    rts = [
        _rt("AAPL", date(2026, 5, 11), 5.0, 0.05),    # near (earnings 5-10)
        _rt("AAPL", date(2026, 6, 1), -3.0, -0.03),   # far
        _rt("KO", date(2026, 5, 11), 2.0, 0.02),      # far (KO sin earnings cerca)
    ]
    earnings = {"AAPL": [date(2026, 5, 10)], "KO": [date(2026, 1, 1)]}
    near, far = classify_round_trips(rts, earnings, 2)
    assert [rt["ticker"] for rt in near] == ["AAPL"]
    assert len(far) == 2


def test_summarize_metricas():
    rts = [_rt("X", date(2026, 5, 1), 10.0, 0.10), _rt("X", date(2026, 5, 2), -5.0, -0.05)]
    s = summarize(rts)
    assert s["n"] == 2
    assert s["total_pnl"] == 5.0
    assert s["win_rate"] == 0.5
    assert summarize([])["n"] == 0


def test_counterfactual_near_perdedor_blackout_ayuda():
    # near perdió plata; far rindió +5% en promedio → redeployar habría mejorado.
    near = [_rt("X", date(2026, 5, 11), -20.0, -0.20, shares=10, buy_price=10)]  # notional 100
    far = [_rt("Y", date(2026, 6, 1), 5.0, 0.05)]
    cf = counterfactual_delta(near, far)
    assert cf["real_near_pnl"] == -20.0
    assert cf["proxy_ret_pct"] == 0.05
    assert cf["cf_pnl"] == 100 * 0.05          # 5.0
    assert cf["delta"] == 5.0 - (-20.0)        # +25 → blackout ayuda
    assert cf["delta"] > 0


def test_counterfactual_sin_near_es_neutro():
    cf = counterfactual_delta([], [_rt("Y", date(2026, 6, 1), 5.0, 0.05)])
    assert cf["delta"] == 0.0


def test_run_sweep_devuelve_una_fila_por_ventana():
    rts = [_rt("AAPL", date(2026, 5, 11), -2.0, -0.02)]
    earnings = {"AAPL": [date(2026, 5, 10)]}
    results = run(rts, earnings, windows=(1, 2, 5))
    assert [r["window_days"] for r in results] == [1, 2, 5]
    # con ventana 1, el BUY +1 día sigue siendo near; todas lo capturan acá.
    assert all(r["near"]["n"] == 1 for r in results)
