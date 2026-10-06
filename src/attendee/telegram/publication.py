"""Private admin /publish flow and the Telegram publisher. Publication rules stay in the service.

Buttons use p:<token>:<action>[:<id>]. Each token binds the admin, chat, message, and step (T45).
"""

import logging
import re
import secrets
from dataclasses import dataclass, field
from enum import Enum, auto

from sqlalchemy.exc import SQLAlchemyError
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import ContextTypes

from attendee.application.authorization import AuthorizationService
from attendee.application.errors import AccessDenied, ApplicationError
from attendee.application.identity import IdentityService
from attendee.application.publication import (
    DraftDTO,
    PublicationService,
    PublishOutcome,
    PublishRejected,
    PublishResult,
    PublishUnknown,
)
from attendee.domain.identity import MembershipRole
from attendee.domain.publication import PublicationStatus
from attendee.telegram import messages

CALLBACK_PATTERN = r"^p:"
PAGE_SIZE = 10


def poll_keyboard(session_id: int) -> InlineKeyboardMarkup:
    """The four PRD §12 buttons: v:<session_id>:<c|n|l|e>."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=f"v:{session_id}:{code}")]
            for label, code in messages.POLL_BUTTONS
        ]
    )


class TelegramPublisher:
    """Send the poll and map Telegram errors to a definite or an unknown result."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_poll(self, telegram_chat_id: int, text: str, session_id: int) -> int:
        try:
            message = await self.bot.send_message(
                telegram_chat_id, text, reply_markup=poll_keyboard(session_id)
            )
        # BadRequest is a subclass of NetworkError, so it comes first.
        except BadRequest as exc:
            raise PublishRejected(type(exc).__name__) from None
        except NetworkError:  # TimedOut and other network errors
            raise PublishUnknown from None
        except TelegramError as exc:  # Forbidden, RetryAfter, ChatMigrated, and other answers
            raise PublishRejected(type(exc).__name__) from None
        return message.message_id


class Step(Enum):
    SESSION = auto()
    GROUP = auto()
    CONFIRM = auto()
    RESOLVE = auto()


@dataclass
class PendingPublication:
    step: Step = Step.SESSION
    token: str | None = None
    message_id: int | None = None
    session_id: int | None = None
    chat_id: int | None = None
    offered_sessions: set[int] = field(default_factory=set[int])
    offered_pages: set[int] = field(default_factory=set[int])
    offered_chats: set[int] = field(default_factory=set[int])


def callback(token: str, action: str, value: int | None = None) -> str:
    data = f"p:{token}:{action}" + ("" if value is None else f":{value}")
    if len(data.encode()) > 64:
        raise ValueError("Callback exceeds Telegram's limit.")
    return data


def parse_callback(data: str | None) -> tuple[str, str, int | None] | None:
    match = re.fullmatch(r"p:([A-Za-z0-9_-]{16}):([spgyvxc])(?::([0-9]{1,19}))?", data or "")
    if match is None:
        return None
    action = match[2]
    value = None if match[3] is None else int(match[3])
    if (action in ("s", "p", "g")) != (value is not None):
        return None
    return match[1], action, value


def _session_label(draft: DraftDTO) -> str:
    text = f"{draft.series_name} · {draft.label or draft.session_date.isoformat()}"
    if draft.publication is PublicationStatus.PUBLISH_UNKNOWN:
        return messages.PUBLISH_SESSION_CHECK.format(session=text)
    if draft.publication is PublicationStatus.PUBLISHING:
        return messages.PUBLISH_SESSION_BUSY.format(session=text)
    return text


class PublicationHandlers:
    def __init__(
        self,
        organization_id: int,
        identity: IdentityService,
        authorization: AuthorizationService,
        publication: PublicationService,
    ) -> None:
        self.organization_id = organization_id
        self.identity = identity
        self.authorization = authorization
        self.publication = publication
        self.pending: dict[tuple[int, int], PendingPublication] = {}

    def _key(self, update: Update) -> tuple[int, int] | None:
        chat, user = update.effective_chat, update.effective_user
        if chat is None or user is None or chat.type != "private":
            return None
        return chat.id, user.id

    async def _actor(self, user_id: int) -> int:
        person = await self.identity.find_by_telegram_user_id(user_id)
        if person is None:
            raise AccessDenied(messages.PUBLISH_DENIED)
        await self.authorization.require_role(self.organization_id, person.id, MembershipRole.ADMIN)
        return person.id

    async def _reply(self, update: Update, text: str) -> None:
        if update.effective_message is not None:
            await update.effective_message.reply_text(text)

    async def _prompt(
        self,
        update: Update,
        pending: PendingPublication,
        step: Step,
        text: str,
        choices: list[tuple[str, str, int | None]],
    ) -> None:
        message = update.effective_message
        assert message is not None
        pending.step = step
        pending.token = secrets.token_urlsafe(12)
        rows = [*choices, (messages.CANCEL, "c", None)]
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(label, callback_data=callback(pending.token, action, value))]
                for label, action, value in rows
            ]
        )
        sent = await message.reply_text(text, reply_markup=keyboard)
        pending.message_id = sent.message_id

    async def _sessions(
        self, update: Update, pending: PendingPublication, actor: int, page: int = 0
    ) -> bool:
        drafts = await self.publication.list_drafts(
            self.organization_id, actor, page * PAGE_SIZE, PAGE_SIZE + 1
        )
        if not drafts and page == 0:
            await self._reply(update, messages.PUBLISH_NO_DRAFTS)
            return False
        shown = drafts[:PAGE_SIZE]
        pending.offered_sessions = {draft.id for draft in shown}
        pending.offered_pages = set()
        choices: list[tuple[str, str, int | None]] = [
            (_session_label(draft), "s", draft.id) for draft in shown
        ]
        if page:
            choices.append((messages.PREVIOUS, "p", page - 1))
            pending.offered_pages.add(page - 1)
        if len(drafts) > PAGE_SIZE:
            choices.append((messages.NEXT, "p", page + 1))
            pending.offered_pages.add(page + 1)
        await self._prompt(update, pending, Step.SESSION, messages.PUBLISH_SELECT_SESSION, choices)
        return True

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        key = self._key(update)
        if key is None or update.effective_message is None:
            return
        self.pending.pop(key, None)
        try:
            actor = await self._actor(key[1])
            pending = PendingPublication()
            if await self._sessions(update, pending, actor):
                self.pending[key] = pending
        except AccessDenied:
            await self._reply(update, messages.PUBLISH_DENIED)
        except SQLAlchemyError:
            await self._database_failure(update, key)

    async def _database_failure(self, update: Update, key: tuple[int, int]) -> None:
        self.pending.pop(key, None)
        logging.getLogger(__name__).error("Publication database operation failed")
        await self._reply(update, messages.PUBLISH_DB_FAILED)

    def _valid(self, pending: PendingPublication, action: str, value: int | None) -> bool:
        if action == "c":
            return True
        if pending.step is Step.SESSION:
            return (action == "s" and value in pending.offered_sessions) or (
                action == "p" and value in pending.offered_pages
            )
        if pending.step is Step.GROUP:
            return action == "g" and value in pending.offered_chats
        if pending.step is Step.CONFIRM:
            return action == "y"
        return action in ("v", "x")

    async def button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        key = self._key(update)
        parsed = parse_callback(query.data)
        pending = None if key is None else self.pending.get(key)
        if (
            key is None
            or pending is None
            or parsed is None
            or pending.token != parsed[0]
            or query.message is None
            or query.message.message_id != pending.message_id
            or not self._valid(pending, parsed[1], parsed[2])
        ):
            await query.answer(messages.PUBLISH_EXPIRED, show_alert=True)
            return
        _, action, value = parsed
        # Consume before the first await. A repeated tap cannot enter this action.
        pending.token = None
        await query.answer()
        try:
            actor = await self._actor(key[1])
            if action == "c":
                self.pending.pop(key, None)
                await self._reply(update, messages.PUBLISH_CANCELLED)
            elif action == "p":
                assert value is not None
                await self._sessions(update, pending, actor, value)
            elif action == "s":
                assert value is not None
                await self._session_selected(update, key, pending, actor, value)
            elif action == "g":
                assert value is not None and pending.session_id is not None
                pending.chat_id = value
                review = await self.publication.review(
                    self.organization_id, actor, pending.session_id, value
                )
                await self._prompt(
                    update,
                    pending,
                    Step.CONFIRM,
                    messages.PUBLISH_REVIEW.format(group=review.chat.title, poll=review.text),
                    [(messages.PUBLISH, "y", None)],
                )
            elif action == "y":
                assert pending.session_id is not None and pending.chat_id is not None
                self.pending.pop(key, None)
                result = await self.publication.publish(
                    self.organization_id,
                    actor,
                    pending.session_id,
                    pending.chat_id,
                    TelegramPublisher(context.bot),
                )
                await self._result(update, key, pending, result)
            else:
                assert pending.session_id is not None
                self.pending.pop(key, None)
                result = await self.publication.resolve(
                    self.organization_id, actor, pending.session_id, seen=action == "v"
                )
                await self._result(update, key, pending, result, resolved=True)
        except AccessDenied:
            self.pending.pop(key, None)
            await self._reply(update, messages.PUBLISH_DENIED)
        except ApplicationError as exc:
            self.pending.pop(key, None)
            await self._reply(update, str(exc))
        except SQLAlchemyError:
            await self._database_failure(update, key)

    async def _session_selected(
        self,
        update: Update,
        key: tuple[int, int],
        pending: PendingPublication,
        actor: int,
        session_id: int,
    ) -> None:
        draft = await self.publication.draft_state(self.organization_id, actor, session_id)
        pending.session_id = draft.id
        if draft.publication is PublicationStatus.PUBLISH_UNKNOWN:
            await self._resolve_prompt(update, pending)
            return
        if draft.publication is PublicationStatus.PUBLISHING:
            self.pending.pop(key, None)
            await self._reply(update, messages.PUBLISH_IN_PROGRESS)
            return
        chats = await self.publication.list_chats(self.organization_id, actor)
        if not chats:
            self.pending.pop(key, None)
            await self._reply(update, messages.PUBLISH_NO_GROUPS)
            return
        pending.offered_chats = {chat.id for chat in chats}
        await self._prompt(
            update,
            pending,
            Step.GROUP,
            messages.PUBLISH_SELECT_GROUP,
            [(chat.title, "g", chat.id) for chat in chats],
        )

    async def _resolve_prompt(self, update: Update, pending: PendingPublication) -> None:
        await self._prompt(
            update,
            pending,
            Step.RESOLVE,
            messages.PUBLISH_UNKNOWN,
            [(messages.I_SEE_POLL, "v", None), (messages.I_CANT_SEE_POLL, "x", None)],
        )

    async def _result(
        self,
        update: Update,
        key: tuple[int, int],
        pending: PendingPublication,
        result: PublishResult,
        resolved: bool = False,
    ) -> None:
        if result.outcome is PublishOutcome.UNKNOWN:
            self.pending[key] = pending
            await self._resolve_prompt(update, pending)
            return
        if result.outcome is PublishOutcome.PUBLISHED:
            text = messages.PUBLISH_DONE_NO_EDIT if resolved else messages.PUBLISH_DONE
        elif result.outcome is PublishOutcome.FAILED:
            text = (
                messages.PUBLISH_NOT_SEEN
                if resolved
                else messages.PUBLISH_FAILED.format(failure=result.failure)
            )
        else:
            text = messages.PUBLISH_IN_PROGRESS
        await self._reply(update, text)
