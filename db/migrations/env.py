import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Append project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from db.session import Base
from shared.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject database URL: prefer CLI -x argument, environment variables, or programmatic override
x_args = context.get_x_argument(as_dictionary=True)
if "sqlalchemy.url" in x_args:
    config.set_main_option("sqlalchemy.url", x_args["sqlalchemy.url"])
elif "DATABASE_SYNC_URL" in os.environ:
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_SYNC_URL"])
elif "DATABASE_URL" in os.environ:
    sync_url = os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    config.set_main_option("sqlalchemy.url", sync_url)
else:
    current_url = config.get_main_option("sqlalchemy.url")
    if not current_url or current_url == "postgresql://mirage:mirage_dev_secret@localhost:5432/mirage_db":
        settings = get_settings()
        config.set_main_option("sqlalchemy.url", settings.database_sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
