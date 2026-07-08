"""Tests offline para analysis/metrics_panel.py — DB sintética en memoria."""
from __future__ import annotations

import json
import sqlite3

import pytest

from analysis import metrics_panel as mp


# ── fixtures ──────────────────────────────────────────────────────────────────
def _make_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_orders (id INTEGER PRIMARY KEY, account_id INT, ticker TEXT, "
        "side TEXT, fill_price REAL, fill_shares REAL, commission_paid REAL, "
        "slippage_cost REAL, signal_score REAL, reason TEXT, status TEXT, filled_at TEXT)"
    )
    con.execute(
        "CREATE TABLE paper_positions (id INTEGER PRIMARY KEY, account_id INT, "
        "ticker TEXT, shares REAL, avg_cost REAL)"
    )
    con.execute(
        "CREATE TABLE historical_data_cache (id INTEGER PRIMARY KEY, ticker TEXT, "
        "period TEXT, interval TEXT, data_json TEXT, fetched_at TEXT)"
    )
    return con


def _order(con, oid, ticker, side, price, shares, when, *, comm=1.0, slip=0.5,
           score=None, reason=None, status="filled", acct=1):
    reason = reason or (f"analyze {side}")
    con.execute(
        "INSERT INTO paper_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (oid, acct, ticker, side, price, shares, comm, slip, score, reason, status, when),
    )


def _hist(con, ticker, closes: list[tuple[str, float]]):
    payload = {
        "columns": ["Open", "High", "Low", "Close", "Volume"],
        "index": [f"{d}T00:00:00.000" for d, _ in closes],
        "data": [[c, c, c, c, 1000] for _, c in closes],
    }
    con.execute(
        "INSERT INTO historical_data_cache (ticker,period,interval,data_json,fetched_at) "
        "VALUES (?,?,?,?,?)",
        (ticker, "2y", "1d", json.dumps(payload), "2026-06-17"),
    )


# ── pair_round_trips ──────────────────────────────────────────────────────────
def test_round_trip_pnl_net_of_costs():
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", comm=1.0, slip=0.5)
    _order(con, 2, "AAA", "SELL", 110.0, 10, "2026-01-05 10:00:00", comm=1.1, slip=0.55)
    orders = mp._filled_orders(con, 1)
    rts = mp.pair_round_trips(orders)
    assert len(rts) == 1
    rt = rts[0]
    # gross = (110-100)*10 = 100 ; costs = 1+0.5+1.1+0.55 = 3.15
    assert rt["pnl"] == pytest.approx(100.0 - 3.15, abs=1e-6)
    assert rt["hold_days"] == 4
    assert rt["exit_kind"] == "signal_sell"


def test_fifo_partial_fills_split_across_lots():
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", comm=0, slip=0)
    _order(con, 2, "AAA", "BUY", 200.0, 10, "2026-01-02 10:00:00", comm=0, slip=0)
    _order(con, 3, "AAA", "SELL", 150.0, 15, "2026-01-10 10:00:00", comm=0, slip=0)
    rts = mp.pair_round_trips(mp._filled_orders(con, 1))
    # 10 sh contra lote $100 (+$500) + 5 sh contra lote $200 (-$250) = +$250
    assert len(rts) == 2
    assert sum(r["pnl"] for r in rts) == pytest.approx(250.0, abs=1e-6)
    assert rts[0]["buy_price"] == 100.0 and rts[1]["buy_price"] == 200.0


def test_open_position_not_paired():
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00")
    rts = mp.pair_round_trips(mp._filled_orders(con, 1))
    assert rts == []


def test_exit_kind_classification():
    assert mp._exit_kind("atr_stop @ 80 ≤ 81") == "atr_stop"
    assert mp._exit_kind("atr_trail @ 1 ≤ 2") == "atr_trail"
    assert mp._exit_kind("analyze SELL (0.31)") == "signal_sell"
    assert mp._exit_kind(None) == "other"


# ── forward_return ────────────────────────────────────────────────────────────
def test_forward_return_basic():
    series = [("2026-01-01", 100.0), ("2026-01-02", 101.0), ("2026-01-03", 102.0),
              ("2026-01-04", 103.0), ("2026-01-05", 104.0), ("2026-01-06", 110.0)]
    # base = idx 0 (100), +5 barras = idx5 (110) -> +10%
    assert mp.forward_return(series, "2026-01-01", 5) == pytest.approx(0.10, abs=1e-9)


def test_forward_return_insufficient_bars():
    series = [("2026-01-01", 100.0), ("2026-01-02", 101.0)]
    assert mp.forward_return(series, "2026-01-01", 5) is None
    assert mp.forward_return(None, "2026-01-01", 5) is None


# ── panels integrales ─────────────────────────────────────────────────────────
def test_build_metrics_realized_and_timing():
    con = _make_db()
    # AAA: round-trip ganador. BBB: round-trip perdedor.
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", comm=0, slip=0, score=0.8)
    _order(con, 2, "AAA", "SELL", 120.0, 10, "2026-01-08 10:00:00", comm=0, slip=0,
           reason="analyze SELL (0.30)")
    _order(con, 3, "BBB", "BUY", 50.0, 20, "2026-01-02 10:00:00", comm=0, slip=0, score=0.7)
    _order(con, 4, "BBB", "SELL", 40.0, 20, "2026-01-09 10:00:00", comm=0, slip=0,
           reason="atr_stop @ 40 ≤ 41")
    # series para forward returns (>=6 barras tras cada buy)
    _hist(con, "AAA", [("2026-01-01", 100.0), ("2026-01-02", 101.0), ("2026-01-05", 102.0),
                       ("2026-01-06", 103.0), ("2026-01-07", 104.0), ("2026-01-08", 105.0),
                       ("2026-01-09", 108.0)])
    _hist(con, "BBB", [("2026-01-02", 50.0), ("2026-01-05", 49.0), ("2026-01-06", 48.0),
                       ("2026-01-07", 47.0), ("2026-01-08", 46.0), ("2026-01-09", 45.0),
                       ("2026-01-12", 44.0)])
    m = mp.build_metrics(con, 1)
    r = m["realized"]
    assert r["n_round_trips"] == 2
    assert r["n_wins"] == 1 and r["n_losses"] == 1
    assert r["total_pnl"] == pytest.approx(200.0 - 200.0, abs=1e-6)  # +200 AAA, -200 BBB
    assert r["by_exit_kind"]["signal_sell"]["pnl"] == pytest.approx(200.0, abs=1e-6)
    assert r["by_exit_kind"]["atr_stop"]["pnl"] == pytest.approx(-200.0, abs=1e-6)
    assert r["worst_ticker"]["ticker"] == "BBB"
    # timing: AAA fwd5 positivo, BBB fwd5 negativo
    t = m["timing"]
    assert t["n5"] == 2
    assert t["good5"] == 1


def test_build_metrics_filters_by_account():
    # MET1: build_metrics devuelve los datos de la cuenta pedida, sin mezclar.
    con = _make_db()
    # Cuenta 1: un round-trip ganador de AAA (+200).
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", comm=0, slip=0, acct=1)
    _order(con, 2, "AAA", "SELL", 120.0, 10, "2026-01-08 10:00:00", comm=0, slip=0,
           reason="analyze SELL (0.30)", acct=1)
    # Cuenta 2: un round-trip perdedor de CCC (-100) → payload distinto.
    _order(con, 10, "CCC", "BUY", 50.0, 10, "2026-02-01 10:00:00", comm=0, slip=0, acct=2)
    _order(con, 11, "CCC", "SELL", 40.0, 10, "2026-02-05 10:00:00", comm=0, slip=0,
           reason="atr_stop @ 40 ≤ 41", acct=2)

    m1 = mp.build_metrics(con, 1)
    m2 = mp.build_metrics(con, 2)

    # Cada cuenta ve solo sus propios round-trips (sin cross-contamination).
    assert m1["realized"]["n_round_trips"] == 1
    assert m1["realized"]["total_pnl"] == pytest.approx(200.0, abs=1e-6)  # solo AAA
    assert m2["realized"]["n_round_trips"] == 1
    assert m2["realized"]["total_pnl"] == pytest.approx(-100.0, abs=1e-6)  # solo CCC


def test_realized_payoff_ratio():
    # E2: payoff = avg_win / |avg_loss|. Ganador +100, perdedor -50 → 2.0.
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 1, "2026-01-01 10:00:00", comm=0, slip=0)
    _order(con, 2, "AAA", "SELL", 200.0, 1, "2026-01-05 10:00:00", comm=0, slip=0)
    _order(con, 3, "BBB", "BUY", 100.0, 1, "2026-01-02 10:00:00", comm=0, slip=0)
    _order(con, 4, "BBB", "SELL", 50.0, 1, "2026-01-06 10:00:00", comm=0, slip=0)
    r = mp.build_metrics(con, 1)["realized"]
    assert r["avg_win"] == pytest.approx(100.0)
    assert r["avg_loss"] == pytest.approx(-50.0)
    assert r["payoff_ratio"] == pytest.approx(2.0)


def _hist_ohlc(con, ticker, bars: list[tuple[str, float, float, float]]):
    """Cache 1d con High/Low distintos del Close: bars = [(date, high, low, close)]."""
    payload = {
        "columns": ["Open", "High", "Low", "Close", "Volume"],
        "index": [f"{d}T00:00:00.000" for d, _, _, _ in bars],
        "data": [[c, h, lw, c, 1000] for _, h, lw, c in bars],
    }
    con.execute(
        "INSERT INTO historical_data_cache (ticker,period,interval,data_json,fetched_at) "
        "VALUES (?,?,?,?,?)",
        (ticker, "2y", "1d", json.dumps(payload), "2026-06-17"),
    )


# ── MAE/MFE (V1) ──────────────────────────────────────────────────────────────
def test_load_ohlc_series_basic():
    con = _make_db()
    _hist_ohlc(con, "AAA", [("2026-01-01", 105.0, 95.0, 100.0),
                            ("2026-01-02", 112.0, 101.0, 110.0)])
    s = mp.load_ohlc_series(con, "AAA")
    assert s == [("2026-01-01", 105.0, 95.0), ("2026-01-02", 112.0, 101.0)]


def test_load_ohlc_series_missing():
    con = _make_db()
    assert mp.load_ohlc_series(con, "ZZZ") is None


def test_excursions_window_high_low():
    # entrada 100; ventana 01→05; max High 130 (MFE +30%), min Low 88 (MAE -12%).
    # La barra del 08 (fuera de la ventana) NO debe influir.
    series = [("2026-01-01", 105.0, 98.0), ("2026-01-02", 115.0, 92.0),
              ("2026-01-03", 130.0, 100.0), ("2026-01-05", 120.0, 88.0),
              ("2026-01-08", 200.0, 60.0)]
    mae, mfe = mp.excursions(series, "2026-01-01", "2026-01-05", 100.0)
    assert mfe == pytest.approx(0.30)
    assert mae == pytest.approx(-0.12)


def test_excursions_none_when_no_series_or_window():
    assert mp.excursions(None, "2026-01-01", "2026-01-05", 100.0) == (None, None)
    # ventana sin barras (todas anteriores a la compra)
    series = [("2025-12-01", 105.0, 95.0)]
    assert mp.excursions(series, "2026-01-01", "2026-01-05", 100.0) == (None, None)


def test_build_metrics_round_trip_mae_mfe():
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", comm=0, slip=0)
    _order(con, 2, "AAA", "SELL", 118.0, 10, "2026-01-05 10:00:00", comm=0, slip=0)
    _hist_ohlc(con, "AAA", [("2026-01-01", 104.0, 99.0, 100.0),
                            ("2026-01-02", 108.0, 90.0, 105.0),   # Low 90 → MAE -10%
                            ("2026-01-03", 125.0, 110.0, 120.0),  # High 125 → MFE +25%
                            ("2026-01-05", 120.0, 115.0, 118.0)])
    r = mp.build_metrics(con, 1)["realized"]
    rt = r["round_trips"][0]
    assert rt["mae"] == pytest.approx(-0.10)
    assert rt["mfe"] == pytest.approx(0.25)
    exc = r["excursion"]
    assert exc["n"] == 1
    assert exc["median_mae"] == pytest.approx(-0.10)
    assert exc["median_mfe"] == pytest.approx(0.25)
    assert exc["worst_mae"] == pytest.approx(-0.10)
    assert exc["best_mfe"] == pytest.approx(0.25)


# ── fricción (V1) ─────────────────────────────────────────────────────────────
def test_friction_panel_sums_all_orders():
    con = _make_db()
    # Round-trip cerrado (BUY+SELL) + una compra de posición abierta (sin SELL).
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", comm=2.0, slip=1.0)
    _order(con, 2, "AAA", "SELL", 120.0, 10, "2026-01-05 10:00:00", comm=2.0, slip=1.0)
    _order(con, 3, "BBB", "BUY", 50.0, 10, "2026-01-03 10:00:00", comm=5.0, slip=2.0)  # abierta
    fr = mp.build_metrics(con, 1)["friction"]
    # comisión total = 2+2+5 = 9 ; slippage = 1+1+2 = 4 ; fricción = 13
    assert fr["commission"] == pytest.approx(9.0)
    assert fr["slippage"] == pytest.approx(4.0)
    assert fr["friction"] == pytest.approx(13.0)
    assert fr["n_orders"] == 3
    # P/L bruto del round-trip cerrado = (120-100)*10 = 200 ; costos round-trip = 6
    # gross = net(194) + costos(6) = 200 ; pct = 13/200
    assert fr["gross_pnl"] == pytest.approx(200.0)
    assert fr["pct_of_gross"] == pytest.approx(13.0 / 200.0)


def test_friction_pct_none_when_gross_not_positive():
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", comm=1.0, slip=0.5)
    _order(con, 2, "AAA", "SELL", 90.0, 10, "2026-01-05 10:00:00", comm=1.0, slip=0.5)
    fr = mp.build_metrics(con, 1)["friction"]
    assert fr["pct_of_gross"] is None  # bruto = -100 < 0


# ── benchmark vs SPY (V1) ─────────────────────────────────────────────────────
def _snap(con, when, equity):
    con.execute(
        "CREATE TABLE IF NOT EXISTS paper_equity_snapshots "
        "(id INTEGER PRIMARY KEY, account_id INT, snapshot_at TEXT, cash REAL, "
        "positions_value REAL, total_equity REAL, portfolio_sigma REAL)"
    )
    con.execute(
        "INSERT INTO paper_equity_snapshots "
        "(account_id, snapshot_at, cash, positions_value, total_equity, portfolio_sigma) "
        "VALUES (1, ?, 0, 0, ?, NULL)",
        (when, equity),
    )


def test_benchmark_panel_vs_spy():
    con = _make_db()
    _snap(con, "2026-01-01 16:00:00", 50000.0)
    _snap(con, "2026-01-31 16:00:00", 52500.0)   # cuenta +5%
    _hist(con, "SPY", [("2026-01-01", 400.0), ("2026-01-15", 404.0), ("2026-01-31", 408.0)])
    bm = mp.build_metrics(con, 1)["benchmark"]
    assert bm["available"] is True
    assert bm["account_return"] == pytest.approx(0.05)
    assert bm["spy_return"] == pytest.approx(0.02)         # 408/400 - 1
    assert bm["vs_spy"] == pytest.approx(0.03)             # alpha del período
    assert bm["start_day"] == "2026-01-01" and bm["end_day"] == "2026-01-31"


def test_benchmark_unavailable_without_snapshots_table():
    con = _make_db()  # _make_db no crea paper_equity_snapshots
    bm = mp.build_metrics(con, 1)["benchmark"]
    assert bm["available"] is False
    assert bm["vs_spy"] is None


def test_benchmark_unavailable_without_spy_cache():
    con = _make_db()
    _snap(con, "2026-01-01 16:00:00", 50000.0)
    _snap(con, "2026-01-31 16:00:00", 52500.0)
    bm = mp.build_metrics(con, 1)["benchmark"]   # sin cache de SPY
    assert bm["available"] is False
    assert bm["account_return"] == pytest.approx(0.05)   # el retorno propio igual se reporta
    assert bm["spy_return"] is None


# ── concentración del book (V2) ───────────────────────────────────────────────
def _company_info(con, ticker, sector):
    con.execute(
        "CREATE TABLE IF NOT EXISTS company_info_cache (id INTEGER PRIMARY KEY, "
        "ticker TEXT, name TEXT, sector TEXT, industry TEXT, fetched_at TEXT)"
    )
    con.execute(
        "INSERT INTO company_info_cache (ticker,sector,fetched_at) VALUES (?,?,?)",
        (ticker, sector, "2026-06-17"),
    )


def test_cached_sector_failopen_without_table():
    con = _make_db()  # _make_db no crea company_info_cache
    assert mp.cached_sector(con, "MU") is None


def test_cached_sector_reads_and_ignores_na():
    con = _make_db()
    _company_info(con, "MU", "Technology")
    _company_info(con, "ZZZ", "N/A")
    assert mp.cached_sector(con, "MU") == "Technology"
    assert mp.cached_sector(con, "ZZZ") is None       # "N/A" → None
    assert mp.cached_sector(con, "NOPE") is None


def test_concentration_panel_weights_and_pnl():
    con = _make_db()
    con.execute("INSERT INTO paper_positions VALUES (1,1,'MU',100,50.0)")
    con.execute("INSERT INTO paper_positions VALUES (2,1,'AAPL',50,100.0)")
    _hist(con, "MU", [("2026-06-16", 55.0), ("2026-06-17", 60.0)])     # mark 60 → mv 6000, upnl +1000
    _hist(con, "AAPL", [("2026-06-16", 110.0), ("2026-06-17", 90.0)])  # mark 90 → mv 4500, upnl -500
    c = mp.build_metrics(con, 1)["concentration"]
    assert c["n"] == 2
    assert c["total_value"] == pytest.approx(10500.0)
    assert c["top_ticker"] == "MU"
    assert c["top_weight"] == pytest.approx(6000.0 / 10500.0)
    assert c["total_unrealized_pnl"] == pytest.approx(500.0)   # +1000 -500
    assert c["best_ticker"] == "MU" and c["worst_ticker"] == "AAPL"
    assert c["pnl_ex_best"] == pytest.approx(-500.0)           # sin MU
    assert c["pnl_ex_worst"] == pytest.approx(1000.0)          # sin AAPL


def test_concentration_panel_sector_from_cache():
    con = _make_db()
    _company_info(con, "MU", "Technology")
    _company_info(con, "AAPL", "Technology")
    con.execute("INSERT INTO paper_positions VALUES (1,1,'MU',100,50.0)")
    con.execute("INSERT INTO paper_positions VALUES (2,1,'AAPL',50,100.0)")
    _hist(con, "MU", [("2026-06-16", 55.0), ("2026-06-17", 60.0)])
    _hist(con, "AAPL", [("2026-06-16", 110.0), ("2026-06-17", 120.0)])
    c = mp.build_metrics(con, 1)["concentration"]
    assert c["sectors"][0]["sector"] == "Technology"
    assert c["sectors"][0]["weight"] == pytest.approx(1.0)


def test_concentration_panel_empty_account():
    con = _make_db()
    c = mp.build_metrics(con, 1)["concentration"]
    assert c["n"] == 0 and c["weights"] == [] and c["top_ticker"] is None


def test_sell_timing_panel_inverted_and_by_kind():
    # MET2: venta buena = precio NO sube después (fwd5 ≤ 0). Signo invertido vs
    # compras. AAA (signal_sell) baja → buena; BBB (atr_stop) sube → regret.
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", comm=0, slip=0)
    _order(con, 2, "AAA", "SELL", 100.0, 10, "2026-01-02 10:00:00", comm=0, slip=0,
           reason="analyze SELL (0.40)", score=0.40)
    _order(con, 3, "BBB", "BUY", 50.0, 10, "2026-01-01 10:00:00", comm=0, slip=0)
    _order(con, 4, "BBB", "SELL", 50.0, 10, "2026-01-02 10:00:00", comm=0, slip=0,
           reason="atr_stop @ 50 ≤ 51", score=0.20)
    _hist(con, "AAA", [("2026-01-02", 100.0), ("2026-01-05", 99.0), ("2026-01-06", 98.0),
                       ("2026-01-07", 97.0), ("2026-01-08", 96.0), ("2026-01-09", 95.0),
                       ("2026-01-12", 94.0)])
    _hist(con, "BBB", [("2026-01-02", 50.0), ("2026-01-05", 51.0), ("2026-01-06", 52.0),
                       ("2026-01-07", 53.0), ("2026-01-08", 54.0), ("2026-01-09", 55.0),
                       ("2026-01-12", 56.0)])
    st = mp.build_metrics(con, 1)["sell_timing"]
    assert st["n5"] == 2
    assert st["good5"] == 1                       # AAA bajó (buena), BBB subió (mala)
    assert st["good5_pct"] == pytest.approx(0.5)
    assert st["by_exit_kind"]["signal_sell"]["good_pct"] == pytest.approx(1.0)
    assert st["by_exit_kind"]["atr_stop"]["good_pct"] == pytest.approx(0.0)
    assert st["by_exit_kind"]["signal_sell"]["mean_fwd5"] < 0   # caída evitada
    assert st["by_exit_kind"]["atr_stop"]["mean_fwd5"] > 0      # regret
    assert st["top_avoided"][0]["ticker"] == "AAA"
    assert st["top_regret"][0]["ticker"] == "BBB"


def test_churn_detection():
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00")
    _order(con, 2, "AAA", "SELL", 105.0, 10, "2026-01-05 10:00:00")
    _order(con, 3, "AAA", "BUY", 104.0, 10, "2026-01-06 10:00:00")  # re-buy gap 1d
    m = mp.build_metrics(con, 1)
    assert m["churn"]["n_le7d"] == 1
    assert m["churn"]["events"][0]["gap_days"] == 1


def test_expired_buys_counted():
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", status="expired")
    _order(con, 2, "AAA", "BUY", 100.0, 10, "2026-01-02 10:00:00", status="filled")
    m = mp.build_metrics(con, 1)
    assert m["expired_buys"]["n"] == 1
    assert m["expired_buys"]["by_ticker"]["AAA"] == 1


def test_open_positions_mtm():
    con = _make_db()
    con.execute("INSERT INTO paper_positions VALUES (1,1,'AAA',10,100.0)")
    _hist(con, "AAA", [("2026-06-16", 100.0), ("2026-06-17", 110.0)])
    m = mp.build_metrics(con, 1)
    pos = m["open_positions"][0]
    assert pos["ticker"] == "AAA"
    assert pos["mark"] == 110.0
    assert pos["mtm_pct"] == pytest.approx(0.10, abs=1e-9)


def test_timeline_cumulative_and_winrate():
    con = _make_db()
    _order(con, 1, "AAA", "BUY", 100.0, 10, "2026-01-01 10:00:00", comm=0, slip=0)
    _order(con, 2, "AAA", "SELL", 110.0, 10, "2026-01-05 10:00:00", comm=0, slip=0)
    _order(con, 3, "BBB", "BUY", 100.0, 10, "2026-01-02 10:00:00", comm=0, slip=0)
    _order(con, 4, "BBB", "SELL", 90.0, 10, "2026-01-06 10:00:00", comm=0, slip=0)
    m = mp.build_metrics(con, 1)
    tl = m["timeline"]
    assert len(tl) == 2
    assert tl[-1]["cum_pnl"] == pytest.approx(0.0, abs=1e-6)  # +100 -100
    assert tl[0]["rolling_win_rate"] == 1.0
    assert tl[-1]["rolling_win_rate"] == 0.5


def test_empty_account_safe():
    con = _make_db()
    m = mp.build_metrics(con, 1)
    assert m["realized"]["n_round_trips"] == 0
    assert m["timeline"] == []
    assert m["timing"]["n5"] == 0


def test_commit_markers_filters_infra(monkeypatch):
    sample = (
        "2026-06-10|T6.4: score-hysteresis en exits\n"
        "2026-06-16|perf(data): batch yfinance downloads\n"
        "2026-06-12|fix(db): WAL + busy_timeout\n"
        "2026-06-10|T6.5: anti-churn v2 — Gate 5b\n"
        "2026-06-09|docs(catalyst): informe\n"
    )

    class _R:
        returncode = 0
        stdout = sample

    monkeypatch.setattr(mp.subprocess, "run", lambda *a, **k: _R())
    out = mp.commit_markers(".")
    subjects = [m["subject"] for m in out]
    assert any("T6.4" in s for s in subjects)
    assert any("anti-churn" in s for s in subjects)
    assert not any(s.startswith("perf(") for s in subjects)
    assert not any(s.startswith("fix(db") for s in subjects)
    assert not any(s.startswith("docs(") for s in subjects)


def test_commit_markers_git_failure_returns_empty(monkeypatch):
    def _boom(*a, **k):
        raise OSError("git not found")

    monkeypatch.setattr(mp.subprocess, "run", _boom)
    assert mp.commit_markers(".") == []
