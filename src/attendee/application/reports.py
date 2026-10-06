"""Admin attendance reports (decisions T72–T76). One read-only transaction per request.

The admin view and the XLSX export both read these DTOs. Neither calculates on its own.
"""

from collections import defaultdict
from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee import copy
from attendee.application.authorization import AuthorizationService
from attendee.application.errors import NotFound
from attendee.domain.attendance import SessionStatus, display_status, is_archived
from attendee.domain.identity import MembershipRole
from attendee.domain.reports import Cell, cell, is_complete, member_name
from attendee.domain.responses import ResponseStatus
from attendee.persistence.models import AttendanceSession, Person
from attendee.repositories.attendance import AttendanceRepository
from attendee.repositories.reports import ReportRepository


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class SeriesChoice(_Frozen):
    id: int
    name: str


class SessionChoice(_Frozen):
    id: int
    session_date: date
    label: str | None
    status: str


class MemberResponse(_Frozen):
    name: str
    status: ResponseStatus | None
    reason: str | None


class SessionReport(_Frozen):
    """PRD §19: one session and every roster member, by name. Only admins get this."""

    series_name: str
    session_date: date
    label: str | None
    status: str
    members: tuple[MemberResponse, ...]

    @property
    def responded(self) -> int:
        return sum(member.status is not None for member in self.members)

    def count(self, status: ResponseStatus) -> int:
        return sum(member.status is status for member in self.members)


class ReportColumn(_Frozen):
    session_date: date
    label: str | None
    complete: bool


class ReportRow(_Frozen):
    name: str
    cells: tuple[Cell, ...]


class SeriesReport(_Frozen):
    """PRD §9 and §28: complete sessions first, then open sessions (decision T73)."""

    series_name: str
    columns: tuple[ReportColumn, ...]
    rows: tuple[ReportRow, ...]


def _sort_key(person: Person) -> tuple[str, int]:
    name = member_name(person.id, person.display_name, person.telegram_handle)
    return name.casefold(), person.id


class ReportService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.authorization = AuthorizationService(session_factory)

    async def _authorize(self, organization_id: int, actor_id: int, session: AsyncSession) -> None:
        await self.authorization.require_role(
            organization_id, actor_id, MembershipRole.ADMIN, session
        )

    async def list_series(
        self, organization_id: int, actor_id: int, offset: int = 0, limit: int = 11
    ) -> list[SeriesChoice]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("Invalid series page.")
        async with self.session_factory() as session:
            await self._authorize(organization_id, actor_id, session)
            rows = await ReportRepository(session, organization_id).series_with_polls(offset, limit)
            return [SeriesChoice(id=row.id, name=row.name) for row in rows]

    async def list_sessions(
        self, organization_id: int, actor_id: int, series_id: int, now: datetime | None = None
    ) -> tuple[str, list[SessionChoice]]:
        """The series name, and its sessions that are not Drafts or archived, newest first (T69)."""
        now = now or datetime.now(UTC)
        async with self.session_factory() as session:
            await self._authorize(organization_id, actor_id, session)
            series = await AttendanceRepository(session, organization_id).series(series_id)
            if series is None:
                raise NotFound(copy.STATS_SERIES_NOT_FOUND)
            rows = await ReportRepository(session, organization_id).sessions(series_id)
            return series.name, [
                SessionChoice(
                    id=row.id,
                    session_date=row.session_date,
                    label=row.label,
                    status=display_status(SessionStatus(row.status), row.deadline, now),
                )
                for row in reversed(rows)
                if not is_archived(row.deadline, now)
            ]

    async def session_report(
        self, organization_id: int, actor_id: int, session_id: int, now: datetime | None = None
    ) -> SessionReport:
        now = now or datetime.now(UTC)
        async with self.session_factory() as session:
            await self._authorize(organization_id, actor_id, session)
            attendance = AttendanceRepository(session, organization_id)
            row = await attendance.get_session(session_id)
            if row is None or row.status == SessionStatus.DRAFT:
                raise NotFound(copy.SESSION_NOT_FOUND)
            series = await attendance.series(row.series_id)
            assert series is not None
            reports = ReportRepository(session, organization_id)
            people = [person for _, person in await reports.roster_people([row.id])]
            answers = {
                response.person_id: response for response in await reports.responses([row.id])
            }
            members: list[MemberResponse] = []
            for person in sorted(people, key=_sort_key):
                answer = answers.get(person.id)
                members.append(
                    MemberResponse(
                        name=member_name(person.id, person.display_name, person.telegram_handle),
                        status=None if answer is None else ResponseStatus(answer.status),
                        reason=None if answer is None else answer.reason,
                    )
                )
            return SessionReport(
                series_name=series.name,
                session_date=row.session_date,
                label=row.label,
                status=display_status(SessionStatus(row.status), row.deadline, now),
                members=tuple(members),
            )

    async def series_report(
        self, organization_id: int, actor_id: int, series_id: int, now: datetime | None = None
    ) -> SeriesReport:
        """Every session that is not a Draft, archived ones included (decision T69)."""
        now = now or datetime.now(UTC)
        async with self.session_factory() as session:
            await self._authorize(organization_id, actor_id, session)
            series = await AttendanceRepository(session, organization_id).series(series_id)
            if series is None:
                raise NotFound(copy.STATS_SERIES_NOT_FOUND)
            reports = ReportRepository(session, organization_id)
            rows = await reports.sessions(series_id)
            complete = {
                row.id: is_complete(SessionStatus(row.status), row.deadline, now) for row in rows
            }
            ordered: list[AttendanceSession] = [row for row in rows if complete[row.id]] + [
                row for row in rows if not complete[row.id]
            ]
            ids = [row.id for row in ordered]
            rosters: dict[int, set[int]] = defaultdict(set)
            people: dict[int, Person] = {}
            for session_id, person in await reports.roster_people(ids):
                rosters[session_id].add(person.id)
                people[person.id] = person
            answers = {
                (response.session_id, response.person_id): ResponseStatus(response.status)
                for response in await reports.responses(ids)
            }
            return SeriesReport(
                series_name=series.name,
                columns=tuple(
                    ReportColumn(
                        session_date=row.session_date, label=row.label, complete=complete[row.id]
                    )
                    for row in ordered
                ),
                rows=tuple(
                    ReportRow(
                        name=member_name(person.id, person.display_name, person.telegram_handle),
                        cells=tuple(
                            cell(person.id in rosters[row.id], answers.get((row.id, person.id)))
                            for row in ordered
                        ),
                    )
                    for person in sorted(people.values(), key=_sort_key)
                ),
            )
