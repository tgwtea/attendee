"""Group discovery, supergroup upgrades, and the Telegram group-admin check (decisions T83, T84).

The bot trusts only Telegram-filled fields. It never accepts a typed user ID or chat ID.
"""

import logging

from sqlalchemy.exc import SQLAlchemyError
from telegram import Bot, Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from attendee import copy
from attendee.application.errors import AdminCheckFailed
from attendee.application.groups import GroupService
from attendee.domain.chats import controls_group, group_chat_type, is_present


class TelegramAdminChecker:
    """Ask Telegram for the user's status in the group. Use no cache (decision T83)."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def is_admin(self, telegram_chat_id: int, telegram_user_id: int) -> bool:
        try:
            member = await self.bot.get_chat_member(telegram_chat_id, telegram_user_id)
        # A definite answer: the user or the bot is not in the chat, or the chat is gone.
        except (BadRequest, Forbidden):
            return False
        except TelegramError as exc:
            logging.getLogger(__name__).warning("Group admin check failed: %s", type(exc).__name__)
            raise AdminCheckFailed(copy.ADMIN_CHECK_FAILED) from None
        return controls_group(member.status)


class GroupHandlers:
    def __init__(self, groups: GroupService) -> None:
        self.groups = groups

    async def member_update(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Telegram reports a change of the bot's own status in a chat."""
        change = update.my_chat_member
        if change is None:
            return
        chat_type = group_chat_type(change.chat.type)
        if chat_type is None:
            return
        try:
            if is_present(change.new_chat_member.status):
                await self.groups.joined(change.chat.id, chat_type, change.chat.title)
            else:
                await self.groups.left(change.chat.id)
        except SQLAlchemyError:
            logging.getLogger(__name__).error("Group membership database operation failed")

    async def migrate(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Telegram reports an upgrade in the old group and in the new supergroup."""
        message = update.effective_message
        if message is None:
            return
        if message.migrate_to_chat_id is not None:
            old, new = message.chat.id, message.migrate_to_chat_id
        elif message.migrate_from_chat_id is not None:
            old, new = message.migrate_from_chat_id, message.chat.id
        else:
            return
        try:
            await self.groups.migrate(old, new)
        except SQLAlchemyError:
            logging.getLogger(__name__).error("Group migration database operation failed")
