"""Safe poll publication (decisions T55–T61).

Transaction 1 claims the session with a publishing attempt. The send runs outside any transaction.
Transaction 2 records the result. Only the request whose insert wins sends.
"""

import logging
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.authorization import AuthorizationService
from attendee.application.chats import ChatDTO
from attendee.application.errors import ApplicationError, NotFound
from attendee.domain.attendance import SessionStatus
from attendee.domain.identity import MembershipRole
from attendee.domain.publication import (
    PUBLISH_LEASE,
    PublicationStatus,
    lease_expired,
    poll_text,
)
from attendee.persistence.database import write_session
from attendee.persistence.models import AttendanceSession, SessionPublication
from attendee.repositories.attendance import AttendanceRepository
from attendee.repositories.chats import ChatRepository
from attendee.repositories.publication import PublicationRepository


class PublishRejected(Exception):
    """Telegram refused the send. No poll appeared, so a retry is safe."""

    def __init__(self, failure: str) -> None:
        super().__init__(failure)
        self.failure = failure


class PublishUnknown(Exception):
    """The send result is unknown. The poll may or may not be in the group."""


class Publisher(Protocol):
    async def send_poll(self, telegram_chat_id: int, text: str, session_id: int) -> int:
        """Post the poll and return its Telegram message ID."""
        ...


class NotDraft(ApplicationError):
    """Only a Draft session can be published."""


class PublishOutcome(StrEnum):
    PUBLISHED = "published"
    FAILED = "failed"
    UNKNOWN = "publish_unknown"
    IN_PROGRESS = "in_progress"


class PublishResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: PublishOutcome
    session_id: int
    failure: str | None = None


class DraftDTO(BaseModel):
    """A Draft session and the state of its active attempt, if one exists."""

    model_config = ConfigDict(frozen=True)
    id: int
    series_name: str
    session_date: date
    label: str | None
    deadline: datetime
    publication: PublicationStatus | None


class PublicationReview(BaseModel):
    model_config = ConfigDict(frozen=True)
    draft: DraftDTO
    chat: ChatDTO
    text: str


class PublicationService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], timezone: str = "Asia/Singapore"
    ) -> None:
        self.session_factory = session_factory
        self.timezone = timezone
        self.authorization = AuthorizationService(session_factory)

    async def _authorize(self, organization_id: int, actor_id: int, session: AsyncSession) -> None:
        await self.authorization.require_role(
            organization_id, actor_id, MembershipRole.ADMIN, session
        )

    async def _draft(
        self, session: AsyncSession, organization_id: int, row: AttendanceSession
    ) -> DraftDTO:
        series = await AttendanceRepository(session, organization_id).series(row.series_id)
        assert series is not None
        active = await PublicationRepository(session, organization_id).active(row.id)
        return DraftDTO(
            id=row.id,
            series_name=series.name,
            session_date=row.session_date,
            label=row.label,
            deadline=row.deadline,
            publication=None if active is None else PublicationStatus(active.status),
        )

    async def _expire(
        self, repository: PublicationRepository, session_id: int, now: datetime
    ) -> None:
        """Move this session's publishing attempt to publish_unknown when its lease expired."""
        active = await repository.active(session_id)
        if (
            active is not None
            and active.status == PublicationStatus.PUBLISHING
            and lease_expired(active.lease_expires_at, now)
        ):
            active.status = PublicationStatus.PUBLISH_UNKNOWN.value
            await repository.session.flush()

    async def _require_draft(
        self, session: AsyncSession, organization_id: int, session_id: int
    ) -> AttendanceSession:
        row = await AttendanceRepository(session, organization_id).get_session(session_id)
        if row is None:
            raise NotFound("Session not found.")
        if row.status != SessionStatus.DRAFT:
            raise NotDraft("This session is no longer a Draft.")
        return row

    async def list_drafts(
        self, organization_id: int, actor_id: int, offset: int = 0, limit: int = 11
    ) -> list[DraftDTO]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("Invalid session page.")
        async with self.session_factory() as session:
            await self._authorize(organization_id, actor_id, session)
            rows = await PublicationRepository(session, organization_id).drafts(offset, limit)
            attendance = AttendanceRepository(session, organization_id)
            result: list[DraftDTO] = []
            for row, attempt in rows:
                series = await attendance.series(row.series_id)
                assert series is not None
                result.append(
                    DraftDTO(
                        id=row.id,
                        series_name=series.name,
                        session_date=row.session_date,
                        label=row.label,
                        deadline=row.deadline,
                        publication=None if attempt is None else PublicationStatus(attempt.status),
                    )
                )
            return result

    async def list_chats(self, organization_id: int, actor_id: int) -> list[ChatDTO]:
        async with self.session_factory() as session:
            await self._authorize(organization_id, actor_id, session)
            rows = await ChatRepository(session, organization_id).all()
            return [ChatDTO.model_validate(row) for row in rows]

    async def draft_state(
        self, organization_id: int, actor_id: int, session_id: int, now: datetime | None = None
    ) -> DraftDTO:
        """Return a Draft session. An expired lease becomes publish_unknown first."""
        now = now or datetime.now(UTC)
        async with write_session(self.session_factory) as session:
            await self._authorize(organization_id, actor_id, session)
            row = await self._require_draft(session, organization_id, session_id)
            await self._expire(PublicationRepository(session, organization_id), row.id, now)
            result = await self._draft(session, organization_id, row)
        return result

    async def review(
        self, organization_id: int, actor_id: int, session_id: int, chat_id: int
    ) -> PublicationReview:
        async with self.session_factory() as session:
            await self._authorize(organization_id, actor_id, session)
            row = await self._require_draft(session, organization_id, session_id)
            chat = await ChatRepository(session, organization_id).get(chat_id)
            if chat is None:
                raise NotFound("Group not found.")
            draft = await self._draft(session, organization_id, row)
            return PublicationReview(
                draft=draft, chat=ChatDTO.model_validate(chat), text=self._text(draft)
            )

    def _text(self, draft: DraftDTO) -> str:
        return poll_text(
            draft.series_name, draft.session_date, draft.label, draft.deadline, self.timezone
        )

    async def publish(
        self,
        organization_id: int,
        actor_id: int,
        session_id: int,
        chat_id: int,
        publisher: Publisher,
        now: datetime | None = None,
    ) -> PublishResult:
        now = now or datetime.now(UTC)
        claimed = await self._claim(organization_id, actor_id, session_id, chat_id, now)
        if isinstance(claimed, PublishResult):
            return claimed
        attempt_id, telegram_chat_id, text = claimed
        log = logging.getLogger(__name__)
        try:
            message_id = await publisher.send_poll(telegram_chat_id, text, session_id)
        except PublishRejected as exc:
            log.warning("Poll publication rejected: %s", exc.failure)
            return await self._record(organization_id, attempt_id, None, exc.failure)
        except PublishUnknown:
            log.warning("Poll publication result unknown for session %s", session_id)
            return await self._record(organization_id, attempt_id, None, None)
        # Any other exception leaves the attempt publishing. Its lease expiry gives publish_unknown.
        return await self._record(organization_id, attempt_id, message_id, None)

    async def _claim(
        self, organization_id: int, actor_id: int, session_id: int, chat_id: int, now: datetime
    ) -> tuple[int, int, str] | PublishResult:
        """Transaction 1. Insert a publishing attempt, or report the active one."""
        try:
            async with write_session(self.session_factory) as session:
                await self._authorize(organization_id, actor_id, session)
                row = await self._require_draft(session, organization_id, session_id)
                chat = await ChatRepository(session, organization_id).get(chat_id)
                if chat is None:
                    raise NotFound("Group not found.")
                repository = PublicationRepository(session, organization_id)
                await self._expire(repository, row.id, now)
                active = await repository.active(row.id)
                if active is not None:
                    outcome = _OUTCOMES[PublicationStatus(active.status)]
                    return PublishResult(outcome=outcome, session_id=row.id)
                attempt = await repository.add(
                    SessionPublication(
                        organization_id=organization_id,
                        session_id=row.id,
                        organization_chat_id=chat.id,
                        status=PublicationStatus.PUBLISHING.value,
                        requested_by=actor_id,
                        lease_expires_at=now + PUBLISH_LEASE,
                    )
                )
                text = self._text(await self._draft(session, organization_id, row))
                claimed = (attempt.id, chat.telegram_chat_id, text)
        except IntegrityError:
            # Another request inserted the active attempt first. That request sends.
            return PublishResult(outcome=PublishOutcome.IN_PROGRESS, session_id=session_id)
        return claimed

    async def _record(
        self, organization_id: int, attempt_id: int, message_id: int | None, failure: str | None
    ) -> PublishResult:
        """Transaction 2. A message ID means success, a failure name means rejection."""
        async with write_session(self.session_factory) as session:
            repository = PublicationRepository(session, organization_id)
            attempt = await repository.get(attempt_id)
            assert attempt is not None
            pending = attempt.status in (
                PublicationStatus.PUBLISHING,
                PublicationStatus.PUBLISH_UNKNOWN,
            )
            if pending and message_id is not None:
                # A late success after lease expiry still sets published.
                await self._mark_published(session, organization_id, attempt, message_id)
            elif pending and failure is not None:
                attempt.status = PublicationStatus.FAILED.value
                attempt.failure = failure
            elif attempt.status == PublicationStatus.PUBLISHING:
                attempt.status = PublicationStatus.PUBLISH_UNKNOWN.value
            await session.flush()
            result = PublishResult(
                outcome=_OUTCOMES[PublicationStatus(attempt.status)],
                session_id=attempt.session_id,
                failure=attempt.failure,
            )
        return result

    async def _mark_published(
        self,
        session: AsyncSession,
        organization_id: int,
        attempt: SessionPublication,
        message_id: int | None,
    ) -> None:
        """Set published and open the session in the caller's transaction."""
        attempt.status = PublicationStatus.PUBLISHED.value
        attempt.telegram_message_id = message_id
        row = await AttendanceRepository(session, organization_id).get_session(attempt.session_id)
        assert row is not None
        if row.status == SessionStatus.DRAFT:
            row.status = SessionStatus.OPEN.value

    async def resolve(
        self,
        organization_id: int,
        actor_id: int,
        session_id: int,
        seen: bool,
        now: datetime | None = None,
    ) -> PublishResult:
        """An admin resolves publish_unknown. A repeat or a stale button changes nothing."""
        now = now or datetime.now(UTC)
        async with write_session(self.session_factory) as session:
            await self._authorize(organization_id, actor_id, session)
            repository = PublicationRepository(session, organization_id)
            await self._expire(repository, session_id, now)
            attempt = await repository.active(session_id)
            if attempt is None:
                raise NotFound("No publication waits for a decision.")
            if attempt.status == PublicationStatus.PUBLISH_UNKNOWN:
                attempt.resolved_by = actor_id
                if seen:
                    # No message ID: the bot cannot edit this poll later.
                    await self._mark_published(session, organization_id, attempt, None)
                else:
                    attempt.status = PublicationStatus.FAILED.value
                    attempt.failure = "not_seen"
                await session.flush()
            result = PublishResult(
                outcome=_OUTCOMES[PublicationStatus(attempt.status)],
                session_id=session_id,
                failure=attempt.failure,
            )
        return result

    async def recover_expired(self, organization_id: int, now: datetime | None = None) -> int:
        """Startup hook. A publishing attempt with an expired lease becomes publish_unknown."""
        now = now or datetime.now(UTC)
        async with write_session(self.session_factory) as session:
            rows = await PublicationRepository(session, organization_id).expired(now)
            for row in rows:
                row.status = PublicationStatus.PUBLISH_UNKNOWN.value
            await session.flush()
        return len(rows)


_OUTCOMES = {
    PublicationStatus.PUBLISHING: PublishOutcome.IN_PROGRESS,
    PublicationStatus.PUBLISHED: PublishOutcome.PUBLISHED,
    PublicationStatus.PUBLISH_UNKNOWN: PublishOutcome.UNKNOWN,
    PublicationStatus.FAILED: PublishOutcome.FAILED,
}
