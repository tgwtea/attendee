"""Organization creation and lookup."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.dto import OrganizationDTO
from attendee.application.errors import ApplicationError
from attendee.domain.identity import validate_slug
from attendee.persistence.models import Organization
from attendee.repositories.identity import OrganizationRepository


class DuplicateOrganization(ApplicationError):
    pass


class OrganizationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def create_organization(self, slug: str, name: str) -> OrganizationDTO:
        validate_slug(slug)
        name = name.strip()
        if not name:
            raise ValueError("The organization name must not be empty")
        try:
            async with self.session_factory.begin() as session:
                organizations = OrganizationRepository(session)
                if await organizations.get_by_slug(slug) is not None:
                    raise DuplicateOrganization(slug)
                organization = await organizations.add(Organization(slug=slug, name=name))
                return OrganizationDTO.model_validate(organization)
        except IntegrityError as exc:
            raise DuplicateOrganization(slug) from exc

    async def find_by_slug(self, slug: str) -> OrganizationDTO | None:
        async with self.session_factory() as session:
            organization = await OrganizationRepository(session).get_by_slug(slug)
            return None if organization is None else OrganizationDTO.model_validate(organization)
