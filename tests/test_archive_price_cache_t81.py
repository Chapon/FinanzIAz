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
    # `strict=True` a propósito: las dos columnas salen del mismo Parquet, así que
    # un largo distinto sería el archivo mal escrito — justo lo que el test mira.
    assert dict(zip(df["id"], df["price"], strict=True)) == antes


def test_es_idempotente(tmp_path):
    """Re-correrlo no duplica ni vuelve a borrar: los meses se funden por ``id``."""
    db = _db(tmp_path, [("AAPL", 100.0, None, None, None, _cuando(30)) for _ in range(4)])
    r1 = mod.archivar(db, keep_days=7)
    r2 = mod.archivar(db, keep_days=7)

    assert r1["borradas"] == 4
    assert r2["candidatas"] == 0 and r2["borradas"] == 0
    df = pq.read_table(next((tmp_path / "price_tape").glob("*.parquet"))).to_pandas()
    assert len(df) == 4 and df["id"].is_unique


def _dias_que_parten_30_y_29(anio: int) -> list[datetime]:
    """Los días en que «hace 30 días» y «hace 29 días» caen en meses distintos (tarea 248).

    Es la forma en que este test estuvo rojo el 2026-09-30: sembraba ``_cuando(30)`` y
    ``_cuando(29)`` —que casi siempre son del mismo mes— y leía **un** Parquet. Se derivan
    en vez de escribirse para que la lista no pueda quedar vieja.
    """
    dia = datetime(anio, 1, 1, 12, tzinfo=timezone.utc)
    out = []
    while dia.year == anio:
        if (dia - timedelta(days=30)).month != (dia - timedelta(days=29)).month:
            out.append(dia)
        dia += timedelta(days=1)
    return out


def _dos_instantes_del_mismo_mes(hoy: datetime) -> tuple[str, str]:
    """El 10 y el 11 de un mes que termina ≥ 40 días antes de ``hoy``: mismo mes, y los dos
    más viejos que cualquier ``keep_days`` de estos tests, sea cual sea el día."""
    base = (hoy.replace(day=1) - timedelta(days=40)).replace(
        day=10, hour=12, minute=0, second=0, microsecond=0
    )
    fmt = "%Y-%m-%d %H:%M:%S"
    return base.strftime(fmt), (base + timedelta(days=1)).strftime(fmt)


def _fijar_reloj(monkeypatch, hoy: datetime) -> None:
    """El corte del archivador sale de ``datetime.now`` en su módulo: se fija ahí."""

    class _Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return hoy if tz is not None else hoy.replace(tzinfo=None)

    monkeypatch.setattr(mod, "datetime", _Reloj)


def test_los_dias_rojos_existen_y_son_los_medidos():
    """Contraprueba del parametrizado de abajo: si esta derivación diera vacío, el test
    del mes pasaría sin probar ningún día rojo. En 2026 son 12 (medido en la tarea 248)."""
    dias = _dias_que_parten_30_y_29(2026)
    assert len(dias) == 12
    assert datetime(2026, 9, 30, 12, tzinfo=timezone.utc) in dias


@pytest.mark.parametrize(
    "hoy",
    [datetime(2026, 9, 15, 12, tzinfo=timezone.utc), *_dias_que_parten_30_y_29(2026)],
    ids=lambda d: d.strftime("%m-%d"),
)
def test_una_segunda_corrida_suma_al_mismo_mes_sin_pisar(tmp_path, monkeypatch, hoy):
    """Lo archivado antes tiene que seguir estando después — el mes se funde, no se reemplaza.

    Las dos filas son **del mismo mes** por construcción, no por casualidad del calendario
    (tarea 248), y el reloj del archivador se fija en cada día en que la versión vieja caía.
    """
    _fijar_reloj(monkeypatch, hoy)
    primero, segundo = _dos_instantes_del_mismo_mes(hoy)
    db = _db(tmp_path, [("AAPL", 100.0, None, None, None, primero)])
    mod.archivar(db, keep_days=7)
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO price_cache (ticker, price, fetched_at) VALUES ('MSFT', 50.0, ?)",
        (segundo,),
    )
    con.commit()
    con.close()

    mod.archivar(db, keep_days=7)

    archivos = list((tmp_path / "price_tape").glob("*.parquet"))
    assert len(archivos) == 1, f"las dos filas eran del mismo mes: {archivos}"
    df = pq.read_table(archivos[0]).to_pandas()
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
