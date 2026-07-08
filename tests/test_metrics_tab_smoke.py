"""Smoke test del wiring de la pestaña Métricas (V1).

Construye ``MetricsTab`` y le pasa un payload real de ``build_metrics`` — atrapa
desajustes entre las claves del payload y las cards/columnas de la UI (p.ej. las
cards nuevas ``excursion``/``benchmark`` y la card de fricción). No asserta píxeles.
Se saltea si PyQt6 no está disponible (imagen headless sin runtime Qt).
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("matplotlib")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from analysis import metrics_panel as mp  # noqa: E402
from ui.metrics_tab import MetricsTab  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _payload_with_data() -> dict:
    """Payload de build_metrics con un round-trip cerrado, SPY y snapshots."""
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
    con.execute(
        "CREATE TABLE paper_equity_snapshots (id INTEGER PRIMARY KEY, account_id INT, "
        "snapshot_at TEXT, cash REAL, positions_value REAL, total_equity REAL, portfolio_sigma REAL)"
    )
    con.execute("INSERT INTO paper_orders VALUES (1,1,'AAA','BUY',100.0,10,1.0,0.5,0.8,"
                "'analyze BUY','filled','2026-01-01 10:00:00')")
    con.execute("INSERT INTO paper_orders VALUES (2,1,'AAA','SELL',120.0,10,1.0,0.5,0.3,"
                "'analyze SELL (0.30)','filled','2026-01-08 10:00:00')")
    payload = {
        "columns": ["Open", "High", "Low", "Close", "Volume"],
        "index": [f"2026-01-0{i}T00:00:00.000" for i in (1, 2, 5, 6, 7, 8)],
        "data": [[c, c + 3, c - 2, c, 1000] for c in (100, 105, 110, 115, 118, 120)],
    }
    con.execute("INSERT INTO historical_data_cache (ticker,period,interval,data_json,fetched_at) "
                "VALUES ('AAA','2y','1d',?,?)", (json.dumps(payload), "2026-01-10"))
    spy = {
        "columns": ["Open", "High", "Low", "Close", "Volume"],
        "index": ["2026-01-01T00:00:00.000", "2026-01-08T00:00:00.000"],
        "data": [[400, 400, 400, 400, 1000], [408, 408, 408, 408, 1000]],
    }
    con.execute("INSERT INTO historical_data_cache (ticker,period,interval,data_json,fetched_at) "
                "VALUES ('SPY','2y','1d',?,?)", (json.dumps(spy), "2026-01-10"))
    con.execute("INSERT INTO paper_equity_snapshots (account_id,snapshot_at,cash,positions_value,"
                "total_equity,portfolio_sigma) VALUES (1,'2026-01-01 16:00:00',0,0,50000,NULL)")
    con.execute("INSERT INTO paper_equity_snapshots (account_id,snapshot_at,cash,positions_value,"
                "total_equity,portfolio_sigma) VALUES (1,'2026-01-08 16:00:00',0,0,52000,NULL)")
    m = mp.build_metrics(con, 1)
    m["commit_markers"] = []
    return m


def test_metrics_tab_renders_full_payload(qapp):
    tab = MetricsTab(account_id=1)
    tab._on_result(_payload_with_data())  # no debe lanzar
    # Las cards nuevas de V1 existen y quedaron con un valor.
    assert tab.cards["excursion"].value_lbl.text() != ""
    assert tab.cards["benchmark"].value_lbl.text() != ""
    assert tab.cards["costs"].value_lbl.text() != ""
    # La tabla de round-trips ganó las columnas MAE/MFE (9 columnas).
    assert tab.rt_table["table"].columnCount() == 9


def test_metrics_tab_renders_empty_payload(qapp):
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_orders (id INTEGER PRIMARY KEY, account_id INT, ticker TEXT, "
        "side TEXT, fill_price REAL, fill_shares REAL, commission_paid REAL, "
        "slippage_cost REAL, signal_score REAL, reason TEXT, status TEXT, filled_at TEXT)"
    )
    con.execute("CREATE TABLE paper_positions (id INTEGER PRIMARY KEY, account_id INT, "
                "ticker TEXT, shares REAL, avg_cost REAL)")
    con.execute("CREATE TABLE historical_data_cache (id INTEGER PRIMARY KEY, ticker TEXT, "
                "period TEXT, interval TEXT, data_json TEXT, fetched_at TEXT)")
    m = mp.build_metrics(con, 1)
    m["commit_markers"] = []
    tab = MetricsTab(account_id=1)
    tab._on_result(m)  # cuenta vacía: no debe lanzar
    assert tab.cards["excursion"].value_lbl.text() == "—"
