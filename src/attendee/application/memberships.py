"""Organization-scoped memberships."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.dto import MembershipDTO
from attendee.application.errors import DuplicateMembership, NotFound
from attendee.domain.identity import MembershipRole
from attendee.persistence.models import Membership
from attendee.repositories.identity import (
    MembershipRepository,
    OrganizationRepository,
    PersonRepository,
)


class MembershipService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def add_membership(
        self, organization_id: int, person_id: int, role: MembershipRole
    ) -> MembershipDTO:
        try:
            async with self.session_factory.begin() as session:
                if await OrganizationRepository(session).get(organization_id) is None:
                    raise NotFound(f"Organization {organization_id}")
                if await PersonRepository(session).get(person_id) is None:
                    raise NotFound(f"Person {person_id}")
                memberships = MembershipRepository(session)
                if await memberships.get(organization_id, person_id) is not None:
                    raise DuplicateMembership(organization_id, person_id)
                membership = await memberships.add(
                    Membership(organization_id=organization_id, person_id=person_id, role=role)
                )
                return MembershipDTO.model_validate(membership)
        except IntegrityError as exc:
            raise DuplicateMembership(organization_id, person_id) from exc

    async def get_membership(self, organization_id: int, person_id: int) -> MembershipDTO | None:
        async with self.session_factory() as session:
            membership = await MembershipRepository(session).get(organization_id, person_id)
            return None if membership is None else MembershipDTO.model_validate(membership)
