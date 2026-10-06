"""Member onboarding: the private /start reply and the name confirmation helpers.

A private /start does not say which group the member belongs to (decision T80), so linking
starts from a poll tap (`ResponseHandlers.link_start`, decisions T88–T90).
Callback data carries the group ID and the person ID, so no proposal is stored (T34). Both are
claims: the service binds only the candidate that the user's own Telegram handle matches.
"""

from dataclasses import dataclass

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from attendee.application.matching import MatchResult
from attendee.domain.matching import MatchOutcome
from attendee.telegram import messages

CALLBACK_PATTERN = r"^m:"


@dataclass(frozen=True)
class MatchAnswer:
    accept: bool
    group_id: int
    person_id: int


def match_callback(accept: bool, group_id: int, person_id: int) -> str:
    return f"m:{'y' if accept else 'n'}:{group_id}:{person_id}"


def parse_match_callback(data: str | None) -> MatchAnswer | None:
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[0] != "m" or parts[1] not in ("y", "n"):
        return None
    if not (
        parts[2].isascii() and parts[2].isdigit() and parts[3].isascii() and parts[3].isdigit()
    ):
        return None
    return MatchAnswer(parts[1] == "y", int(parts[2]), int(parts[3]))


def render(result: MatchResult, group_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """Map a match result to a reply. Show the candidate name only (PRD §26)."""
    if result.outcome is MatchOutcome.BY_TELEGRAM_ID:
        return messages.ALREADY_LINKED, None
    if result.outcome is MatchOutcome.BOUND_BY_HANDLE:
        return messages.LINKED, None
    if result.outcome is MatchOutcome.PROPOSED and result.person is not None:
        person = result.person
        if person.display_name is None:
            return messages.NOT_MATCHED, None
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        messages.YES, callback_data=match_callback(True, group_id, person.id)
                    ),
                    InlineKeyboardButton(
                        messages.NO, callback_data=match_callback(False, group_id, person.id)
                    ),
                ]
            ]
        )
        return messages.confirm_name(person.display_name), keyboard
    return messages.NOT_MATCHED, None


class OnboardingHandlers:
    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """A private /start names no group. The member links from a group poll instead."""
        message = update.effective_message
        if message is None:
            return
        await message.reply_text(messages.START_FROM_GROUP)


async def edit_text(query: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    """Replace the message text. A repeated callback that changes nothing is not an error."""
    try:
        await query.edit_message_text(text, reply_markup=keyboard)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise
