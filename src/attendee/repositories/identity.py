"""Database access for identity records. Repositories never commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.persistence.models import Membership, Organization, Person


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, organization_id: int) -> Organization | None:
        return await self.session.get(Organization, organization_id)

    async def get_by_slug(self, slug: str) -> Organization | None:
        return await self.session.scalar(select(Organization).where(Organization.slug == slug))

    async def add(self, organization: Organization) -> Organization:
        self.session.add(organization)
        await self.session.flush()
        return organization


class PersonRepository:
    """Global identity. It has no organization scope and grants no access."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, person_id: int) -> Person | None:
        return await self.session.get(Person, person_id)

    async def get_by_telegram_user_id(self, telegram_user_id: int) -> Person | None:
        return await self.session.scalar(
            select(Person).where(Person.telegram_user_id == telegram_user_id)
        )

    async def add(self, person: Person) -> Person:
        self.session.add(person)
        await self.session.flush()
        return person


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, organization_id: int, person_id: int) -> Membership | None:
        return await self.session.scalar(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.person_id == person_id,
            )
        )

    async def add(self, membership: Membership) -> Membership:
        self.session.add(membership)
        await self.session.flush()
        return membership
