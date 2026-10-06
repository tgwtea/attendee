"""Admin attendance creation. One write transaction owns each committed snapshot."""

import hashlib
from datetime import UTC, date, datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee import copy
from attendee.application.errors import ApplicationError, NotFound
from attendee.application.groups import GroupAccess
from attendee.domain.attendance import (
    SessionStatus,
    clean_name,
    display_status,
    normalize_series_name,
)
from attendee.persistence.database import write_session
from attendee.persistence.models import AttendanceSeries, AttendanceSession
from attendee.repositories.attendance import AttendanceRepository


class DuplicateSeries(ApplicationError):
    """A group already has this normalized series name."""


class RosterChanged(ApplicationError):
    """The current roster differs from the preview. Confirm a new preview."""


class CreationConflict(ApplicationError):
    """A creation key belongs to different input or another creator."""


class SeriesDTO(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: int
    group_id: int
    name: str
    created_by: int
    created_at: datetime


class SessionInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    series_id: int | None = Field(default=None, gt=0)
    new_series_name: str | None = None
    session_date: date
    label: str | None = None
    deadline: AwareDatetime
    creation_key: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("new_series_name", "label")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return None if value is None else clean_name(value)

    @field_validator("deadline")
    @classmethod
    def to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def one_series(self) -> Self:
        if (self.series_id is None) == (self.new_series_name is None):
            raise ValueError("Select an existing series or supply a new series name.")
        return self


class SessionPreview(BaseModel):
    model_config = ConfigDict(frozen=True)
    request: SessionInput
    series_name: str
    person_ids: tuple[int, ...]


class SessionDTO(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int
    group_id: int
    series_id: int
    series_name: str
    session_date: date
    label: str | None
    deadline: datetime
    status: SessionStatus
    display_status: str
    created_by: int
    created_at: datetime
    person_ids: tuple[int, ...]


class AttendanceService:
    """`actor_id` is the Telegram user ID of a group admin (decision T83).

    Each operation asks Telegram for the admin role before its transaction starts.
    """

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], access: GroupAccess
    ) -> None:
        self.session_factory = session_factory
        self.access = access

    async def list_series(
        self, group_id: int, actor_id: int, offset: int = 0, limit: int = 11
    ) -> list[SeriesDTO]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("Invalid series page.")
        await self.access.require_admin(group_id, actor_id)
        async with self.session_factory() as session:
            rows = await AttendanceRepository(session, group_id).list_series(offset, limit)
            return [SeriesDTO.model_validate(row) for row in rows]

    async def _add_series(
        self, repository: AttendanceRepository, actor_id: int, name: str
    ) -> AttendanceSeries:
        name = clean_name(name)
        normalized = normalize_series_name(name)
        if await repository.series_by_name(normalized) is not None:
            raise DuplicateSeries(copy.SERIES_EXISTS)
        row = AttendanceSeries(
            group_id=repository.group_id,
            name=name,
            normalized_name=normalized,
            created_by=actor_id,
        )
        return await repository.add_series(row)

    async def create_series(self, group_id: int, actor_id: int, name: str) -> SeriesDTO:
        await self.access.require_admin(group_id, actor_id)
        async with write_session(self.session_factory) as session:
            row = await self._add_series(AttendanceRepository(session, group_id), actor_id, name)
            result = SeriesDTO.model_validate(row)
        return result

    async def preview_session(
        self, group_id: int, actor_id: int, request: SessionInput
    ) -> SessionPreview:
        await self.access.require_admin(group_id, actor_id)
        async with self.session_factory() as session:
            repository = AttendanceRepository(session, group_id)
            if request.series_id is not None:
                series = await repository.series(request.series_id)
                if series is None:
                    raise NotFound(copy.SERIES_NOT_FOUND)
                name = series.name
            else:
                assert request.new_series_name is not None
                name = request.new_series_name
                if await repository.series_by_name(normalize_series_name(name)) is not None:
                    raise DuplicateSeries(copy.SERIES_EXISTS)
            return SessionPreview(
                request=request, series_name=name, person_ids=await repository.required_people()
            )

    async def create_session(
        self, group_id: int, actor_id: int, preview: SessionPreview
    ) -> SessionDTO:
        fingerprint = hashlib.sha256(preview.model_dump_json().encode()).hexdigest()
        request = preview.request
        await self.access.require_admin(group_id, actor_id)
        async with write_session(self.session_factory) as session:
            repository = AttendanceRepository(session, group_id)
            existing = await repository.session_by_key(request.creation_key)
            if existing is not None:
                if existing.created_by != actor_id or existing.request_fingerprint != fingerprint:
                    raise CreationConflict(copy.SESSION_KEY_CONFLICT)
                return await self._result(repository, existing)
            people = await repository.required_people()
            if people != preview.person_ids:
                raise RosterChanged(copy.SESSION_ROSTER_CHANGED)
            if request.series_id is not None:
                series = await repository.series(request.series_id)
                if series is None:
                    raise NotFound(copy.SERIES_NOT_FOUND)
            else:
                assert request.new_series_name is not None
                series = await self._add_series(repository, actor_id, request.new_series_name)
            row = AttendanceSession(
                group_id=group_id,
                series_id=series.id,
                session_date=request.session_date,
                label=request.label,
                deadline=request.deadline,
                created_by=actor_id,
                creation_key=request.creation_key,
                request_fingerprint=fingerprint,
            )
            await repository.add_session(row)
            await repository.add_roster(row.id, people)
            result = await self._result(repository, row)
        return result

    async def get_session(
        self, group_id: int, actor_id: int, session_id: int, now: datetime | None = None
    ) -> SessionDTO:
        await self.access.require_admin(group_id, actor_id)
        async with self.session_factory() as session:
            repository = AttendanceRepository(session, group_id)
            row = await repository.get_session(session_id)
            if row is None:
                raise NotFound(copy.SESSION_NOT_FOUND)
            return await self._result(repository, row, now)

    async def _result(
        self, repository: AttendanceRepository, row: AttendanceSession, now: datetime | None = None
    ) -> SessionDTO:
        series = await repository.series(row.series_id)
        assert series is not None
        status = SessionStatus(row.status)
        return SessionDTO(
            id=row.id,
            group_id=row.group_id,
            series_id=row.series_id,
            series_name=series.name,
            session_date=row.session_date,
            label=row.label,
            deadline=row.deadline,
            status=status,
            display_status=display_status(status, row.deadline, now or datetime.now(UTC)),
            created_by=row.created_by,
            created_at=row.created_at,
            person_ids=await repository.roster(row.id),
        )
