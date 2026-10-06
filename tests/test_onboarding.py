import pytest
from conftest import add_group
from sqlalchemy import select
from telegram_fakes import buttons, callback_update, context, message_update, replies

from attendee.application.identity import IdentityService
from attendee.application.matching import AccountMatchingService
from attendee.domain.matching import UnresolvedReason
from attendee.persistence.models import Person, UnresolvedMatch
from attendee.telegram import messages
from attendee.telegram.onboarding import OnboardingHandlers, match_callback, render


@pytest.fixture
async def club(group):
    return group


@pytest.fixture
def matching(session_factory):
    return AccountMatchingService(session_factory)


@pytest.fixture
def handlers(matching):
    return OnboardingHandlers(matching)


async def add_member(factory, group_id, name, handle=None, telegram_user_id=None):
    return await IdentityService(factory).create_person(group_id, name, telegram_user_id, handle)


async def propose(matching, group_id, telegram_user_id, username):
    """The reply that a match in this group shows. A poll tap starts it in sub-step 2."""
    text, markup = render(await matching.match(group_id, telegram_user_id, username), group_id)
    return text, buttons(markup)


async def press(handlers, telegram_user_id, username, data):
    update = callback_update(telegram_user_id, username, data)
    await handlers.answer(update, context())
    query = update.callback_query
    query.answer.assert_awaited_once()
    call = query.edit_message_text.await_args
    return call.args[0], buttons(call.kwargs.get("reply_markup"))


async def telegram_id_of(factory, person_id):
    async with factory() as session:
        return (await session.get(Person, person_id)).telegram_user_id


async def unresolved(factory):
    async with factory() as session:
        rows = await session.scalars(select(UnresolvedMatch).order_by(UnresolvedMatch.id))
        return [(row.telegram_user_id, row.reason) for row in rows]


async def test_private_start_points_to_the_group_poll(handlers, club, session_factory):
    """A private /start names no group, so it binds nothing (decision T80)."""
    await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    update = message_update(555, "sarahlim")
    await handlers.start(update, context())
    assert replies(update) == [(messages.START_FROM_GROUP, None)]
    assert await unresolved(session_factory) == []


async def test_linked_account(matching, club, session_factory):
    await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim", 555)
    assert await propose(matching, club.id, 555, "sarahlim") == (messages.ALREADY_LINKED, [])


async def test_confirmed_handle_match(handlers, matching, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    text, keyboard = await propose(matching, club.id, 555, "SarahLim")
    yes = match_callback(True, club.id, sarah.id)
    no = match_callback(False, club.id, sarah.id)
    assert (text, keyboard) == (messages.confirm_name("Sarah Lim"), [("Yes", yes), ("No", no)])
    assert await telegram_id_of(session_factory, sarah.id) is None
    assert await press(handlers, 555, "SarahLim", yes) == (messages.LINKED, [])
    assert await telegram_id_of(session_factory, sarah.id) == 555
    # A repeated Yes or a late No has no extra effect.
    assert await press(handlers, 555, "SarahLim", yes) == (messages.ALREADY_LINKED, [])
    assert await press(handlers, 555, "SarahLim", no) == (messages.ALREADY_LINKED, [])
    assert await telegram_id_of(session_factory, sarah.id) == 555
    assert await unresolved(session_factory) == []


async def test_rejected_match(handlers, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    no = match_callback(False, club.id, sarah.id)
    for _ in range(2):
        assert await press(handlers, 555, "sarahlim", no) == (messages.NOT_MATCHED, [])
    assert await telegram_id_of(session_factory, sarah.id) is None
    assert await unresolved(session_factory) == [(555, UnresolvedReason.CANDIDATE_REJECTED)]


async def test_no_match_and_no_username(matching, club, session_factory):
    await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    assert await propose(matching, club.id, 555, "someoneelse") == (messages.NOT_MATCHED, [])
    assert await propose(matching, club.id, 556, None) == (messages.NOT_MATCHED, [])
    assert await unresolved(session_factory) == [
        (555, UnresolvedReason.NO_MATCH),
        (556, UnresolvedReason.NO_MATCH),
    ]


async def test_ambiguous_match_shows_no_names(matching, club, session_factory):
    for name in ("Twin Alpha", "Twin Beta"):
        await add_member(session_factory, club.id, name, "@twins")
    text, keyboard = await propose(matching, club.id, 555, "twins")
    assert (text, keyboard) == (messages.NOT_MATCHED, [])
    assert "Twin" not in text


async def test_confirmation_after_another_account_bound_the_person(
    handlers, matching, club, session_factory
):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    yes = match_callback(True, club.id, sarah.id)
    await propose(matching, club.id, 555, "sarahlim")
    await propose(matching, club.id, 777, "sarahlim")
    assert await press(handlers, 777, "sarahlim", yes) == (messages.LINKED, [])
    assert await press(handlers, 555, "sarahlim", yes) == (messages.NOT_MATCHED, [])
    assert await telegram_id_of(session_factory, sarah.id) == 777


async def test_forged_group_in_callback_binds_nothing(handlers, club, session_factory):
    """The group ID in the button is a claim. Only the user's own handle can match."""
    other = await add_group(session_factory, -200, "Other")
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    await add_member(session_factory, other.id, "Owner", "@owner")
    forged = match_callback(True, other.id, sarah.id)
    assert await press(handlers, 555, "sarahlim", forged) == (messages.NOT_MATCHED, [])
    assert await telegram_id_of(session_factory, sarah.id) is None


async def test_stale_and_malformed_callbacks(handlers, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    for data in (match_callback(True, club.id + 99, sarah.id), "m:y:x:1", "m:maybe"):
        assert await press(handlers, 555, "sarahlim", data) == (messages.PROPOSAL_EXPIRED, [])
    assert await telegram_id_of(session_factory, sarah.id) is None
