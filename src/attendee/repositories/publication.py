"""Organization-scoped publication attempt queries. Repositories never commit."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.domain.attendance import SessionStatus
from attendee.domain.publication import ACTIVE_STATUSES, PublicationStatus
from attendee.persistence.models import AttendanceSession, SessionPublication


class PublicationRepository:
    def __init__(self, session: AsyncSession, organization_id: int) -> None:
        self.session = session
        self.organization_id = organization_id

    async def add(self, attempt: SessionPublication) -> SessionPublication:
        if attempt.organization_id != self.organization_id:
            raise ValueError("Publication organization differs from repository scope.")
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def get(self, attempt_id: int) -> SessionPublication | None:
        return await self.session.scalar(
            select(SessionPublication).where(
                SessionPublication.organization_id == self.organization_id,
                SessionPublication.id == attempt_id,
            )
        )

    async def active(self, session_id: int) -> SessionPublication | None:
        """Return the one publishing, publish_unknown, or published attempt of a session."""
        return await self.session.scalar(
            select(SessionPublication).where(
                SessionPublication.organization_id == self.organization_id,
                SessionPublication.session_id == session_id,
                SessionPublication.status.in_([status.value for status in ACTIVE_STATUSES]),
            )
        )

    async def expired(self, now: datetime) -> list[SessionPublication]:
        rows = await self.session.scalars(
            select(SessionPublication).where(
                SessionPublication.organization_id == self.organization_id,
                SessionPublication.status == PublicationStatus.PUBLISHING.value,
                SessionPublication.lease_expires_at <= now,
            )
        )
        return list(rows)

    async def drafts(
        self, offset: int, limit: int
    ) -> list[tuple[AttendanceSession, SessionPublication | None]]:
        """Draft sessions, newest date first, each with its active attempt if one exists."""
        rows = await self.session.execute(
            select(AttendanceSession, SessionPublication)
            .outerjoin(
                SessionPublication,
                (SessionPublication.organization_id == AttendanceSession.organization_id)
                & (SessionPublication.session_id == AttendanceSession.id)
                & SessionPublication.status.in_([status.value for status in ACTIVE_STATUSES]),
            )
            .where(
                AttendanceSession.organization_id == self.organization_id,
                AttendanceSession.status == SessionStatus.DRAFT.value,
            )
            .order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in rows]
