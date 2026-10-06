import os
import sqlite3
import subprocess
from contextlib import closing

from conftest import ROOT, run_alembic

HEAD_TABLES = {
    "groups",
    "people",
    "unresolved_matches",
    "attendance_series",
    "attendance_sessions",
    "session_roster_entries",
    "session_publications",
    "session_responses",
    "session_response_events",
    "alembic_version",
}


def tables(database):
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {name for (name,) in rows}


def test_fresh_and_repeated_upgrade(tmp_path):
    database = tmp_path / "migration.db"
    for _ in range(2):
        result = run_alembic(database, "upgrade", "head")
        assert result.returncode == 0, result.stderr
    assert tables(database) == HEAD_TABLES
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            ("0001_groups",)
        ]


def test_upgrade_from_empty_foundation(tmp_path):
    # The foundation upgrade created only an empty alembic_version table.
    database = tmp_path / "foundation.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
        connection.commit()
    result = run_alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert tables(database) == HEAD_TABLES


def test_database_from_replaced_revisions_stops(tmp_path):
    """The 0001_groups baseline replaced 0001_identity to 0007 (decision T86).

    A database that an old revision created holds no live data. Alembic refuses it, so the
    entry point stops before the bot starts. Delete that database and upgrade again.
    """
    database = tmp_path / "old.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('0007_session_responses')")
        connection.commit()
    result = run_alembic(database, "upgrade", "head")
    assert result.returncode != 0
    assert "0007_session_responses" in result.stderr


def test_models_match_migration_and_downgrade(tmp_path):
    database = tmp_path / "check.db"
    assert run_alembic(database, "upgrade", "head").returncode == 0
    result = run_alembic(database, "check")
    assert result.returncode == 0, result.stdout + result.stderr
    result = run_alembic(database, "downgrade", "base")
    assert result.returncode == 0, result.stderr
    assert tables(database) == {"alembic_version"}


def test_failed_revision_rolls_back_schema(tmp_path):
    import shutil

    scripts = tmp_path / "alembic"
    shutil.copytree(ROOT / "alembic", scripts)
    (scripts / "versions" / "failure.py").write_text(
        "from alembic import op\n"
        'revision = "failure"\n'
        'down_revision = "0001_groups"\n'
        "def upgrade():\n"
        '    op.execute("CREATE TABLE migration_probe (id INTEGER)")\n'
        '    raise RuntimeError("deliberate migration failure")\n'
        "def downgrade():\n"
        "    pass\n"
    )
    configuration = tmp_path / "alembic.ini"
    configuration.write_text(f"[alembic]\nscript_location = {scripts}\n")
    database = tmp_path / "failed.db"
    result = subprocess.run(
        [str(ROOT / ".venv/bin/alembic"), "-c", str(configuration), "upgrade", "head"],
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "deliberate migration failure" in result.stderr
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='migration_probe'"
            ).fetchall()
            == []
        )
        # One transaction covers every pending revision, so 0001_groups also rolls back.
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name='people'").fetchall()
            == []
        )
