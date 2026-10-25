from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from app import models  # noqa: F401  (registers tables on SQLModel.metadata)
from app.config import get_settings

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SQLModel.metadata


def run_migrations_online() -> None:
    # A separate engine WITHOUT the app's "PRAGMA foreign_keys=ON": SQLite batch migrations
    # rebuild tables (create copy, DROP old, rename), and with foreign keys on, dropping the old
    # table would cascade-delete every child row (tags, colors, photos).
    engine = create_engine(f"sqlite:///{get_settings().db_path}", poolclass=NullPool)
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.commit()  # end SQLAlchemy's autobegun transaction so Alembic owns (and commits) its own
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite needs batch mode for ALTER
        )
        with context.begin_transaction():
            context.run_migrations()
        problems = connection.execute(text("PRAGMA foreign_key_check")).fetchall()
        if problems:
            raise RuntimeError(f"foreign key check failed after migration: {problems[:5]}")
    engine.dispose()


run_migrations_online()
