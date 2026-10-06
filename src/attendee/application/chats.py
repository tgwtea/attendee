"""Group chat registration. One short write transaction owns each change.

The caller reads the sender's Telegram group role before the transaction starts.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.authorization import AuthorizationService
from attendee.application.errors import AccessDenied
from attendee.domain.attendance import clean_name
from attendee.domain.chats import ChatType, controls_group
from attendee.domain.identity import MembershipRole
from attendee.persistence.database import write_session
from attendee.persistence.models import OrganizationChat
from attendee.repositories.chats import ChatRepository


class RegistrationOutcome(StrEnum):
    REGISTERED = "registered"
    REFRESHED = "refreshed"
    TAKEN = "taken"


class ChatDTO(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: int
    organization_id: int
    telegram_chat_id: int
    chat_type: ChatType
    title: str
    registered_by: int
    registered_at: datetime
    updated_at: datetime


class ChatRegistration(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: RegistrationOutcome
    chat: ChatDTO | None


class ChatRegistrationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.authorization = AuthorizationService(session_factory)

    async def register(
        self,
        organization_id: int,
        actor_id: int,
        telegram_chat_id: int,
        chat_type: ChatType,
        title: str,
        group_role: str,
    ) -> ChatRegistration:
        """Register a group for an actor who is an organization admin and a group admin.

        A group that another organization holds stays unchanged. A repeat refreshes the title.
        """
        title = clean_name(title)
        if not controls_group(group_role):
            raise AccessDenied("Only a group creator or administrator can register a group.")
        async with write_session(self.session_factory) as session:
            await self.authorization.require_role(
                organization_id, actor_id, MembershipRole.ADMIN, session
            )
            repository = ChatRepository(session, organization_id)
            owner = await repository.owner(telegram_chat_id)
            if owner is not None and owner != organization_id:
                return ChatRegistration(outcome=RegistrationOutcome.TAKEN, chat=None)
            row = await repository.by_telegram_id(telegram_chat_id)
            if row is None:
                row = await repository.add(
                    OrganizationChat(
                        organization_id=organization_id,
                        telegram_chat_id=telegram_chat_id,
                        chat_type=chat_type.value,
                        title=title,
                        registered_by=actor_id,
                    )
                )
                outcome = RegistrationOutcome.REGISTERED
            else:
                row.chat_type = chat_type.value
                row.title = title
                await session.flush()
                outcome = RegistrationOutcome.REFRESHED
            result = ChatRegistration(outcome=outcome, chat=ChatDTO.model_validate(row))
        return result

    async def migrate(self, organization_id: int, old_chat_id: int, new_chat_id: int) -> bool:
        """Follow a group upgrade to a supergroup. Telegram gives the supergroup a new chat ID.

        Return True only when this call moved a registered chat. A repeat changes nothing.
        """
        async with write_session(self.session_factory) as session:
            repository = ChatRepository(session, organization_id)
            row = await repository.by_telegram_id(old_chat_id)
            if row is None or await repository.owner(new_chat_id) is not None:
                return False
            row.telegram_chat_id = new_chat_id
            row.chat_type = ChatType.SUPERGROUP.value
            await session.flush()
        return True
