import os
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_empty_migrations_are_repeatable(tmp_path):
    database = tmp_path / "migration.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}"}
    for _ in range(2):
        result = subprocess.run(
            [str(ROOT / ".venv/bin/alembic"), "-c", str(ROOT / "alembic.ini"), "upgrade", "head"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert set(tables) <= {("alembic_version",)}
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)


def test_failed_revision_rolls_back_schema(tmp_path):
    import shutil

    scripts = tmp_path / "alembic"
    shutil.copytree(ROOT / "alembic", scripts)
    (scripts / "versions" / "failure.py").write_text(
        "from alembic import op\n"
        'revision = "failure"\n'
        "down_revision = None\n"
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
