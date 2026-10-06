"""Linking an account from a poll tap (decisions T88–T90)."""

from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import add_group
from sqlalchemy import select, update
from telegram import ForceReply
from telegram_fakes import buttons, callback_update, context, message_update, replies
from test_attendance import create

from attendee.application.groups import GroupService
from attendee.application.identity import IdentityService
from attendee.application.matching import AccountMatchingService
from attendee.application.responses import ResponseService
from attendee.domain.attendance import SessionStatus
from attendee.domain.matching import UnresolvedReason
from attendee.domain.responses import ResponseStatus
from attendee.persistence.models import AttendanceSession, Person, SessionResponse, UnresolvedMatch
from attendee.telegram import messages
from attendee.telegram.onboarding import OnboardingHandlers, match_callback
from attendee.telegram.responses import PendingReason, ResponseHandlers

SARAH = 555
_ids = count(1000)


@pytest.fixture
async def club(attendance_club, session_factory):
    """(group, Sarah unlinked with @sarahlim, an Open session)."""
    group = attendance_club[0]
    sarah = await add_member(session_factory, group.id, "Sarah Lim", "@sarahlim")
    draft = await create(attendance_club)
    await set_status(session_factory, draft.id, SessionStatus.OPEN)
    return group, sarah, draft


@pytest.fixture
def handlers(session_factory):
    return make_handlers(session_factory)


def make_handlers(factory):
    return ResponseHandlers(
        GroupService(factory), ResponseService(factory), AccountMatchingService(factory)
    )


async def add_member(factory, group_id, name, handle=None, telegram_user_id=None):
    return await IdentityService(factory).create_person(group_id, name, telegram_user_id, handle)


async def set_status(factory, session_id, status):
    async with factory.begin() as session:
        await session.execute(
            update(AttendanceSession)
            .where(AttendanceSession.id == session_id)
            .values(status=status.value)
        )


def bot():
    send = AsyncMock(side_effect=lambda *_a, **_k: SimpleNamespace(message_id=next(_ids)))
    return SimpleNamespace(bot=SimpleNamespace(username="attendee_bot", send_message=send))


def sent(ctx):
    return [
        (call.args[1], call.kwargs.get("reply_markup"))
        for call in ctx.bot.send_message.await_args_list
    ]


async def tap(handlers, session_id, code, user=SARAH, username="sarahlim", chat_id=-100):
    update = callback_update(
        user, username, f"v:{session_id}:{code}", chat_id=chat_id, chat_type="supergroup"
    )
    await handlers.tap(update, bot())
    return update.callback_query.answer


async def link_start(handlers, user=SARAH, username="sarahlim", ctx=None):
    update = message_update(user, username, text="/start link")
    await handlers.link_start(update, ctx or bot())
    [(text, markup)] = replies(update)
    return text, buttons(markup)


async def press(handlers, data, user=SARAH, username="sarahlim", ctx=None):
    update = callback_update(user, username, data)
    await handlers.link_answer(update, ctx or bot())
    update.callback_query.answer.assert_awaited_once()
    call = update.callback_query.edit_message_text.await_args
    return call.args[0], buttons(call.kwargs.get("reply_markup"))


async def telegram_id_of(factory, person_id):
    async with factory() as session:
        return (await session.get(Person, person_id)).telegram_user_id


async def responses(factory):
    async with factory() as session:
        rows = await session.scalars(select(SessionResponse))
        return [(row.status, row.reason) for row in rows]


async def unresolved(factory):
    async with factory() as session:
        rows = await session.scalars(select(UnresolvedMatch).order_by(UnresolvedMatch.id))
        return [(row.telegram_user_id, row.reason) for row in rows]


async def test_private_start_points_to_the_group_poll(session_factory):
    """A private /start names no group, so it binds nothing (decision T80)."""
    update = message_update(SARAH, "sarahlim")
    await OnboardingHandlers().start(update, context())
    assert replies(update) == [(messages.START_FROM_GROUP, None)]
    assert await unresolved(session_factory) == []


async def test_coming_tap_is_saved_after_yes(handlers, club, session_factory):
    group, sarah, draft = club
    answer = await tap(handlers, draft.id, "c")
    answer.assert_awaited_once_with(url="https://t.me/attendee_bot?start=link")
    # The tap is kept. Nothing is bound or saved before Yes (T88).
    assert handlers.links == {SARAH: PendingReason(group.id, draft.id, ResponseStatus.COMING)}
    assert await telegram_id_of(session_factory, sarah.id) is None
    assert await responses(session_factory) == []

    text, keyboard = await link_start(handlers)
    yes = match_callback(True, group.id, sarah.id)
    no = match_callback(False, group.id, sarah.id)
    assert (text, keyboard) == (messages.confirm_name("Sarah Lim"), [("Yes", yes), ("No", no)])

    ctx = bot()
    assert await press(handlers, yes, ctx=ctx) == (messages.LINKED, [])
    assert sent(ctx) == [(messages.RECORDED.format(status="Coming"), None)]
    assert await telegram_id_of(session_factory, sarah.id) == SARAH
    assert await responses(session_factory) == [("coming", None)]
    assert handlers.links == {}
    # A repeated Yes links nothing new and saves nothing new.
    assert await press(handlers, yes) == (messages.LINK_TAP_AGAIN, [])
    assert await responses(session_factory) == [("coming", None)]


async def test_reason_tap_asks_for_the_reason_after_yes(handlers, club, session_factory):
    group, sarah, draft = club
    await tap(handlers, draft.id, "l")
    await link_start(handlers)
    ctx = bot()
    await press(handlers, match_callback(True, group.id, sarah.id), ctx=ctx)
    [(prompt, markup)] = sent(ctx)
    assert prompt == messages.REASON_PROMPT.format(
        status="Late", session="Patrons Day on 13 October 2026"
    )
    assert isinstance(markup, ForceReply)
    # Nothing is saved before the reason arrives (PRD §23).
    assert await responses(session_factory) == []
    [prompt_id] = [key[1] for key in handlers.prompts if key[0] == SARAH]
    reply = message_update(SARAH, "sarahlim", text="Class ends late")
    reply.effective_message.reply_to_message = SimpleNamespace(message_id=prompt_id)
    await handlers.reason(reply, ctx)
    assert await responses(session_factory) == [("late", "Class ends late")]


async def test_no_links_nothing_and_drops_the_tap(handlers, club, session_factory):
    group, sarah, draft = club
    await tap(handlers, draft.id, "c")
    await link_start(handlers)
    no = match_callback(False, group.id, sarah.id)
    expected = messages.LINK_NOT_FOUND.format(handle="sarahlim")
    assert await press(handlers, no) == (expected, [])
    assert await telegram_id_of(session_factory, sarah.id) is None
    assert await responses(session_factory) == []
    assert handlers.links == {}
    assert await unresolved(session_factory) == [(SARAH, UnresolvedReason.CANDIDATE_REJECTED)]


async def test_no_match_shows_only_the_users_own_username(handlers, club, session_factory):
    _, _, draft = club
    await tap(handlers, draft.id, "c", user=556, username="SomeoneElse")
    text, keyboard = await link_start(handlers, user=556, username="SomeoneElse")
    assert (text, keyboard) == (messages.LINK_NOT_FOUND.format(handle="SomeoneElse"), [])
    assert "Sarah" not in text and "sarahlim" not in text
    await tap(handlers, draft.id, "c", user=557, username=None)
    assert await link_start(handlers, user=557, username=None) == (messages.LINK_NO_USERNAME, [])
    assert handlers.links == {}
    assert await unresolved(session_factory) == [
        (556, UnresolvedReason.NO_MATCH),
        (557, UnresolvedReason.NO_MATCH),
    ]


async def test_two_matches_show_no_names(handlers, club, session_factory):
    group, _, draft = club
    for name in ("Twin Alpha", "Twin Beta"):
        await add_member(session_factory, group.id, name, "@twins")
    await tap(handlers, draft.id, "c", user=558, username="twins")
    text, keyboard = await link_start(handlers, user=558, username="twins")
    assert (text, keyboard) == (messages.LINK_NOT_FOUND.format(handle="twins"), [])
    assert "Twin" not in text
    assert await unresolved(session_factory) == [(558, UnresolvedReason.AMBIGUOUS)]


async def test_start_link_without_a_kept_tap(handlers, club):
    assert await link_start(handlers) == (messages.LINK_NO_PENDING, [])


async def test_yes_after_a_restart_links_and_asks_for_a_new_tap(handlers, club, session_factory):
    group, sarah, draft = club
    await tap(handlers, draft.id, "c")
    await link_start(handlers)
    restarted = make_handlers(session_factory)
    yes = match_callback(True, group.id, sarah.id)
    assert await press(restarted, yes) == (messages.LINK_TAP_AGAIN, [])
    assert await telegram_id_of(session_factory, sarah.id) == SARAH
    assert await responses(session_factory) == []
    # The next tap is an ordinary tap of a linked member.
    answer = await tap(restarted, draft.id, "c")
    answer.assert_awaited_once_with(messages.RECORDED.format(status="Coming"), show_alert=True)


async def test_closed_poll_still_links(handlers, club, session_factory):
    group, sarah, draft = club
    await tap(handlers, draft.id, "c")
    await link_start(handlers)
    await set_status(session_factory, draft.id, SessionStatus.CLOSED)
    ctx = bot()
    assert await press(handlers, match_callback(True, group.id, sarah.id), ctx=ctx) == (
        messages.LINKED,
        [],
    )
    assert sent(ctx) == [(messages.POLL_CLOSED, None)]
    assert await telegram_id_of(session_factory, sarah.id) == SARAH
    assert await responses(session_factory) == []


async def test_new_tap_replaces_the_kept_tap(handlers, club):
    group, _, draft = club
    await tap(handlers, draft.id, "c")
    await tap(handlers, draft.id, "e")
    assert handlers.links[SARAH] == PendingReason(group.id, draft.id, ResponseStatus.LEAVING_EARLY)


async def test_another_account_bound_the_person_first(handlers, club, session_factory):
    group, sarah, draft = club
    yes = match_callback(True, group.id, sarah.id)
    for user in (SARAH, 777):
        await tap(handlers, draft.id, "c", user=user)
        await link_start(handlers, user=user)
    assert await press(handlers, yes, user=777) == (messages.LINKED, [])
    expected = messages.LINK_NOT_FOUND.format(handle="sarahlim")
    assert await press(handlers, yes) == (expected, [])
    assert await telegram_id_of(session_factory, sarah.id) == 777


async def test_forged_group_in_callback_binds_nothing(handlers, club, session_factory):
    """The group ID in the button is a claim. Only the user's own handle can match."""
    _, sarah, draft = club
    other = await add_group(session_factory, -200, "Other")
    await add_member(session_factory, other.id, "Owner", "@owner")
    await tap(handlers, draft.id, "c")
    forged = match_callback(True, other.id, sarah.id)
    expected = messages.LINK_NOT_FOUND.format(handle="sarahlim")
    assert await press(handlers, forged) == (expected, [])
    assert await telegram_id_of(session_factory, sarah.id) is None


async def test_tap_in_another_group_is_not_saved_by_this_link(handlers, club, session_factory):
    """A Yes for group A never saves a kept tap from group B."""
    group, sarah, draft = club
    other = await add_group(session_factory, -200, "Other")
    await add_member(session_factory, other.id, "Sarah L.", "@sarahlim")
    await tap(handlers, draft.id, "c", chat_id=-200)
    # The session is not in Other, and Sarah is not linked there: the tap is kept for Other.
    assert handlers.links[SARAH].group_id == other.id
    yes = match_callback(True, group.id, sarah.id)
    assert await press(handlers, yes) == (messages.LINK_TAP_AGAIN, [])
    assert await responses(session_factory) == []


async def test_stale_and_malformed_callbacks(handlers, club, session_factory):
    group, sarah, _ = club
    for data in (match_callback(True, group.id + 99, sarah.id), "m:y:x:1", "m:maybe"):
        assert await press(handlers, data) == (messages.PROPOSAL_EXPIRED, [])
    assert await telegram_id_of(session_factory, sarah.id) is None
