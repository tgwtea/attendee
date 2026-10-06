from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from telegram.error import Forbidden
from telegram_fakes import group_update, replies

from attendee.application.chats import ChatRegistrationService, RegistrationOutcome
from attendee.application.errors import AccessDenied
from attendee.application.identity import IdentityService
from attendee.application.memberships import MembershipService
from attendee.application.organizations import OrganizationService
from attendee.domain.chats import ChatType, controls_group, registrable_chat_type
from attendee.domain.identity import MembershipRole
from attendee.persistence.models import OrganizationChat
from attendee.telegram import messages
from attendee.telegram.chats import ANONYMOUS_ADMIN_ID, ChatHandlers


@pytest.fixture
def chats(session_factory):
    return ChatRegistrationService(session_factory)


@pytest.fixture
def handlers(attendance_club, session_factory, chats):
    org = attendance_club[0]
    return ChatHandlers(org.id, IdentityService(session_factory), chats)


def bot_context(status="administrator", error=None):
    get_chat_member = AsyncMock(return_value=SimpleNamespace(status=status), side_effect=error)
    return SimpleNamespace(bot=SimpleNamespace(get_chat_member=get_chat_member))


async def stored(factory):
    async with factory() as session:
        rows = await session.scalars(select(OrganizationChat).order_by(OrganizationChat.id))
        return [
            (row.organization_id, row.telegram_chat_id, row.chat_type, row.title) for row in rows
        ]


async def other_admin(session_factory, telegram_user_id=2002):
    org = await OrganizationService(session_factory).create_organization("band", "Band")
    person = await IdentityService(session_factory).create_person("Other", telegram_user_id)
    await MembershipService(session_factory).add_membership(org.id, person.id, MembershipRole.ADMIN)
    return org, person


def test_domain_rules():
    assert registrable_chat_type("group") is ChatType.GROUP
    assert registrable_chat_type("supergroup") is ChatType.SUPERGROUP
    assert registrable_chat_type("channel") is None
    assert registrable_chat_type("private") is None
    assert controls_group("creator") and controls_group("administrator")
    for role in ("member", "restricted", "left", "kicked"):
        assert not controls_group(role)


async def test_register_then_refresh(attendance_club, chats, session_factory):
    org, admin, _, _ = attendance_club
    first = await chats.register(org.id, admin.id, -100, ChatType.GROUP, " Samba ", "creator")
    assert first.outcome is RegistrationOutcome.REGISTERED
    assert first.chat is not None and first.chat.registered_by == admin.id
    again = await chats.register(
        org.id, admin.id, -100, ChatType.GROUP, "Samba 2026", "administrator"
    )
    assert again.outcome is RegistrationOutcome.REFRESHED
    assert again.chat is not None and again.chat.id == first.chat.id
    assert await stored(session_factory) == [(org.id, -100, "group", "Samba 2026")]


async def test_one_organization_registers_several_groups(attendance_club, chats, session_factory):
    org, admin, _, _ = attendance_club
    await chats.register(org.id, admin.id, -100, ChatType.SUPERGROUP, "Juniors", "creator")
    await chats.register(org.id, admin.id, -200, ChatType.SUPERGROUP, "Seniors", "creator")
    assert [row[1] for row in await stored(session_factory)] == [-100, -200]


@pytest.mark.parametrize("role", ["member", "restricted", "left", "kicked"])
async def test_group_role_must_control_the_group(attendance_club, chats, session_factory, role):
    org, admin, _, _ = attendance_club
    with pytest.raises(AccessDenied):
        await chats.register(org.id, admin.id, -100, ChatType.GROUP, "Samba", role)
    assert await stored(session_factory) == []


async def test_organization_role_must_be_admin(attendance_club, chats, session_factory):
    org, _, member, _ = attendance_club
    with pytest.raises(AccessDenied):
        await chats.register(org.id, member.id, -100, ChatType.GROUP, "Samba", "creator")
    assert await stored(session_factory) == []


async def test_another_organization_cannot_take_a_group(attendance_club, chats, session_factory):
    org, admin, _, _ = attendance_club
    await chats.register(org.id, admin.id, -100, ChatType.GROUP, "Samba", "creator")
    band, other = await other_admin(session_factory)
    result = await chats.register(band.id, other.id, -100, ChatType.GROUP, "Mine", "creator")
    assert result.outcome is RegistrationOutcome.TAKEN and result.chat is None
    assert await stored(session_factory) == [(org.id, -100, "group", "Samba")]


async def test_migrate_moves_chat_once(attendance_club, chats, session_factory):
    org, admin, _, _ = attendance_club
    await chats.register(org.id, admin.id, -100, ChatType.GROUP, "Samba", "creator")
    assert await chats.migrate(org.id, -100, -1001) is True
    assert await chats.migrate(org.id, -100, -1001) is False
    assert await stored(session_factory) == [(org.id, -1001, "supergroup", "Samba")]


async def test_migrate_ignores_other_organizations(attendance_club, chats, session_factory):
    org, admin, _, _ = attendance_club
    await chats.register(org.id, admin.id, -100, ChatType.GROUP, "Samba", "creator")
    band, _ = await other_admin(session_factory)
    assert await chats.migrate(band.id, -100, -1001) is False
    assert await chats.migrate(org.id, -999, -1001) is False
    assert await stored(session_factory) == [(org.id, -100, "group", "Samba")]


async def test_handler_registers_group(handlers, session_factory):
    update = group_update(1001, chat_id=-100, chat_type="group", title="Samba")
    context = bot_context("creator")
    await handlers.register(update, context)
    context.bot.get_chat_member.assert_awaited_once_with(-100, 1001)
    assert replies(update) == [(messages.REGISTERED, None)]
    assert len(await stored(session_factory)) == 1
    await handlers.register(update, bot_context("creator"))
    assert replies(update)[-1] == (messages.REGISTER_REFRESHED, None)


@pytest.mark.parametrize(
    "update",
    [
        group_update(ANONYMOUS_ADMIN_ID, sender_chat=SimpleNamespace(id=-100)),
        group_update(ANONYMOUS_ADMIN_ID),
        group_update(None),
    ],
    ids=["sender-chat", "anonymous-bot", "no-sender"],
)
async def test_handler_rejects_anonymous_sender(handlers, session_factory, update):
    context = bot_context("creator")
    await handlers.register(update, context)
    context.bot.get_chat_member.assert_not_awaited()
    assert replies(update) == [(messages.REGISTER_ANONYMOUS, None)]
    assert await stored(session_factory) == []


async def test_handler_rejects_unknown_account_without_role_check(handlers, session_factory):
    update = group_update(4242)
    context = bot_context("creator")
    await handlers.register(update, context)
    context.bot.get_chat_member.assert_not_awaited()
    assert replies(update) == [(messages.REGISTER_DENIED, None)]
    assert await stored(session_factory) == []


async def test_handler_rejects_group_member(handlers, session_factory):
    update = group_update(1001)
    await handlers.register(update, bot_context("member"))
    assert replies(update) == [(messages.REGISTER_DENIED, None)]
    assert await stored(session_factory) == []


async def test_handler_reports_failed_role_check(handlers, session_factory):
    update = group_update(1001)
    await handlers.register(update, bot_context(error=Forbidden("bot was kicked")))
    assert replies(update) == [(messages.REGISTER_CHECK_FAILED, None)]
    assert await stored(session_factory) == []


async def test_handler_reports_taken_group(attendance_club, handlers, session_factory):
    band, other = await other_admin(session_factory)
    await ChatRegistrationService(session_factory).register(
        band.id, other.id, -100, ChatType.SUPERGROUP, "Band", "creator"
    )
    update = group_update(1001, chat_id=-100)
    await handlers.register(update, bot_context("creator"))
    assert replies(update) == [(messages.REGISTER_TAKEN, None)]


async def test_handler_ignores_channel(handlers):
    update = group_update(1001, chat_type="channel")
    context = bot_context("creator")
    await handlers.register(update, context)
    context.bot.get_chat_member.assert_not_awaited()
    assert replies(update) == []


async def test_handler_reports_database_failure(handlers, monkeypatch, caplog):
    async def fail(*_args):
        raise OperationalError("statement", {}, Exception("locked"))

    monkeypatch.setattr(handlers.chats, "register", fail)
    update = group_update(1001)
    await handlers.register(update, bot_context("creator"))
    assert replies(update) == [(messages.REGISTER_FAILED, None)]
    assert "Chat registration database operation failed" in caplog.text


@pytest.mark.parametrize(
    "update",
    [
        group_update(None, chat_id=-100, chat_type="group", migrate_to_chat_id=-1001),
        group_update(None, chat_id=-1001, migrate_from_chat_id=-100),
    ],
    ids=["old-group", "new-supergroup"],
)
async def test_handler_follows_group_upgrade(attendance_club, handlers, session_factory, update):
    org, admin, _, _ = attendance_club
    await handlers.chats.register(org.id, admin.id, -100, ChatType.GROUP, "Samba", "creator")
    await handlers.migrate(update, bot_context())
    await handlers.migrate(update, bot_context())
    assert await stored(session_factory) == [(org.id, -1001, "supergroup", "Samba")]


async def test_registration_count_is_one_per_group(attendance_club, chats, session_factory):
    org, admin, _, _ = attendance_club
    for _ in range(3):
        await chats.register(org.id, admin.id, -100, ChatType.GROUP, "Samba", "creator")
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OrganizationChat)) == 1
