"""People of one group. These operations grant no access."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.dto import PersonDTO
from attendee.application.errors import DuplicateTelegramUserId, NotFound
from attendee.domain.identity import normalize_handle
from attendee.persistence.models import Person
from attendee.repositories.groups import GroupRepository
from attendee.repositories.identity import PersonRepository


def _clean(value: str | None) -> str | None:
    value = None if value is None else value.strip()
    return value or None


def _handle(value: str | None) -> str | None:
    value = _clean(value)
    return None if value is None else normalize_handle(value)


class IdentityService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def create_person(
        self,
        group_id: int,
        display_name: str | None,
        telegram_user_id: int | None = None,
        telegram_handle: str | None = None,
    ) -> PersonDTO:
        """Always create a new person in the group. Equal names never merge two people."""
        display_name = _clean(display_name)
        if display_name is None and telegram_user_id is None:
            raise ValueError("A person needs a display name or a Telegram user ID")
        if telegram_user_id is not None and telegram_user_id <= 0:
            raise ValueError("A Telegram user ID must be positive")
        telegram_handle = _handle(telegram_handle)
        try:
            async with self.session_factory.begin() as session:
                if await GroupRepository(session).get(group_id) is None:
                    raise NotFound(f"Group {group_id}")
                people = PersonRepository(session, group_id)
                if (
                    telegram_user_id is not None
                    and await people.get_by_telegram_user_id(telegram_user_id) is not None
                ):
                    raise DuplicateTelegramUserId(telegram_user_id)
                person = await people.add(
                    Person(
                        group_id=group_id,
                        display_name=display_name,
                        telegram_user_id=telegram_user_id,
                        telegram_handle=telegram_handle,
                    )
                )
                return PersonDTO.model_validate(person)
        except IntegrityError as exc:
            raise DuplicateTelegramUserId(telegram_user_id) from exc

    async def find_by_telegram_user_id(
        self, group_id: int, telegram_user_id: int
    ) -> PersonDTO | None:
        async with self.session_factory() as session:
            person = await PersonRepository(session, group_id).get_by_telegram_user_id(
                telegram_user_id
            )
            return None if person is None else PersonDTO.model_validate(person)

    async def change_handle(
        self, group_id: int, person_id: int, telegram_handle: str | None
    ) -> PersonDTO:
        """Change the handle only. The person and Telegram user ID stay the same."""
        telegram_handle = _handle(telegram_handle)
        async with self.session_factory.begin() as session:
            person = await PersonRepository(session, group_id).get(person_id)
            if person is None:
                raise NotFound(f"Person {person_id}")
            person.telegram_handle = telegram_handle
            await session.flush()
            return PersonDTO.model_validate(person)
