"""T7.3 — Tests de la migración catch-up 0004 y del sync alembic en init_db.

Cierra M1 del code review 2026-06-09: alembic vuelve a ser el único camino de
esquema. Verifica tres invariantes:

1. **Equivalencia**: una DB en estado-0003 real (sin las tablas T-CAT ni las
   columnas parchadas) que corre ``upgrade head`` termina con exactamente el
   mismo esquema (tablas, columnas, índices) que ``Base.metadata.create_all``.
2. **Idempotencia**: ``upgrade head`` sobre una DB ya-completa stampeada en
   0003 (el caso de la DB de producción) no rompe ni duplica nada.
3. **Onboarding**: ``_alembic_sync`` stampea ``head`` en una DB nueva (sin
   ``alembic_version``) y hace upgrade cuando la tabla existe.

Requiere alembic instalado (requirements.txt desde T7.3) y SQLite >= 3.35
para DROP COLUMN al fabricar el estado-0003.
"""

from __future__ import annotations

import sqlite3

import pytest
import sqlalchemy as sa

alembic = pytest.importorskip("alembic")

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

import paper_trading.models  # noqa: F401  — registra tablas paper en Base.metadata
from alembic import command
from database import models as db_models
from database.models import Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Delta que 0004 debe cubrir (mantener en sync con la docstring de 0004).
POST_0003_TABLES = ("earnings_cache", "analyst_data_cache", "news_events", "analyst_estimate_snapshots")
POST_0003_COLUMNS = (
    ("paper_accounts", "slack_notify"),
    ("paper_equity_snapshots", "portfolio_sigma"),
    ("positions", "purchase_date"),
)

_SQLITE_SUPPORTS_DROP_COLUMN = sqlite3.sqlite_version_info >= (3, 35, 0)


def _cfg(db_path) -> Config:
    """Config programático apuntando a una DB temporal (mismo patrón que _alembic_sync)."""
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _head(cfg: Config) -> str:
    """Revisión head actual del timeline — los tests no hardcodean '000X'."""
    return ScriptDirectory.from_config(cfg).get_current_head()


def _schema_snapshot(engine) -> dict:
    """{tabla: (set(columnas), set(índices))} ignorando housekeeping de alembic/sqlite."""
    insp = sa.inspect(engine)
    snap = {}
    for t in insp.get_table_names():
        if t in ("alembic_version", "sqlite_sequence"):
            continue
        cols = {c["name"] for c in insp.get_columns(t)}
        idxs = {
            i["name"]
            for i in insp.get_indexes(t)
            if i["name"] and not i["name"].startswith("sqlite_autoindex")
        }
        snap[t] = (cols, idxs)
    return snap


def _fresh_full_db(path):
    """DB con el esquema actual completo vía create_all (la referencia)."""
    engine = sa.create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine


def _rev0003_db(path):
    """Fabrica una DB en estado-0003: esquema actual MENOS el delta de 0004."""
    engine = _fresh_full_db(path)
    with engine.begin() as conn:
        for t in POST_0003_TABLES:
            conn.execute(sa.text(f"DROP TABLE {t}"))
        for table, col in POST_0003_COLUMNS:
            conn.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN {col}"))
    command.stamp(_cfg(path), "0003")
    return engine


@pytest.mark.skipif(not _SQLITE_SUPPORTS_DROP_COLUMN, reason="SQLite < 3.35: sin DROP COLUMN")
def test_upgrade_from_0003_reaches_create_all_schema(tmp_path):
    """upgrade head desde estado-0003 == esquema de create_all (tablas+columnas+índices)."""
    ref_engine = _fresh_full_db(tmp_path / "ref.db")
    mig_path = tmp_path / "mig.db"
    mig_engine = _rev0003_db(mig_path)

    # Sanity: el estado-0003 de verdad NO tiene el delta.
    pre = _schema_snapshot(mig_engine)
    for t in POST_0003_TABLES:
        assert t not in pre
    assert "slack_notify" not in pre["paper_accounts"][0]

    command.upgrade(_cfg(mig_path), "head")

    assert _schema_snapshot(mig_engine) == _schema_snapshot(ref_engine)


def test_upgrade_is_idempotent_on_complete_db(tmp_path):
    """El caso producción: DB completa stampeada en 0003 → upgrade head es no-op seguro."""
    path = tmp_path / "prod.db"
    engine = _fresh_full_db(path)
    command.stamp(_cfg(path), "0003")
    before = _schema_snapshot(engine)

    command.upgrade(_cfg(path), "head")  # 0004/0005 corren con guards → sin DDL
    command.upgrade(_cfg(path), "head")  # ya en head → no-op

    assert _schema_snapshot(engine) == before
    with engine.connect() as conn:
        rev = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert rev == _head(_cfg(path))


def test_alembic_sync_stamps_fresh_db(tmp_path):
    """DB nueva (sin alembic_version): _alembic_sync stampea head, no corre DDL."""
    path = tmp_path / "fresh.db"
    engine = _fresh_full_db(path)
    assert not sa.inspect(engine).has_table("alembic_version")

    db_models._alembic_sync(engine=engine, db_path=str(path))

    with engine.connect() as conn:
        rev = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert rev == _head(_cfg(path))


def test_alembic_sync_upgrades_stamped_db(tmp_path):
    """DB existente stampeada atrás: _alembic_sync la lleva a head."""
    if not _SQLITE_SUPPORTS_DROP_COLUMN:
        pytest.skip("SQLite < 3.35: sin DROP COLUMN")
    path = tmp_path / "old.db"
    engine = _rev0003_db(path)

    db_models._alembic_sync(engine=engine, db_path=str(path))

    insp = sa.inspect(engine)
    assert insp.has_table("news_events")
    assert any(c["name"] == "slack_notify" for c in insp.get_columns("paper_accounts"))
    with engine.connect() as conn:
        rev = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert rev == _head(_cfg(path))


@pytest.mark.skipif(not _SQLITE_SUPPORTS_DROP_COLUMN, reason="SQLite < 3.35: sin DROP COLUMN")
def test_downgrade_0004_removes_delta(tmp_path):
    """downgrade 0003 revierte el delta (simétrico, también con guards)."""
    path = tmp_path / "down.db"
    engine = _rev0003_db(path)
    cfg = _cfg(path)
    command.upgrade(cfg, "head")

    command.downgrade(cfg, "0003")

    insp = sa.inspect(engine)
    for t in POST_0003_TABLES:
        assert not insp.has_table(t)
    assert not any(c["name"] == "slack_notify" for c in insp.get_columns("paper_accounts"))


# ── 0005: news_events.classified_by (T7.4) ───────────────────────────────────


@pytest.mark.skipif(not _SQLITE_SUPPORTS_DROP_COLUMN, reason="SQLite < 3.35: sin DROP COLUMN")
def test_upgrade_from_0004_adds_classified_by(tmp_path):
    """DB en estado-0004 real (sin classified_by) → upgrade head agrega la columna."""
    path = tmp_path / "v4.db"
    engine = _fresh_full_db(path)
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE news_events DROP COLUMN classified_by"))
    command.stamp(_cfg(path), "0004")

    command.upgrade(_cfg(path), "head")

    insp = sa.inspect(engine)
    assert any(c["name"] == "classified_by" for c in insp.get_columns("news_events"))


def test_0005_is_idempotent_when_column_exists(tmp_path):
    """DB completa (create_all ya trae classified_by) stampeada en 0004 → guard salta el DDL."""
    path = tmp_path / "v4full.db"
    engine = _fresh_full_db(path)
    command.stamp(_cfg(path), "0004")
    before = _schema_snapshot(engine)

    command.upgrade(_cfg(path), "head")

    assert _schema_snapshot(engine) == before


# ── 0008: alerts.is_paused (ALRT1) ───────────────────────────────────────────


@pytest.mark.skipif(not _SQLITE_SUPPORTS_DROP_COLUMN, reason="SQLite < 3.35: sin DROP COLUMN")
def test_upgrade_from_0007_adds_is_paused(tmp_path):
    """DB en estado-0007 real (sin is_paused) → upgrade head agrega la columna."""
    path = tmp_path / "v7.db"
    engine = _fresh_full_db(path)
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE alerts DROP COLUMN is_paused"))
    command.stamp(_cfg(path), "0007")

    command.upgrade(_cfg(path), "head")

    insp = sa.inspect(engine)
    assert any(c["name"] == "is_paused" for c in insp.get_columns("alerts"))


def test_0008_is_idempotent_when_column_exists(tmp_path):
    """DB completa (create_all ya trae is_paused) stampeada en 0007 → guard salta el DDL."""
    path = tmp_path / "v7full.db"
    engine = _fresh_full_db(path)
    command.stamp(_cfg(path), "0007")
    before = _schema_snapshot(engine)

    command.upgrade(_cfg(path), "head")

    assert _schema_snapshot(engine) == before
