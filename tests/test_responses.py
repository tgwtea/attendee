from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from telegram import Chat, Message, MessageEntity, User
from telegram import Update as TelegramUpdate
from telegram_fakes import callback_update, message_update, replies
from test_attendance import add_member, create

from attendee.application.organizations import OrganizationService
from attendee.application.responses import (
    NotLinked,
    NotOnRoster,
    ResponseService,
    SessionNotOpen,
)
from attendee.domain.attendance import SessionStatus
from attendee.domain.responses import (
    ReasonMissing,
    ReasonTooLong,
    ResponseStatus,
    clean_reason,
    parse_vote,
)
from attendee.main import create_handlers
from attendee.persistence.models import AttendanceSession, SessionResponse, SessionResponseEvent
from attendee.telegram import messages
from attendee.telegram.bootstrap import build_application
from attendee.telegram.responses import PendingReason, ResponseHandlers

MEMBER_TG = 2002
NOW = datetime(2026, 10, 6, 4, tzinfo=UTC)


@pytest.fixture
async def open_session(attendance_club, session_factory):
    """An Open session whose roster holds a linked member."""
    org, *_ = attendance_club
    await add_member(session_factory, org.id, "Sarah", telegram_id=MEMBER_TG)
    draft = await create(attendance_club)
    await set_status(session_factory, draft.id, SessionStatus.OPEN)
    return org, draft


async def set_status(factory, session_id, status):
    async with factory.begin() as session:
        await session.execute(
            update(AttendanceSession)
            .where(AttendanceSession.id == session_id)
            .values(status=status.value)
        )


async def current(factory):
    async with factory() as session:
        rows = await session.scalars(select(SessionResponse))
        return [(row.status, row.reason) for row in rows]


async def events(factory):
    async with factory() as session:
        rows = await session.scalars(select(SessionResponseEvent).order_by(SessionResponseEvent.id))
        return [(row.status, row.reason, row.telegram_user_id) for row in rows]


def test_vote_data_and_reason_rules():
    assert parse_vote("v:42:c") == (42, ResponseStatus.COMING)
    assert parse_vote("v:42:e") == (42, ResponseStatus.LEAVING_EARLY)
    for data in (None, "", "v:42", "v:42:x", "v:-1:c", "v:42:c:1", "p:42:c", "v:4a:c"):
        assert parse_vote(data) is None
    assert ResponseStatus.COMING.value_for_attendance == 1
    assert {status.value_for_attendance for status in ResponseStatus} == {0, 1}
    assert clean_reason(ResponseStatus.COMING, "ignored") is None
    assert clean_reason(ResponseStatus.LATE, "  Class ends at 7:30  ") == "Class ends at 7:30"
    with pytest.raises(ReasonMissing):
        clean_reason(ResponseStatus.LATE, " \n ")
    with pytest.raises(ReasonMissing):
        clean_reason(ResponseStatus.NOT_COMING, None)
    with pytest.raises(ReasonTooLong):
        clean_reason(ResponseStatus.LATE, "x" * 1001)
    assert clean_reason(ResponseStatus.LATE, "x" * 1000) == "x" * 1000


async def test_record_replaces_current_and_audits_each_change(open_session, session_factory):
    org, draft = open_session
    service = ResponseService(session_factory)
    first = await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.COMING, now=NOW)
    assert first.changed
    # A repeated tap writes nothing (PRD §35).
    repeat = await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.COMING, now=NOW)
    assert not repeat.changed
    late = await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.LATE, " Class ", NOW)
    assert late.reason == "Class"
    assert await current(session_factory) == [("late", "Class")]
    assert await events(session_factory) == [
        ("coming", None, MEMBER_TG),
        ("late", "Class", MEMBER_TG),
    ]
    # A new reason for the same status is a change.
    await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.LATE, "Bus", NOW)
    assert await current(session_factory) == [("late", "Bus")]
    assert len(await events(session_factory)) == 3


async def test_bad_reason_writes_nothing(open_session, session_factory):
    org, draft = open_session
    service = ResponseService(session_factory)
    with pytest.raises(ReasonMissing):
        await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.LATE, "  ")
    with pytest.raises(ReasonTooLong):
        await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.LATE, "x" * 1001)
    assert await current(session_factory) == []
    assert await events(session_factory) == []


async def test_checks_link_roster_and_open_status(attendance_club, open_session, session_factory):
    org, draft = open_session
    service = ResponseService(session_factory)
    with pytest.raises(NotLinked):
        await service.check(org.id, 9999, draft.id)
    # A member added after the snapshot is not on this session's roster.
    await add_member(session_factory, org.id, "Late Joiner", telegram_id=3003)
    with pytest.raises(NotOnRoster):
        await service.record(org.id, 3003, draft.id, ResponseStatus.COMING)
    # Another organization cannot reach this session.
    other = await OrganizationService(session_factory).create_organization("other", "Other")
    with pytest.raises(SessionNotOpen):
        await service.check(other.id, MEMBER_TG, draft.id)
    with pytest.raises(SessionNotOpen):
        await service.check(org.id, MEMBER_TG, draft.id + 100)
    for status in (SessionStatus.DRAFT, SessionStatus.CLOSED):
        await set_status(session_factory, draft.id, status)
        with pytest.raises(SessionNotOpen):
            await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.COMING)
    assert await current(session_factory) == []


async def test_deadline_does_not_block_open_session(open_session, session_factory):
    org, draft = open_session
    after_deadline = datetime(2026, 12, 1, tzinfo=UTC)
    assert draft.deadline < after_deadline
    result = await ResponseService(session_factory).record(
        org.id, MEMBER_TG, draft.id, ResponseStatus.COMING, now=after_deadline
    )
    assert result.changed


def bot_context():
    return SimpleNamespace(bot=SimpleNamespace(username="attendee_bot"))


def group_tap(session_id, code, telegram_user_id=MEMBER_TG):
    return callback_update(
        telegram_user_id, "sarah", f"v:{session_id}:{code}", chat_id=-100, chat_type="supergroup"
    )


@pytest.fixture
def handlers(open_session, session_factory):
    org, _ = open_session
    return ResponseHandlers(org.id, ResponseService(session_factory))


async def test_coming_tap_records_with_private_popup(handlers, open_session, session_factory):
    _, draft = open_session
    tap = group_tap(draft.id, "c")
    await handlers.tap(tap, bot_context())
    tap.callback_query.answer.assert_awaited_once_with(
        "Attendance recorded: Coming", show_alert=True
    )
    # Nothing goes to the group chat.
    assert replies(tap) == []
    assert await current(session_factory) == [("coming", None)]


async def test_late_flow_from_tap_to_reason(handlers, open_session, session_factory):
    _, draft = open_session
    tap = group_tap(draft.id, "l")
    await handlers.tap(tap, bot_context())
    tap.callback_query.answer.assert_awaited_once_with(url="https://t.me/attendee_bot?start=reason")
    assert handlers.pending == {MEMBER_TG: PendingReason(draft.id, ResponseStatus.LATE)}
    # Nothing is saved before the reason arrives (PRD §23 clarification).
    assert await current(session_factory) == []
    start = message_update(MEMBER_TG, "sarah", text="/start reason")
    await handlers.start(start, bot_context())
    assert replies(start) == [
        (
            "You selected Late for Patrons Day on 13 October 2026.\n\nPlease enter your reason.",
            None,
        )
    ]
    text = message_update(MEMBER_TG, "sarah", text="Class ends at 7:30pm.")
    await handlers.reason(text, bot_context())
    assert replies(text) == [("Attendance recorded: Late\nReason: Class ends at 7:30pm.", None)]
    assert handlers.pending == {}
    assert await current(session_factory) == [("late", "Class ends at 7:30pm.")]


async def test_start_without_pending_tap(handlers):
    start = message_update(MEMBER_TG, "sarah", text="/start reason")
    await handlers.start(start, bot_context())
    assert replies(start) == [(messages.NO_PENDING_REASON, None)]


async def test_bad_reason_keeps_pending_tap(handlers, open_session, session_factory):
    _, draft = open_session
    await handlers.tap(group_tap(draft.id, "n"), bot_context())
    blank = message_update(MEMBER_TG, "sarah", text="   ")
    await handlers.reason(blank, bot_context())
    long = message_update(MEMBER_TG, "sarah", text="x" * 1001)
    await handlers.reason(long, bot_context())
    assert replies(blank) == [(messages.REASON_MISSING, None)]
    assert replies(long) == [(messages.REASON_TOO_LONG, None)]
    assert MEMBER_TG in handlers.pending
    assert await current(session_factory) == []


async def test_new_tap_replaces_pending_and_coming_clears_it(handlers, open_session):
    _, draft = open_session
    await handlers.tap(group_tap(draft.id, "n"), bot_context())
    await handlers.tap(group_tap(draft.id, "e"), bot_context())
    assert handlers.pending[MEMBER_TG].status is ResponseStatus.LEAVING_EARLY
    await handlers.tap(group_tap(draft.id, "c"), bot_context())
    assert handlers.pending == {}


async def test_database_failure_keeps_pending_tap(
    handlers, open_session, session_factory, monkeypatch
):
    _, draft = open_session
    await handlers.tap(group_tap(draft.id, "l"), bot_context())

    async def fail(*_args, **_kwargs):
        raise OperationalError("INSERT", {}, Exception("locked"))

    monkeypatch.setattr(handlers.responses, "record", fail)
    text = message_update(MEMBER_TG, "sarah", text="Class")
    await handlers.reason(text, bot_context())
    assert replies(text) == [(messages.REASON_NOT_SAVED, None)]
    assert MEMBER_TG in handlers.pending


async def test_closed_between_tap_and_reason(handlers, open_session, session_factory):
    _, draft = open_session
    await handlers.tap(group_tap(draft.id, "l"), bot_context())
    await set_status(session_factory, draft.id, SessionStatus.CLOSED)
    text = message_update(MEMBER_TG, "sarah", text="Class")
    await handlers.reason(text, bot_context())
    assert replies(text) == [(messages.POLL_CLOSED, None)]
    assert handlers.pending == {}
    assert await current(session_factory) == []


async def test_tap_rejections_use_popups(handlers, open_session, session_factory):
    _, draft = open_session
    unknown = group_tap(draft.id, "c", telegram_user_id=9999)
    await handlers.tap(unknown, bot_context())
    unknown.callback_query.answer.assert_awaited_once_with(messages.NOT_MATCHED, show_alert=True)
    invalid = callback_update(MEMBER_TG, "sarah", "v:bad", chat_id=-100, chat_type="supergroup")
    await handlers.tap(invalid, bot_context())
    invalid.callback_query.answer.assert_awaited_once_with(messages.VOTE_INVALID, show_alert=True)
    await set_status(session_factory, draft.id, SessionStatus.CLOSED)
    closed = group_tap(draft.id, "l")
    await handlers.tap(closed, bot_context())
    closed.callback_query.answer.assert_awaited_once_with(messages.POLL_CLOSED, show_alert=True)
    assert handlers.pending == {}


def private_text(text, user_id=MEMBER_TG):
    entities = (
        [MessageEntity(MessageEntity.BOT_COMMAND, 0, len(text.split()[0]))]
        if text.startswith("/")
        else []
    )
    message = Message(
        1,
        NOW,
        Chat(user_id, Chat.PRIVATE),
        from_user=User(user_id, "Sarah", False),
        text=text,
        entities=entities,
    )
    # CommandHandler reads the bot username to accept /start@attendee_bot.
    message.set_bot(SimpleNamespace(username="attendee_bot"))  # pyright: ignore[reportArgumentType]
    return TelegramUpdate(1, message=message)


def first_handler(application, update):
    return next(
        (handler for handler in application.handlers[0] if handler.check_update(update)), None
    )


def test_routing_sends_text_to_reason_only_with_pending_tap():
    """Only the first matching handler runs, so handler order decides the route."""
    application = build_application("123:ABC", create_handlers(Mock(), 1))
    reason_handler = application.handlers[0][0]
    responses = reason_handler.callback.__self__
    # Without a pending tap, stray private text matches no handler.
    assert first_handler(application, private_text("Overseas")) is None
    responses.pending[MEMBER_TG] = PendingReason(1, ResponseStatus.LATE)
    assert first_handler(application, private_text("Overseas")) is reason_handler
    # Commands never count as a reason.
    assert first_handler(application, private_text("/attendance")) is not reason_handler
    start = first_handler(application, private_text("/start reason"))
    assert start.callback == responses.start
    plain = first_handler(application, private_text("/start"))
    assert plain.callback != responses.start
