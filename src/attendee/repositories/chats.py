"""Organization-scoped chat queries. Repositories never commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.persistence.models import OrganizationChat


class ChatRepository:
    def __init__(self, session: AsyncSession, organization_id: int) -> None:
        self.session = session
        self.organization_id = organization_id

    async def owner(self, telegram_chat_id: int) -> int | None:
        """Return the organization ID that holds this chat, in any organization.

        A Telegram chat is unique across organizations. This read returns no other chat data.
        """
        return await self.session.scalar(
            select(OrganizationChat.organization_id).where(
                OrganizationChat.telegram_chat_id == telegram_chat_id
            )
        )

    async def by_telegram_id(self, telegram_chat_id: int) -> OrganizationChat | None:
        return await self.session.scalar(
            select(OrganizationChat).where(
                OrganizationChat.organization_id == self.organization_id,
                OrganizationChat.telegram_chat_id == telegram_chat_id,
            )
        )

    async def add(self, chat: OrganizationChat) -> OrganizationChat:
        if chat.organization_id != self.organization_id:
            raise ValueError("Chat organization differs from repository scope.")
        self.session.add(chat)
        await self.session.flush()
        return chat

    async def get(self, chat_id: int) -> OrganizationChat | None:
        return await self.session.scalar(
            select(OrganizationChat).where(
                OrganizationChat.organization_id == self.organization_id,
                OrganizationChat.id == chat_id,
            )
        )

    async def all(self) -> list[OrganizationChat]:
        rows = await self.session.scalars(
            select(OrganizationChat)
            .where(OrganizationChat.organization_id == self.organization_id)
            .order_by(OrganizationChat.title, OrganizationChat.id)
        )
        return list(rows)
