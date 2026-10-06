"""Organization-scoped report queries. Read only. Repositories never commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.domain.attendance import SessionStatus
from attendee.persistence.models import (
    AttendanceSeries,
    AttendanceSession,
    Person,
    SessionResponse,
    SessionRosterEntry,
)


class ReportRepository:
    def __init__(self, session: AsyncSession, organization_id: int) -> None:
        self.session = session
        self.organization_id = organization_id

    async def series_with_polls(self, offset: int, limit: int) -> list[AttendanceSeries]:
        """Series with at least one session that is not a Draft, by name."""
        published = select(AttendanceSession.id).where(
            AttendanceSession.organization_id == self.organization_id,
            AttendanceSession.series_id == AttendanceSeries.id,
            AttendanceSession.status != SessionStatus.DRAFT.value,
        )
        rows = await self.session.scalars(
            select(AttendanceSeries)
            .where(AttendanceSeries.organization_id == self.organization_id, published.exists())
            .order_by(AttendanceSeries.normalized_name, AttendanceSeries.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows)

    async def sessions(self, series_id: int) -> list[AttendanceSession]:
        """Sessions of the series that are not Drafts, oldest date first."""
        rows = await self.session.scalars(
            select(AttendanceSession)
            .where(
                AttendanceSession.organization_id == self.organization_id,
                AttendanceSession.series_id == series_id,
                AttendanceSession.status != SessionStatus.DRAFT.value,
            )
            .order_by(AttendanceSession.session_date, AttendanceSession.id)
        )
        return list(rows)

    async def roster_people(self, session_ids: list[int]) -> list[tuple[int, Person]]:
        """(session ID, person) for every roster entry of the sessions."""
        rows = await self.session.execute(
            select(SessionRosterEntry.session_id, Person)
            .join(Person, Person.id == SessionRosterEntry.person_id)
            .where(
                SessionRosterEntry.organization_id == self.organization_id,
                SessionRosterEntry.session_id.in_(session_ids),
            )
        )
        return [(row[0], row[1]) for row in rows]

    async def responses(self, session_ids: list[int]) -> list[SessionResponse]:
        rows = await self.session.scalars(
            select(SessionResponse).where(
                SessionResponse.organization_id == self.organization_id,
                SessionResponse.session_id.in_(session_ids),
            )
        )
        return list(rows)
