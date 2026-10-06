import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from attendee.config.settings import Settings
from attendee.persistence.base import Base
from attendee.persistence.database import create_engine, create_session_factory, write_session


async def test_connections_and_sessions(tmp_path):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    engine = create_engine(settings)
    try:
        async with engine.connect() as first, engine.connect() as second:
            for connection in (first, second):
                assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
                assert await connection.scalar(text("PRAGMA journal_mode")) == "wal"
                assert await connection.scalar(text("PRAGMA busy_timeout")) == 5000
        factory = create_session_factory(engine)
        async with factory.begin() as session:
            await session.execute(text("CREATE TABLE foundation_probe (id INTEGER PRIMARY KEY)"))
            await session.execute(text("INSERT INTO foundation_probe VALUES (1)"))
        with pytest.raises(RuntimeError):
            async with factory.begin() as session:
                await session.execute(text("INSERT INTO foundation_probe VALUES (2)"))
                raise RuntimeError("rollback")
        async with factory() as session:
            assert await session.scalar(text("SELECT count(*) FROM foundation_probe")) == 1
    finally:
        await engine.dispose()
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT id FROM foundation_probe").fetchall() == [(1,)]


async def test_foreign_keys_enforced(tmp_path):
    engine = create_engine(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}"))
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
            await connection.execute(
                text("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))")
            )
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(text("INSERT INTO child VALUES (9)"))
    finally:
        await engine.dispose()


def test_metadata_has_all_tables():
    from attendee.persistence import models  # noqa: F401

    assert set(Base.metadata.tables) == {
        "groups",
        "people",
        "unresolved_matches",
        "session_publications",
        "attendance_series",
        "attendance_sessions",
        "session_roster_entries",
        "session_responses",
        "session_response_events",
    }


async def test_write_session_begins_immediate(tmp_path):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'lock.db'}")
    engine = create_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory.begin() as session:
            await session.execute(text("CREATE TABLE lock_probe (id INTEGER)"))
        async with write_session(factory) as session:
            await session.execute(text("SELECT 1"))
            # The write lock is held before any write, so another writer cannot start.
            other = sqlite3.connect(settings.database_path, timeout=0)
            try:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    other.execute("BEGIN IMMEDIATE")
            finally:
                other.close()
            await session.execute(text("INSERT INTO lock_probe VALUES (1)"))
        with pytest.raises(RuntimeError):
            async with write_session(factory) as session:
                await session.execute(text("INSERT INTO lock_probe VALUES (2)"))
                raise RuntimeError("rollback")
        async with factory() as session:
            assert await session.scalar(text("SELECT count(*) FROM lock_probe")) == 1
    finally:
        await engine.dispose()


async def test_schema_transaction_rolls_back(tmp_path):
    engine = create_engine(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'ddl.db'}"))
    try:
        with pytest.raises(RuntimeError):
            async with engine.begin() as connection:
                await connection.execute(text("CREATE TABLE rollback_probe (id INTEGER)"))
                raise RuntimeError("failed migration")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM sqlite_master WHERE name='rollback_probe'")
                )
                == 0
            )
    finally:
        await engine.dispose()
