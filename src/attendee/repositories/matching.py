"""Database access for unresolved Telegram matches. Repositories never commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.persistence.models import UnresolvedMatch


class UnresolvedMatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, organization_id: int, telegram_user_id: int) -> UnresolvedMatch | None:
        return await self.session.scalar(
            select(UnresolvedMatch).where(
                UnresolvedMatch.organization_id == organization_id,
                UnresolvedMatch.telegram_user_id == telegram_user_id,
            )
        )

    async def list_open(self, organization_id: int) -> list[UnresolvedMatch]:
        result = await self.session.scalars(
            select(UnresolvedMatch)
            .where(
                UnresolvedMatch.organization_id == organization_id,
                UnresolvedMatch.resolved_at.is_(None),
            )
            .order_by(UnresolvedMatch.id)
        )
        return list(result)

    async def add(self, match: UnresolvedMatch) -> UnresolvedMatch:
        self.session.add(match)
        await self.session.flush()
        return match
