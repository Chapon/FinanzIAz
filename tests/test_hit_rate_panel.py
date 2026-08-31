"""
Tests para scripts/dashboard_data — hit-rate tracking real (T6.3, ex-T07).

Cubre:
  _reason_kind:
    - analyze BUY / analyze SELL (0.31) → "signal"
    - atr_stop / atr_trail / vol_trim → su familia; None/desconocido → "other"

  _score_bucket:
    - ancho 0.1 con clamp en el tope; None → None

  _hit_for:
    - BUY hit ⇔ fwd5 > 0; SELL hit ⇔ fwd5 <= 0; None propaga

  _hit_rate_panel:
    - score sentinel (1.0 en exits atr_*) excluido de by_bucket y de avg_score
    - by_bucket agrupa por (side, bucket) con calibration_gap = p_up − avg_score
    - by_reason separa signal / atr_stop / atr_trail
    - realized_pct por SELL vía FIFO (match por ticker+filled_at normalizado)
    - sell_reliability filtra SELLs señal en [0.20, 0.45]
    - by_regime usa _regime_for_dates (monkeypatched); sin proxy → [] + note
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

import scripts.dashboard_data as dashboard_data
from scripts.baseline_metrics import load_fills
from scripts.dashboard_data import (
    _hit_for,
    _hit_group_stats,
    _hit_rate_panel,
    _reason_kind,
    _score_bucket,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE historical_data_cache ("
        "id INTEGER PRIMARY KEY, ticker TEXT, period TEXT, interval TEXT, "
        "data_json TEXT, fetched_at TEXT)"
    )
    con.execute(
        "CREATE TABLE paper_orders ("
        "id INTEGER PRIMARY KEY, account_id INTEGER, ticker TEXT, side TEXT, "
        "status TEXT, fill_price REAL, fill_shares REAL, signal_score REAL, "
        "filled_at TEXT, reason TEXT, commission_paid REAL, slippage_cost REAL)"
    )
    return con


def _bdays(start: date, n: int) -> list[str]:
    """n días hábiles consecutivos desde start (inclusive)."""
    out: list[str] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _seed_series(
    con: sqlite3.Connection, ticker: str, closes: list[float], start: date = date(2026, 1, 5)
) -> list[str]:
    """Carga una serie 1d en cache (orient=split). Devuelve las fechas."""
    dates = _bdays(start, len(closes))
    payload = {
        "columns": ["Open", "Close"],
        "index": dates,
        "data": [[c, c] for c in closes],
    }
    con.execute(
        "INSERT INTO historical_data_cache (ticker, period, interval, data_json, fetched_at) "
        "VALUES (?, '1y', '1d', ?, '2026-06-01T00:00:00')",
        (ticker, json.dumps(payload)),
    )
    return dates


def _order(
    con: sqlite3.Connection,
    *,
    ticker: str,
    side: str,
    price: float,
    shares: float,
    filled_at: str,
    reason: str,
    score: float | None,
    account_id: int = 1,
) -> None:
    con.execute(
        "INSERT INTO paper_orders (account_id, ticker, side, status, fill_price, "
        "fill_shares, signal_score, filled_at, reason, commission_paid, slippage_cost) "
        "VALUES (?, ?, ?, 'filled', ?, ?, ?, ?, ?, 0, 0)",
        (account_id, ticker, side, price, shares, score, filled_at, reason),
    )


def _panel(con: sqlite3.Connection, account_id: int = 1) -> dict:
    fills = load_fills(con, account_id)
    return _hit_rate_panel(con, account_id, fills)


# ── _reason_kind ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("analyze BUY", "signal"),
        ("analyze SELL (0.31)", "signal"),
        ("atr_stop @ 121.99 ≤ 124.46 (entry 131.12 − 2.0×ATR 3.33)", "atr_stop"),
        ("atr_trail @ 70.81 ≤ 71.21 (peak 74.14 − 2.0×ATR 1.46)", "atr_trail"),
        ("vol_trim σ 0.32 > target 0.25", "vol_trim"),
        (None, "other"),
        ("", "other"),
        ("manual override", "other"),
    ],
)
def test_reason_kind(reason, expected):
    assert _reason_kind(reason) == expected


# ── _score_bucket ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.0, "0.0-0.1"),
        (0.31, "0.3-0.4"),
        (0.4, "0.4-0.5"),
        (0.999, "0.9-1.0"),
        (1.0, "0.9-1.0"),  # clamp al tope
        (None, None),
    ],
)
def test_score_bucket(score, expected):
    assert _score_bucket(score) == expected


# ── _hit_for ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "side,fwd5,expected",
    [
        ("BUY", 0.02, True),
        ("BUY", -0.02, False),
        ("BUY", 0.0, False),
        ("SELL", -0.02, True),
        ("SELL", 0.0, True),
        ("SELL", 0.02, False),
        ("BUY", None, None),
        ("SELL", None, None),
    ],
)
def test_hit_for(side, fwd5, expected):
    assert _hit_for(side, fwd5) is expected


# ── _hit_group_stats ─────────────────────────────────────────────────────────


def test_group_stats_empty():
    s = _hit_group_stats([])
    assert s["n"] == 0
    assert s["hit_rate_fwd5"] is None
    assert s["median_fwd5"] is None
    assert s["avg_score"] is None
    assert s["median_realized_pct"] is None


def test_group_stats_mixed_none():
    orders = [
        {"fwd5": 0.10, "fwd20": None, "hit": True, "signal_score": 0.3, "realized_pct": 0.05},
        {"fwd5": -0.10, "fwd20": None, "hit": False, "signal_score": 0.4, "realized_pct": None},
        {"fwd5": None, "fwd20": None, "hit": None, "signal_score": None, "realized_pct": None},
    ]
    s = _hit_group_stats(orders)
    assert s["n"] == 3
    assert s["n_fwd5"] == 2
    assert s["hit_rate_fwd5"] == pytest.approx(0.5)
    assert s["p_up_fwd5"] == pytest.approx(0.5)
    assert s["median_fwd5"] == pytest.approx(0.0)
    assert s["avg_score"] == pytest.approx(0.35)
    assert s["median_realized_pct"] == pytest.approx(0.05)


# ── _hit_rate_panel ──────────────────────────────────────────────────────────


def test_panel_buckets_and_sentinel_excluded(monkeypatch):
    """SELL señal con score entra al bucket; SELL atr con score 1.0 no."""
    monkeypatch.setattr(dashboard_data, "_regime_for_dates", lambda con, d: None)
    con = _make_db()
    # Serie plana 100 → fwd5 = 0 en todas partes (SELL hit, BUY no-hit)
    dates = _seed_series(con, "AAA", [100.0] * 30)
    _order(
        con,
        ticker="AAA",
        side="BUY",
        price=100,
        shares=10,
        filled_at=f"{dates[2]} 10:00:00",
        reason="analyze BUY",
        score=0.65,
    )
    _order(
        con,
        ticker="AAA",
        side="SELL",
        price=100,
        shares=5,
        filled_at=f"{dates[5]} 10:00:00",
        reason="analyze SELL (0.31)",
        score=0.31,
    )
    _order(
        con,
        ticker="AAA",
        side="SELL",
        price=100,
        shares=5,
        filled_at=f"{dates[8]} 10:00:00",
        reason="atr_trail @ 99 ≤ 100 (peak 105 − 2.0×ATR 3)",
        score=1.0,
    )

    panel = _panel(con)
    buckets = {(b["side"], b["bucket"]) for b in panel["by_bucket"]}
    assert ("BUY", "0.6-0.7") in buckets
    assert ("SELL", "0.3-0.4") in buckets
    # el sentinel 1.0 del atr_trail NO genera bucket 0.9-1.0
    assert ("SELL", "0.9-1.0") not in buckets

    kinds = {(r["side"], r["reason_kind"]): r for r in panel["by_reason"]}
    assert kinds[("SELL", "atr_trail")]["n"] == 1
    # avg_score del grupo atr es None (sentinel anulado)
    assert kinds[("SELL", "atr_trail")]["avg_score"] is None
    assert kinds[("SELL", "signal")]["n"] == 1

    # serie plana: SELL hit (fwd5 = 0 ≤ 0), BUY no-hit
    assert kinds[("SELL", "signal")]["hit_rate_fwd5"] == 1.0
    assert kinds[("BUY", "signal")]["hit_rate_fwd5"] == 0.0

    # sin proxy de mercado → by_regime vacío + note
    assert panel["by_regime"] == []
    assert any("by_regime" in n for n in panel["notes"])


def test_panel_fwd_and_calibration_gap(monkeypatch):
    """Serie creciente: SELLs venden algo que sube → gap > 0."""
    monkeypatch.setattr(dashboard_data, "_regime_for_dates", lambda con, d: None)
    con = _make_db()
    closes = [100.0 * (1.02**i) for i in range(30)]  # +2% por barra
    dates = _seed_series(con, "BBB", closes)
    _order(
        con,
        ticker="BBB",
        side="BUY",
        price=closes[1],
        shares=10,
        filled_at=f"{dates[1]} 10:00:00",
        reason="analyze BUY",
        score=0.70,
    )
    _order(
        con,
        ticker="BBB",
        side="SELL",
        price=closes[6],
        shares=10,
        filled_at=f"{dates[6]} 10:00:00",
        reason="analyze SELL (0.30)",
        score=0.30,
    )

    panel = _panel(con)
    sell_bucket = next(b for b in panel["by_bucket"] if b["side"] == "SELL")
    # fwd5 = 1.02^5 − 1
    assert sell_bucket["median_fwd5"] == pytest.approx(1.02**5 - 1, rel=1e-9)
    # precio subió tras el SELL: p_up = 1.0, score 0.30 → gap = +0.70
    assert sell_bucket["p_up_fwd5"] == 1.0
    assert sell_bucket["calibration_gap"] == pytest.approx(0.70)
    assert sell_bucket["hit_rate_fwd5"] == 0.0

    buy_bucket = next(b for b in panel["by_bucket"] if b["side"] == "BUY")
    assert buy_bucket["hit_rate_fwd5"] == 1.0


def test_panel_realized_pct_fifo(monkeypatch):
    """SELL matchea su round-trip FIFO: realized = proceeds/cost − 1."""
    monkeypatch.setattr(dashboard_data, "_regime_for_dates", lambda con, d: None)
    con = _make_db()
    dates = _seed_series(con, "CCC", [100.0] * 30)
    _order(
        con,
        ticker="CCC",
        side="BUY",
        price=100.0,
        shares=10,
        filled_at=f"{dates[1]} 10:00:00",
        reason="analyze BUY",
        score=0.70,
    )
    _order(
        con,
        ticker="CCC",
        side="SELL",
        price=110.0,
        shares=10,
        filled_at=f"{dates[10]} 10:00:00",
        reason="analyze SELL (0.30)",
        score=0.30,
    )

    panel = _panel(con)
    kinds = {(r["side"], r["reason_kind"]): r for r in panel["by_reason"]}
    assert kinds[("SELL", "signal")]["median_realized_pct"] == pytest.approx(0.10)
    # los BUY no llevan realized
    assert kinds[("BUY", "signal")]["median_realized_pct"] is None


def test_panel_sell_reliability_range(monkeypatch):
    """Solo SELLs señal con score en [0.20, 0.45] entran al resumen."""
    monkeypatch.setattr(dashboard_data, "_regime_for_dates", lambda con, d: None)
    con = _make_db()
    dates = _seed_series(con, "DDD", [100.0] * 40)
    in_range = [0.25, 0.40]
    out_of_range = [0.47, 0.10]
    for i, sc in enumerate(in_range + out_of_range):
        _order(
            con,
            ticker="DDD",
            side="SELL",
            price=100,
            shares=1,
            filled_at=f"{dates[2 + i]} 10:00:00",
            reason=f"analyze SELL ({sc:.2f})",
            score=sc,
        )

    panel = _panel(con)
    rel = panel["sell_reliability"]
    assert rel is not None
    assert rel["n"] == 2
    assert rel["avg_score"] == pytest.approx(0.325)
    assert rel["range"] == [0.20, 0.45]


def test_panel_by_regime_groups(monkeypatch):
    """Con un mapa fecha→régimen inyectado, agrupa por (regime, side)."""
    con = _make_db()
    dates = _seed_series(con, "EEE", [100.0] * 30)
    d_bull, d_bear = dates[2], dates[10]
    _order(
        con,
        ticker="EEE",
        side="BUY",
        price=100,
        shares=1,
        filled_at=f"{d_bull} 10:00:00",
        reason="analyze BUY",
        score=0.7,
    )
    _order(
        con,
        ticker="EEE",
        side="SELL",
        price=100,
        shares=1,
        filled_at=f"{d_bear} 10:00:00",
        reason="analyze SELL (0.30)",
        score=0.3,
    )
    monkeypatch.setattr(
        dashboard_data,
        "_regime_for_dates",
        lambda con, ds: {d_bull: "bull_quiet", d_bear: "bear"},
    )

    panel = _panel(con)
    groups = {(g["regime"], g["side"]): g["n"] for g in panel["by_regime"]}
    assert groups == {("bull_quiet", "BUY"): 1, ("bear", "SELL"): 1}
    assert not any("by_regime" in n for n in panel["notes"])


def test_panel_other_account_excluded(monkeypatch):
    monkeypatch.setattr(dashboard_data, "_regime_for_dates", lambda con, d: None)
    con = _make_db()
    dates = _seed_series(con, "FFF", [100.0] * 30)
    _order(
        con,
        ticker="FFF",
        side="BUY",
        price=100,
        shares=1,
        filled_at=f"{dates[2]} 10:00:00",
        reason="analyze BUY",
        score=0.7,
        account_id=2,
    )
    panel = _panel(con, account_id=1)
    assert all(r["n"] == 0 for r in panel["by_reason"]) or panel["by_reason"] == []
    assert panel["sell_reliability"] is None


def test_panel_pending_fwd_noted(monkeypatch):
    """Fill muy reciente sin barras futuras → fwd5 None + note."""
    monkeypatch.setattr(dashboard_data, "_regime_for_dates", lambda con, d: None)
    con = _make_db()
    dates = _seed_series(con, "GGG", [100.0] * 10)
    _order(
        con,
        ticker="GGG",
        side="SELL",
        price=100,
        shares=1,
        filled_at=f"{dates[-1]} 10:00:00",
        reason="analyze SELL (0.30)",
        score=0.3,
    )
    panel = _panel(con)
    assert any("sin fwd5" in n for n in panel["notes"])
    kinds = {(r["side"], r["reason_kind"]): r for r in panel["by_reason"]}
    assert kinds[("SELL", "signal")]["n_fwd5"] == 0
    assert kinds[("SELL", "signal")]["hit_rate_fwd5"] is None
