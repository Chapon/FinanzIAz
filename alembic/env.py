"""
Alembic environment.

This file is invoked by ``alembic <command>``. We import the project's
``database.models`` (and ``paper_trading.models`` so its tables register on
the same Base.metadata) and point the migration runner at the live SQLite
file via ``DB_PATH``.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make ``database`` / ``paper_trading`` importable when alembic runs from
# the project root.
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database.models import Base, DB_PATH  # noqa: E402
import paper_trading.models  # noqa: E402, F401  — registers paper-trading tables

config = context.config

# Inject the runtime DB URL (overrides alembic.ini's empty `sqlalchemy.url`).
config.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite-specific niceties:
        render_as_batch=True,         # required for SQLite ALTER support
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — opens a connection to the DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
