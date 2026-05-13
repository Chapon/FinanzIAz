"""
Tests for ``database.backup``.

Verifies the backup→list→rotate→restore lifecycle. Uses the in-memory
``test_db`` fixture indirectly: we create a *real* on-disk SQLite file in
``tmp_path`` and monkey-patch ``DB_PATH`` so the backup utility writes its
snapshots next to the test DB instead of the user's ``~/.finanzias``.
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def real_db(tmp_path, monkeypatch):
    """
    Create a real SQLite file at ``tmp_path/finanzias.db`` and rebind
    ``database.backup`` constants to point there. Returns the Path.
    """
    db_path = tmp_path / "finanzias.db"
    # Create a tiny schema so the backup has actual content to copy.
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE foo (id INTEGER PRIMARY KEY, val TEXT);
        INSERT INTO foo (val) VALUES ('hello'), ('world');
    """)
    conn.commit()
    conn.close()

    # Re-point the backup module's constants to the temp dir.
    import database.backup as bk

    monkeypatch.setattr(bk, "DB_PATH", str(db_path))
    monkeypatch.setattr(bk, "DB_DIR", db_path.parent)
    monkeypatch.setattr(bk, "BACKUP_DIR", db_path.parent / "backups")
    monkeypatch.setattr(bk, "DB_STEM", db_path.stem)
    return db_path


def test_backup_database_creates_file(real_db):
    from database.backup import backup_database, list_backups

    out = backup_database(reason="manual")
    assert out is not None
    assert out.exists()
    assert "manual" in out.name
    assert out.stat().st_size > 0
    assert len(list_backups()) == 1


def test_backup_skips_when_source_missing(tmp_path, monkeypatch):
    """When the live DB doesn't exist, backup logs and returns None — no crash."""
    import database.backup as bk

    monkeypatch.setattr(bk, "DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setattr(bk, "DB_DIR", tmp_path)
    monkeypatch.setattr(bk, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(bk, "DB_STEM", "missing")
    assert bk.backup_database() is None


def test_rotate_backups_keeps_last_n(real_db):
    from database.backup import backup_database, list_backups, rotate_backups

    # Create 5 backups with slightly different filenames (artificially staggered)
    for i in range(5):
        # Sleep is unnecessary because backup_database() embeds a fresh
        # timestamp every call — but two backups taken in the same second
        # would collide. Force unique by renaming.
        out = backup_database(reason=f"r{i}")
        assert out is not None

    assert len(list_backups()) == 5
    deleted = rotate_backups(keep=3)
    assert deleted == 2
    assert len(list_backups()) == 3


def test_rotate_backups_no_op_when_under_limit(real_db):
    from database.backup import backup_database, rotate_backups

    backup_database(reason="only-one")
    deleted = rotate_backups(keep=10)
    assert deleted == 0


def test_restore_database_preserves_rollback(real_db):
    """After restore, the previous live DB is preserved as <name>.before-restore."""
    from database.backup import backup_database, restore_database

    # 1. Take a backup of the original DB.
    snap = backup_database(reason="snap")
    assert snap is not None

    # 2. Modify the live DB so we can detect whether the restore worked.
    conn = sqlite3.connect(str(real_db))
    conn.execute("INSERT INTO foo (val) VALUES ('AFTER_BACKUP')")
    conn.commit()
    conn.close()

    # Sanity: the modification is in the live DB.
    conn = sqlite3.connect(str(real_db))
    rows_before_restore = [r[0] for r in conn.execute("SELECT val FROM foo").fetchall()]
    conn.close()
    assert "AFTER_BACKUP" in rows_before_restore

    # 3. Restore from the snapshot.
    assert restore_database(snap) is True

    # 4. Live DB no longer has the modification.
    conn = sqlite3.connect(str(real_db))
    rows_after_restore = [r[0] for r in conn.execute("SELECT val FROM foo").fetchall()]
    conn.close()
    assert "AFTER_BACKUP" not in rows_after_restore

    # 5. The pre-restore safety copy exists.
    rollback = real_db.with_suffix(real_db.suffix + ".before-restore")
    assert rollback.exists()


def test_restore_missing_file_returns_false(tmp_path, real_db):
    from database.backup import restore_database

    assert restore_database(tmp_path / "nope.db") is False
