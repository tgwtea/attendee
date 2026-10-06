"""Group-scoped response queries. Repositories never commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attendee.persistence.models import SessionResponse, SessionResponseEvent, SessionRosterEntry


class ResponseRepository:
    def __init__(self, session: AsyncSession, group_id: int) -> None:
        self.session = session
        self.group_id = group_id

    async def on_roster(self, session_id: int, person_id: int) -> bool:
        entry = await self.session.get(SessionRosterEntry, (self.group_id, session_id, person_id))
        return entry is not None

    async def current(self, session_id: int, person_id: int) -> SessionResponse | None:
        return await self.session.get(SessionResponse, (self.group_id, session_id, person_id))

    async def add(self, response: SessionResponse) -> SessionResponse:
        if response.group_id != self.group_id:
            raise ValueError("Response group differs from repository scope.")
        self.session.add(response)
        await self.session.flush()
        return response

    async def add_event(self, event: SessionResponseEvent) -> SessionResponseEvent:
        if event.group_id != self.group_id:
            raise ValueError("Response event group differs from repository scope.")
        self.session.add(event)
        await self.session.flush()
        return event

    async def events(self, session_id: int, person_id: int) -> list[SessionResponseEvent]:
        rows = await self.session.scalars(
            select(SessionResponseEvent)
            .where(
                SessionResponseEvent.group_id == self.group_id,
                SessionResponseEvent.session_id == session_id,
                SessionResponseEvent.person_id == person_id,
            )
            .order_by(SessionResponseEvent.id)
        )
        return list(rows)
