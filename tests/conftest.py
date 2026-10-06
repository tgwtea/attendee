"""Keep foundation tests independent of local environment settings."""

import os
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from attendee.config.settings import Settings
from attendee.domain import attendance as attendance_domain
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


REAL_ARCHIVE_AFTER = attendance_domain.ARCHIVE_AFTER


@pytest.fixture(autouse=True)
def no_archive_by_default(monkeypatch):
    """Fixtures use fixed 2026 deadlines, and services read the real clock.

    Without this, every test that reaches an archive check would fail 7 days after those
    deadlines. Tests of archiving request the `archive_after` fixture instead.
    """
    monkeypatch.setattr(attendance_domain, "ARCHIVE_AFTER", timedelta(days=365 * 100))


@pytest.fixture
def archive_after(monkeypatch):
    """Restore the real archive delay for this test. Pass explicit times to the services."""
    monkeypatch.setattr(attendance_domain, "ARCHIVE_AFTER", REAL_ARCHIVE_AFTER)
    return REAL_ARCHIVE_AFTER


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


@pytest.fixture
async def attendance_club(session_factory):
    from attendee.application.attendance import AttendanceService
    from attendee.application.identity import IdentityService
    from attendee.application.memberships import MembershipService
    from attendee.application.organizations import OrganizationService
    from attendee.domain.identity import MembershipRole

    org = await OrganizationService(session_factory).create_organization("club", "Club")
    identity = IdentityService(session_factory)
    memberships = MembershipService(session_factory)
    admin = await identity.create_person("Admin", 1001)
    member = await identity.create_person("Member")
    await memberships.add_membership(org.id, admin.id, MembershipRole.ADMIN)
    await memberships.add_membership(org.id, member.id, MembershipRole.MEMBER)
    return org, admin, member, AttendanceService(session_factory)
