import fcntl
import sqlite3
from contextlib import closing

import pytest

from attendee.backup import backup_database
from attendee.config.settings import Settings


def make_settings(tmp_path):
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'source.db'}",
        backup_dir=tmp_path / "backups",
    )


def test_backup_includes_wal_and_keeps_latest_14(tmp_path):
    settings = make_settings(tmp_path)
    with closing(sqlite3.connect(settings.database_path)) as source:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("PRAGMA wal_autocheckpoint=0")
        source.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
        source.execute("INSERT INTO probe VALUES (42)")
        source.commit()
        assert settings.database_path.with_suffix(".db-wal").exists()
        settings.backup_dir.mkdir()
        unrelated = settings.backup_dir / "other.sqlite3"
        unrelated.write_text("preserve")
        for _ in range(16):
            backup = backup_database(settings)
        assert len(list(settings.backup_dir.glob("attendee-*.sqlite3"))) == 14
        assert unrelated.read_text() == "preserve"
        with closing(sqlite3.connect(backup)) as reader:
            assert reader.execute("SELECT id FROM probe").fetchall() == [(42,)]
        assert not list(settings.backup_dir.glob("*.partial"))


def test_missing_source_does_not_create_database(tmp_path):
    settings = make_settings(tmp_path)
    with pytest.raises(FileNotFoundError):
        backup_database(settings)
    assert not settings.database_path.exists()


def test_failure_preserves_backups(tmp_path):
    settings = make_settings(tmp_path)
    settings.database_path.write_text("not a database")
    settings.backup_dir.mkdir()
    old = settings.backup_dir / "attendee-old.sqlite3"
    old.write_text("preserve")
    with pytest.raises(sqlite3.DatabaseError):
        backup_database(settings)
    assert old.read_text() == "preserve"
    assert not list(settings.backup_dir.glob("*.partial"))


def test_backup_lock_prevents_overlap(tmp_path):
    settings = make_settings(tmp_path)
    with closing(sqlite3.connect(settings.database_path)):
        pass
    settings.backup_dir.mkdir()
    with (settings.backup_dir / ".backup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            backup_database(settings)
