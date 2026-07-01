"""Sanity de precios fuera de banda (backlog E5).

Cubre el bug KLAC 2026-06-01/05: Yahoo devolvió una cotización con la escala
~10× corrupta (~$1.940 cuando el precio real era ~$194) y ese valor pasó el
filtro y se usó como precio de entrada/salida de un round-trip entero, inflando
el notional, el DD, el ADV y hasta la muestra de salidas ATR.

Tres capas de defensa:
  1. ``data.yahoo_finance`` — guard prospectivo en el fetch en vivo.
  2. ``paper_trading.engine`` — sanity-check antes de fillar (belt-and-braces).
  3. ``scripts.audit_price_contamination`` — barrido retroactivo de la DB viva.
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from data import yahoo_finance as yfm


# ── Helpers de seeding ────────────────────────────────────────────────────────


def _seed_history(ticker: str, closes: list[tuple[str, float]], period: str = "2y") -> None:
    """Escribe un frame diario cacheado con los (fecha, close) dados."""
    from database.models import HistoricalDataCache, session_scope

    idx = pd.to_datetime([d for d, _ in closes])
    df = pd.DataFrame(
        {
            "Open": [c for _, c in closes],
            "High": [c for _, c in closes],
            "Low": [c for _, c in closes],
            "Close": [c for _, c in closes],
            "Volume": [1_000_000.0] * len(closes),
        },
        index=idx,
    )
    with session_scope() as s:
        s.add(
            HistoricalDataCache(
                ticker=ticker.upper(),
                period=period,
                interval="1d",
                data_json=df.to_json(orient="split", date_format="iso"),
            )
        )


# ── Capa 1a — predicado puro ``is_price_out_of_band`` ─────────────────────────


def test_out_of_band_flags_10x():
    assert yfm.is_price_out_of_band(1942.70, 194.0) is True


def test_in_band_is_ok():
    # Un movimiento day-over-day del 20% NO es basura de escala.
    assert yfm.is_price_out_of_band(232.0, 194.0) is False


def test_out_of_band_fail_open_on_missing():
    assert yfm.is_price_out_of_band(None, 194.0) is False
    assert yfm.is_price_out_of_band(1942.70, None) is False
    assert yfm.is_price_out_of_band(1942.70, 0.0) is False
    assert yfm.is_price_out_of_band(-5.0, 194.0) is False


def test_out_of_band_disabled_when_band_zero():
    # band=0 desactiva el guard (fail-open explícito).
    assert yfm.is_price_out_of_band(1942.70, 194.0, band=0.0) is False


def test_out_of_band_respects_custom_band():
    # Con banda del 400%, un desvío del 410% queda fuera pero el 390% no.
    assert yfm.is_price_out_of_band(990.0, 194.0, band=4.0) is True
    assert yfm.is_price_out_of_band(950.0, 194.0, band=4.0) is False


# ── Capa 1b — ``reference_close`` lee el último close cacheado ────────────────


def test_reference_close_returns_last_cached_close():
    _seed_history("KLAC", [("2026-05-28", 250.0), ("2026-05-29", 305.14)])
    assert yfm.reference_close("KLAC") == pytest.approx(305.14)


def test_reference_close_none_without_cache():
    assert yfm.reference_close("NOCACHE") is None


def test_reference_close_ignores_nonpositive():
    _seed_history("ZZZ", [("2026-05-28", 100.0), ("2026-05-29", 0.0)])
    assert yfm.reference_close("ZZZ") == pytest.approx(100.0)


# ── Capa 1c — guard en el fetch en vivo (get_bulk_prices / get_current_price) ──


def _fake_fetch(prices: dict[str, float]):
    def _inner(ticker: str):
        px = prices.get(ticker.upper())
        if px is None:
            return None
        return {"ticker": ticker.upper(), "price": px, "change_pct": None,
                "volume": None, "market_cap": None}
    return _inner


def test_get_bulk_prices_rejects_out_of_band(monkeypatch, caplog):
    _seed_history("KLAC", [("2026-05-29", 194.0)])
    _seed_history("AAPL", [("2026-05-29", 200.0)])
    monkeypatch.setattr(
        yfm, "_fetch_ticker_info", _fake_fetch({"KLAC": 1942.70, "AAPL": 205.0})
    )
    import logging

    with caplog.at_level(logging.WARNING, logger="data.yahoo_finance"):
        out = yfm.get_bulk_prices(["KLAC", "AAPL"])

    # El precio corrupto de KLAC se descarta (miss); AAPL (in-band) pasa.
    assert out["KLAC"] is None
    assert out["AAPL"] is not None and out["AAPL"]["price"] == pytest.approx(205.0)
    assert any("fuera de banda" in r.message for r in caplog.records)


def test_get_bulk_prices_does_not_cache_corrupt_price(monkeypatch):
    _seed_history("KLAC", [("2026-05-29", 194.0)])
    monkeypatch.setattr(yfm, "_fetch_ticker_info", _fake_fetch({"KLAC": 1942.70}))
    yfm.get_bulk_prices(["KLAC"])

    # No se escribió el precio corrupto en la PriceCache.
    from database.models import PriceCache, session_scope

    with session_scope() as s:
        assert s.query(PriceCache).filter(PriceCache.ticker == "KLAC").count() == 0


def test_get_bulk_prices_passes_without_reference(monkeypatch):
    # Sin histórico cacheado → fail-open: no bloqueamos (no podemos juzgar escala).
    monkeypatch.setattr(yfm, "_fetch_ticker_info", _fake_fetch({"NEW": 1942.70}))
    out = yfm.get_bulk_prices(["NEW"])
    assert out["NEW"] is not None and out["NEW"]["price"] == pytest.approx(1942.70)


def test_get_current_price_rejects_out_of_band(monkeypatch):
    _seed_history("KLAC", [("2026-05-29", 194.0)])
    monkeypatch.setattr(yfm, "_fetch_ticker_info", _fake_fetch({"KLAC": 1942.70}))
    assert yfm.get_current_price("KLAC") is None


# ── Capa 2 — sanity-check del engine ──────────────────────────────────────────


def test_engine_price_out_of_band_reads_reference():
    from paper_trading import engine

    _seed_history("KLAC", [("2026-05-29", 194.0)])
    assert engine._price_out_of_band("KLAC", 1942.70) is True
    assert engine._price_out_of_band("KLAC", 200.0) is False
    # Sin referencia → fail-open.
    assert engine._price_out_of_band("NOCACHE", 1942.70) is False


# ── Capa 3 — auditoría de la DB viva ──────────────────────────────────────────


def _build_audit_db(tmp_path):
    """DB sqlite mínima con las tablas que toca el auditor."""
    db = tmp_path / "audit.db"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE paper_accounts (id INTEGER PRIMARY KEY, cash REAL);
        CREATE TABLE paper_positions (
            id INTEGER PRIMARY KEY, account_id INTEGER, ticker TEXT, shares REAL);
        CREATE TABLE paper_orders (
            id INTEGER PRIMARY KEY, account_id INTEGER, ticker TEXT, side TEXT,
            status TEXT, fill_price REAL, fill_shares REAL, commission_paid REAL,
            filled_at TEXT, reason TEXT, notes TEXT);
        CREATE TABLE historical_data_cache (
            id INTEGER PRIMARY KEY, ticker TEXT, period TEXT, interval TEXT,
            data_json TEXT, fetched_at TEXT);
        """
    )
    return db, con


def _cache_frame(closes: list[tuple[str, float]]) -> str:
    idx = pd.to_datetime([d for d, _ in closes])
    df = pd.DataFrame({"Close": [c for _, c in closes]}, index=idx)
    return df.to_json(orient="split", date_format="iso")


def test_audit_finds_klac_and_ignores_clean(tmp_path):
    from scripts import audit_price_contamination as audit

    db, con = _build_audit_db(tmp_path)
    con.execute("INSERT INTO paper_accounts VALUES (1, 7202.22)")
    # KLAC round-trip corrupto (~10×) + un AAPL sano.
    con.executemany(
        "INSERT INTO paper_orders VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (73, 1, "KLAC", "BUY", "filled", 1942.70, 2.0, 0.36, "2026-06-01", "analyze BUY", None),
            (77, 1, "KLAC", "SELL", "filled", 1987.83, 2.0, 0.47, "2026-06-05", "atr_trail", None),
            (10, 1, "AAPL", "BUY", "filled", 200.0, 5.0, 0.30, "2026-06-01", "analyze BUY", None),
        ],
    )
    con.execute(
        "INSERT INTO historical_data_cache VALUES (1,'KLAC','2y','1d',?, '2026-06-30')",
        (_cache_frame([("2026-06-01", 194.0), ("2026-06-05", 192.92)]),),
    )
    con.execute(
        "INSERT INTO historical_data_cache VALUES (2,'AAPL','2y','1d',?, '2026-06-30')",
        (_cache_frame([("2026-06-01", 201.0)]),),
    )
    con.commit()

    found = audit.find_contaminated(con)
    assert sorted(o.order_id for o in found) == [73, 77]
    assert all(o.ticker == "KLAC" for o in found)


def test_audit_net_cash_effect_matches_realized_pnl():
    from scripts import audit_price_contamination as audit

    buy = audit.ContamOrder(73, 1, "KLAC", "BUY", 1942.700865, 2.0, 0.35607,
                            "2026-06-01", "", 194.0, 9.0)
    sell = audit.ContamOrder(77, 1, "KLAC", "SELL", 1987.8305875, 2.0, 0.466925,
                             "2026-06-05", "", 192.92, 9.3)
    # neto = proceeds − cost = P/L realizado inflado (~+$89.44).
    assert audit._net_cash_effect([buy, sell]) == pytest.approx(89.44, abs=0.05)


def test_audit_apply_void_reverts_cash_and_marks_orders(tmp_path):
    from scripts import audit_price_contamination as audit

    db, con = _build_audit_db(tmp_path)
    con.execute("INSERT INTO paper_accounts VALUES (1, 7202.22)")
    con.executemany(
        "INSERT INTO paper_orders VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (73, 1, "KLAC", "BUY", "filled", 1942.700865, 2.0, 0.35607, "2026-06-01", "buy", None),
            (77, 1, "KLAC", "SELL", "filled", 1987.8305875, 2.0, 0.466925, "2026-06-05", "atr", None),
        ],
    )
    con.commit()
    orders = [
        audit.ContamOrder(73, 1, "KLAC", "BUY", 1942.700865, 2.0, 0.35607, "2026-06-01", "buy", 194.0, 9.0),
        audit.ContamOrder(77, 1, "KLAC", "SELL", 1987.8305875, 2.0, 0.466925, "2026-06-05", "atr", 192.92, 9.3),
    ]
    voided, skipped = audit.apply_void(con, orders)
    con.commit()

    assert skipped == []
    assert sorted(o.order_id for o in voided) == [73, 77]
    cash = con.execute("SELECT cash FROM paper_accounts WHERE id=1").fetchone()[0]
    assert cash == pytest.approx(7202.22 - 89.44, abs=0.05)  # revirtió el P/L inflado
    statuses = dict(con.execute("SELECT id, status FROM paper_orders").fetchall())
    assert statuses == {73: "voided", 77: "voided"}


def test_audit_apply_void_skips_open_position(tmp_path):
    from scripts import audit_price_contamination as audit

    db, con = _build_audit_db(tmp_path)
    con.execute("INSERT INTO paper_accounts VALUES (1, 5000.0)")
    con.execute("INSERT INTO paper_positions VALUES (1, 1, 'MLTX', 10.0)")
    con.execute(
        "INSERT INTO paper_orders VALUES (5,1,'MLTX','BUY','filled',900.0,10.0,0.3,'2026-06-01','buy',NULL)"
    )
    con.commit()
    orders = [audit.ContamOrder(5, 1, "MLTX", "BUY", 900.0, 10.0, 0.3, "2026-06-01", "buy", 90.0, 9.0)]
    voided, skipped = audit.apply_void(con, orders)
    con.commit()

    # Posición abierta → NO se toca (manejo manual); caja intacta.
    assert voided == []
    assert [o.order_id for o in skipped] == [5]
    assert con.execute("SELECT cash FROM paper_accounts WHERE id=1").fetchone()[0] == pytest.approx(5000.0)
    assert con.execute("SELECT status FROM paper_orders WHERE id=5").fetchone()[0] == "filled"
