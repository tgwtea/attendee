"""Group-scoped publication attempt queries. Repositories never commit."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.domain.attendance import SessionStatus
from attendee.domain.publication import ACTIVE_STATUSES, PublicationStatus
from attendee.persistence.models import AttendanceSession, SessionPublication


class PublicationRepository:
    def __init__(self, session: AsyncSession, group_id: int) -> None:
        self.session = session
        self.group_id = group_id

    async def add(self, attempt: SessionPublication) -> SessionPublication:
        if attempt.group_id != self.group_id:
            raise ValueError("Publication group differs from repository scope.")
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def get(self, attempt_id: int) -> SessionPublication | None:
        return await self.session.scalar(
            select(SessionPublication).where(
                SessionPublication.group_id == self.group_id,
                SessionPublication.id == attempt_id,
            )
        )

    async def active(self, session_id: int) -> SessionPublication | None:
        """Return the one publishing, publish_unknown, or published attempt of a session."""
        return await self.session.scalar(
            select(SessionPublication).where(
                SessionPublication.group_id == self.group_id,
                SessionPublication.session_id == session_id,
                SessionPublication.status.in_([status.value for status in ACTIVE_STATUSES]),
            )
        )

    async def drafts(
        self, offset: int, limit: int, archive_cutoff: datetime
    ) -> list[tuple[AttendanceSession, SessionPublication | None]]:
        """Draft sessions that are not archived, newest date first, with any active attempt."""
        rows = await self.session.execute(
            select(AttendanceSession, SessionPublication)
            .outerjoin(
                SessionPublication,
                (SessionPublication.group_id == AttendanceSession.group_id)
                & (SessionPublication.session_id == AttendanceSession.id)
                & SessionPublication.status.in_([status.value for status in ACTIVE_STATUSES]),
            )
            .where(
                AttendanceSession.group_id == self.group_id,
                AttendanceSession.status == SessionStatus.DRAFT.value,
                AttendanceSession.deadline >= archive_cutoff,
            )
            .order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in rows]


async def expired_attempts(session: AsyncSession, now: datetime) -> list[SessionPublication]:
    """Publishing attempts with an expired lease, in every group. Only startup reads this."""
    rows = await session.scalars(
        select(SessionPublication).where(
            SessionPublication.status == PublicationStatus.PUBLISHING.value,
            SessionPublication.lease_expires_at <= now,
        )
    )
    return list(rows)
