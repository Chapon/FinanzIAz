"""El instrumento del spike de noticias (tarea 413): que cuente lo que dice que cuenta."""

from __future__ import annotations

import sqlite3

from scripts.measure_news_cost_benefit_t413 import medir_db, medir_log

_LOG = """\
2026-11-09 10:00:00 [INFO   ] paper_trading.scheduler: daily catalyst refresh starting (harvest + classify)
2026-11-09 10:05:00 [INFO   ] scripts.harvest_catalysts: Harvest: 127/127 tickers en 300s | news +900 (dup 9100) | estimates +1269 (dup 0) | failed 0
2026-11-09 10:05:01 [INFO   ] scripts.classify_catalysts: classifying with hybrid-ollama backend (model=qwen2.5:14b)
2026-11-09 10:50:01 [INFO   ] scripts.classify_catalysts: Classify: scanned 900 | classified 900 | failed 0
2026-11-09 11:00:00 [INFO   ] paper_trading.scheduler: hourly catalyst harvest starting (harvest-only, RTH)
2026-11-09 11:05:00 [WARNING] scripts.harvest_catalysts: Harvest: 127/127 tickers en 300s | news +100 (dup 9900) | estimates +0 (dup 1269) | failed 0
2026-11-09 11:06:00 [WARNING] scripts.harvest_catalysts: [dry-run] Harvest: 12/12 tickers en 26s | news +0 (dup 50) | estimates +0 (dup 0) | failed 0
2026-11-10 09:00:00 [INFO   ] __main__: Iniciando FinanzIAs
"""


def test_el_log_separa_horario_de_diario_y_no_cuenta_el_dry_run(tmp_path):
    p = tmp_path / "f.log"
    p.write_text(_LOG, encoding="utf-8")
    r = medir_log(p)
    h = r["harvest"]
    assert h["corridas"] == 2  # el dry-run no cuenta
    assert (h["recibidas"], h["nuevas"]) == (20000, 1000)
    assert h["por_disparo"]["diario"]["est_nuevas"] == 1269
    assert h["por_disparo"]["horario"]["est_recibidas"] == 1269
    assert h["por_disparo"]["horario"]["nuevas"] == 100
    c = r["clasificacion"]
    assert (c["clasificadas"], c["s_por_noticia"]) == (900, 3.0)
    assert (r["dias_con_log"], r["dias_con_harvest"]) == (2, 1)


def _db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE news_events (id INTEGER PRIMARY KEY, ticker TEXT, title TEXT, content TEXT,
          source TEXT, url TEXT, published_at TEXT, fetched_at TEXT, event_type TEXT,
          classified_by TEXT, classified_at TEXT);
        CREATE TABLE paper_orders (account_id INT, ticker TEXT, side TEXT, fill_shares REAL,
          filled_at TEXT, status TEXT);
        CREATE TABLE paper_watchlist (account_id INT, ticker TEXT);
        CREATE TABLE claude_opinions (fecha TEXT);
        """
    )
    filas = [
        # el mismo titular en dos fuentes (con distinto espaciado/mayúsculas): ninguna es única
        ("AAA", "Big  News", "finnhub:Yahoo", "2026-11-02 10:00:00"),
        ("AAA", "big news", "yfinance:search", "2026-11-02 11:00:00"),
        # mismo título pero OTRO ticker: es única de su fuente
        ("BBB", "Big News", "finnhub:Yahoo", "2026-11-02 10:00:00"),
        # AAA fuera de la tenencia (después de vender)
        ("AAA", "Later", "sec_8k", "2026-11-06 10:00:00"),
    ]
    con.executemany(
        "INSERT INTO news_events (ticker,title,source,published_at,fetched_at) VALUES (?,?,?,?,?)",
        [(t, ti, s, f, f) for t, ti, s, f in filas],
    )
    con.executemany(
        "INSERT INTO paper_orders VALUES (2,?,?,?,?,'filled')",
        [("AAA", "BUY", 10, "2026-11-01 00:00:00"), ("AAA", "SELL", 10, "2026-11-05 00:00:00")],
    )
    con.execute("INSERT INTO paper_watchlist VALUES (2,'AAA')")
    con.commit()
    con.close()


def test_unica_por_fuente_y_tenencia_por_fecha(tmp_path):
    p = tmp_path / "x.db"
    _db(p)
    r = medir_db(p)
    pf = r["news_events"]["por_fuente"]
    assert pf["finnhub:Yahoo"]["solo_esta_fuente"] == 1  # sólo la de BBB
    assert pf["yfinance:search"]["solo_esta_fuente"] == 0
    assert pf["sec_8k"]["solo_esta_fuente"] == 1
    uso = r["uso"]
    # las dos de AAA del 02/11 (en cartera); ni la de BBB ni la del 06/11
    assert uso["filas_de_ticker_en_cartera"] == 2
    assert uso["filas_fuera_de_la_watchlist_viva"] == 1
