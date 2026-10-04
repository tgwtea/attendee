from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from attendee.application.authorization import AuthorizationService
from attendee.application.errors import AccessDenied, DuplicateMembership, DuplicateTelegramUserId
from attendee.application.identity import IdentityService
from attendee.application.memberships import MembershipService
from attendee.application.organizations import DuplicateOrganization, OrganizationService
from attendee.domain.identity import MembershipRole
from attendee.persistence.database import create_engine, create_session_factory

ADMIN = MembershipRole.ADMIN
MEMBER = MembershipRole.MEMBER


@pytest.fixture
def services(session_factory):
    return (
        OrganizationService(session_factory),
        IdentityService(session_factory),
        MembershipService(session_factory),
        AuthorizationService(session_factory),
    )


async def test_one_person_two_organizations_independent_roles(services):
    organizations, identity, memberships, authorization = services
    first = await organizations.create_organization("first-club", "First Club")
    second = await organizations.create_organization("second-club", "Second Club")
    third = await organizations.create_organization("third-club", "Third Club")
    person = await identity.create_person("Sarah Lim", telegram_user_id=111)
    await memberships.add_membership(first.id, person.id, ADMIN)
    await memberships.add_membership(second.id, person.id, MEMBER)

    assert (await authorization.require_role(first.id, person.id, ADMIN)).role is ADMIN
    assert (await authorization.require_role(first.id, person.id, MEMBER)).role is ADMIN
    assert (await authorization.require_role(second.id, person.id, MEMBER)).role is MEMBER
    with pytest.raises(AccessDenied):
        await authorization.require_role(second.id, person.id, ADMIN)
    with pytest.raises(AccessDenied):
        await authorization.require_role(third.id, person.id, MEMBER)


async def test_unknown_person_or_organization_is_denied(services):
    organizations, identity, _, authorization = services
    organization = await organizations.create_organization("club", "Club")
    person = await identity.create_person("No Membership")
    for organization_id, person_id in ((organization.id, person.id), (999, person.id)):
        with pytest.raises(AccessDenied):
            await authorization.require_role(organization_id, person_id, MEMBER)
    with pytest.raises(AccessDenied):
        await authorization.require_role(organization.id, 999, MEMBER)


async def test_duplicate_telegram_id_and_membership_rejected(services, session_factory):
    organizations, identity, memberships, _ = services
    organization = await organizations.create_organization("club", "Club")
    person = await identity.create_person("A", telegram_user_id=222)
    with pytest.raises(DuplicateTelegramUserId):
        await identity.create_person("B", telegram_user_id=222)
    await memberships.add_membership(organization.id, person.id, MEMBER)
    with pytest.raises(DuplicateMembership):
        await memberships.add_membership(organization.id, person.id, ADMIN)
    with pytest.raises(DuplicateOrganization):
        await organizations.create_organization("club", "Other")

    now = "2026-10-04 00:00:00"
    statements = [
        f"INSERT INTO people (telegram_user_id, created_at, updated_at) "
        f"VALUES (222, '{now}', '{now}')",
        f"INSERT INTO memberships (organization_id, person_id, role, created_at, updated_at) "
        f"VALUES ({organization.id}, {person.id}, 'admin', '{now}', '{now}')",
        f"INSERT INTO memberships (organization_id, person_id, role, created_at, updated_at) "
        f"VALUES (999, {person.id}, 'member', '{now}', '{now}')",
        f"INSERT INTO people (created_at, updated_at) VALUES ('{now}', '{now}')",
        f"INSERT INTO people (telegram_user_id, created_at, updated_at) "
        f"VALUES (0, '{now}', '{now}')",
        f"INSERT INTO organizations (slug, name, created_at) VALUES ('', 'x', '{now}')",
    ]
    for statement in statements:
        with pytest.raises(IntegrityError):
            async with session_factory.begin() as session:
                await session.execute(text(statement))


async def test_invalid_role_rejected_by_database(services, session_factory):
    organizations, identity, _, _ = services
    organization = await organizations.create_organization("club", "Club")
    person = await identity.create_person("A")
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO memberships (organization_id, person_id, role, created_at, "
                    "updated_at) VALUES (:o, :p, 'owner', '2026-10-04', '2026-10-04')"
                ),
                {"o": organization.id, "p": person.id},
            )


async def test_people_without_telegram_id_and_same_names_stay_separate(services):
    _, identity, _, _ = services
    first = await identity.create_person("John Tan", telegram_handle="@johntan")
    second = await identity.create_person("John Tan")
    assert first.telegram_user_id is None
    assert second.telegram_user_id is None
    assert first.id != second.id
    with pytest.raises(ValueError):
        await identity.create_person("  ")
    with pytest.raises(ValueError):
        await identity.create_person(None, telegram_user_id=-5)


async def test_handle_change_keeps_identity(services):
    _, identity, _, _ = services
    person = await identity.create_person("Sarah Lim", 333, "@sarahlim")
    changed = await identity.change_handle(person.id, "@sarah_new")
    assert (changed.id, changed.telegram_user_id) == (person.id, 333)
    assert changed.telegram_handle == "@sarah_new"
    found = await identity.find_by_telegram_user_id(333)
    assert found is not None
    assert found.id == person.id
    assert found.telegram_handle == "@sarah_new"


async def test_timestamps_are_utc(services):
    _, identity, _, _ = services
    person = await identity.create_person("A")
    found = await identity.change_handle(person.id, "@a")
    for value in (found.created_at, found.updated_at):
        assert value.tzinfo is UTC
        assert abs(datetime.now(UTC) - value).total_seconds() < 60


async def test_data_persists_after_engine_recreation(migrated_settings):
    engine = create_engine(migrated_settings)
    try:
        factory = create_session_factory(engine)
        organization = await OrganizationService(factory).create_organization("club", "Club")
        person = await IdentityService(factory).create_person("A", telegram_user_id=444)
        await MembershipService(factory).add_membership(organization.id, person.id, ADMIN)
    finally:
        await engine.dispose()
    engine = create_engine(migrated_settings)
    try:
        factory = create_session_factory(engine)
        found = await IdentityService(factory).find_by_telegram_user_id(444)
        assert found is not None
        membership = await AuthorizationService(factory).require_role(
            organization.id, found.id, ADMIN
        )
        assert membership.person_id == person.id
    finally:
        await engine.dispose()
