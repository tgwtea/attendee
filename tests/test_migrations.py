import os
import sqlite3
import subprocess
from contextlib import closing

import pytest
from conftest import ROOT, run_alembic

ATTENDANCE_TABLES = {"attendance_series", "attendance_sessions", "session_roster_entries"}
IDENTITY_TABLES = {"organizations", "people", "memberships", "unresolved_matches"}


def tables(database):
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {name for (name,) in rows}


def test_fresh_and_repeated_upgrade(tmp_path):
    database = tmp_path / "migration.db"
    for _ in range(2):
        result = run_alembic(database, "upgrade", "head")
        assert result.returncode == 0, result.stderr
    assert tables(database) == IDENTITY_TABLES | ATTENDANCE_TABLES | {"alembic_version"}
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            ("0004_attendance",)
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
    assert tables(database) == IDENTITY_TABLES | ATTENDANCE_TABLES | {"alembic_version"}


def test_upgrade_from_identity_normalizes_handles(tmp_path):
    database = tmp_path / "identity.db"
    assert run_alembic(database, "upgrade", "0001_identity").returncode == 0
    with closing(sqlite3.connect(database)) as connection:
        connection.executemany(
            "INSERT INTO people (display_name, telegram_handle, created_at, updated_at) "
            "VALUES (?, ?, '2026-10-04 00:00:00', '2026-10-04 00:00:00')",
            [("A", " @SarahLim "), ("B", "@a"), ("C", None), ("D", "johntan")],
        )
        connection.commit()
    result = run_alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert tables(database) == IDENTITY_TABLES | ATTENDANCE_TABLES | {"alembic_version"}
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute(
            "SELECT display_name, telegram_handle FROM people ORDER BY id"
        ).fetchall()
    assert rows == [("A", "sarahlim"), ("B", None), ("C", None), ("D", "johntan")]
    result = run_alembic(database, "downgrade", "0001_identity")
    assert result.returncode == 0, result.stderr
    assert tables(database) == IDENTITY_TABLES - {"unresolved_matches"} | {"alembic_version"}


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
        'down_revision = "0004_attendance"\n'
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
        # One transaction covers every pending revision, so 0001 also rolls back.
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name='people'").fetchall()
            == []
        )


def test_candidate_rejected_reason_upgrade_and_downgrade(tmp_path):
    database = tmp_path / "reason.db"
    assert run_alembic(database, "upgrade", "0002_import_matching").returncode == 0
    insert = (
        "INSERT INTO unresolved_matches (organization_id, telegram_user_id, reason, "
        "created_at, updated_at) VALUES (1, ?, ?, '2026-10-04 00:00:00', '2026-10-04 00:00:00')"
    )
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "INSERT INTO organizations (slug, name, created_at) "
            "VALUES ('club', 'Club', '2026-10-04 00:00:00')"
        )
        connection.execute(insert, (5, "ambiguous"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, (6, "candidate_rejected"))
        connection.commit()
    result = run_alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(insert, (6, "candidate_rejected"))
        connection.commit()
    result = run_alembic(database, "downgrade", "0002_import_matching")
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute(
            "SELECT telegram_user_id, reason FROM unresolved_matches ORDER BY id"
        ).fetchall()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert rows == [(5, "ambiguous"), (6, "no_match")]


def test_attendance_upgrade_downgrade_preserves_identity(tmp_path):
    database = tmp_path / "attendance-upgrade.db"
    assert run_alembic(database, "upgrade", "0003_candidate_rejected").returncode == 0
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO organizations (id,slug,name,created_at) "
            "VALUES (1,'club','Club','2026-10-05 00:00:00')"
        )
        connection.execute(
            "INSERT INTO people (id,display_name,created_at,updated_at) "
            "VALUES (1,'Admin','2026-10-05 00:00:00','2026-10-05 00:00:00')"
        )
        connection.execute(
            "INSERT INTO memberships (organization_id,person_id,role,created_at,updated_at) "
            "VALUES (1,1,'admin','2026-10-05 00:00:00','2026-10-05 00:00:00')"
        )
        connection.commit()
    result = run_alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for table in ATTENDANCE_TABLES:
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
        connection.execute(
            "INSERT INTO attendance_series "
            "(id,organization_id,name,normalized_name,created_by,created_at) "
            "VALUES (1,1,'Practice','practice',1,'2026-10-05 00:00:00')"
        )
        connection.execute(
            "INSERT INTO attendance_sessions "
            "(id,organization_id,series_id,session_date,deadline,status,"
            "created_by,created_at,creation_key,request_fingerprint) "
            "VALUES (1,1,1,'2026-10-13','2026-10-12 12:00:00','draft',1,"
            "'2026-10-05 00:00:00','request-key','fingerprint')"
        )
        connection.execute(
            "INSERT INTO session_roster_entries "
            "(organization_id,session_id,person_id) VALUES (1,1,1)"
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.commit()
    assert run_alembic(database, "check").returncode == 0
    result = run_alembic(database, "downgrade", "0003_candidate_rejected")
    assert result.returncode == 0, result.stderr
    assert tables(database) == IDENTITY_TABLES | {"alembic_version"}
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT display_name FROM people").fetchall() == [("Admin",)]
        assert connection.execute("SELECT role FROM memberships").fetchall() == [("admin",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert run_alembic(database, "upgrade", "head").returncode == 0
    assert run_alembic(database, "check").returncode == 0
