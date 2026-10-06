from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import add_group
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from telegram import Chat, ForceReply, Message, MessageEntity, User
from telegram import Update as TelegramUpdate
from telegram_fakes import callback_update, message_update, replies
from test_attendance import add_member, create

from attendee.application.groups import GroupService
from attendee.application.matching import AccountMatchingService
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
from attendee.telegram.responses import CONFIRM_SECONDS, PendingReason, ResponseHandlers

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
    # Another group cannot reach this session.
    other = await add_group(session_factory, -200, "Other")
    with pytest.raises(NotLinked):
        await service.check(other.id, MEMBER_TG, draft.id)
    await add_member(session_factory, other.id, "Sarah", telegram_id=MEMBER_TG)
    with pytest.raises(SessionNotOpen):
        await service.check(other.id, MEMBER_TG, draft.id)
    with pytest.raises(SessionNotOpen):
        await service.check(org.id, MEMBER_TG, draft.id + 100)
    for status in (SessionStatus.DRAFT, SessionStatus.CLOSED):
        await set_status(session_factory, draft.id, status)
        with pytest.raises(SessionNotOpen):
            await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.COMING)
    assert await current(session_factory) == []


async def test_deadline_does_not_block_open_session(open_session, session_factory, archive_after):
    org, draft = open_session
    service = ResponseService(session_factory)
    # Up to ARCHIVE_AFTER past the deadline, an Open session takes responses.
    last_moment = draft.deadline + archive_after
    await service.check(org.id, MEMBER_TG, draft.id, last_moment)
    result = await service.record(
        org.id, MEMBER_TG, draft.id, ResponseStatus.COMING, now=last_moment
    )
    assert result.changed


async def test_archived_session_blocks_responses_and_keeps_data(
    open_session, session_factory, archive_after
):
    org, draft = open_session
    service = ResponseService(session_factory)
    await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.LATE, "Bus", NOW)
    archived = draft.deadline + archive_after + timedelta(seconds=1)
    with pytest.raises(SessionNotOpen):
        await service.check(org.id, MEMBER_TG, draft.id, archived)
    with pytest.raises(SessionNotOpen):
        await service.record(org.id, MEMBER_TG, draft.id, ResponseStatus.COMING, now=archived)
    # Archiving deletes nothing. The response stays for admin export.
    assert await current(session_factory) == [("late", "Bus")]


def bot_context():
    return SimpleNamespace(bot=SimpleNamespace(username="attendee_bot"))


def group_tap(session_id, code, telegram_user_id=MEMBER_TG):
    return callback_update(
        telegram_user_id, "sarah", f"v:{session_id}:{code}", chat_id=-100, chat_type="supergroup"
    )


@pytest.fixture
def handlers(open_session, session_factory):
    return ResponseHandlers(
        GroupService(session_factory),
        ResponseService(session_factory),
        AccountMatchingService(session_factory),
    )


async def test_coming_tap_records_with_private_popup(handlers, open_session, session_factory):
    _, draft = open_session
    tap = group_tap(draft.id, "c")
    await handlers.tap(tap, bot_context())
    tap.callback_query.answer.assert_awaited_once_with(
        messages.RECORDED.format(status="Coming"), show_alert=True
    )
    # Nothing goes to the group chat.
    assert replies(tap) == []
    assert await current(session_factory) == [("coming", None)]


async def test_late_flow_from_tap_to_reason(handlers, open_session, session_factory):
    group, draft = open_session
    tap = group_tap(draft.id, "l")
    await handlers.tap(tap, bot_context())
    tap.callback_query.answer.assert_awaited_once_with(url="https://t.me/attendee_bot?start=reason")
    assert handlers.pending == {MEMBER_TG: PendingReason(group.id, draft.id, ResponseStatus.LATE)}
    # Nothing is saved before the reason arrives (PRD §23 clarification).
    assert await current(session_factory) == []
    start = message_update(MEMBER_TG, "sarah", text="/start reason")
    await handlers.start(start, bot_context())
    prompt = messages.REASON_PROMPT.format(status="Late", session="Patrons Day on 13 October 2026")
    assert replies(start)[0][0] == prompt
    assert isinstance(replies(start)[0][1], ForceReply)
    text = message_update(MEMBER_TG, "sarah", text="Class ends at 7:30pm.")
    await reply_reason(handlers, text)
    recorded = messages.RECORDED_REASON.format(status="Late", reason="Class ends at 7:30pm.")
    assert replies(text) == [(recorded, None)]
    assert handlers.pending == {}
    assert await current(session_factory) == [("late", "Class ends at 7:30pm.")]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clocked(open_session, session_factory):
    clock = FakeClock()
    groups = GroupService(session_factory)
    matching = AccountMatchingService(session_factory)
    return ResponseHandlers(groups, ResponseService(session_factory), matching, clock), clock


async def test_change_needs_second_tap(clocked, open_session, session_factory):
    handlers, clock = clocked
    group, draft = open_session
    await handlers.tap(group_tap(draft.id, "c"), bot_context())
    first = group_tap(draft.id, "l")
    await handlers.tap(first, bot_context())
    first.callback_query.answer.assert_awaited_once_with(
        messages.CONFIRM_REPLACE.format(current="Coming", new="Late", seconds=CONFIRM_SECONDS),
        show_alert=True,
    )
    # The first tap opens nothing and saves nothing.
    assert handlers.pending == {}
    assert await current(session_factory) == [("coming", None)]
    clock.now += CONFIRM_SECONDS - 1
    second = group_tap(draft.id, "l")
    await handlers.tap(second, bot_context())
    second.callback_query.answer.assert_awaited_once_with(
        url="https://t.me/attendee_bot?start=reason"
    )
    assert handlers.pending == {MEMBER_TG: PendingReason(group.id, draft.id, ResponseStatus.LATE)}
    assert handlers.armed == {}


async def test_late_second_tap_or_other_button_arms_again(clocked, open_session, session_factory):
    handlers, clock = clocked
    org, draft = open_session
    await ResponseService(session_factory).record(
        org.id, MEMBER_TG, draft.id, ResponseStatus.LATE, "Bus"
    )
    await handlers.tap(group_tap(draft.id, "c"), bot_context())
    clock.now += CONFIRM_SECONDS
    expired = group_tap(draft.id, "c")
    await handlers.tap(expired, bot_context())
    assert "Tap Coming again" in expired.callback_query.answer.await_args.args[0]
    # A different button replaces the armed change.
    other = group_tap(draft.id, "n")
    await handlers.tap(other, bot_context())
    assert "Tap Not Coming again" in other.callback_query.answer.await_args.args[0]
    coming = group_tap(draft.id, "c")
    await handlers.tap(coming, bot_context())
    assert "Tap Coming again" in coming.callback_query.answer.await_args.args[0]
    confirm = group_tap(draft.id, "c")
    await handlers.tap(confirm, bot_context())
    confirm.callback_query.answer.assert_awaited_once_with(
        messages.RECORDED.format(status="Coming"), show_alert=True
    )
    assert await current(session_factory) == [("coming", None)]


async def test_same_status_tap_needs_no_confirmation(clocked, open_session, session_factory):
    handlers, _ = clocked
    _, draft = open_session
    await handlers.tap(group_tap(draft.id, "c"), bot_context())
    repeat = group_tap(draft.id, "c")
    await handlers.tap(repeat, bot_context())
    repeat.callback_query.answer.assert_awaited_once_with(
        messages.RECORDED.format(status="Coming"), show_alert=True
    )
    assert handlers.armed == {}


async def test_start_without_pending_tap(handlers):
    start = message_update(MEMBER_TG, "sarah", text="/start reason")
    await handlers.start(start, bot_context())
    assert replies(start) == [(messages.NO_PENDING_REASON, None)]


async def test_bad_reason_keeps_pending_tap(handlers, open_session, session_factory):
    _, draft = open_session
    await handlers.tap(group_tap(draft.id, "n"), bot_context())
    blank = message_update(MEMBER_TG, "sarah", text="   ")
    await reply_reason(handlers, blank)
    long = message_update(MEMBER_TG, "sarah", text="x" * 1001)
    await reply_reason(handlers, long)
    assert replies(blank)[0][0] == messages.REASON_MISSING
    assert isinstance(replies(blank)[0][1], ForceReply)
    assert replies(long)[0][0] == messages.REASON_TOO_LONG
    assert isinstance(replies(long)[0][1], ForceReply)
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

    await handlers.start(message_update(MEMBER_TG, "sarah", text="/start reason"), bot_context())
    monkeypatch.setattr(handlers.responses, "record", fail)
    text = message_update(MEMBER_TG, "sarah", text="Class")
    await reply_reason(handlers, text)
    assert replies(text)[0][0] == messages.REASON_NOT_SAVED
    assert isinstance(replies(text)[0][1], ForceReply)
    assert MEMBER_TG in handlers.pending


async def test_closed_between_tap_and_reason(handlers, open_session, session_factory):
    _, draft = open_session
    await handlers.tap(group_tap(draft.id, "l"), bot_context())
    await handlers.start(message_update(MEMBER_TG, "sarah", text="/start reason"), bot_context())
    await set_status(session_factory, draft.id, SessionStatus.CLOSED)
    text = message_update(MEMBER_TG, "sarah", text="Class")
    await reply_reason(handlers, text)
    assert replies(text) == [(messages.POLL_CLOSED, None)]
    assert handlers.pending == {}
    assert await current(session_factory) == []


async def test_tap_rejections_use_popups(handlers, open_session, session_factory):
    _, draft = open_session
    invalid = callback_update(MEMBER_TG, "sarah", "v:bad", chat_id=-100, chat_type="supergroup")
    await handlers.tap(invalid, bot_context())
    invalid.callback_query.answer.assert_awaited_once_with(messages.VOTE_INVALID, show_alert=True)
    await set_status(session_factory, draft.id, SessionStatus.CLOSED)
    closed = group_tap(draft.id, "l")
    await handlers.tap(closed, bot_context())
    closed.callback_query.answer.assert_awaited_once_with(messages.POLL_CLOSED, show_alert=True)
    assert handlers.pending == {}


async def test_tap_counts_only_in_the_group_of_the_poll(handlers, open_session, session_factory):
    """The group comes from the poll message's chat, which Telegram fills (decision T80)."""
    group, draft = open_session
    other = await add_group(session_factory, -200, "Other")
    await add_member(session_factory, other.id, "Sarah", telegram_id=MEMBER_TG)
    for chat_id in (-200, -999):
        tap = callback_update(
            MEMBER_TG, "sarah", f"v:{draft.id}:c", chat_id=chat_id, chat_type="supergroup"
        )
        await handlers.tap(tap, bot_context())
        tap.callback_query.answer.assert_awaited_once_with(messages.POLL_CLOSED, show_alert=True)
    assert await current(session_factory) == []
    late = group_tap(draft.id, "l")
    await handlers.tap(late, bot_context())
    assert handlers.pending[MEMBER_TG].group_id == group.id


def private_text(text, user_id=MEMBER_TG, reply_to_message=None):
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
        reply_to_message=reply_to_message,
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
    application = build_application("123:ABC", create_handlers(Mock(), Mock()))
    reason_handler = application.handlers[0][0]
    responses = reason_handler.callback.__self__
    # Without a pending tap, stray private text matches no handler.
    assert first_handler(application, private_text("Overseas")) is None
    responses.pending[MEMBER_TG] = PendingReason(1, 1, ResponseStatus.LATE)
    assert first_handler(application, private_text("Overseas")) is None
    prompt = private_text("Please reply").message
    responses.prompts[MEMBER_TG, prompt.message_id] = responses.pending[MEMBER_TG]
    reply = private_text("Overseas", reply_to_message=prompt)
    assert first_handler(application, reply) is reason_handler
    # Commands never count as a reason.
    assert first_handler(application, private_text("/attendance")) is not reason_handler
    start = first_handler(application, private_text("/start reason"))
    assert start.callback == responses.start
    link = first_handler(application, private_text("/start link"))
    assert link.callback == responses.link_start
    plain = first_handler(application, private_text("/start"))
    assert plain.callback != responses.start


async def reply_reason(handlers, update):
    if not handlers.prompts:
        await handlers.start(
            message_update(MEMBER_TG, "sarah", text="/start reason"), bot_context()
        )
    prompt_id = [key[1] for key in handlers.prompts if key[0] == MEMBER_TG][-1]
    update.effective_message.reply_to_message = SimpleNamespace(message_id=prompt_id)
    await handlers.reason(update, bot_context())


async def test_repeated_callback_does_not_confirm_change(handlers, open_session, session_factory):
    org, draft = open_session
    await ResponseService(session_factory).record(
        org.id, MEMBER_TG, draft.id, ResponseStatus.LATE, "Bus"
    )
    first = group_tap(draft.id, "c")
    await handlers.tap(first, bot_context())
    await handlers.tap(first, bot_context())
    assert await current(session_factory) == [("late", "Bus")]
    assert len(await events(session_factory)) == 1
    await handlers.tap(group_tap(draft.id, "c"), bot_context())
    assert await current(session_factory) == [("coming", None)]
    # A delayed repeat of the original callback also has no effect.
    await handlers.tap(first, bot_context())
    assert len(await events(session_factory)) == 2


async def test_reason_reply_keeps_original_session(
    handlers, open_session, attendance_club, session_factory
):
    org, first = open_session
    second = await create(attendance_club, series_id=first.series_id, new_series_name=None)
    await set_status(session_factory, second.id, SessionStatus.OPEN)
    await handlers.tap(group_tap(first.id, "l"), bot_context())
    await handlers.start(message_update(MEMBER_TG, "sarah", text="/start reason"), bot_context())
    await handlers.tap(group_tap(second.id, "n"), bot_context())
    await reply_reason(handlers, message_update(MEMBER_TG, "sarah", text="Class for first session"))
    async with session_factory() as session:
        saved = await session.scalars(select(SessionResponse))
        assert [(row.session_id, row.reason) for row in saved] == [
            (first.id, "Class for first session")
        ]
    assert handlers.pending[MEMBER_TG].session_id == second.id


async def test_unrelated_text_does_not_save_reason(handlers, open_session, session_factory):
    _, draft = open_session
    await handlers.tap(group_tap(draft.id, "l"), bot_context())
    await handlers.start(message_update(MEMBER_TG, "sarah", text="/start reason"), bot_context())
    await handlers.reason(message_update(MEMBER_TG, "sarah", text="New series name"), bot_context())
    assert await current(session_factory) == []
    assert handlers.pending
