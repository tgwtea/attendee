"""Group-scoped access to people. Repositories never commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.persistence.models import Person


class PersonRepository:
    """People of one group. A person in another group is never visible here (decision T82)."""

    def __init__(self, session: AsyncSession, group_id: int) -> None:
        self.session = session
        self.group_id = group_id

    async def get(self, person_id: int) -> Person | None:
        return await self.session.scalar(
            select(Person).where(Person.group_id == self.group_id, Person.id == person_id)
        )

    async def get_by_telegram_user_id(self, telegram_user_id: int) -> Person | None:
        return await self.session.scalar(
            select(Person).where(
                Person.group_id == self.group_id, Person.telegram_user_id == telegram_user_id
            )
        )

    async def add(self, person: Person) -> Person:
        if person.group_id != self.group_id:
            raise ValueError("Person group differs from repository scope.")
        self.session.add(person)
        await self.session.flush()
        return person

    async def members(self) -> list[Person]:
        """Every person in the group, in person ID order."""
        rows = await self.session.scalars(
            select(Person).where(Person.group_id == self.group_id).order_by(Person.id)
        )
        return list(rows)

    async def member_ids(self) -> tuple[int, ...]:
        rows = await self.session.scalars(
            select(Person.id).where(Person.group_id == self.group_id).order_by(Person.id)
        )
        return tuple(rows)

    async def find_unbound_by_handle(self, telegram_handle: str) -> list[Person]:
        """People of the group with this canonical handle and no Telegram user ID."""
        rows = await self.session.scalars(
            select(Person)
            .where(
                Person.group_id == self.group_id,
                Person.telegram_handle == telegram_handle,
                Person.telegram_user_id.is_(None),
            )
            .order_by(Person.id)
        )
        return list(rows)
