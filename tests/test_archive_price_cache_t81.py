"""Tarea 81 — archivar la cinta intradía de ``price_cache`` sin perder una fila.

Lo que se fija acá no es "el script corre" sino el **orden** que lo hace seguro:
**escribir → verificar → borrar**. Un archivador que borra antes de confirmar que
el destino tiene el dato no es un archivador, es un `DELETE` con pasos de más — y
lo que estaría borrando es la **única serie intradía del proyecto** (una marca
cada ~6 min de 133 tickers, el precio que la app vio en cada scan; el cache
Parquet de barras sólo tiene diarias).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pyarrow")

import pyarrow.parquet as pq

from scripts import archive_price_cache as mod

_ESQUEMA = """
CREATE TABLE price_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    price REAL NOT NULL,
    change_pct REAL,
    volume REAL,
    market_cap REAL,
    fetched_at TIMESTAMP
)
"""


def _db(tmp_path, filas):
    p = tmp_path / "t.db"
    con = sqlite3.connect(p)
    con.execute(_ESQUEMA)
    con.executemany(
        "INSERT INTO price_cache (ticker, price, change_pct, volume, market_cap, fetched_at) "
        "VALUES (?,?,?,?,?,?)",
        filas,
    )
    con.commit()
    con.close()
    return str(p)


def _cuando(dias_atras: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias_atras)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture(autouse=True)
def _tape_en_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "TAPE_DIR", tmp_path / "price_tape")


def test_archiva_las_viejas_y_deja_las_recientes(tmp_path):
    viejas = [("AAPL", 100.0 + i, 1.0, 10.0, 1e9, _cuando(30)) for i in range(5)]
    nuevas = [("AAPL", 200.0 + i, 1.0, 10.0, 1e9, _cuando(0.1)) for i in range(3)]
    db = _db(tmp_path, viejas + nuevas)

    r = mod.archivar(db, keep_days=7)

    assert r["archivadas"] == 5 and r["borradas"] == 5
    con = sqlite3.connect(db)
    quedan = con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
    con.close()
    assert quedan == 3, "las recientes son las que el TTL todavía podría leer"


def test_no_se_pierde_una_sola_fila(tmp_path):
    """La cuenta que importa: lo que salió de SQLite está en el Parquet, fila por fila."""
    filas = [(f"T{i % 4}", 10.0 + i, None, None, None, _cuando(20)) for i in range(40)]
    db = _db(tmp_path, filas)
    con = sqlite3.connect(db)
    antes = {r[0]: r[1] for r in con.execute("SELECT id, price FROM price_cache")}
    con.close()

    mod.archivar(db, keep_days=7)

    archivos = list((tmp_path / "price_tape").glob("*.parquet"))
    assert archivos, "no escribió ningún archivo"
    df = pq.read_table(archivos[0]).to_pandas()
    assert dict(zip(df["id"], df["price"])) == antes


def test_es_idempotente(tmp_path):
    """Re-correrlo no duplica ni vuelve a borrar: los meses se funden por ``id``."""
    db = _db(tmp_path, [("AAPL", 100.0, None, None, None, _cuando(30)) for _ in range(4)])
    r1 = mod.archivar(db, keep_days=7)
    r2 = mod.archivar(db, keep_days=7)

    assert r1["borradas"] == 4
    assert r2["candidatas"] == 0 and r2["borradas"] == 0
    df = pq.read_table(next((tmp_path / "price_tape").glob("*.parquet"))).to_pandas()
    assert len(df) == 4 and df["id"].is_unique


def test_una_segunda_corrida_suma_al_mismo_mes_sin_pisar(tmp_path):
    """Lo archivado antes tiene que seguir estando después — el mes se funde, no se reemplaza."""
    db = _db(tmp_path, [("AAPL", 100.0, None, None, None, _cuando(30))])
    mod.archivar(db, keep_days=7)
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO price_cache (ticker, price, fetched_at) VALUES ('MSFT', 50.0, ?)",
        (_cuando(29),),
    )
    con.commit()
    con.close()

    mod.archivar(db, keep_days=7)

    df = pq.read_table(next((tmp_path / "price_tape").glob("*.parquet"))).to_pandas()
    assert sorted(df["ticker"]) == ["AAPL", "MSFT"]


def test_dry_run_no_escribe_ni_borra(tmp_path):
    db = _db(tmp_path, [("AAPL", 100.0, None, None, None, _cuando(30)) for _ in range(3)])

    r = mod.archivar(db, keep_days=7, dry_run=True)

    assert r["candidatas"] == 3 and r["borradas"] == 0
    assert not (tmp_path / "price_tape").exists()
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0] == 3
    con.close()


def test_si_el_archivo_no_verifica_no_se_borra_nada(tmp_path, monkeypatch):
    """**El invariante que hace seguro al script.** Si la verificación no encuentra
    los ids en el Parquet, esas filas **se quedan** en SQLite: se prefiere un
    archivador que no avanza a uno que borra a ciegas."""
    db = _db(tmp_path, [("AAPL", 100.0, None, None, None, _cuando(30)) for _ in range(6)])
    monkeypatch.setattr(mod, "_escribir_mes", lambda mes, df: set())  # "no quedó nada"

    r = mod.archivar(db, keep_days=7)

    assert r["archivadas"] == 0 and r["borradas"] == 0
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0] == 6
    con.close()


def test_una_verificacion_parcial_borra_solo_lo_verificado(tmp_path, monkeypatch):
    """Y si el archivo tiene la mitad, se borra la mitad — no todo ni nada."""
    db = _db(tmp_path, [("AAPL", 100.0, None, None, None, _cuando(30)) for _ in range(6)])
    real = mod._escribir_mes
    monkeypatch.setattr(mod, "_escribir_mes", lambda mes, df: set(list(real(mes, df))[:3]))

    r = mod.archivar(db, keep_days=7)

    assert r["borradas"] == 3
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0] == 3
    con.close()


def test_parte_por_mes(tmp_path):
    """Un archivo por mes: sin eso, un año de cinta sería un solo Parquet enorme."""
    hoy = datetime.now(timezone.utc)
    filas = [
        ("AAPL", 1.0, None, None, None, (hoy - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")),
        ("AAPL", 2.0, None, None, None, (hoy - timedelta(days=80)).strftime("%Y-%m-%d %H:%M:%S")),
    ]
    db = _db(tmp_path, filas)

    mod.archivar(db, keep_days=7)

    archivos = sorted(p.name for p in (tmp_path / "price_tape").glob("*.parquet"))
    assert len(archivos) == 2, archivos
    assert all(len(n) == len("2026-07.parquet") for n in archivos)
