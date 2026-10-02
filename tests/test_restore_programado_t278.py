"""Tarea 278 — el restore se programa y corre al arrancar; y hay backup antes de migrar.

El defecto (``docs/auditoria_operacion_backups_2026-10-02.md`` [B-1], medido por el
``verificador``): el botón de Settings hacía ``shutil.copy2`` del backup sobre la base viva
con la app abierta y la base en WAL. Según el tamaño del WAL, el restore se revertía solo
al cerrar la app o dejaba la base corrupta, y el ``.before-restore`` perdía lo que estaba
en el WAL. Y [B-2]: ``init_db`` migraba antes del backup diario.

El caso que separa las dos versiones es una app que **se cerró mal**: el ``.db`` y el
``-wal`` quedan en disco con filas sin volcar. Con ``copy2`` la copia para deshacer pierde
esas filas; con la API de backup de SQLite, no.

**Una mutación que sale verde, y por qué está bien.** Cambiar a ``copy2`` sólo la copia
del **restore** (no la del rollback) no pone nada en rojo: el paso anterior —el rollback por
la API de SQLite— abre y cierra una conexión sobre la base viva, y al cerrarse la última
conexión SQLite **vuelca el WAL y lo borra**. Cuando llega el restore ya no hay WAL viejo,
así que ``copy2`` ahí sería equivalente. Es una mutación equivalente bajo la precondición
del arranque (sin otras conexiones); el restore va igual por la API de SQLite, que no
depende de ese orden.
"""

from __future__ import annotations

import ast
import shutil
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def rutas(tmp_path, monkeypatch):
    import database.backup as bk

    live = tmp_path / "finanzias.db"
    monkeypatch.setattr(bk, "DB_PATH", str(live))
    monkeypatch.setattr(bk, "DB_DIR", tmp_path)
    monkeypatch.setattr(bk, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(bk, "DB_STEM", live.stem)
    return tmp_path, live


def _filas(path: Path) -> int:
    """Cuenta en SOLO LECTURA: una conexión normal, al cerrarse, vuelca el WAL al ``.db`` y
    borraría el estado de «app cerrada mal» que el test necesita (pasó: con una conexión
    normal acá, las mutaciones a ``copy2`` salían verdes)."""
    c = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        c.close()


def _backup_con(tmp_path: Path, n: int) -> Path:
    d = tmp_path / "backups"
    d.mkdir(exist_ok=True)
    b = d / "finanzias_2026-10-01_10-00-00_daily.db"
    c = sqlite3.connect(str(b))
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    c.executemany("INSERT INTO t (v) VALUES (?)", [("backup",)] * n)
    c.commit()
    c.close()
    return b


def _viva_cerrada_MAL(tmp_path: Path, live: Path, base: int, en_wal: int) -> None:
    """Deja en ``live`` una base en WAL con ``en_wal`` filas SIN volcar, como tras un cierre abrupto."""
    origen = tmp_path / "origen"
    origen.mkdir()
    src = origen / "finanzias.db"
    c = sqlite3.connect(str(src))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    c.executemany("INSERT INTO t (v) VALUES (?)", [("viejo",)] * base)
    c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.executemany("INSERT INTO t (v) VALUES (?)", [("en-el-wal",)] * en_wal)
    c.commit()
    # Copia de los archivos con la conexión ABIERTA: el estado en disco de una app cortada.
    for suf in ("", "-wal", "-shm"):
        if Path(str(src) + suf).exists():
            shutil.copyfile(str(src) + suf, str(live) + suf)
    c.close()
    assert Path(str(live) + "-wal").exists() and Path(str(live) + "-wal").stat().st_size > 0


def test_el_restore_programado_RESTAURA_y_la_copia_conserva_el_WAL(rutas):
    from database.backup import apply_pending_restore, schedule_restore

    tmp_path, live = rutas
    _viva_cerrada_MAL(tmp_path, live, base=100, en_wal=50)
    backup = _backup_con(tmp_path, 10)

    assert schedule_restore(backup) is True
    assert _filas(live) == 150, "programar NO debe tocar la base"
    assert apply_pending_restore() == backup.resolve()

    assert _filas(live) == 10, "la base no quedó igual al backup"
    c = sqlite3.connect(str(live))
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    c.close()
    rollback = live.with_suffix(".db.before-restore")
    assert _filas(rollback) == 150, "la copia para deshacer perdió las filas que estaban en el WAL"
    assert not live.with_name(live.name + ".restore-pending").exists()


def test_sin_restore_programado_no_toca_nada(rutas):
    from database.backup import apply_pending_restore

    tmp_path, live = rutas
    _viva_cerrada_MAL(tmp_path, live, base=5, en_wal=5)
    assert apply_pending_restore() is None
    assert _filas(live) == 10


def test_un_backup_ROTO_no_se_programa(rutas):
    from database.backup import schedule_restore

    tmp_path, live = rutas
    roto = tmp_path / "backups" / "finanzias_roto.db"
    roto.parent.mkdir()
    roto.write_bytes(b"esto no es una base sqlite" * 100)
    assert schedule_restore(roto) is False
    assert not live.with_name(live.name + ".restore-pending").exists()


def test_un_restore_que_falla_NO_reintenta_en_cada_arranque_y_deja_la_base(rutas):
    from database.backup import apply_pending_restore, schedule_restore

    tmp_path, live = rutas
    _viva_cerrada_MAL(tmp_path, live, base=7, en_wal=3)
    backup = _backup_con(tmp_path, 10)
    assert schedule_restore(backup)
    backup.unlink()  # desapareció entre programar y arrancar

    assert apply_pending_restore() is None
    assert _filas(live) == 10  # la de antes: 7 + 3
    marcador = live.with_name(live.name + ".restore-pending")
    assert not marcador.exists()
    assert marcador.with_name(marcador.name + ".failed").exists()


# ── [B-2] backup antes de migrar ─────────────────────────────────────────────


def _con_version(live: Path, version: str | None) -> None:
    c = sqlite3.connect(str(live))
    c.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
    if version is not None:
        c.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        c.execute("INSERT INTO alembic_version VALUES (?)", (version,))
    c.commit()
    c.close()


def _head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def test_una_base_ATRASADA_tiene_migracion_pendiente_y_se_respalda(rutas):
    from database.backup import backup_if_migration_pending, migration_pending

    _, live = rutas
    _con_version(live, "0001")
    assert migration_pending() is True
    out = backup_if_migration_pending()
    assert out is not None and "pre-migration" in out.name and out.exists()


def test_una_base_en_el_HEAD_no_se_respalda(rutas):
    from database.backup import backup_if_migration_pending, migration_pending

    _, live = rutas
    _con_version(live, _head())
    assert migration_pending() is False
    assert backup_if_migration_pending() is None


def test_una_base_NUEVA_no_cuenta_como_migracion(rutas):
    from database.backup import migration_pending

    _, live = rutas
    _con_version(live, None)
    assert migration_pending() is False


# ── El cable ─────────────────────────────────────────────────────────────────


def test_main_aplica_el_restore_y_el_backup_ANTES_de_init_db():
    """Después de `init_db` ya hay conexiones abiertas: el restore no restauraría."""
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "main")
    llamadas = [n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    lineas = {
        nombre: min(
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == nombre
        )
        for nombre in ("apply_pending_restore", "backup_if_migration_pending", "init_db")
        if nombre in llamadas
    }
    assert set(lineas) == {"apply_pending_restore", "backup_if_migration_pending", "init_db"}
    assert lineas["apply_pending_restore"] < lineas["backup_if_migration_pending"] < lineas["init_db"]


def test_settings_PROGRAMA_el_restore_y_no_copia_con_la_app_abierta():
    src = (Path(__file__).resolve().parent.parent / "ui" / "settings_tab.py").read_text(encoding="utf-8")
    assert "schedule_restore(" in src
    assert "restore_database(" not in src
