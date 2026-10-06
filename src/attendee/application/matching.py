"""Match a Telegram account to a person in one group. Never guess an identity."""

import logging
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.dto import PersonDTO, UnresolvedMatchDTO
from attendee.application.errors import NotFound
from attendee.domain.identity import normalize_handle
from attendee.domain.matching import MatchOutcome, UnresolvedReason
from attendee.persistence.database import write_session
from attendee.persistence.models import UnresolvedMatch
from attendee.persistence.types import utc_now
from attendee.repositories.groups import GroupRepository
from attendee.repositories.identity import PersonRepository
from attendee.repositories.matching import UnresolvedMatchRepository

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchResult:
    outcome: MatchOutcome
    person: PersonDTO | None = None
    reason: UnresolvedReason | None = None


def _checked_input(telegram_user_id: int, telegram_handle: str | None) -> str | None:
    if telegram_user_id <= 0:
        raise ValueError("A Telegram user ID must be positive")
    return _canonical_or_none(telegram_handle)


def _canonical_or_none(telegram_handle: str | None) -> str | None:
    if telegram_handle is None or not telegram_handle.strip():
        return None
    try:
        return normalize_handle(telegram_handle)
    except ValueError:
        return None


class AccountMatchingService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def match(
        self, group_id: int, telegram_user_id: int, telegram_handle: str | None
    ) -> MatchResult:
        """Match by Telegram user ID first, then by canonical handle, in this group only.

        A Telegram ID match returns BY_TELEGRAM_ID. A single handle candidate returns PROPOSED
        and binds nothing: the member must confirm the candidate name first (T31).
        Matching never uses a name and never creates a person. If no single member matches,
        the service binds nothing and records an unresolved match for admin resolution.
        A repeated call with the same input has no extra effect.
        """
        handle = _checked_input(telegram_user_id, telegram_handle)
        async with write_session(self.session_factory) as session:
            return await self._match(session, group_id, telegram_user_id, handle)

    async def confirm(
        self,
        group_id: int,
        telegram_user_id: int,
        telegram_handle: str | None,
        person_id: int,
    ) -> MatchResult:
        """Bind the Telegram ID to the confirmed candidate if the match still proposes it.

        One write transaction matches again and binds. A changed state binds nothing and returns
        the fresh result: BY_TELEGRAM_ID, UNRESOLVED, or PROPOSED for another candidate.
        A repeated confirmation returns BY_TELEGRAM_ID and has no extra effect.
        """
        handle = _checked_input(telegram_user_id, telegram_handle)
        async with write_session(self.session_factory) as session:
            result = await self._match(session, group_id, telegram_user_id, handle)
            if result.outcome is not MatchOutcome.PROPOSED or result.person is None:
                return result
            if result.person.id != person_id:
                return result
            person = await PersonRepository(session, group_id).get(person_id)
            assert person is not None
            unresolved = UnresolvedMatchRepository(session)
            try:
                async with session.begin_nested():
                    person.telegram_user_id = telegram_user_id
            except IntegrityError:
                # The write lock makes this unreachable in one database; keep the guarantee.
                return await self._unresolved(
                    unresolved,
                    group_id,
                    telegram_user_id,
                    handle,
                    UnresolvedReason.TELEGRAM_ID_TAKEN,
                )
            await self._resolve(unresolved, group_id, telegram_user_id)
            await session.flush()
            LOGGER.info(
                "Bound a Telegram account to person %d in group %d",
                person.id,
                group_id,
            )
            return MatchResult(MatchOutcome.BOUND_BY_HANDLE, PersonDTO.model_validate(person))

    async def reject(
        self, group_id: int, telegram_user_id: int, telegram_handle: str | None
    ) -> MatchResult:
        """Record that the member rejected the proposed candidate. Bind nothing.

        A Telegram ID that already matches a member returns BY_TELEGRAM_ID and changes nothing.
        A repeated rejection has no extra effect.
        """
        handle = _checked_input(telegram_user_id, telegram_handle)
        async with write_session(self.session_factory) as session:
            result = await self._match(session, group_id, telegram_user_id, handle)
            if result.outcome is not MatchOutcome.PROPOSED:
                return result
            return await self._unresolved(
                UnresolvedMatchRepository(session),
                group_id,
                telegram_user_id,
                handle,
                UnresolvedReason.CANDIDATE_REJECTED,
            )

    async def _match(
        self,
        session: AsyncSession,
        group_id: int,
        telegram_user_id: int,
        handle: str | None,
    ) -> MatchResult:
        if await GroupRepository(session).get(group_id) is None:
            raise NotFound(f"Group {group_id}")
        people = PersonRepository(session, group_id)
        unresolved = UnresolvedMatchRepository(session)

        person = await people.get_by_telegram_user_id(telegram_user_id)
        if person is not None:
            if person.telegram_handle != handle:
                person.telegram_handle = handle
            await self._resolve(unresolved, group_id, telegram_user_id)
            await session.flush()
            return MatchResult(MatchOutcome.BY_TELEGRAM_ID, PersonDTO.model_validate(person))

        if handle is None:
            return await self._unresolved(
                unresolved,
                group_id,
                telegram_user_id,
                None,
                UnresolvedReason.NO_MATCH,
            )
        candidates = await people.find_unbound_by_handle(handle)
        if len(candidates) != 1:
            reason = UnresolvedReason.AMBIGUOUS if candidates else UnresolvedReason.NO_MATCH
            return await self._unresolved(unresolved, group_id, telegram_user_id, handle, reason)
        return MatchResult(MatchOutcome.PROPOSED, PersonDTO.model_validate(candidates[0]))

    async def list_unresolved(self, group_id: int) -> list[UnresolvedMatchDTO]:
        async with self.session_factory() as session:
            matches = await UnresolvedMatchRepository(session).list_open(group_id)
            return [UnresolvedMatchDTO.model_validate(match) for match in matches]

    @staticmethod
    async def _unresolved(
        repository: UnresolvedMatchRepository,
        group_id: int,
        telegram_user_id: int,
        handle: str | None,
        reason: UnresolvedReason,
    ) -> MatchResult:
        record = await repository.get(group_id, telegram_user_id)
        if record is None:
            await repository.add(
                UnresolvedMatch(
                    group_id=group_id,
                    telegram_user_id=telegram_user_id,
                    telegram_handle=handle,
                    reason=reason,
                )
            )
        elif (record.reason, record.telegram_handle, record.resolved_at) != (reason, handle, None):
            record.reason = reason
            record.telegram_handle = handle
            record.resolved_at = None
        LOGGER.info("Unresolved Telegram match in group %d: %s", group_id, reason)
        return MatchResult(MatchOutcome.UNRESOLVED, reason=reason)

    @staticmethod
    async def _resolve(
        repository: UnresolvedMatchRepository, group_id: int, telegram_user_id: int
    ) -> None:
        record = await repository.get(group_id, telegram_user_id)
        if record is not None and record.resolved_at is None:
            record.resolved_at = utc_now()
