"""Member onboarding in a private chat: /start, then a name confirmation for a handle match.

The handlers only translate between Telegram and AccountMatchingService (decision T34).
Callback data carries the organization ID and the person ID, so no proposal is stored.
"""

from dataclasses import dataclass

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from attendee.application.matching import AccountMatchingService, MatchResult
from attendee.domain.matching import MatchOutcome
from attendee.telegram import messages

CALLBACK_PATTERN = r"^m:"


@dataclass(frozen=True)
class MatchAnswer:
    accept: bool
    organization_id: int
    person_id: int


def match_callback(accept: bool, organization_id: int, person_id: int) -> str:
    return f"m:{'y' if accept else 'n'}:{organization_id}:{person_id}"


def parse_match_callback(data: str | None) -> MatchAnswer | None:
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[0] != "m" or parts[1] not in ("y", "n"):
        return None
    if not (
        parts[2].isascii() and parts[2].isdigit() and parts[3].isascii() and parts[3].isdigit()
    ):
        return None
    return MatchAnswer(parts[1] == "y", int(parts[2]), int(parts[3]))


def render(result: MatchResult, organization_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
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
                        messages.YES, callback_data=match_callback(True, organization_id, person.id)
                    ),
                    InlineKeyboardButton(
                        messages.NO, callback_data=match_callback(False, organization_id, person.id)
                    ),
                ]
            ]
        )
        return messages.confirm_name(person.display_name), keyboard
    return messages.NOT_MATCHED, None


class OnboardingHandlers:
    def __init__(self, organization_id: int, matching: AccountMatchingService) -> None:
        self.organization_id = organization_id
        self.matching = matching

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return
        result = await self.matching.match(self.organization_id, user.id, user.username)
        text, keyboard = render(result, self.organization_id)
        await message.reply_text(text, reply_markup=keyboard)

    async def answer(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        answer = parse_match_callback(query.data)
        if answer is None or answer.organization_id != self.organization_id:
            await edit_text(query, messages.PROPOSAL_EXPIRED, None)
            return
        user = query.from_user
        if answer.accept:
            result = await self.matching.confirm(
                self.organization_id, user.id, user.username, answer.person_id
            )
        else:
            result = await self.matching.reject(self.organization_id, user.id, user.username)
        text, keyboard = render(result, self.organization_id)
        await edit_text(query, text, keyboard)


async def edit_text(query: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    """Replace the message text. A repeated callback that changes nothing is not an error."""
    try:
        await query.edit_message_text(text, reply_markup=keyboard)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise
