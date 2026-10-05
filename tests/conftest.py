"""Keep foundation tests independent of local environment settings."""

import os
import subprocess
from pathlib import Path

import pytest

from attendee.config.settings import Settings
from attendee.persistence.database import create_engine, create_session_factory


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "DATABASE_URL",
        "APP_TIMEZONE",
        "BOOTSTRAP_ADMIN_IDS",
        "LOG_LEVEL",
        "BACKUP_DIR",
        "SQLITE_BUSY_TIMEOUT_MS",
        "BOT_ORGANIZATION",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


ROOT = Path(__file__).resolve().parents[1]


def run_alembic(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / ".venv/bin/alembic"), "-c", str(ROOT / "alembic.ini"), *arguments],
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}"},
        capture_output=True,
        text=True,
    )


@pytest.fixture
def migrated_settings(tmp_path):
    database = tmp_path / "identity.db"
    result = run_alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    return Settings(database_url=f"sqlite+aiosqlite:///{database}")


@pytest.fixture
async def session_factory(migrated_settings):
    engine = create_engine(migrated_settings)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
