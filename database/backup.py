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
``schedule_restore(backup_path)``         — lo que usa el botón de Settings: deja
                                              el restore PROGRAMADO (tarea 278).
``apply_pending_restore()``                — lo ejecuta en ``main.py`` al arrancar,
                                              antes de ``init_db``, sin conexiones.
``restore_database(backup_path)``          — el restore en sí, por la API de backup
                                              de SQLite; sólo sin conexiones abiertas.
``backup_if_migration_pending()``          — backup ``pre-migration`` antes de que
                                              ``init_db`` migre (tarea 278, [B-2]).

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
from database.readonly import readonly_uri

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


def _sqlite_copy(src: Path, dst: Path) -> None:
    """Copia ``src`` sobre ``dst`` con la API de backup de SQLite.

    A diferencia de ``shutil.copy2``, lee la base **a través de SQLite**: incluye lo que
    todavía está en el ``-wal`` de ``src``, y del lado de ``dst`` SQLite primero recupera su
    propio WAL y después reemplaza todas las páginas. Por eso es la única forma correcta de
    copiar una base en modo WAL (tarea 278).
    """
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
        d.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        d.close()
        s.close()


def _quick_check(path: Path) -> bool:
    try:
        c = sqlite3.connect(readonly_uri(path), uri=True)
        try:
            return c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            c.close()
    except Exception:
        return False


def restore_database(backup_path: Path | str) -> bool:
    """Reemplaza la base viva por ``backup_path`` y guarda la anterior como ``<name>.before-restore``.

    **Sólo con la base sin conexiones abiertas** — hoy la llama únicamente
    ``apply_pending_restore`` al arrancar, antes de ``init_db``. Era el botón de Settings
    con la app corriendo, y con la base en WAL eso no funcionaba (tarea 278, medido): según
    el tamaño del WAL el restore se revertía solo al cerrar la app o dejaba la base
    corrupta, y el ``.before-restore`` —hecho con ``shutil.copy2``— perdía lo que estaba
    en el WAL. Las dos copias van ahora por la API de backup de SQLite.

    Devuelve True si la base quedó igual al backup y pasa ``quick_check``.
    """
    try:
        backup = Path(backup_path)
        if not backup.exists() or not backup.is_file():
            log.error("restore_database: %s does not exist", backup)
            return False
        if not _quick_check(backup):
            log.error("restore_database: %s no pasa quick_check — no se restaura", backup)
            return False
        live = Path(DB_PATH)
        if live.exists():
            rollback = live.with_suffix(live.suffix + ".before-restore")
            if rollback.exists():
                rollback.unlink()
            _sqlite_copy(live, rollback)
            log.info("Existing DB saved to %s before restore", rollback)
        _sqlite_copy(backup, live)
        if not _quick_check(live):
            log.error("restore_database: la base restaurada no pasa quick_check")
            return False
        log.info("Database restored from %s", backup)
        return True
    except Exception:
        log.exception("restore_database failed")
        return False


# ── Restore programado (tarea 278) ──────────────────────────────────────────


def _pending_marker() -> Path:
    """Marcador del restore pendiente, al lado de la base viva."""
    live = Path(DB_PATH)
    return live.with_name(live.name + ".restore-pending")


def schedule_restore(backup_path: Path | str) -> bool:
    """Deja programado el restore de ``backup_path`` para el próximo arranque.

    Lo llama el botón de Settings. **No toca la base**: con la app corriendo hay
    conexiones abiertas y un WAL vivo, y copiar encima no restaura (tarea 278). El restore
    lo hace ``apply_pending_restore`` en ``main.py``, antes de abrir ninguna conexión.
    """
    backup = Path(backup_path)
    if not backup.is_file() or not _quick_check(backup):
        log.error("schedule_restore: %s no existe o no pasa quick_check", backup)
        return False
    try:
        _pending_marker().write_text(str(backup.resolve()), encoding="utf-8")
    except Exception:
        log.exception("schedule_restore: no se pudo escribir el marcador")
        return False
    log.info("Restore programado para el próximo arranque: %s", backup)
    return True


def pending_restore() -> Path | None:
    """El backup que quedó programado, o ``None``."""
    m = _pending_marker()
    if not m.exists():
        return None
    try:
        return Path(m.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def apply_pending_restore() -> Path | None:
    """Ejecuta el restore programado, si hay uno. Va en ``main.py`` **antes** de ``init_db``.

    Devuelve el backup restaurado, o ``None`` si no había nada o falló. Si falla, el
    marcador se renombra a ``.failed`` para no reintentar en cada arranque, y la base queda
    como estaba (el ``.before-restore`` se escribe antes de tocarla).
    """
    m = _pending_marker()
    if not m.exists():
        return None
    backup = pending_restore()
    ok = backup is not None and restore_database(backup)
    try:
        if ok:
            m.unlink()
        else:
            m.replace(m.with_name(m.name + ".failed"))
    except Exception:
        log.exception("apply_pending_restore: no se pudo limpiar el marcador")
    if ok:
        log.warning("Restore programado aplicado al arrancar: %s", backup)
        return backup
    log.error("Restore programado FALLÓ (%s): la base queda como estaba", backup)
    return None


# ── Backup antes de migrar (tarea 278, [B-2]) ───────────────────────────────


def migration_pending(db_path: Path | str | None = None) -> bool:
    """True si la base tiene ``alembic_version`` y no está en el head de los scripts.

    Una base nueva (sin ``alembic_version``) no cuenta: no hay nada que proteger.
    """
    path = Path(db_path) if db_path is not None else Path(DB_PATH)
    if not path.exists():
        return False
    try:
        c = sqlite3.connect(readonly_uri(path), uri=True)
        try:
            fila = c.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            c.close()
    except sqlite3.Error:
        return False
    if not fila:
        return False
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    return fila[0] != ScriptDirectory.from_config(cfg).get_current_head()


def backup_if_migration_pending() -> Path | None:
    """Backup ``pre-migration`` si ``init_db`` va a migrar. Va en ``main.py`` antes de ``init_db``.

    El backup diario se toma **después** de ``init_db`` y una vez por día: una migración nueva
    corría sin copia tomada justo antes, y si fallaba la app no arrancaba y el backup del día
    no se tomaba nunca. Best-effort: un error se loguea y el arranque sigue.
    """
    try:
        if migration_pending():
            return backup_database(reason="pre-migration")
    except Exception:
        log.exception("backup_if_migration_pending failed")
    return None
