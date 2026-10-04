"""Repeatable initial admin setup for one explicitly named organization."""

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.dto import OrganizationDTO
from attendee.domain.identity import MembershipRole, validate_slug
from attendee.persistence.models import Membership, Organization, Person
from attendee.repositories.identity import (
    MembershipRepository,
    OrganizationRepository,
    PersonRepository,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BootstrapResult:
    organization: OrganizationDTO
    organization_created: bool
    people_created: int
    memberships_created: int
    members_promoted: int
    admins_unchanged: int


async def bootstrap_organization(
    session_factory: async_sessionmaker[AsyncSession],
    slug: str,
    name: str,
    telegram_user_ids: tuple[int, ...],
) -> BootstrapResult:
    """Create the organization and admin memberships. Never demote or remove anyone.

    One transaction covers the whole setup, so a failure leaves no partial records.
    """
    validate_slug(slug)
    name = name.strip()
    if not name:
        raise ValueError("The organization name must not be empty")
    if not telegram_user_ids:
        raise ValueError("BOOTSTRAP_ADMIN_IDS is empty")
    people_created = memberships_created = promoted = unchanged = 0
    async with session_factory.begin() as session:
        organizations = OrganizationRepository(session)
        people = PersonRepository(session)
        memberships = MembershipRepository(session)
        organization = await organizations.get_by_slug(slug)
        organization_created = organization is None
        if organization is None:
            organization = await organizations.add(Organization(slug=slug, name=name))
        elif organization.name != name:
            LOGGER.warning("Organization %s keeps its stored name", slug)
        for telegram_user_id in telegram_user_ids:
            person = await people.get_by_telegram_user_id(telegram_user_id)
            if person is None:
                person = await people.add(Person(telegram_user_id=telegram_user_id))
                people_created += 1
            membership = await memberships.get(organization.id, person.id)
            if membership is None:
                await memberships.add(
                    Membership(
                        organization_id=organization.id,
                        person_id=person.id,
                        role=MembershipRole.ADMIN,
                    )
                )
                memberships_created += 1
            elif membership.role != MembershipRole.ADMIN:
                membership.role = MembershipRole.ADMIN
                promoted += 1
            else:
                unchanged += 1
        await session.flush()
        return BootstrapResult(
            organization=OrganizationDTO.model_validate(organization),
            organization_created=organization_created,
            people_created=people_created,
            memberships_created=memberships_created,
            members_promoted=promoted,
            admins_unchanged=unchanged,
        )
