"""SQLite engine and session construction."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from attendee.config.settings import Settings

_BEGIN_OPTION = "attendee_sqlite_begin"


def create_engine(settings: Settings) -> AsyncEngine:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        settings.database_url,
        connect_args={"timeout": settings.sqlite_busy_timeout_ms / 1000},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def configure_connection(connection: DBAPIConnection, _: ConnectionPoolEntry) -> None:
        # Let SQLAlchemy own BEGIN, including DDL and savepoints.
        connection.isolation_level = None
        cursor = connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout = {settings.sqlite_busy_timeout_ms}")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def begin_transaction(connection: Connection) -> None:
        if connection.get_execution_options().get(_BEGIN_OPTION) == "IMMEDIATE":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.exec_driver_sql("BEGIN")

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def write_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Run one transaction that takes the SQLite write lock at BEGIN.

    A deferred transaction that reads and then writes fails at once if another writer committed
    first. BEGIN IMMEDIATE makes the second writer wait for the busy timeout instead.
    The transaction commits on success and rolls back on any exception.
    """
    async with session_factory() as session:
        await session.connection(execution_options={_BEGIN_OPTION: "IMMEDIATE"})
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        await session.commit()
