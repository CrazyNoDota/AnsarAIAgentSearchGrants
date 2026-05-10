import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database.connection import Base
from core.config import get_settings

# Import all models so autogenerate picks them up
import models  # noqa: F401

config = context.config
settings = get_settings()

# Migrations must run against the *direct* Postgres connection
# (Supabase port 5432). The pgbouncer pooler at 6543 cannot run DDL
# with asyncpg's prepared statements. DIRECT_URL takes precedence here.
def _migration_url() -> str:
    direct = os.getenv("DIRECT_URL", "")
    if direct:
        if direct.startswith("postgresql://"):
            return "postgresql+asyncpg://" + direct[len("postgresql://"):]
        if direct.startswith("postgres://"):
            return "postgresql+asyncpg://" + direct[len("postgres://"):]
        return direct
    return settings.database_url


# `%` is the ConfigParser interpolation char — escape any percent signs that
# come from URL-encoded passwords (e.g. "%21" for "!").
config.set_main_option("sqlalchemy.url", _migration_url().replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
