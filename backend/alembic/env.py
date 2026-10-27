from sqlalchemy import inspect

from alembic import context
from app.auth import models  # noqa: F401
from app.core.config import get_settings
from app.db import Base, Database

target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        url=get_settings().sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    db = Database(get_settings())
    try:
        with db.engine.connect() as connection:
            tables = inspect(connection).get_table_names()
            if tables and "alembic_version" not in tables:
                raise RuntimeError("Refusing to migrate a nonempty, unmanaged database")
            # End the read-only inspection transaction before Alembic owns its transaction.
            connection.rollback()
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        db.close()
