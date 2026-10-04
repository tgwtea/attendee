"""Authorization from membership in the requested organization only."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.dto import MembershipDTO
from attendee.application.errors import AccessDenied
from attendee.domain.identity import MembershipRole, role_satisfies
from attendee.repositories.identity import MembershipRepository


class AuthorizationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def require_role(
        self, organization_id: int, person_id: int, required: MembershipRole
    ) -> MembershipDTO:
        """Return the membership, or raise AccessDenied. No membership grants no access."""
        async with self.session_factory() as session:
            membership = await MembershipRepository(session).get(organization_id, person_id)
            if membership is None or not role_satisfies(membership.role, required):
                raise AccessDenied(f"Organization {organization_id} requires {required}")
            return MembershipDTO.model_validate(membership)
