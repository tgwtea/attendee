"""Build an empty Telegram application without product handlers."""

from typing import Any

from telegram.ext import Application, ContextTypes, ExtBot

# These dictionaries match the library defaults; no product state exists yet.
type BotApplication = Application[
    ExtBot[None], ContextTypes.DEFAULT_TYPE, dict[Any, Any], dict[Any, Any], dict[Any, Any], None
]


def build_application(token: str) -> BotApplication:
    return Application.builder().token(token).concurrent_updates(False).job_queue(None).build()
