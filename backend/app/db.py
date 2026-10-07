from datetime import UTC, datetime

from sqlalchemy import DateTime, Engine, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetime that is always UTC on both sides of the driver.

    PostgreSQL keeps the offset in timestamptz, SQLite drops it, so values are normalised to UTC
    on the way in and tagged as UTC on the way out. Naive values are rejected instead of guessed.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to a UTC column")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def normalize_url(url: str) -> str:
    """Accept plain libpq URLs, such as the `uri` key CloudNativePG puts in its app secret,
    and point them at the psycopg 3 driver this project installs."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def make_engine(url: str) -> Engine:
    url = normalize_url(url)
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)

    # SQLite is only used by the test suite and for local experiments.
    if url in ("sqlite://", "sqlite:///:memory:"):
        # One shared connection, otherwise every pooled connection gets its own empty database.
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        engine = create_engine(url)
    _fix_sqlite_transactions(engine)
    return engine


def _fix_sqlite_transactions(engine: Engine) -> None:
    """Let SQLAlchemy, not the sqlite3 driver, decide when transactions begin.

    The driver's implicit BEGIN handling breaks SAVEPOINT, which the code relies on. This is the
    workaround from the SQLAlchemy documentation for pysqlite.
    """

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def _on_begin(connection):
        connection.exec_driver_sql("BEGIN")


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
