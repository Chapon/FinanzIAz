"""
Tests para scripts/dashboard_data — panel opportunity cost post-SELL (T6.2).

Cubre:
  _load_close_series:
    - parsea data_json orient="split" plano
    - columnas MultiIndex serializadas como listas
    - elige la fila con fetched_at más reciente
    - filtra closes nulos/<=0; None si no hay fila o JSON roto

  _fwd_return_from_series:
    - retorno close-to-close exacto a 5 días hábiles
    - fecha en finde → entra el siguiente día hábil
    - None si faltan barras futuras (SELL reciente)

  _post_sell_panel:
    - per_sell con fwd5/fwd20 correctos, asc por filled_at
    - solo SELL filled de la cuenta pedida
    - monthly agrupa por YYYY-MM con mediana y pct_positive
    - summary global con mean/median
    - ticker sin cache → fwds None pero el sell aparece igual
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

from scripts.dashboard_data import (
    _fwd_return_from_series,
    _load_close_series,
    _post_sell_panel,
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
        "status TEXT, fill_price REAL, filled_at TEXT, reason TEXT, "
        "signal_score REAL)"
    )
    return con


def _busdays(start: date, n: int) -> list[date]:
    """n días hábiles (lun-vie) empezando en o después de start."""
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _split_json(dates: list[date], closes: list[float], multiindex: bool = False) -> str:
    cols = ["Close", "High", "Low", "Open", "Volume"]
    if multiindex:
        cols = [[c, "TEST"] for c in cols]
    return json.dumps(
        {
            "columns": cols,
            "index": [f"{d.isoformat()}T00:00:00.000" for d in dates],
            "data": [[c, c * 1.01, c * 0.99, c, 1000] for c in closes],
        }
    )


def _insert_cache(
    con, ticker, dates, closes, fetched_at="2026-06-09 00:00:00", interval="1d", multiindex=False
):
    con.execute(
        "INSERT INTO historical_data_cache (ticker, period, interval, data_json, fetched_at) "
        "VALUES (?, '1y', ?, ?, ?)",
        (ticker, interval, _split_json(dates, closes, multiindex), fetched_at),
    )


def _insert_sell(
    con,
    account_id,
    ticker,
    filled_at,
    fill_price=100.0,
    reason="signal",
    score=0.30,
    side="SELL",
    status="filled",
):
    con.execute(
        "INSERT INTO paper_orders (account_id, ticker, side, status, fill_price, "
        "filled_at, reason, signal_score) VALUES (?,?,?,?,?,?,?,?)",
        (account_id, ticker, side, status, fill_price, filled_at, reason, score),
    )


# Serie estándar: 30 días hábiles desde el lunes 2026-04-06, closes 100,101,...
START = date(2026, 4, 6)  # lunes
DATES = _busdays(START, 30)
CLOSES = [100.0 + i for i in range(30)]


# ── _load_close_series ───────────────────────────────────────────────────────


class TestLoadCloseSeries:
    def test_parses_flat_columns(self):
        con = _make_db()
        _insert_cache(con, "AAA", DATES, CLOSES)
        pairs = _load_close_series(con, "AAA")
        assert pairs is not None and len(pairs) == 30
        assert pairs[0] == (DATES[0].isoformat(), 100.0)
        assert pairs[-1] == (DATES[-1].isoformat(), 129.0)

    def test_parses_multiindex_columns(self):
        con = _make_db()
        _insert_cache(con, "BBB", DATES, CLOSES, multiindex=True)
        pairs = _load_close_series(con, "BBB")
        assert pairs is not None and pairs[5][1] == 105.0

    def test_picks_most_recent_fetched_at(self):
        con = _make_db()
        _insert_cache(con, "CCC", DATES[:10], CLOSES[:10], fetched_at="2026-05-01 00:00:00")
        _insert_cache(con, "CCC", DATES, CLOSES, fetched_at="2026-06-09 00:00:00")
        pairs = _load_close_series(con, "CCC")
        assert len(pairs) == 30

    def test_filters_bad_closes(self):
        con = _make_db()
        closes = CLOSES.copy()
        raw = json.loads(_split_json(DATES, closes))
        raw["data"][3][0] = None
        raw["data"][4][0] = 0.0
        con.execute(
            "INSERT INTO historical_data_cache (ticker, period, interval, data_json, fetched_at) "
            "VALUES ('DDD','1y','1d',?, '2026-06-09 00:00:00')",
            (json.dumps(raw),),
        )
        pairs = _load_close_series(con, "DDD")
        assert len(pairs) == 28

    def test_no_row_returns_none(self):
        con = _make_db()
        assert _load_close_series(con, "NOPE") is None

    def test_broken_json_returns_none(self):
        con = _make_db()
        con.execute(
            "INSERT INTO historical_data_cache (ticker, period, interval, data_json, fetched_at) "
            "VALUES ('EEE','1y','1d','{not json', '2026-06-09 00:00:00')"
        )
        assert _load_close_series(con, "EEE") is None

    def test_ignores_non_daily_interval(self):
        con = _make_db()
        _insert_cache(con, "FFF", DATES, CLOSES, interval="1h")
        assert _load_close_series(con, "FFF") is None


# ── _fwd_return_from_series ──────────────────────────────────────────────────


class TestFwdReturn:
    PAIRS = [(d.isoformat(), c) for d, c in zip(DATES, CLOSES, strict=True)]

    def test_exact_5d(self):
        # base = close del día 0 (100), exit = close del día 5 (105)
        r = _fwd_return_from_series(self.PAIRS, DATES[0].isoformat(), 5)
        assert r == pytest.approx(105.0 / 100.0 - 1.0)

    def test_weekend_enters_next_busday(self):
        # sábado entre DATES[4] (vie) y DATES[5] (lun) → base = lunes (105)
        saturday = (DATES[4] + timedelta(days=1)).isoformat()
        r = _fwd_return_from_series(self.PAIRS, saturday, 5)
        assert r == pytest.approx(110.0 / 105.0 - 1.0)

    def test_insufficient_future_bars(self):
        assert _fwd_return_from_series(self.PAIRS, DATES[-3].isoformat(), 5) is None

    def test_date_after_series(self):
        assert _fwd_return_from_series(self.PAIRS, "2027-01-01", 5) is None

    def test_empty_series(self):
        assert _fwd_return_from_series([], "2026-04-06", 5) is None


# ── _post_sell_panel ─────────────────────────────────────────────────────────


class TestPostSellPanel:
    def _setup(self):
        con = _make_db()
        _insert_cache(con, "AAA", DATES, CLOSES)
        return con

    def test_per_sell_fwd_values(self):
        con = self._setup()
        d0 = DATES[0].isoformat()
        _insert_sell(con, 1, "AAA", f"{d0} 15:30:00", fill_price=100.0)
        panel = _post_sell_panel(con, 1)
        assert panel["summary"]["n_sells"] == 1
        s = panel["per_sell"][0]
        assert s["ticker"] == "AAA"
        assert s["fwd5"] == pytest.approx(0.05)
        assert s["fwd20"] == pytest.approx(0.20)

    def test_only_filled_sells_of_account(self):
        con = self._setup()
        d0 = DATES[0].isoformat()
        _insert_sell(con, 1, "AAA", f"{d0} 15:30:00")
        _insert_sell(con, 1, "AAA", f"{d0} 15:30:00", side="BUY")  # no
        _insert_sell(con, 1, "AAA", f"{d0} 15:30:00", status="expired")  # no
        _insert_sell(con, 2, "AAA", f"{d0} 15:30:00")  # otra cuenta
        panel = _post_sell_panel(con, 1)
        assert panel["summary"]["n_sells"] == 1

    def test_recent_sell_has_none_fwd(self):
        con = self._setup()
        _insert_sell(con, 1, "AAA", f"{DATES[-1].isoformat()} 15:30:00")
        panel = _post_sell_panel(con, 1)
        s = panel["per_sell"][0]
        assert s["fwd5"] is None and s["fwd20"] is None
        assert panel["summary"]["n_fwd5"] == 0
        assert panel["summary"]["median_fwd5"] is None

    def test_ticker_without_cache(self):
        con = self._setup()
        _insert_sell(con, 1, "ZZZ", f"{DATES[0].isoformat()} 15:30:00")
        panel = _post_sell_panel(con, 1)
        assert panel["summary"]["n_sells"] == 1
        assert panel["per_sell"][0]["fwd5"] is None

    def test_monthly_grouping_and_summary(self):
        con = self._setup()
        # 2 sells en abril (fwd5 = +5/100, +5/105 → ambos positivos),
        # 1 sell en mayo (DATES[20] = 2026-05-04, fwd5 = 125/120-1)
        _insert_sell(con, 1, "AAA", f"{DATES[0].isoformat()} 15:30:00")
        _insert_sell(con, 1, "AAA", f"{DATES[5].isoformat()} 15:30:00")
        _insert_sell(con, 1, "AAA", f"{DATES[20].isoformat()} 15:30:00")
        panel = _post_sell_panel(con, 1)

        months = [m["month"] for m in panel["monthly"]]
        assert months == ["2026-04", "2026-05"]
        abril = panel["monthly"][0]
        assert abril["n_sells"] == 2 and abril["n_fwd5"] == 2
        assert abril["pct_positive_fwd5"] == 1.0
        assert abril["median_fwd5"] == pytest.approx((0.05 + (110.0 / 105.0 - 1.0)) / 2.0)
        mayo = panel["monthly"][1]
        assert mayo["n_sells"] == 1
        assert mayo["median_fwd5"] == pytest.approx(125.0 / 120.0 - 1.0)

        summ = panel["summary"]
        assert summ["n_sells"] == 3 and summ["n_fwd5"] == 3
        assert summ["pct_positive_fwd5"] == 1.0
        assert summ["mean_fwd5"] == pytest.approx(
            (0.05 + (110.0 / 105.0 - 1.0) + (125.0 / 120.0 - 1.0)) / 3.0
        )

    def test_ordered_ascending(self):
        con = self._setup()
        _insert_sell(con, 1, "AAA", f"{DATES[5].isoformat()} 15:30:00")
        _insert_sell(con, 1, "AAA", f"{DATES[0].isoformat()} 15:30:00")
        panel = _post_sell_panel(con, 1)
        fills = [s["filled_at"] for s in panel["per_sell"]]
        assert fills == sorted(fills)

    def test_no_sells(self):
        con = self._setup()
        panel = _post_sell_panel(con, 1)
        assert panel["per_sell"] == [] and panel["monthly"] == []
        assert panel["summary"]["n_sells"] == 0
