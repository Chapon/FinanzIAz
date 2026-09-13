"""
Lightweight SQLite backup utility for FinanzIAs.

Public API
----------
``backup_database(reason="manual")``       — make a snapshot now, return path.
``rotate_backups(keep=7)``                 — keep the last N DAILY snapshots.
``prune_adhoc_backups(keep_days=30)``      — delete non-daily snapshots older
                                              than N days, by the date in the name.
``maybe_rotate_daily(keep=7)``             — call once at app start; performs
                                              a backup if today's hasn't been
                                              made yet, then rotates and prunes.
``list_backups()``                         — list existing snapshot files.
``restore_database(backup_path)``          — atomically replace the live DB
                                              with a backup (returns True on
                                              success). Caller is responsible
                                              for closing all open sessions
                                              before invoking this.

Backups are stored in ``<DB_DIR>/backups/`` next to ``finanzias.db`` so they
move with the project folder. Filenames look like
``finanzias_2026-05-07_18-32-04_daily.db`` so they sort naturally and the
reason is embedded.

Implementation
--------------
- Uses SQLite's online ``BACKUP`` API via ``sqlite3.Connection.backup`` —
  consistent even while the app is running and writing.
- Skips ``__pycache__``, falls back to a plain file copy if the backup API
  is unavailable for any reason.
- All operations are best-effort: any exception is logged, never propagated
  to the UI thread.

Retención — tareas 187 y 193
----------------------------
**Hay dos poblaciones y cada una tiene su regla.** Los **diarios**
(``finanzias_AAAA-MM-DD_HH-MM-SS_daily.db``) rotan por **cantidad**: quedan los últimos
``keep``. Los **sueltos** —``pre_*``/``post_*`` que se crean a mano antes de una operación
riesgosa, y los que crea la UI (``manual``, ``pre-delete-account``, ``pre-delete-position``)—
se borran a los **30 días** de la fecha de su nombre (decisión de Chapa, tarea 187). Lo que
no es ``.db`` (``settings_pre_*.json``, ``pit_*…json``) **no se toca nunca**: es evidencia de
una decisión, no una red de seguridad.

**Antes las dos poblaciones rotaban juntas, y eso borraba los diarios** (tarea 193).
``rotate_backups`` contaba todos los ``finanzias_*.db`` y borraba los primeros **por orden
alfabético**; ``finanzias_2026-…`` ordena antes que ``finanzias_pre_…``, así que con 5 sueltos
quedaban **2** diarios, y con 7 el daily recién creado **se borraba en su propio arranque**.

**La antigüedad sale del nombre, no del mtime,** porque el mtime de un backup no es su edad:
el smoke test de la suite abría backups y les cambiaba la fecha (tarea 188). Un nombre sin
fecha legible **no se borra**.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from config.logging_config import get_logger
from database.models import DB_PATH

log = get_logger(__name__)

DB_DIR = Path(DB_PATH).parent
BACKUP_DIR = DB_DIR / "backups"
DB_STEM = Path(DB_PATH).stem  # "finanzias"

# Tarea 187: los backups sueltos se conservan 30 días desde la fecha de su nombre.
ADHOC_KEEP_DAYS = 30

# La fecha de un nombre de backup: `2026-09-12` (los que escribe `backup_database`) o
# `20260912` (los que se crean a mano, `finanzias_pre_t81_20260902_140200.db`).
_FECHA_EN_NOMBRE = re.compile(r"(?<!\d)(20\d{2})-?(\d{2})-?(\d{2})(?!\d)")


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def backup_database(reason: str = "manual") -> Path | None:
    """
    Snapshot the live SQLite database to ``<DB_DIR>/backups/``.

    ``reason`` is a short tag baked into the filename so you can tell apart
    daily snapshots, pre-migration backups, and manual ones.
    Returns the path on success, ``None`` on failure (always logged).
    """
    try:
        src = Path(DB_PATH)
        if not src.exists():
            log.warning("backup_database: source DB %s does not exist", src)
            return None

        _ensure_backup_dir()
        safe_reason = "".join(c for c in reason if c.isalnum() or c in "-_") or "manual"
        dst = BACKUP_DIR / f"{DB_STEM}_{_timestamp()}_{safe_reason}.db"

        # Try the online backup API first — consistent across in-flight writes.
        # Use explicit close(): the sqlite3 context manager only commits/rolls
        # back, it does NOT close the connection. On Windows, open handles
        # prevent the file from being deleted by rotate_backups.
        try:
            src_conn = sqlite3.connect(str(src))
            dst_conn = sqlite3.connect(str(dst))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()
        except Exception:
            log.warning("Online backup failed, falling back to file copy", exc_info=True)
            shutil.copy2(src, dst)

        log.info("Database backed up to %s", dst)
        return dst
    except Exception:
        log.exception("backup_database failed")
        return None


def list_backups() -> list[Path]:
    """Return existing snapshot files sorted oldest → newest."""
    if not BACKUP_DIR.exists():
        return []
    items = sorted(BACKUP_DIR.glob(f"{DB_STEM}_*.db"))
    return items


def _es_diario(p: Path) -> bool:
    """Un snapshot DIARIO, por el patrón exacto que escribe ``maybe_rotate_daily``."""
    return (
        re.fullmatch(
            rf"{re.escape(DB_STEM)}_\d{{4}}-\d{{2}}-\d{{2}}_\d{{2}}-\d{{2}}-\d{{2}}_daily\.db", p.name
        )
        is not None
    )


def list_daily_backups() -> list[Path]:
    """Sólo los snapshots diarios, del más viejo al más nuevo."""
    return [p for p in list_backups() if _es_diario(p)]


def _fecha_del_nombre(nombre: str) -> date | None:
    m = _FECHA_EN_NOMBRE.search(nombre)
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _borrar_backup(p: Path) -> bool:
    """Borra la base y **después** sus side files (tarea 143). ``True`` si se borró la base."""
    try:
        p.unlink()
    except Exception:
        log.exception("Could not delete backup %s", p)
        return False
    # Los side files van DESPUÉS de la base y con su propio try: si falla borrar
    # un `-shm` no se pierde la rotación, que es lo que importa.
    for sufijo in ("-wal", "-shm"):
        lado = p.with_name(p.name + sufijo)
        try:
            lado.unlink(missing_ok=True)
        except OSError:
            log.warning("No se pudo borrar el side file %s", lado)
    return True


def adhoc_backups_vencidos(keep_days: int = ADHOC_KEEP_DAYS, *, today: date | None = None) -> list[Path]:
    """Los backups **sueltos** (``.db`` no diarios) con más de ``keep_days`` desde la fecha de su nombre.

    Un nombre sin fecha legible no entra: ante la duda, un backup se conserva.
    """
    hoy = today or date.today()
    vencidos = []
    for p in list_backups():
        if _es_diario(p):
            continue
        fecha = _fecha_del_nombre(p.name)
        if fecha is not None and (hoy - fecha).days > keep_days:
            vencidos.append(p)
    return vencidos


def prune_adhoc_backups(keep_days: int = ADHOC_KEEP_DAYS, *, today: date | None = None) -> list[Path]:
    """Borra los backups sueltos vencidos (tarea 187). Devuelve los que borró."""
    if keep_days <= 0:
        return []
    borrados = [p for p in adhoc_backups_vencidos(keep_days, today=today) if _borrar_backup(p)]
    if borrados:
        log.info("Backups sueltos con más de %d días borrados: %s", keep_days, [p.name for p in borrados])
    return borrados


def rotate_backups(keep: int = 7) -> int:
    """
    Delete oldest DAILY backups so at most ``keep`` remain. Returns number deleted.

    **Sólo los diarios** (tarea 193). Contaba todos los ``finanzias_*.db`` y borraba los
    primeros por orden alfabético, así que los sueltos (``pre_*``, ``post_*``, los de la UI)
    le comían los lugares a los diarios — y con 7 sueltos borraba el daily recién creado.

    **Una base SQLite en modo WAL son TRES archivos** (``.db``, ``.db-wal``,
    ``.db-shm``) y esto borraba **uno** (tarea 143). Medido el 2026-09-08: **18 side
    files huérfanos** de 9 backups que ya no existían. El daño directo era ~288 KB,
    pero el mecanismo garantizaba que se acumulara sin techo — y **un ``-wal`` al lado
    de una base no es inerte**: si algún día se restaura por copia, SQLite lo aplica.

    El contador que se devuelve sigue siendo el de **bases** borradas, no el de
    archivos: es lo que el llamador reporta y lo que sus tests fijan.
    """
    if keep <= 0:
        return 0
    backups = list_daily_backups()
    if len(backups) <= keep:
        return 0
    to_delete = backups[: len(backups) - keep]
    deleted = sum(1 for p in to_delete if _borrar_backup(p))
    if deleted:
        log.info("Rotated backups: deleted %d, kept %d", deleted, keep)
    return deleted


def _today_already_backed_up() -> bool:
    today = date.today().isoformat()
    return any(today in p.name for p in list_daily_backups())


def maybe_rotate_daily(*, keep: int = 7) -> Path | None:
    """
    Make today's daily snapshot if it hasn't been made yet, then rotate the dailies
    and prune the ad-hoc snapshots older than ``ADHOC_KEEP_DAYS`` (tareas 187 y 193).

    Designed to be called once on app startup — it's idempotent and silent
    when there's nothing to do, so it's cheap.
    """
    try:
        if _today_already_backed_up():
            rotate_backups(keep=keep)
            prune_adhoc_backups()
            return None
        path = backup_database(reason="daily")
        rotate_backups(keep=keep)
        prune_adhoc_backups()
        return path
    except Exception:
        log.exception("maybe_rotate_daily failed")
        return None


def restore_database(backup_path: Path | str) -> bool:
    """
    Replace the live DB with the contents of ``backup_path`` atomically.

    The caller is responsible for closing all open SQLAlchemy sessions
    BEFORE invoking this; the function itself just performs the file swap.
    The previous DB is preserved alongside as ``<name>.before-restore.db``
    so you can roll back if the restored copy turns out to be bad.

    Returns True on success, False otherwise.
    """
    try:
        backup = Path(backup_path)
        if not backup.exists() or not backup.is_file():
            log.error("restore_database: %s does not exist", backup)
            return False
        live = Path(DB_PATH)
        if live.exists():
            rollback = live.with_suffix(live.suffix + ".before-restore")
            shutil.copy2(live, rollback)
            log.info("Existing DB saved to %s before restore", rollback)
        shutil.copy2(backup, live)
        log.info("Database restored from %s", backup)
        return True
    except Exception:
        log.exception("restore_database failed")
        return False
