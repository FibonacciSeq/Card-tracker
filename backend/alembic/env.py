from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine, text

from alembic import context
from app import models  # noqa: F401
from app.config import settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

migration_url = settings.migration_database_url or settings.database_url
config.set_main_option("sqlalchemy.url", migration_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _widen_version_table(engine) -> None:
    """Allow revision identifiers longer than Alembic's default 32 characters.

    Earlier revisions already use a 38-character id
    (``0006_customer_notification_preferences``). Widening here fixes both
    fresh databases and existing ones before Alembic writes the next version.
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "version_num VARCHAR(64) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        connection.execute(
            text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")
        )


def run_migrations_online() -> None:
    engine = create_engine(migration_url, pool_pre_ping=True)
    _widen_version_table(engine)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
