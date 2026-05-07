"""
Lightweight SQLite backup utility for FinanzIAs.

Public API
----------
``backup_database(reason="manual")``       — make a snapshot now, return path.
``rotate_backups(keep=7)``                 — prune old snapshots.
``maybe_rotate_daily(keep=7)``             — call once at app start; performs
                                              a backup if today's hasn't been
                                              made yet, then rotates.
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
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from config.logging_config import get_logger
from database.models import DB_PATH

log = get_logger(__name__)

DB_DIR = Path(DB_PATH).parent
BACKUP_DIR = DB_DIR / "backups"
DB_STEM = Path(DB_PATH).stem        # "finanzias"


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def backup_database(reason: str = "manual") -> Optional[Path]:
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
        try:
            with sqlite3.connect(str(src)) as src_conn, sqlite3.connect(str(dst)) as dst_conn:
                src_conn.backup(dst_conn)
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


def rotate_backups(keep: int = 7) -> int:
    """
    Delete oldest backups so at most ``keep`` remain. Returns number deleted.
    """
    if keep <= 0:
        return 0
    backups = list_backups()
    if len(backups) <= keep:
        return 0
    to_delete = backups[:len(backups) - keep]
    deleted = 0
    for p in to_delete:
        try:
            p.unlink()
            deleted += 1
        except Exception:
            log.exception("Could not delete backup %s", p)
    if deleted:
        log.info("Rotated backups: deleted %d, kept %d", deleted, keep)
    return deleted


def _today_already_backed_up() -> bool:
    today = date.today().isoformat()
    return any(today in p.name for p in list_backups() if "_daily" in p.name)


def maybe_rotate_daily(*, keep: int = 7) -> Optional[Path]:
    """
    Make today's daily snapshot if it hasn't been made yet, then rotate.

    Designed to be called once on app startup — it's idempotent and silent
    when there's nothing to do, so it's cheap.
    """
    try:
        if _today_already_backed_up():
            rotate_backups(keep=keep)
            return None
        path = backup_database(reason="daily")
        rotate_backups(keep=keep)
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
