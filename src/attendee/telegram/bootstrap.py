"""Build the long-polling Telegram application and register the product handlers."""

from collections.abc import Sequence
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    BaseHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ExtBot,
    MessageHandler,
    filters,
)

from attendee.telegram import onboarding, uploads
from attendee.telegram.attendance import CALLBACK_PATTERN, AttendanceHandlers
from attendee.telegram.chats import ChatHandlers

# These dictionaries match the library defaults. Attendance state lives in its handlers.
type BotApplication = Application[
    ExtBot[None], ContextTypes.DEFAULT_TYPE, dict[Any, Any], dict[Any, Any], dict[Any, Any], None
]
# Conversation callbacks return state integers; other callbacks return None.
type BotHandler = BaseHandler[Update, ContextTypes.DEFAULT_TYPE, Any]


def bot_handlers(
    members: onboarding.OnboardingHandlers,
    admins: uploads.UploadHandlers,
    attendance: AttendanceHandlers,
    chats: ChatHandlers,
) -> list[BotHandler]:
    """Private chat handlers, plus group registration and group upgrades."""
    private = filters.ChatType.PRIVATE
    return [
        attendance.conversation(),
        CallbackQueryHandler(attendance.expired, pattern=CALLBACK_PATTERN),
        CommandHandler("start", members.start, filters=private),
        CallbackQueryHandler(members.answer, pattern=onboarding.CALLBACK_PATTERN),
        MessageHandler(filters.Document.ALL & private, admins.document),
        CallbackQueryHandler(admins.button, pattern=uploads.CALLBACK_PATTERN),
        CommandHandler("register", chats.register, filters=filters.ChatType.GROUPS),
        MessageHandler(filters.StatusUpdate.MIGRATE, chats.migrate),
    ]


def build_application(token: str, handlers: Sequence[BotHandler] = ()) -> BotApplication:
    application = (
        Application.builder().token(token).concurrent_updates(False).job_queue(None).build()
    )
    for handler in handlers:
        application.add_handler(handler)
    return application
