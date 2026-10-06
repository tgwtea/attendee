"""Group chat registration. The handlers translate between Telegram and ChatRegistrationService.

The bot trusts only Telegram-filled sender fields. It never accepts a typed user ID.
"""

import logging

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from attendee.application.chats import ChatRegistrationService, RegistrationOutcome
from attendee.application.errors import AccessDenied
from attendee.application.identity import IdentityService
from attendee.domain.chats import registrable_chat_type
from attendee.telegram import messages

# Telegram shows an anonymous group admin as this bot account.
ANONYMOUS_ADMIN_ID = 1087968824

_REPLIES = {
    RegistrationOutcome.REGISTERED: messages.REGISTERED,
    RegistrationOutcome.REFRESHED: messages.REGISTER_REFRESHED,
    RegistrationOutcome.TAKEN: messages.REGISTER_TAKEN,
}


class ChatHandlers:
    def __init__(
        self, organization_id: int, identity: IdentityService, chats: ChatRegistrationService
    ) -> None:
        self.organization_id = organization_id
        self.identity = identity
        self.chats = chats

    async def register(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message, chat = update.effective_message, update.effective_chat
        if message is None or chat is None:
            return
        chat_type = registrable_chat_type(chat.type)
        if chat_type is None:
            return
        sender = message.from_user
        if message.sender_chat is not None or sender is None or sender.id == ANONYMOUS_ADMIN_ID:
            await message.reply_text(messages.REGISTER_ANONYMOUS)
            return
        log = logging.getLogger(__name__)
        try:
            person = await self.identity.find_by_telegram_user_id(sender.id)
            if person is None:
                await message.reply_text(messages.REGISTER_DENIED)
                return
            # Read the Telegram role before the write transaction to keep the transaction short.
            try:
                member = await context.bot.get_chat_member(chat.id, sender.id)
            except TelegramError as exc:
                log.warning("Group role check failed: %s", type(exc).__name__)
                await message.reply_text(messages.REGISTER_CHECK_FAILED)
                return
            result = await self.chats.register(
                self.organization_id,
                person.id,
                chat.id,
                chat_type,
                chat.title or str(chat.id),
                member.status,
            )
        except AccessDenied:
            await message.reply_text(messages.REGISTER_DENIED)
            return
        except SQLAlchemyError:
            log.error("Chat registration database operation failed")
            await message.reply_text(messages.REGISTER_FAILED)
            return
        await message.reply_text(_REPLIES[result.outcome])

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
            await self.chats.migrate(self.organization_id, old, new)
        except SQLAlchemyError:
            logging.getLogger(__name__).error("Chat migration database operation failed")
