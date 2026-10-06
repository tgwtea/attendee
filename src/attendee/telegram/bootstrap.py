"""Build the long-polling Telegram application and register the product handlers."""

from collections.abc import Sequence
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    BaseHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    ExtBot,
    MessageHandler,
    filters,
)

from attendee.telegram import onboarding, uploads
from attendee.telegram.attendance import CALLBACK_PATTERN, AttendanceHandlers
from attendee.telegram.groups import GroupHandlers
from attendee.telegram.publication import CALLBACK_PATTERN as PUBLISH_PATTERN
from attendee.telegram.publication import PublicationHandlers
from attendee.telegram.responses import CALLBACK_PATTERN as VOTE_PATTERN
from attendee.telegram.responses import LINK_PATTERN, START_PATTERN, ResponseHandlers
from attendee.telegram.stats import CALLBACK_PATTERN as STATS_PATTERN
from attendee.telegram.stats import StatsHandlers

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
    groups: GroupHandlers,
    publication: PublicationHandlers,
    responses: ResponseHandlers,
    stats: StatsHandlers,
) -> list[BotHandler]:
    """Private chat handlers, group joins and upgrades, and group poll buttons.

    Only the first matching handler runs. The reason handler comes before /attendance, but it
    matches only a reply to a known prompt, so other private text still reaches /attendance.
    "/start reason" and "/start link" come before the onboarding /start.
    """
    private = filters.ChatType.PRIVATE
    return [
        MessageHandler(
            private & filters.TEXT & ~filters.COMMAND & responses.has_pending, responses.reason
        ),
        attendance.conversation(),
        CallbackQueryHandler(attendance.expired, pattern=CALLBACK_PATTERN),
        MessageHandler(private & filters.Regex(START_PATTERN), responses.start),
        MessageHandler(private & filters.Regex(LINK_PATTERN), responses.link_start),
        CommandHandler("start", members.start, filters=private),
        CallbackQueryHandler(responses.link_answer, pattern=onboarding.CALLBACK_PATTERN),
        MessageHandler(filters.Document.ALL & private, admins.document),
        CallbackQueryHandler(admins.pick_group, pattern=uploads.GROUP_PATTERN),
        CallbackQueryHandler(admins.button, pattern=uploads.CALLBACK_PATTERN),
        ChatMemberHandler(groups.member_update, ChatMemberHandler.MY_CHAT_MEMBER),
        MessageHandler(filters.StatusUpdate.MIGRATE, groups.migrate),
        CommandHandler("publish", publication.start, filters=private),
        CallbackQueryHandler(publication.button, pattern=PUBLISH_PATTERN),
        CallbackQueryHandler(responses.tap, pattern=VOTE_PATTERN),
        CommandHandler("stats", stats.start, filters=private),
        CallbackQueryHandler(stats.button, pattern=STATS_PATTERN),
    ]


def build_application(token: str, handlers: Sequence[BotHandler] = ()) -> BotApplication:
    application = (
        Application.builder().token(token).concurrent_updates(False).job_queue(None).build()
    )
    for handler in handlers:
        application.add_handler(handler)
    return application
