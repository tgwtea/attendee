import asyncio

import pytest
from conftest import add_group
from sqlalchemy import func, select

from attendee.application.identity import IdentityService
from attendee.application.matching import AccountMatchingService
from attendee.domain.matching import MatchOutcome, UnresolvedReason
from attendee.persistence.database import create_engine, create_session_factory
from attendee.persistence.models import Person, UnresolvedMatch


@pytest.fixture
def matching(session_factory):
    return AccountMatchingService(session_factory)


@pytest.fixture
async def club(group):
    return group


async def add_member(factory, group_id, name, handle=None, telegram_user_id=None):
    return await IdentityService(factory).create_person(group_id, name, telegram_user_id, handle)


async def unresolved_rows(factory):
    async with factory() as session:
        return list(await session.scalars(select(UnresolvedMatch).order_by(UnresolvedMatch.id)))


async def bind(matching, group_id, telegram_user_id, handle):
    proposal = await matching.match(group_id, telegram_user_id, handle)
    assert proposal.outcome is MatchOutcome.PROPOSED
    return await matching.confirm(group_id, telegram_user_id, handle, proposal.person.id)


async def bound_count(factory, telegram_user_id):
    async with factory() as session:
        return await session.scalar(
            select(func.count())
            .select_from(Person)
            .where(Person.telegram_user_id == telegram_user_id)
        )


async def test_handle_match_proposes_and_binds_nothing(matching, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    result = await matching.match(club.id, 555, "@SarahLim")
    assert (result.outcome, result.person.id, result.person.telegram_user_id) == (
        MatchOutcome.PROPOSED,
        sarah.id,
        None,
    )
    assert await bound_count(session_factory, 555) == 0
    assert await unresolved_rows(session_factory) == []


async def test_confirm_binds_then_matches_by_id(matching, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    result = await bind(matching, club.id, 555, "@SarahLim")
    assert result.outcome is MatchOutcome.BOUND_BY_HANDLE
    assert result.person is not None
    assert (result.person.id, result.person.telegram_user_id) == (sarah.id, 555)

    again = await matching.match(club.id, 555, "sarahlim")
    assert again.outcome is MatchOutcome.BY_TELEGRAM_ID
    assert again.person == result.person
    assert await unresolved_rows(session_factory) == []
    repeated = await matching.confirm(club.id, 555, "sarahlim", sarah.id)
    assert (repeated.outcome, repeated.person) == (MatchOutcome.BY_TELEGRAM_ID, result.person)


async def test_reject_binds_nothing_and_records_once(matching, club, session_factory):
    await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    first = await matching.reject(club.id, 555, "@sarahlim")
    [record] = await unresolved_rows(session_factory)
    second = await matching.reject(club.id, 555, "@sarahlim")
    [again] = await unresolved_rows(session_factory)
    assert first == second
    assert (first.outcome, first.reason) == (
        MatchOutcome.UNRESOLVED,
        UnresolvedReason.CANDIDATE_REJECTED,
    )
    assert (again.id, again.updated_at) == (record.id, record.updated_at)
    assert await bound_count(session_factory, 555) == 0
    # A later confirmation still binds, and it resolves the record.
    await bind(matching, club.id, 555, "@sarahlim")
    assert await matching.list_unresolved(club.id) == []


async def test_reject_after_binding_changes_nothing(matching, club, session_factory):
    await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    await bind(matching, club.id, 555, "@sarahlim")
    result = await matching.reject(club.id, 555, "@sarahlim")
    assert result.outcome is MatchOutcome.BY_TELEGRAM_ID
    assert await bound_count(session_factory, 555) == 1


async def test_confirm_after_another_account_bound_the_person(matching, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    proposal = await matching.match(club.id, 555, "@sarahlim")
    await bind(matching, club.id, 777, "@sarahlim")
    result = await matching.confirm(club.id, 555, "@sarahlim", proposal.person.id)
    assert (result.outcome, result.reason) == (MatchOutcome.UNRESOLVED, UnresolvedReason.NO_MATCH)
    assert await bound_count(session_factory, 555) == 0
    assert await bound_count(session_factory, 777) == 1
    assert sarah.id == proposal.person.id


async def test_confirm_for_another_candidate_binds_nothing(matching, club, session_factory):
    await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    alex = await add_member(session_factory, club.id, "Alex Ng", "@alexng")
    # The account now has another handle, so the old confirmation is stale.
    result = await matching.confirm(club.id, 555, "@sarahlim", alex.id)
    assert result.outcome is MatchOutcome.PROPOSED
    assert result.person.id != alex.id
    assert await bound_count(session_factory, 555) == 0


async def test_handle_change_after_binding_keeps_identity(matching, club, session_factory):
    sarah = await add_member(session_factory, club.id, "Sarah Lim", "@sarahlim")
    await bind(matching, club.id, 555, "sarahlim")
    result = await matching.match(club.id, 555, "@sarah_new")
    assert result.outcome is MatchOutcome.BY_TELEGRAM_ID
    assert result.person is not None
    assert (result.person.id, result.person.telegram_handle) == (sarah.id, "sarah_new")
    # The old handle no longer binds anyone else.
    other = await matching.match(club.id, 777, "sarahlim")
    assert (other.outcome, other.reason) == (MatchOutcome.UNRESOLVED, UnresolvedReason.NO_MATCH)


async def test_no_match_and_name_is_never_used(matching, club, session_factory):
    await add_member(session_factory, club.id, "sarahlim", "@someone")
    result = await matching.match(club.id, 555, "@sarahlim")
    assert (result.outcome, result.person, result.reason) == (
        MatchOutcome.UNRESOLVED,
        None,
        UnresolvedReason.NO_MATCH,
    )
    no_handle = await matching.match(club.id, 556, None)
    assert no_handle.reason is UnresolvedReason.NO_MATCH
    [first, second] = await unresolved_rows(session_factory)
    assert (first.telegram_user_id, first.telegram_handle) == (555, "sarahlim")
    assert (second.telegram_user_id, second.telegram_handle) == (556, None)


async def test_ambiguous_handle_binds_nobody(matching, club, session_factory):
    for name in ("Twin A", "Twin B"):
        await add_member(session_factory, club.id, name, "@twins")
    result = await matching.match(club.id, 555, "@twins")
    assert result.reason is UnresolvedReason.AMBIGUOUS
    async with session_factory() as session:
        bound = await session.scalar(
            select(func.count()).select_from(Person).where(Person.telegram_user_id == 555)
        )
    assert bound == 0


async def test_telegram_id_bound_in_another_group_does_not_block(matching, club, session_factory):
    """Each group has its own copy of a person, so one user links in each group (T82)."""
    other = await add_group(session_factory, -200, "Other")
    owner = await add_member(session_factory, other.id, "Owner", "@owner", 555)
    sarah = await add_member(session_factory, club.id, "Sarah", "@sarahlim")
    result = await bind(matching, club.id, 555, "@sarahlim")
    assert (result.outcome, result.person.id) == (MatchOutcome.BOUND_BY_HANDLE, sarah.id)
    assert (await matching.match(other.id, 555, "@owner")).person.id == owner.id
    assert await bound_count(session_factory, 555) == 2


async def test_repeated_call_has_no_extra_effect(matching, club, session_factory):
    first = await matching.match(club.id, 555, "@nobody")
    [record] = await unresolved_rows(session_factory)
    second = await matching.match(club.id, 555, "@nobody")
    [again] = await unresolved_rows(session_factory)
    assert first == second
    assert (again.id, again.updated_at, again.reason) == (
        record.id,
        record.updated_at,
        record.reason,
    )


async def test_later_success_resolves_the_record(matching, club, session_factory):
    await matching.match(club.id, 555, "@sarahlim")
    await add_member(session_factory, club.id, "Sarah", "@sarahlim")
    assert len(await matching.list_unresolved(club.id)) == 1
    assert (await bind(matching, club.id, 555, "@sarahlim")).person is not None
    assert await matching.list_unresolved(club.id) == []
    [record] = await unresolved_rows(session_factory)
    assert record.resolved_at is not None


async def test_matching_is_isolated_per_group(matching, club, session_factory):
    other = await add_group(session_factory, -200, "Other")
    await add_member(session_factory, other.id, "Sarah", "@sarahlim")
    result = await matching.match(club.id, 555, "@sarahlim")
    assert result.reason is UnresolvedReason.NO_MATCH
    assert len(await matching.list_unresolved(club.id)) == 1
    assert await matching.list_unresolved(other.id) == []


async def test_concurrent_calls_bind_one_telegram_id_once(club, session_factory, migrated_settings):
    sarah = await add_member(session_factory, club.id, "Sarah", "@sarahlim")
    alex = await add_member(session_factory, club.id, "Alex", "@alexng")
    engines = [create_engine(migrated_settings) for _ in range(4)]
    try:
        services = [AccountMatchingService(create_session_factory(engine)) for engine in engines]
        results = await asyncio.gather(
            services[0].confirm(club.id, 555, "@sarahlim", sarah.id),
            services[1].confirm(club.id, 555, "@sarahlim", sarah.id),
            services[2].confirm(club.id, 555, "@alexng", alex.id),
            services[3].confirm(club.id, 777, "@sarahlim", sarah.id),
        )
    finally:
        for engine in engines:
            await engine.dispose()
    async with session_factory() as session:
        bound = list(
            await session.execute(
                select(Person.telegram_handle, Person.telegram_user_id).where(
                    Person.telegram_user_id.is_not(None)
                )
            )
        )
    # Each Telegram ID binds to one person only, and each person holds one ID only.
    telegram_ids = [telegram_user_id for _, telegram_user_id in bound]
    assert len(telegram_ids) == len(set(telegram_ids)) >= 1
    assert sum(result.outcome is MatchOutcome.BOUND_BY_HANDLE for result in results) == len(bound)
    sarah_ids = {
        result.person.id
        for result in results[:2]
        if result.person is not None and result.outcome is not MatchOutcome.PROPOSED
    }
    assert len(sarah_ids) <= 1


async def test_concurrent_identical_calls_bind_once(club, session_factory, migrated_settings):
    sarah = await add_member(session_factory, club.id, "Sarah", "@sarahlim")
    engines = [create_engine(migrated_settings) for _ in range(5)]
    try:
        results = await asyncio.gather(
            *(
                AccountMatchingService(create_session_factory(engine)).confirm(
                    club.id, 555, "@sarahlim", sarah.id
                )
                for engine in engines
            )
        )
    finally:
        for engine in engines:
            await engine.dispose()
    assert {result.person.id for result in results if result.person is not None} == {sarah.id}
    assert sorted(result.outcome for result in results) == sorted(
        [MatchOutcome.BOUND_BY_HANDLE] + [MatchOutcome.BY_TELEGRAM_ID] * 4
    )
