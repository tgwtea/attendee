from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import ADMIN_ID, GROUP_CHAT_ID, add_group
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut
from telegram_fakes import group_update

from attendee.application.errors import AccessDenied, AdminCheckFailed
from attendee.application.groups import GroupService
from attendee.application.identity import IdentityService
from attendee.domain.chats import ChatType, controls_group, group_chat_type, is_present
from attendee.persistence.models import Group
from attendee.telegram.groups import GroupHandlers, TelegramAdminChecker


@pytest.fixture
def groups(session_factory):
    return GroupService(session_factory)


async def stored(factory):
    async with factory() as session:
        rows = await session.scalars(select(Group).order_by(Group.id))
        return [(row.telegram_chat_id, row.chat_type, row.title, row.active) for row in rows]


def member_update(status, *, chat_id=-100, chat_type="supergroup", title="Samba Group"):
    """Telegram reports the bot's own new status in a chat (my_chat_member)."""
    chat = SimpleNamespace(id=chat_id, type=chat_type, title=title)
    change = SimpleNamespace(chat=chat, new_chat_member=SimpleNamespace(status=status))
    return SimpleNamespace(my_chat_member=change)


def test_domain_rules():
    assert group_chat_type("group") is ChatType.GROUP
    assert group_chat_type("supergroup") is ChatType.SUPERGROUP
    assert group_chat_type("channel") is None
    assert group_chat_type("private") is None
    assert controls_group("creator") and controls_group("administrator")
    for status in ("member", "restricted", "left", "kicked"):
        assert not controls_group(status)
    for status in ("creator", "administrator", "member", "restricted"):
        assert is_present(status)
    assert not is_present("left") and not is_present("kicked")


async def test_join_leave_and_rejoin_keep_one_row(groups, session_factory):
    handlers = GroupHandlers(groups)
    await handlers.member_update(member_update("member"), None)
    await handlers.member_update(member_update("member"), None)
    assert await stored(session_factory) == [(-100, "supergroup", "Samba Group", True)]
    await handlers.member_update(member_update("kicked"), None)
    assert await stored(session_factory) == [(-100, "supergroup", "Samba Group", False)]
    assert await groups.left(-100) is False
    # A rejoin reactivates the same group and refreshes its title. Its data stays.
    await handlers.member_update(member_update("administrator", title="  Samba  2026 "), None)
    assert await stored(session_factory) == [(-100, "supergroup", "Samba 2026", True)]


async def test_join_ignores_private_chats_and_channels(groups, session_factory):
    handlers = GroupHandlers(groups)
    await handlers.member_update(member_update("member", chat_type="channel"), None)
    await handlers.member_update(member_update("member", chat_id=5, chat_type="private"), None)
    await handlers.member_update(SimpleNamespace(my_chat_member=None), None)
    assert await stored(session_factory) == []


async def test_title_fallback(groups):
    assert (await groups.joined(-100, ChatType.GROUP, "  ")).title == "-100"
    assert (await groups.joined(-100, ChatType.GROUP, "x" * 300)).title == "x" * 200


@pytest.mark.parametrize(
    "update",
    [
        group_update(None, chat_id=-100, chat_type="group", migrate_to_chat_id=-1001),
        group_update(None, chat_id=-1001, migrate_from_chat_id=-100),
    ],
    ids=["old-group", "new-supergroup"],
)
async def test_upgrade_moves_one_row_and_keeps_the_internal_id(groups, session_factory, update):
    before = await groups.joined(-100, ChatType.GROUP, "Samba")
    person = await IdentityService(session_factory).create_person(before.id, "Member")
    handlers = GroupHandlers(groups)
    await handlers.migrate(update, None)
    await handlers.migrate(update, None)
    assert await stored(session_factory) == [(-1001, "supergroup", "Samba", True)]
    after = await groups.by_telegram_id(-1001)
    assert after is not None and after.id == before.id == person.group_id


async def test_upgrade_removes_an_empty_row_for_the_new_chat(groups, session_factory):
    old = await groups.joined(-100, ChatType.GROUP, "Samba")
    await groups.joined(-1001, ChatType.SUPERGROUP, "Samba")
    assert await groups.migrate(-100, -1001) is True
    assert await stored(session_factory) == [(-1001, "supergroup", "Samba", True)]
    assert (await groups.by_telegram_id(-1001)).id == old.id


async def test_upgrade_keeps_both_rows_when_the_new_chat_has_data(groups, session_factory):
    await groups.joined(-100, ChatType.GROUP, "Samba")
    newer = await groups.joined(-1001, ChatType.SUPERGROUP, "Samba")
    await IdentityService(session_factory).create_person(newer.id, "Member")
    assert await groups.migrate(-100, -1001) is False
    assert [row[0] for row in await stored(session_factory)] == [-100, -1001]


async def test_unknown_upgrade_and_unrelated_message_change_nothing(groups, session_factory):
    handlers = GroupHandlers(groups)
    assert await groups.migrate(-5, -6) is False
    await handlers.migrate(group_update(None, chat_id=-100), None)
    assert await stored(session_factory) == []


async def test_database_failure_is_logged(groups, monkeypatch, caplog):
    async def fail(*args):
        raise OperationalError("UPDATE", {}, Exception("locked"))

    monkeypatch.setattr(groups, "joined", fail)
    monkeypatch.setattr(groups, "migrate", fail)
    handlers = GroupHandlers(groups)
    await handlers.member_update(member_update("member"), None)
    await handlers.migrate(group_update(None, chat_id=-100, migrate_to_chat_id=-1001), None)
    assert "Group membership database operation failed" in caplog.text
    assert "Group migration database operation failed" in caplog.text


async def test_chat_id_is_unique(groups, session_factory):
    await groups.joined(-100, ChatType.GROUP, "Samba")
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            session.add(Group(telegram_chat_id=-100, chat_type="group", title="Copy"))
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Group)) == 1


async def test_access_checks_each_group_separately(session_factory, group, access, admins):
    other = await add_group(session_factory, -200, "Band")
    admins.grant(-200, 2002)
    assert (await access.require_admin(group.id, ADMIN_ID)).id == group.id
    with pytest.raises(AccessDenied):
        await access.require_admin(other.id, ADMIN_ID)
    with pytest.raises(AccessDenied):
        await access.require_admin(999, ADMIN_ID)
    assert [g.id for g in await access.admin_groups(ADMIN_ID)] == [group.id]
    admins.grant(-200, ADMIN_ID)
    # By title: Band before Samba Group.
    assert [g.id for g in await access.admin_groups(ADMIN_ID)] == [other.id, group.id]
    assert await access.admin_groups(5001) == []
    # Each call asks Telegram again. Nothing is cached.
    admins.calls.clear()
    await access.require_admin(group.id, ADMIN_ID)
    await access.require_admin(group.id, ADMIN_ID)
    assert admins.calls == [(GROUP_CHAT_ID, ADMIN_ID)] * 2


async def test_inactive_group_grants_nothing(session_factory, group, access, admins):
    await GroupService(session_factory).left(GROUP_CHAT_ID)
    admins.calls.clear()
    with pytest.raises(AccessDenied):
        await access.require_admin(group.id, ADMIN_ID)
    assert await access.admin_groups(ADMIN_ID) == []
    assert admins.calls == []


def checker(status="administrator", error=None):
    get_chat_member = AsyncMock(return_value=SimpleNamespace(status=status), side_effect=error)
    return TelegramAdminChecker(SimpleNamespace(get_chat_member=get_chat_member))


@pytest.mark.parametrize(
    ("status", "expected"),
    [("creator", True), ("administrator", True), ("member", False), ("left", False)],
)
async def test_telegram_checker_statuses(status, expected):
    assert await checker(status).is_admin(-100, ADMIN_ID) is expected


@pytest.mark.parametrize("error", [BadRequest("Participant_id_invalid"), Forbidden("kicked")])
async def test_telegram_checker_definite_refusal_is_not_admin(error):
    assert await checker(error=error).is_admin(-100, ADMIN_ID) is False


@pytest.mark.parametrize("error", [TimedOut(), RetryAfter(5)])
async def test_telegram_checker_no_answer_fails_closed(error, caplog):
    with pytest.raises(AdminCheckFailed):
        await checker(error=error).is_admin(-100, ADMIN_ID)
    assert "Group admin check failed" in caplog.text
