from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import Settings
from app.schema import CURRENT_REVISION


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, settings: Settings):
        self.engine = create_engine(
            settings.sqlalchemy_url,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=5,
            isolation_level="READ COMMITTED",
            hide_parameters=True,
            connect_args={"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5},
        )
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self):
        # One Session per unit of work. Context exit commits or rolls back, then always closes.
        with self.sessions() as session, session.begin():
            yield session

    def ready(self):
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                return revision == CURRENT_REVISION
        except Exception:
            return False

    def close(self):
        self.engine.dispose()
