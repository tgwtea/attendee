import pytest
from sqlalchemy import select
from telegram_fakes import buttons, callback_update, context, message_update, replies

from attendee.application.identity import IdentityService
from attendee.application.matching import AccountMatchingService
from attendee.application.memberships import MembershipService
from attendee.application.organizations import OrganizationService
from attendee.domain.identity import MembershipRole
from attendee.domain.matching import UnresolvedReason
from attendee.persistence.models import Person, UnresolvedMatch
from attendee.telegram import messages
from attendee.telegram.onboarding import OnboardingHandlers, match_callback


@pytest.fixture
async def club(session_factory):
    return await OrganizationService(session_factory).create_organization("club", "Club")


@pytest.fixture
def handlers(club, session_factory):
    return OnboardingHandlers(club.id, AccountMatchingService(session_factory))


async def add_member(factory, organization_id, name, handle=None, telegram_user_id=None):
    person = await IdentityService(factory).create_person(name, telegram_user_id, handle)
    await MembershipService(factory).add_membership(
        organization_id, person.id, MembershipRole.MEMBER
    )
    return person


async def start(handlers, telegram_user_id, username):
    update = message_update(telegram_user_id, username)
    await handlers.start(update, context())
    [(text, markup)] = replies(update)
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


async def test_linked_account(handlers, club, session_factory):
    await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim", 555)
    assert await start(handlers, 555, "sarahlim") == (messages.ALREADY_LINKED, [])


async def test_confirmed_handle_match(handlers, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    text, keyboard = await start(handlers, 555, "SarahLim")
    yes = match_callback(True, club.id, sarah.id)
    no = match_callback(False, club.id, sarah.id)
    assert (text, keyboard) == ("Are you Sarah Lim?", [("Yes", yes), ("No", no)])
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


async def test_no_match_and_no_username(handlers, club, session_factory):
    await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    assert await start(handlers, 555, "someoneelse") == (messages.NOT_MATCHED, [])
    assert await start(handlers, 556, None) == (messages.NOT_MATCHED, [])
    assert await unresolved(session_factory) == [
        (555, UnresolvedReason.NO_MATCH),
        (556, UnresolvedReason.NO_MATCH),
    ]


async def test_ambiguous_match_shows_no_names(handlers, club, session_factory):
    for name in ("Twin Alpha", "Twin Beta"):
        await add_member(session_factory, club.id, name, "@twins")
    text, keyboard = await start(handlers, 555, "twins")
    assert (text, keyboard) == (messages.NOT_MATCHED, [])
    assert "Twin" not in text


async def test_taken_telegram_id_shows_no_details(handlers, club, session_factory):
    other = await OrganizationService(session_factory).create_organization("other", "Other")
    await add_member(session_factory, other.id, "Owner", "@owner", 555)
    await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    text, keyboard = await start(handlers, 555, "sarahlim")
    assert (text, keyboard) == (messages.NOT_MATCHED, [])
    assert "owner" not in text.lower() and "555" not in text
    assert await unresolved(session_factory) == [(555, UnresolvedReason.TELEGRAM_ID_TAKEN)]


async def test_confirmation_after_another_account_bound_the_person(handlers, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    yes = match_callback(True, club.id, sarah.id)
    await start(handlers, 555, "sarahlim")
    await start(handlers, 777, "sarahlim")
    assert await press(handlers, 777, "sarahlim", yes) == (messages.LINKED, [])
    assert await press(handlers, 555, "sarahlim", yes) == (messages.NOT_MATCHED, [])
    assert await telegram_id_of(session_factory, sarah.id) == 777


async def test_stale_and_malformed_callbacks(handlers, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    for data in (match_callback(True, club.id + 1, sarah.id), "m:y:x:1", "m:maybe"):
        assert await press(handlers, 555, "sarahlim", data) == (messages.PROPOSAL_EXPIRED, [])
    assert await telegram_id_of(session_factory, sarah.id) is None
