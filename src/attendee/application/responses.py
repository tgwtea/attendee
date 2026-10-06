"""Member responses to an Open session (decisions T62–T67).

`check` reads only. `record` checks again and writes in one BEGIN IMMEDIATE transaction,
because an admin can close the session or change the roster between a tap and a reason.
"""

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.errors import ApplicationError
from attendee.domain.attendance import SessionStatus, is_archived
from attendee.domain.responses import ResponseStatus, clean_reason
from attendee.persistence.database import write_session
from attendee.persistence.models import AttendanceSession, SessionResponse, SessionResponseEvent
from attendee.repositories.attendance import AttendanceRepository
from attendee.repositories.identity import PersonRepository
from attendee.repositories.responses import ResponseRepository


class NotLinked(ApplicationError):
    """No person has this Telegram user ID."""


class NotOnRoster(ApplicationError):
    """The person is not in the roster snapshot of this session."""


class SessionNotOpen(ApplicationError):
    """The session is Draft, Closed, archived, or not in this organization."""


class ResponseTarget(BaseModel):
    """The session that a member responds to, for the private reason prompt."""

    model_config = ConfigDict(frozen=True)
    session_id: int
    series_name: str
    session_date: date
    label: str | None
    # The saved response before this tap, for the replace confirmation (decision T68).
    current_status: ResponseStatus | None = None


class ResponseResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: ResponseStatus
    reason: str | None
    changed: bool


class ResponseService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def _target(
        self,
        session: AsyncSession,
        organization_id: int,
        telegram_user_id: int,
        session_id: int,
        now: datetime,
    ) -> tuple[int, AttendanceSession, ResponseTarget]:
        person = await PersonRepository(session).get_by_telegram_user_id(telegram_user_id)
        if person is None:
            raise NotLinked
        attendance = AttendanceRepository(session, organization_id)
        row = await attendance.get_session(session_id)
        # A missed deadline does not block an Open session (PRD §7, decision T49).
        # An archived session does (decision T69).
        if row is None or row.status != SessionStatus.OPEN or is_archived(row.deadline, now):
            raise SessionNotOpen
        responses = ResponseRepository(session, organization_id)
        if not await responses.on_roster(row.id, person.id):
            raise NotOnRoster
        series = await attendance.series(row.series_id)
        assert series is not None
        current = await responses.current(row.id, person.id)
        target = ResponseTarget(
            session_id=row.id,
            series_name=series.name,
            session_date=row.session_date,
            label=row.label,
            current_status=None if current is None else ResponseStatus(current.status),
        )
        return person.id, row, target

    async def check(
        self,
        organization_id: int,
        telegram_user_id: int,
        session_id: int,
        now: datetime | None = None,
    ) -> ResponseTarget:
        """Raise NotLinked, SessionNotOpen, or NotOnRoster. Write nothing."""
        async with self.session_factory() as session:
            _, _, target = await self._target(
                session, organization_id, telegram_user_id, session_id, now or datetime.now(UTC)
            )
            return target

    async def record(
        self,
        organization_id: int,
        telegram_user_id: int,
        session_id: int,
        status: ResponseStatus,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> ResponseResult:
        """Save the current response and one audit row. A repeat writes nothing.

        Raise ReasonMissing or ReasonTooLong before any database work.
        """
        reason = clean_reason(status, reason)
        now = now or datetime.now(UTC)
        async with write_session(self.session_factory) as session:
            person_id, row, _ = await self._target(
                session, organization_id, telegram_user_id, session_id, now
            )
            repository = ResponseRepository(session, organization_id)
            current = await repository.current(row.id, person_id)
            if current is not None and current.status == status and current.reason == reason:
                return ResponseResult(status=status, reason=reason, changed=False)
            if current is None:
                await repository.add(
                    SessionResponse(
                        organization_id=organization_id,
                        session_id=row.id,
                        person_id=person_id,
                        status=status.value,
                        reason=reason,
                        responded_at=now,
                        updated_at=now,
                    )
                )
            else:
                current.status = status.value
                current.reason = reason
                current.updated_at = now
            await repository.add_event(
                SessionResponseEvent(
                    organization_id=organization_id,
                    session_id=row.id,
                    person_id=person_id,
                    status=status.value,
                    reason=reason,
                    telegram_user_id=telegram_user_id,
                    created_at=now,
                )
            )
        return ResponseResult(status=status, reason=reason, changed=True)
