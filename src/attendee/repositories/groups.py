"""Group queries. Repositories never commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.persistence.models import Group


class GroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, group_id: int) -> Group | None:
        return await self.session.get(Group, group_id)

    async def by_telegram_id(self, telegram_chat_id: int) -> Group | None:
        return await self.session.scalar(
            select(Group).where(Group.telegram_chat_id == telegram_chat_id)
        )

    async def add(self, group: Group) -> Group:
        self.session.add(group)
        await self.session.flush()
        return group

    async def active(self) -> list[Group]:
        rows = await self.session.scalars(
            select(Group).where(Group.active.is_(True)).order_by(Group.title, Group.id)
        )
        return list(rows)
