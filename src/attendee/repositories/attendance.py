"""Organization-scoped attendance queries. Repositories never commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.persistence.models import (
    AttendanceSeries,
    AttendanceSession,
    Membership,
    SessionRosterEntry,
)


class AttendanceRepository:
    def __init__(self, session: AsyncSession, organization_id: int) -> None:
        self.session = session
        self.organization_id = organization_id

    async def add_series(self, series: AttendanceSeries) -> AttendanceSeries:
        if series.organization_id != self.organization_id:
            raise ValueError("Series organization differs from repository scope.")
        self.session.add(series)
        await self.session.flush()
        return series

    async def add_session(self, attendance: AttendanceSession) -> AttendanceSession:
        if attendance.organization_id != self.organization_id:
            raise ValueError("Session organization differs from repository scope.")
        self.session.add(attendance)
        await self.session.flush()
        return attendance

    async def add_roster(self, session_id: int, person_ids: tuple[int, ...]) -> None:
        self.session.add_all(
            [
                SessionRosterEntry(
                    organization_id=self.organization_id, session_id=session_id, person_id=person_id
                )
                for person_id in person_ids
            ]
        )
        await self.session.flush()

    async def series(self, series_id: int) -> AttendanceSeries | None:
        return await self.session.scalar(
            select(AttendanceSeries).where(
                AttendanceSeries.organization_id == self.organization_id,
                AttendanceSeries.id == series_id,
            )
        )

    async def series_by_name(self, normalized_name: str) -> AttendanceSeries | None:
        return await self.session.scalar(
            select(AttendanceSeries).where(
                AttendanceSeries.organization_id == self.organization_id,
                AttendanceSeries.normalized_name == normalized_name,
            )
        )

    async def list_series(self, offset: int, limit: int) -> list[AttendanceSeries]:
        rows = await self.session.scalars(
            select(AttendanceSeries)
            .where(
                AttendanceSeries.organization_id == self.organization_id,
            )
            .order_by(AttendanceSeries.normalized_name, AttendanceSeries.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows)

    async def required_people(self) -> tuple[int, ...]:
        rows = await self.session.scalars(
            select(Membership.person_id)
            .where(
                Membership.organization_id == self.organization_id,
            )
            .order_by(Membership.person_id)
        )
        return tuple(rows)

    async def session_by_key(self, key: str) -> AttendanceSession | None:
        return await self.session.scalar(
            select(AttendanceSession).where(
                AttendanceSession.organization_id == self.organization_id,
                AttendanceSession.creation_key == key,
            )
        )

    async def get_session(self, session_id: int) -> AttendanceSession | None:
        return await self.session.scalar(
            select(AttendanceSession).where(
                AttendanceSession.organization_id == self.organization_id,
                AttendanceSession.id == session_id,
            )
        )

    async def roster(self, session_id: int) -> tuple[int, ...]:
        rows = await self.session.scalars(
            select(SessionRosterEntry.person_id)
            .where(
                SessionRosterEntry.organization_id == self.organization_id,
                SessionRosterEntry.session_id == session_id,
            )
            .order_by(SessionRosterEntry.person_id)
        )
        return tuple(rows)
