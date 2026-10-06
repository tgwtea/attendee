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
        "LOG_LEVEL",
        "BACKUP_DIR",
        "SQLITE_BUSY_TIMEOUT_MS",
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


GROUP_CHAT_ID = -100
ADMIN_ID = 1001


class FakeAdmins:
    """Stand-in for the Telegram group-admin check. Holds (chat ID, user ID) pairs."""

    def __init__(self) -> None:
        self.pairs: set[tuple[int, int]] = set()
        self.calls: list[tuple[int, int]] = []
        self.fail = False

    def grant(self, telegram_chat_id: int, telegram_user_id: int) -> None:
        self.pairs.add((telegram_chat_id, telegram_user_id))

    def revoke(self, telegram_chat_id: int, telegram_user_id: int) -> None:
        self.pairs.discard((telegram_chat_id, telegram_user_id))

    async def is_admin(self, telegram_chat_id: int, telegram_user_id: int) -> bool:
        from attendee import copy
        from attendee.application.errors import AdminCheckFailed

        self.calls.append((telegram_chat_id, telegram_user_id))
        if self.fail:
            raise AdminCheckFailed(copy.ADMIN_CHECK_FAILED)
        return (telegram_chat_id, telegram_user_id) in self.pairs


@pytest.fixture
def admins():
    return FakeAdmins()


@pytest.fixture
def access(session_factory, admins):
    from attendee.application.groups import GroupAccess

    return GroupAccess(session_factory, admins)


async def add_group(session_factory, telegram_chat_id=GROUP_CHAT_ID, title="Samba Group"):
    from attendee.application.groups import GroupService
    from attendee.domain.chats import ChatType

    return await GroupService(session_factory).joined(telegram_chat_id, ChatType.SUPERGROUP, title)


@pytest.fixture
async def group(session_factory, admins):
    """One group. ADMIN_ID is a Telegram admin of it and is not on its namelist."""
    result = await add_group(session_factory)
    admins.grant(result.telegram_chat_id, ADMIN_ID)
    return result


@pytest.fixture
async def attendance_club(session_factory, group, access):
    """(group, admin Telegram user ID, member person, AttendanceService)."""
    from attendee.application.attendance import AttendanceService
    from attendee.application.identity import IdentityService

    member = await IdentityService(session_factory).create_person(group.id, "Member")
    return group, ADMIN_ID, member, AttendanceService(session_factory, access)
