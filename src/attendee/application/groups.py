"""Telegram groups and group-admin access (decisions T80–T85).

The bot learns a group when Telegram reports that the bot joined it. A Telegram group admin is
a bot admin for that group only. The bot stores no admin list: each admin action asks Telegram.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee import copy
from attendee.application.errors import AccessDenied
from attendee.domain.chats import ChatType
from attendee.persistence.database import write_session
from attendee.persistence.models import Group
from attendee.repositories.groups import GroupRepository


class GroupDTO(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: int
    telegram_chat_id: int
    chat_type: ChatType
    title: str
    active: bool
    created_at: datetime
    updated_at: datetime


class AdminChecker(Protocol):
    async def is_admin(self, telegram_chat_id: int, telegram_user_id: int) -> bool:
        """Return True for a group creator or administrator.

        Raise AdminCheckFailed when Telegram gives no answer.
        """
        ...


def _title(title: str | None, telegram_chat_id: int) -> str:
    """Telegram allows group titles up to 128 characters. Cut a longer one; never reject it."""
    return " ".join((title or "").split())[:200] or str(telegram_chat_id)


class GroupService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def joined(
        self, telegram_chat_id: int, chat_type: ChatType, title: str | None
    ) -> GroupDTO:
        """Add the group, or make a known group active again. A repeat refreshes the title."""
        async with write_session(self.session_factory) as session:
            repository = GroupRepository(session)
            row = await repository.by_telegram_id(telegram_chat_id)
            if row is None:
                row = await repository.add(
                    Group(
                        telegram_chat_id=telegram_chat_id,
                        chat_type=chat_type.value,
                        title=_title(title, telegram_chat_id),
                    )
                )
            else:
                row.chat_type = chat_type.value
                row.title = _title(title, telegram_chat_id)
                row.active = True
                await session.flush()
            result = GroupDTO.model_validate(row)
        return result

    async def left(self, telegram_chat_id: int) -> bool:
        """Mark the group inactive and keep its data. Return True only if this call changed it."""
        async with write_session(self.session_factory) as session:
            row = await GroupRepository(session).by_telegram_id(telegram_chat_id)
            if row is None or not row.active:
                return False
            row.active = False
            await session.flush()
        return True

    async def migrate(self, old_chat_id: int, new_chat_id: int) -> bool:
        """Follow a group upgrade to a supergroup. Telegram gives the supergroup a new chat ID.

        The internal group ID stays the same, so no other table changes (decision T81).
        A row that a join update created for the new chat ID is removed if nothing refers to it.
        Return True only when this call moved the group. A repeat changes nothing.
        """
        async with write_session(self.session_factory) as session:
            repository = GroupRepository(session)
            row = await repository.by_telegram_id(old_chat_id)
            if row is None:
                return False
            newer = await repository.by_telegram_id(new_chat_id)
            if newer is not None:
                try:
                    async with session.begin_nested():
                        await session.delete(newer)
                except IntegrityError:
                    return False
            row.telegram_chat_id = new_chat_id
            row.chat_type = ChatType.SUPERGROUP.value
            row.active = True
            await session.flush()
        return True

    async def by_telegram_id(self, telegram_chat_id: int) -> GroupDTO | None:
        async with self.session_factory() as session:
            row = await GroupRepository(session).by_telegram_id(telegram_chat_id)
            return None if row is None else GroupDTO.model_validate(row)


class GroupAccess:
    """Admin checks. Each check reads the group, then asks Telegram outside any transaction."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], checker: AdminChecker
    ) -> None:
        self.session_factory = session_factory
        self.checker = checker

    async def require_admin(self, group_id: int, telegram_user_id: int) -> GroupDTO:
        """Return the active group, or raise AccessDenied. Raise AdminCheckFailed on no answer."""
        async with self.session_factory() as session:
            row = await GroupRepository(session).get(group_id)
            group = None if row is None else GroupDTO.model_validate(row)
        if group is None or not group.active:
            raise AccessDenied(copy.ADMIN_DENIED)
        if not await self.checker.is_admin(group.telegram_chat_id, telegram_user_id):
            raise AccessDenied(copy.ADMIN_DENIED)
        return group

    async def admin_groups(self, telegram_user_id: int) -> list[GroupDTO]:
        """The active groups where the user is an admin, by title. One Telegram call per group."""
        async with self.session_factory() as session:
            rows = await GroupRepository(session).active()
            groups = [GroupDTO.model_validate(row) for row in rows]
        return [
            group
            for group in groups
            if await self.checker.is_admin(group.telegram_chat_id, telegram_user_id)
        ]
