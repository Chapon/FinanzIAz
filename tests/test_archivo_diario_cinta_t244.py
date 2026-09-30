"""Tarea 244 — la cinta intradía de ``price_cache`` se archiva sola, 1×/día.

La 81 decidió **archivar, no podar** (es la única serie intradía del proyecto) y dejó el
archivador como script manual. Corrió una vez, el 2026-09-02; para el 2026-09-30 la tabla
tenía ~200k filas sin archivar y la DB había vuelto de 42,8 a ~90 MB. Lo encontró la
auditoría del 2026-09-30 ([E-1] de `docs/auditoria_estado_2026-09-30.md`). Decisión de Chapa:
automático diario.

Lo que se fija: (1) el gate deja correr **una** vez por día calendario, con el reloj
avanzado; (2) el worker corre el archivador sobre la DB que redirige ``FINANZIAS_DB_PATH``,
archiva y borra lo verificado; (3) un fallo **no borra nada** y se reporta; (4) el job está
cableado al arranque y al tick diario.
"""

from __future__ import annotations

import inspect
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

pytest.importorskip("pyarrow")

from database import models
from paper_trading import scheduler as sch
from scripts import archive_price_cache as arch


def test_corre_UNA_vez_por_dia_con_el_reloj_avanzado():
    ultimo = None
    corridas = []
    dia0 = date(2026, 9, 28)
    for minuto in range(3 * 24 * 60):  # tres días de ticks por minuto
        hoy = (datetime(2026, 9, 28) + timedelta(minutes=minuto)).date()
        if sch.price_tape_archive_due(enabled=True, today=hoy, last=ultimo, worker_running=False):
            ultimo = hoy
            corridas.append(hoy)
    assert corridas == [dia0, dia0 + timedelta(days=1), dia0 + timedelta(days=2)]


def test_apagado_o_con_un_worker_vivo_no_corre():
    hoy = date(2026, 9, 30)
    assert not sch.price_tape_archive_due(enabled=False, today=hoy, last=None, worker_running=False)
    assert not sch.price_tape_archive_due(enabled=True, today=hoy, last=None, worker_running=True)


def _db_con_cinta(path, filas):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE price_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, "
        "price REAL NOT NULL, change_pct REAL, volume REAL, market_cap REAL, fetched_at TIMESTAMP)"
    )
    con.executemany("INSERT INTO price_cache (ticker, price, fetched_at) VALUES (?,?,?)", filas)
    con.commit()
    con.close()


def _hace(dias: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def db_y_cinta(tmp_path, monkeypatch):
    db = tmp_path / "cinta.db"
    _db_con_cinta(db, [("AAPL", 1.0, _hace(20)), ("AAPL", 2.0, _hace(20)), ("MSFT", 3.0, _hace(0.1))])
    monkeypatch.setattr(models, "DB_PATH", str(db))
    monkeypatch.setattr(arch, "TAPE_DIR", tmp_path / "price_tape")
    return db


def _correr_worker():
    w = sch.PriceTapeArchiveWorker()
    ok, err = [], []
    w.archive_completed.connect(ok.append)
    w.archive_failed.connect(err.append)
    w.run()  # sincrónico: es lo que corre el hilo
    return ok, err


def _filas(db) -> int:
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
    finally:
        con.close()


def test_el_worker_archiva_y_borra_SOLO_lo_viejo_de_la_DB_redirigida(db_y_cinta, tmp_path):
    ok, err = _correr_worker()
    assert err == [] and ok and ok[0]["archivadas"] == 2 and ok[0]["borradas"] == 2
    assert _filas(db_y_cinta) == 1, "la fila reciente se queda en la DB"
    assert list((tmp_path / "price_tape").glob("*.parquet")), "no escribió la cinta"


def test_un_fallo_de_escritura_no_borra_nada_y_se_reporta(db_y_cinta, monkeypatch):
    def _disco_lleno(mes, df):
        raise OSError("No space left on device")

    monkeypatch.setattr(arch, "_escribir_mes", _disco_lleno)
    ok, err = _correr_worker()
    assert ok == [] and len(err) == 1 and "No space left" in err[0]
    assert _filas(db_y_cinta) == 3, "un fallo no puede borrar filas"


def test_el_job_esta_cableado_al_arranque_y_al_tick_diario():
    """El gate y el worker andan solos; esto fija que alguien los llame (la lección de la 228)."""
    assert "_maybe_archive_price_tape" in inspect.getsource(sch.PaperScheduler.start)
    assert "_maybe_archive_price_tape" in inspect.getsource(sch.PaperScheduler._on_daily_tick)
    assert "price_tape_archive_due" in inspect.getsource(sch.PaperScheduler._maybe_archive_price_tape)
