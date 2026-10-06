import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import add_group
from sqlalchemy import select
from telegram.error import (
    BadRequest,
    ChatMigrated,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TimedOut,
)
from telegram_fakes import buttons, callback_update, message_update, replies
from test_attendance import add_member, create

from attendee.application.errors import AccessDenied, NotFound
from attendee.application.groups import GroupService
from attendee.application.publication import (
    NotDraft,
    PublicationService,
    PublishOutcome,
    PublishRejected,
    PublishUnknown,
    recover_expired,
)
from attendee.domain.attendance import SessionStatus
from attendee.domain.publication import PUBLISH_LEASE, PublicationStatus, poll_text
from attendee.persistence.models import AttendanceSession, SessionPublication
from attendee.telegram import messages
from attendee.telegram.publication import (
    PublicationHandlers,
    TelegramPublisher,
    callback,
    parse_callback,
)

NOW = datetime(2026, 10, 6, 4, tzinfo=UTC)


class FakePublisher:
    """Records each send. An optional error or gate controls the result."""

    def __init__(self, error=None, gate=None, during=None):
        self.sent = []
        self.error = error
        self.gate = gate
        self.during = during
        self.started = asyncio.Event()

    async def send_poll(self, telegram_chat_id, text, session_id):
        self.sent.append((telegram_chat_id, text, session_id))
        self.started.set()
        if self.during is not None:
            await self.during()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return 500 + len(self.sent)


@pytest.fixture
def service(session_factory, access):
    return PublicationService(session_factory, access, "Asia/Singapore")


@pytest.fixture
async def ready(attendance_club):
    """(group, admin Telegram user ID, Draft session). The poll goes to the session's group."""
    group, admin, _, _ = attendance_club
    draft = await create(attendance_club)
    return group, admin, draft


async def attempts(factory):
    async with factory() as session:
        rows = await session.scalars(select(SessionPublication).order_by(SessionPublication.id))
        return [(row.status, row.telegram_message_id, row.failure) for row in rows]


async def session_status(factory, session_id):
    async with factory() as session:
        return await session.scalar(
            select(AttendanceSession.status).where(AttendanceSession.id == session_id)
        )


def test_poll_text_follows_prd_and_has_no_counts():
    text = poll_text(
        "Patrons Day",
        date(2026, 10, 13),
        None,
        datetime(2026, 10, 12, 12, tzinfo=UTC),
        "Asia/Singapore",
    )
    assert text == (
        "Attendance — Patrons Day\n\n"
        "Tuesday, 13 October 2026\n"
        "Please reply by Monday, 12 October 2026 at 8:00 PM (Asia/Singapore).\n\n"
        "Your answer is private. Only admins see it."
    )
    labelled = poll_text(
        "Prac",
        date(2026, 10, 13),
        "Week 3",
        datetime(2026, 10, 12, 1, tzinfo=UTC),
        "Asia/Singapore",
    )
    assert "Week 3\n" in labelled and "at 9:00 AM" in labelled
    # PRD §12: no aggregate counts in the group message.
    for word in ("Required", "responded", "outstanding", "Coming"):
        assert word not in text and word not in labelled


async def test_publish_opens_session(ready, service, session_factory):
    group, admin, draft = ready
    publisher = FakePublisher()
    result = await service.publish(group.id, admin, draft.id, publisher, NOW)
    assert result.outcome is PublishOutcome.PUBLISHED
    assert [(sent[0], sent[2]) for sent in publisher.sent] == [(-100, draft.id)]
    assert "Your answer is private." in publisher.sent[0][1]
    assert await attempts(session_factory) == [("published", 501, None)]
    assert await session_status(session_factory, draft.id) == SessionStatus.OPEN
    # An Open session is no longer a Draft. Nothing sends again.
    with pytest.raises(NotDraft):
        await service.publish(group.id, admin, draft.id, publisher, NOW)
    assert len(publisher.sent) == 1


async def test_concurrent_publish_sends_once(ready, service, session_factory):
    group, admin, draft = ready
    gate = asyncio.Event()
    publisher = FakePublisher(gate=gate)
    first = asyncio.create_task(service.publish(group.id, admin, draft.id, publisher, NOW))
    await publisher.started.wait()
    others = await asyncio.gather(
        *(service.publish(group.id, admin, draft.id, publisher, NOW) for _ in range(3))
    )
    gate.set()
    assert (await first).outcome is PublishOutcome.PUBLISHED
    assert {result.outcome for result in others} == {PublishOutcome.IN_PROGRESS}
    assert len(publisher.sent) == 1
    assert await attempts(session_factory) == [("published", 501, None)]


async def test_simultaneous_claims_send_once(ready, service, session_factory):
    group, admin, draft = ready
    publisher = FakePublisher()
    results = await asyncio.gather(
        *(service.publish(group.id, admin, draft.id, publisher, NOW) for _ in range(4)),
        return_exceptions=True,
    )
    # A later claim sees publishing (IN_PROGRESS) or the Open session (NotDraft). Neither sends.
    published = [r for r in results if getattr(r, "outcome", None) is PublishOutcome.PUBLISHED]
    assert len(published) == 1
    assert all(
        isinstance(r, NotDraft) or r.outcome is PublishOutcome.IN_PROGRESS
        for r in results
        if r not in published
    )
    assert len(publisher.sent) == 1
    assert await attempts(session_factory) == [("published", 501, None)]


async def test_rejection_sets_failed_and_retry_publishes(ready, service, session_factory):
    group, admin, draft = ready
    rejected = await service.publish(
        group.id, admin, draft.id, FakePublisher(PublishRejected("Forbidden")), NOW
    )
    assert rejected.outcome is PublishOutcome.FAILED and rejected.failure == "Forbidden"
    assert await session_status(session_factory, draft.id) == SessionStatus.DRAFT
    retry = await service.publish(group.id, admin, draft.id, FakePublisher(), NOW)
    assert retry.outcome is PublishOutcome.PUBLISHED
    assert await attempts(session_factory) == [
        ("failed", None, "Forbidden"),
        ("published", 501, None),
    ]


async def test_timeout_then_seen_opens_without_message(ready, service, session_factory):
    group, admin, draft = ready
    publisher = FakePublisher(PublishUnknown())
    result = await service.publish(group.id, admin, draft.id, publisher, NOW)
    assert result.outcome is PublishOutcome.UNKNOWN
    # An unknown result blocks a new send until an admin decides.
    again = await service.publish(group.id, admin, draft.id, publisher, NOW)
    assert again.outcome is PublishOutcome.UNKNOWN and len(publisher.sent) == 1
    seen = await service.resolve(group.id, admin, draft.id, seen=True, now=NOW)
    assert seen.outcome is PublishOutcome.PUBLISHED
    assert await attempts(session_factory) == [("published", None, None)]
    assert await session_status(session_factory, draft.id) == SessionStatus.OPEN
    # A repeated button changes nothing.
    repeat = await service.resolve(group.id, admin, draft.id, seen=False, now=NOW)
    assert repeat.outcome is PublishOutcome.PUBLISHED


async def test_timeout_then_not_seen_allows_retry(ready, service, session_factory):
    group, admin, draft = ready
    await service.publish(group.id, admin, draft.id, FakePublisher(PublishUnknown()), NOW)
    not_seen = await service.resolve(group.id, admin, draft.id, seen=False, now=NOW)
    assert not_seen.outcome is PublishOutcome.FAILED
    assert await session_status(session_factory, draft.id) == SessionStatus.DRAFT
    with pytest.raises(NotFound):
        await service.resolve(group.id, admin, draft.id, seen=True, now=NOW)
    retry = await service.publish(group.id, admin, draft.id, FakePublisher(), NOW)
    assert retry.outcome is PublishOutcome.PUBLISHED


async def test_crash_lease_expires_at_restart(ready, service, session_factory):
    group, admin, draft = ready
    # A non-Telegram error stands in for a crash: the attempt stays publishing.
    with pytest.raises(RuntimeError):
        await service.publish(group.id, admin, draft.id, FakePublisher(RuntimeError("crash")), NOW)
    assert await attempts(session_factory) == [("publishing", None, None)]
    assert await recover_expired(session_factory, NOW + PUBLISH_LEASE - timedelta(seconds=1)) == 0
    assert await recover_expired(session_factory, NOW + PUBLISH_LEASE) == 1
    assert await attempts(session_factory) == [("publish_unknown", None, None)]
    assert await recover_expired(session_factory, NOW + PUBLISH_LEASE) == 0


async def test_crash_lease_expires_at_publish(ready, service, session_factory):
    group, admin, draft = ready
    with pytest.raises(RuntimeError):
        await service.publish(group.id, admin, draft.id, FakePublisher(RuntimeError("crash")), NOW)
    publisher = FakePublisher()
    within = await service.publish(group.id, admin, draft.id, publisher, NOW)
    assert within.outcome is PublishOutcome.IN_PROGRESS
    later = NOW + PUBLISH_LEASE
    after = await service.publish(group.id, admin, draft.id, publisher, later)
    assert after.outcome is PublishOutcome.UNKNOWN
    assert publisher.sent == []
    state = await service.draft_state(group.id, admin, draft.id, later)
    assert state.publication is PublicationStatus.PUBLISH_UNKNOWN


async def test_late_success_still_publishes(ready, service, session_factory):
    group, admin, draft = ready

    async def lease_expires_during_send():
        await recover_expired(session_factory, NOW + PUBLISH_LEASE)

    publisher = FakePublisher(during=lease_expires_during_send)
    result = await service.publish(group.id, admin, draft.id, publisher, NOW)
    assert result.outcome is PublishOutcome.PUBLISHED
    assert await attempts(session_factory) == [("published", 501, None)]
    assert await session_status(session_factory, draft.id) == SessionStatus.OPEN


async def test_non_admin_cannot_publish_or_resolve(ready, service, session_factory):
    group, _, draft = ready
    # A user who is not a Telegram admin of the group.
    outsider = 5001
    publisher = FakePublisher()
    with pytest.raises(AccessDenied):
        await service.publish(group.id, outsider, draft.id, publisher, NOW)
    with pytest.raises(AccessDenied):
        await service.resolve(group.id, outsider, draft.id, seen=True, now=NOW)
    with pytest.raises(AccessDenied):
        await service.list_drafts(group.id, outsider)
    assert publisher.sent == [] and await attempts(session_factory) == []


async def test_session_of_another_group_is_not_found(ready, service, session_factory, admins):
    group, admin, draft = ready
    band = await add_group(session_factory, -200, "Band")
    admins.grant(band.telegram_chat_id, 2002)
    publisher = FakePublisher()
    # A Band admin cannot publish or review a Samba session, even with its ID.
    with pytest.raises(NotFound):
        await service.publish(band.id, 2002, draft.id, publisher, NOW)
    with pytest.raises(NotFound):
        await service.review(band.id, 2002, draft.id)
    with pytest.raises(AccessDenied):
        await service.publish(group.id, 2002, draft.id, publisher, NOW)
    assert publisher.sent == []
    review = await service.review(group.id, admin, draft.id)
    assert review.group.title == "Samba Group"


async def test_poll_follows_a_group_upgrade(ready, service, session_factory):
    group, admin, draft = ready
    await GroupService(session_factory).migrate(group.telegram_chat_id, -1009)
    publisher = FakePublisher()
    # The fake admin check knows the old chat ID only, so grant the new one.
    service.access.checker.grant(-1009, admin)
    await service.publish(group.id, admin, draft.id, publisher, NOW)
    assert [sent[0] for sent in publisher.sent] == [-1009]


async def test_missing_session_is_not_found(ready, service):
    group, admin, _ = ready
    with pytest.raises(NotFound):
        await service.publish(group.id, admin, 999, FakePublisher(), NOW)


async def test_list_drafts_shows_attempt_state(ready, service, attendance_club):
    group, admin, draft = ready
    second = await create(attendance_club, new_series_name="Prac")
    await service.publish(group.id, admin, draft.id, FakePublisher(PublishUnknown()), NOW)
    drafts = {row.id: row.publication for row in await service.list_drafts(group.id, admin)}
    assert drafts == {draft.id: PublicationStatus.PUBLISH_UNKNOWN, second.id: None}


async def test_archived_draft_is_hidden_and_cannot_publish(ready, service, archive_after):
    group, admin, draft = ready
    archived = draft.deadline + archive_after + timedelta(seconds=1)
    assert [row.id for row in await service.list_drafts(group.id, admin, now=NOW)] == [draft.id]
    assert await service.list_drafts(group.id, admin, now=archived) == []
    with pytest.raises(NotDraft, match="archived"):
        await service.publish(group.id, admin, draft.id, FakePublisher(), archived)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (BadRequest("chat not found"), PublishRejected),
        (Forbidden("bot was kicked"), PublishRejected),
        (RetryAfter(timedelta(seconds=5)), PublishRejected),
        (ChatMigrated(-1001), PublishRejected),
        (InvalidToken(), PublishRejected),
        (TimedOut(), PublishUnknown),
        (NetworkError("reset"), PublishUnknown),
    ],
)
async def test_telegram_error_mapping(error, expected):
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=error))
    with pytest.raises(expected) as raised:
        await TelegramPublisher(bot).send_poll(-100, "text", 7)
    if expected is PublishRejected:
        assert raised.value.failure == type(error).__name__


async def test_telegram_publisher_sends_poll_buttons():
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=42)))
    assert await TelegramPublisher(bot).send_poll(-100, "text", 7) == 42
    markup = bot.send_message.await_args.kwargs["reply_markup"]
    assert buttons(markup) == [
        ("Coming", "v:7:c"),
        ("Not Coming", "v:7:n"),
        ("Late", "v:7:l"),
        ("Leaving Early", "v:7:e"),
    ]


def test_callback_format():
    token = "A" * 16
    assert parse_callback(callback(token, "s", 5)) == (token, "s", 5)
    assert parse_callback(callback(token, "y")) == (token, "y", None)
    assert parse_callback(f"p:{token}:s") is None
    assert parse_callback(f"p:{token}:y:3") is None
    assert parse_callback(f"a:{token}:y") is None


# Handler flow


@pytest.fixture
def flow(attendance_club, access, service):
    return PublicationHandlers(access, service)


def bot_context(message_id=900, error=None):
    send = AsyncMock(return_value=SimpleNamespace(message_id=message_id), side_effect=error)
    return SimpleNamespace(bot=SimpleNamespace(send_message=send))


async def press(flow, action, value=None, user_id=1001, context=None):
    pending = flow.pending[(user_id, user_id)]
    update = callback_update(
        user_id, None, callback(pending.token, action, value), message_id=pending.message_id
    )
    await flow.button(update, context or bot_context())
    return update


async def test_handler_publishes_after_review(ready, flow, session_factory):
    _, _, draft = ready
    start = message_update(1001, None, text="/publish")
    await flow.start(start, bot_context())
    [(text, markup)] = replies(start)
    assert text == messages.PUBLISH_SELECT_SESSION
    assert buttons(markup)[0][0] == "Patrons Day · 2026-10-13"
    # One group: no group step. The review names the session's group.
    reviewed = await press(flow, "s", draft.id)
    review_text = replies(reviewed)[0][0]
    assert review_text.startswith("Group: Samba Group\n\nAttendance — Patrons Day")
    context = bot_context()
    published = await press(flow, "y", context=context)
    assert replies(published) == [(messages.PUBLISH_DONE, None)]
    assert context.bot.send_message.await_count == 1
    assert await session_status(session_factory, draft.id) == SessionStatus.OPEN
    assert (1001, 1001) not in flow.pending


async def test_handler_timeout_shows_resolution(ready, flow, session_factory):
    _, _, draft = ready
    await flow.start(message_update(1001, None, text="/publish"), bot_context())
    await press(flow, "s", draft.id)
    unknown = await press(flow, "y", context=bot_context(error=TimedOut()))
    [(text, markup)] = replies(unknown)
    assert text == messages.PUBLISH_UNKNOWN
    assert [label for label, _ in buttons(markup)] == [
        messages.I_SEE_POLL,
        messages.I_CANT_SEE_POLL,
        messages.CANCEL,
    ]
    failed = await press(flow, "x")
    assert replies(failed) == [(messages.PUBLISH_NOT_SEEN, None)]
    assert await attempts(session_factory) == [("failed", None, "not_seen")]


async def test_handler_unknown_session_offers_resolution(ready, flow, service, session_factory):
    group, admin, draft = ready
    await service.publish(group.id, admin, draft.id, FakePublisher(PublishUnknown()), NOW)
    start = message_update(1001, None, text="/publish")
    await flow.start(start, bot_context())
    assert buttons(replies(start)[0][1])[0][0].endswith("(check)")
    selected = await press(flow, "s", draft.id)
    assert replies(selected)[0][0] == messages.PUBLISH_UNKNOWN
    seen = await press(flow, "v")
    assert replies(seen) == [(messages.PUBLISH_DONE_NO_EDIT, None)]
    assert await session_status(session_factory, draft.id) == SessionStatus.OPEN


async def test_handler_rejection_message(ready, flow):
    _, _, draft = ready
    await flow.start(message_update(1001, None, text="/publish"), bot_context())
    await press(flow, "s", draft.id)
    rejected = await press(flow, "y", context=bot_context(error=Forbidden("kicked")))
    assert replies(rejected) == [(messages.PUBLISH_FAILED.format(failure="Forbidden"), None)]


async def test_handler_stale_and_repeated_buttons(ready, flow):
    _, _, draft = ready
    await flow.start(message_update(1001, None, text="/publish"), bot_context())
    pending = flow.pending[(1001, 1001)]
    token, message_id = pending.token, pending.message_id
    await press(flow, "s", draft.id)
    repeat = callback_update(1001, None, callback(token, "s", draft.id), message_id=message_id)
    await flow.button(repeat, bot_context())
    repeat.callback_query.answer.assert_awaited_once_with(messages.PUBLISH_EXPIRED, show_alert=True)
    # A group button that the prompt never offered.
    pending = flow.pending[(1001, 1001)]
    forged = callback_update(
        1001, None, callback(pending.token, "g", 999), message_id=pending.message_id
    )
    await flow.button(forged, bot_context())
    forged.callback_query.answer.assert_awaited_once_with(messages.PUBLISH_EXPIRED, show_alert=True)


async def test_handler_denies_non_admin(ready, flow, session_factory, attendance_club, admins):
    await add_member(session_factory, attendance_club[0].id, "Linked", telegram_id=3003)
    start = message_update(3003, None, text="/publish")
    await flow.start(start, bot_context())
    assert replies(start) == [(messages.PUBLISH_DENIED, None)]
    stranger = message_update(4004, None, text="/publish")
    await flow.start(stranger, bot_context())
    assert replies(stranger) == [(messages.PUBLISH_DENIED, None)]
    assert flow.pending == {}
    admins.fail = True
    failed = message_update(1001, None, text="/publish")
    await flow.start(failed, bot_context())
    assert replies(failed) == [(messages.ADMIN_CHECK_FAILED, None)]
    assert flow.pending == {}


async def test_handler_needs_drafts(attendance_club, flow):
    start = message_update(1001, None, text="/publish")
    await flow.start(start, bot_context())
    assert replies(start) == [(messages.PUBLISH_NO_DRAFTS, None)]
    assert flow.pending == {}


async def test_handler_admin_of_two_groups_picks_the_group(ready, flow, session_factory, admins):
    _, _, draft = ready
    band = await add_group(session_factory, -200, "Band")
    admins.grant(band.telegram_chat_id, 1001)
    start = message_update(1001, None, text="/publish")
    await flow.start(start, bot_context())
    [(text, markup)] = replies(start)
    assert text == messages.SELECT_GROUP
    assert [label for label, _ in buttons(markup)] == ["Band", "Samba Group", messages.CANCEL]
    # Band has no Draft session.
    empty = await press(flow, "g", band.id)
    assert replies(empty) == [(messages.PUBLISH_NO_DRAFTS, None)]
    assert (1001, 1001) not in flow.pending
    await flow.start(message_update(1001, None, text="/publish"), bot_context())
    samba = flow.pending[(1001, 1001)].offered_groups - {band.id}
    sessions = await press(flow, "g", samba.pop())
    assert buttons(replies(sessions)[0][1])[0][0] == "Patrons Day · 2026-10-13"
    reviewed = await press(flow, "s", draft.id)
    assert replies(reviewed)[0][0].startswith("Group: Samba Group")


async def test_handler_pages_of_ten(attendance_club, flow, session_factory):
    for index in range(11):
        await create(attendance_club, new_series_name=f"Series {index:02}")
    start = message_update(1001, None, text="/publish")
    await flow.start(start, bot_context())
    labels = [label for label, _ in buttons(replies(start)[0][1])]
    assert len(labels) == 12 and labels[-2:] == [messages.NEXT, messages.CANCEL]
    page = await press(flow, "p", 1)
    labels = [label for label, _ in buttons(replies(page)[0][1])]
    assert len(labels) == 3 and labels[-2:] == [messages.PREVIOUS, messages.CANCEL]


async def test_namelist_member_is_not_an_admin(ready, service, session_factory):
    group, _, draft = ready
    member = await add_member(session_factory, group.id, "Viewer", telegram_id=3003)
    with pytest.raises(AccessDenied):
        await service.review(group.id, member.telegram_user_id, draft.id)
