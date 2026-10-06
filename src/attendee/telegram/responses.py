"""Member responses: a group tap, then a reason in the private chat for non-Coming statuses.

A tap that changes a saved status asks for a second tap first (decision T68).

A response takes up to three updates: the tap, "/start reason", and the reason text.
The private prompt links the reason reply to its original pending tap (decision T78).
The state lives in process memory, so a restart loses it and the member taps again.
The group of a tap is the chat of the poll message, which Telegram fills (decision T80).

An unlinked member's tap is kept, and the member confirms their name in the private chat.
After Yes, the bot saves the kept tap, so the member taps once only (decisions T88–T90).
"""

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from telegram import Bot, CallbackQuery, ForceReply, Message, Update
from telegram.ext import ContextTypes, filters

from attendee.application.errors import NotFound
from attendee.application.groups import GroupDTO, GroupService
from attendee.application.matching import AccountMatchingService, MatchResult
from attendee.application.responses import (
    NotLinked,
    NotOnRoster,
    ResponseService,
    ResponseTarget,
    SessionNotOpen,
)
from attendee.domain.matching import MatchOutcome
from attendee.domain.responses import ReasonMissing, ReasonTooLong, ResponseStatus, parse_vote
from attendee.telegram import messages
from attendee.telegram.onboarding import edit_text, parse_match_callback, render

CALLBACK_PATTERN = r"^v:"
START_PAYLOAD = "reason"
START_PATTERN = rf"^/start {START_PAYLOAD}$"
LINK_PAYLOAD = "link"
LINK_PATTERN = rf"^/start {LINK_PAYLOAD}$"


@dataclass(frozen=True)
class PendingReason:
    group_id: int
    session_id: int
    status: ResponseStatus


# A member confirms a change of status with a second tap within this time (decision T68).
CONFIRM_SECONDS = 60


@dataclass(frozen=True)
class ArmedChange:
    session_id: int
    status: ResponseStatus
    expires_at: float
    callback_id: str


class HasPendingReason(filters.MessageFilter):
    """Match a reply to a known reason prompt. Other text reaches /attendance."""

    def __init__(self, prompts: dict[tuple[int, int], PendingReason]) -> None:
        super().__init__(name="HasPendingReason")
        self.prompts = prompts

    def filter(self, message: Message) -> bool:
        return (
            message.from_user is not None
            and message.reply_to_message is not None
            and (message.from_user.id, message.reply_to_message.message_id) in self.prompts
        )


def _denied_text(exc: NotLinked | NotOnRoster | SessionNotOpen) -> str:
    if isinstance(exc, NotLinked):
        return messages.NOT_MATCHED
    if isinstance(exc, NotOnRoster):
        return messages.NOT_ON_ROSTER
    return messages.POLL_CLOSED


def _not_found_text(username: str | None) -> str:
    """Show only the user's own username. Two matches give the same text, with no names."""
    if not username:
        return messages.LINK_NO_USERNAME
    return messages.LINK_NOT_FOUND.format(handle=username.removeprefix("@"))


def _session_name(target: ResponseTarget) -> str:
    day = f"{target.session_date.day} {target.session_date:%B %Y}"
    if target.label:
        return f"{target.series_name} ({target.label}) on {day}"
    return f"{target.series_name} on {day}"


class ResponseHandlers:
    def __init__(
        self,
        groups: GroupService,
        responses: ResponseService,
        matching: AccountMatchingService,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.groups = groups
        self.responses = responses
        self.matching = matching
        self.clock = clock
        self.pending: dict[int, PendingReason] = {}
        # The kept tap of an unlinked member, one per Telegram user ID. Memory only (T88).
        self.links: dict[int, PendingReason] = {}
        self.prompts: dict[tuple[int, int], PendingReason] = {}
        self.has_pending = HasPendingReason(self.prompts)
        self.callbacks: OrderedDict[str, None] = OrderedDict()
        # Memory only, like `pending`. A restart forgets an armed change.
        self.armed: dict[tuple[int, int], ArmedChange] = {}

    def _needs_confirmation(
        self,
        user_id: int,
        session_id: int,
        status: ResponseStatus,
        current: ResponseStatus | None,
        callback_id: str,
    ) -> bool:
        """Arm on the first tap that changes a saved status. A second tap in time disarms."""
        key = (user_id, session_id)
        armed = self.armed.pop(key, None)
        if current is None or current is status:
            return False
        now = self.clock()
        if (
            armed is not None
            and armed.session_id == session_id
            and armed.status is status
            and armed.callback_id != callback_id
            and now < armed.expires_at
        ):
            return False
        self.armed[key] = ArmedChange(session_id, status, now + CONFIRM_SECONDS, callback_id)
        return True

    async def tap(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """A poll button in the group. Every answer is visible to the tapping member only."""
        query = update.callback_query
        if query is None:
            return
        if query.id in self.callbacks:
            await query.answer(messages.VOTE_REPEAT, show_alert=True)
            return
        self.callbacks[query.id] = None
        if len(self.callbacks) > 4096:
            self.callbacks.popitem(last=False)
        vote = parse_vote(query.data)
        if vote is None:
            await query.answer(messages.VOTE_INVALID, show_alert=True)
            return
        session_id, status = vote
        user_id = query.from_user.id
        group: GroupDTO | None = None
        try:
            group = (
                None
                if query.message is None
                else await self.groups.by_telegram_id(query.message.chat.id)
            )
            if group is None or not group.active:
                raise SessionNotOpen
            target = await self.responses.check(group.id, user_id, session_id)
            if self._needs_confirmation(
                user_id, session_id, status, target.current_status, query.id
            ):
                assert target.current_status is not None
                await query.answer(
                    messages.CONFIRM_REPLACE.format(
                        current=target.current_status.label,
                        new=status.label,
                        seconds=CONFIRM_SECONDS,
                    ),
                    show_alert=True,
                )
                return
            if status is ResponseStatus.COMING:
                # Clear state for this session only after the database commit.
                await self.responses.record(group.id, user_id, session_id, status)
                self._clear_session(user_id, group.id, session_id)
                await query.answer(messages.RECORDED.format(status=status.label), show_alert=True)
                return
        except NotLinked:
            # Keep the tap. The member confirms their name in the private chat first (T88).
            assert group is not None
            self.links[user_id] = PendingReason(group.id, session_id, status)
            await query.answer(url=f"https://t.me/{context.bot.username}?start={LINK_PAYLOAD}")
            return
        except (NotOnRoster, SessionNotOpen) as exc:
            await query.answer(_denied_text(exc), show_alert=True)
            return
        except SQLAlchemyError:
            logging.getLogger(__name__).error("Response database operation failed")
            await query.answer(messages.TAP_NOT_SAVED, show_alert=True)
            return
        # A new tap replaces the pending one. Nothing is in the database yet.
        self.pending[user_id] = PendingReason(group.id, session_id, status)
        await query.answer(url=f"https://t.me/{context.bot.username}?start={START_PAYLOAD}")

    async def link_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Private "/start link". Match the user's own Telegram username in the tap's group.

        The bot never asks for a username and never shows another member's data (T89).
        """
        message, user = update.effective_message, update.effective_user
        if message is None or user is None:
            return
        kept = self.links.get(user.id)
        if kept is None:
            await message.reply_text(messages.LINK_NO_PENDING)
            return
        try:
            result = await self.matching.match(kept.group_id, user.id, user.username)
        except (NotFound, SQLAlchemyError):
            logging.getLogger(__name__).error("Account matching failed")
            await message.reply_text(messages.TAP_NOT_SAVED)
            return
        if result.outcome is MatchOutcome.BY_TELEGRAM_ID:
            # Linked since the tap, for example from another device.
            self.links.pop(user.id, None)
            await self._apply(context.bot, user.id, kept)
            return
        text, keyboard = render(result, kept.group_id)
        if keyboard is None:
            self.links.pop(user.id, None)
            text = _not_found_text(user.username)
        await message.reply_text(text, reply_markup=keyboard)

    async def link_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Yes or No to "Are you <name>?". Yes links the account and saves the kept tap (T90).

        The group and person IDs in the button are claims. The service binds only the person
        that the user's own Telegram username proposes in that group.
        """
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        answer = parse_match_callback(query.data)
        if answer is None:
            await edit_text(query, messages.PROPOSAL_EXPIRED, None)
            return
        user = query.from_user
        try:
            if answer.accept:
                result = await self.matching.confirm(
                    answer.group_id, user.id, user.username, answer.person_id
                )
            else:
                result = await self.matching.reject(answer.group_id, user.id, user.username)
        except NotFound:
            await edit_text(query, messages.PROPOSAL_EXPIRED, None)
            return
        await self._after_match(query, context.bot, answer.group_id, result)

    async def _after_match(
        self, query: CallbackQuery, bot: Bot, group_id: int, result: MatchResult
    ) -> None:
        user_id = query.from_user.id
        if result.outcome not in (MatchOutcome.BOUND_BY_HANDLE, MatchOutcome.BY_TELEGRAM_ID):
            text, keyboard = render(result, group_id)
            if result.outcome is MatchOutcome.UNRESOLVED:
                self.links.pop(user_id, None)
                text = _not_found_text(query.from_user.username)
            await edit_text(query, text, keyboard)
            return
        kept = self.links.get(user_id)
        if kept is None or kept.group_id != group_id:
            # A restart lost the kept tap, or it belongs to another group.
            await edit_text(query, messages.LINK_TAP_AGAIN, None)
            return
        del self.links[user_id]
        await edit_text(query, messages.LINKED, None)
        await self._apply(bot, user_id, kept)

    async def _apply(self, bot: Bot, user_id: int, kept: PendingReason) -> None:
        """Save a kept Coming tap, or ask for the reason of another status, in the private chat."""
        try:
            if kept.status is ResponseStatus.COMING:
                await self.responses.record(kept.group_id, user_id, kept.session_id, kept.status)
                self._clear_session(user_id, kept.group_id, kept.session_id)
                await bot.send_message(user_id, messages.RECORDED.format(status=kept.status.label))
                return
            target = await self.responses.check(kept.group_id, user_id, kept.session_id)
        except (NotLinked, NotOnRoster, SessionNotOpen) as exc:
            await bot.send_message(user_id, _denied_text(exc))
            return
        except SQLAlchemyError:
            logging.getLogger(__name__).error("Response database operation failed")
            await bot.send_message(user_id, messages.TAP_NOT_SAVED)
            return
        self.pending[user_id] = kept
        text = messages.REASON_PROMPT.format(
            status=kept.status.label, session=_session_name(target)
        )
        prompt = await bot.send_message(user_id, text, reply_markup=ForceReply(selective=True))
        self.prompts[user_id, prompt.message_id] = kept

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Private "/start reason" from the deep link. Ask for the reason of the pending tap."""
        message, user = update.effective_message, update.effective_user
        if message is None or user is None:
            return
        pending = self.pending.get(user.id)
        if pending is None:
            await message.reply_text(messages.NO_PENDING_REASON)
            return
        try:
            target = await self.responses.check(pending.group_id, user.id, pending.session_id)
        except (NotLinked, NotOnRoster, SessionNotOpen) as exc:
            self._drop(user.id, pending)
            await message.reply_text(_denied_text(exc))
            return
        except SQLAlchemyError:
            logging.getLogger(__name__).error("Response database operation failed")
            await message.reply_text(messages.TAP_NOT_SAVED)
            return
        await self._prompt(
            message,
            user.id,
            pending,
            messages.REASON_PROMPT.format(
                status=pending.status.label, session=_session_name(target)
            ),
        )

    async def reason(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Private text from a user with a pending tap. Never log the reason text."""
        message, user = update.effective_message, update.effective_user
        if message is None or user is None:
            return
        if message.reply_to_message is None:
            return
        pending = self.prompts.get((user.id, message.reply_to_message.message_id))
        if pending is None:
            return
        try:
            result = await self.responses.record(
                pending.group_id, user.id, pending.session_id, pending.status, message.text
            )
        except ReasonMissing:
            await self._prompt(message, user.id, pending, messages.REASON_MISSING)
            return
        except ReasonTooLong:
            await self._prompt(message, user.id, pending, messages.REASON_TOO_LONG)
            return
        except (NotLinked, NotOnRoster, SessionNotOpen) as exc:
            self._drop(user.id, pending)
            await message.reply_text(_denied_text(exc))
            return
        except SQLAlchemyError:
            # Keep the pending tap. PRD §36: confirm only after the save.
            logging.getLogger(__name__).error("Response database operation failed")
            await self._prompt(message, user.id, pending, messages.REASON_NOT_SAVED)
            return
        self._clear_session(user.id, pending.group_id, pending.session_id)
        await message.reply_text(
            messages.RECORDED_REASON.format(status=result.status.label, reason=result.reason)
        )

    async def _prompt(
        self, message: Message, user_id: int, pending: PendingReason, text: str
    ) -> None:
        prompt = await message.reply_text(text, reply_markup=ForceReply(selective=True))
        self.prompts[user_id, prompt.message_id] = pending

    def _clear_session(self, user_id: int, group_id: int, session_id: int) -> None:
        """Invalidate all old prompts for the saved session. Other sessions keep their state."""
        for key, target in list(self.prompts.items()):
            if key[0] == user_id and (target.group_id, target.session_id) == (group_id, session_id):
                del self.prompts[key]
        for pending in (self.pending, self.links):
            target = pending.get(user_id)
            if target is not None and (target.group_id, target.session_id) == (
                group_id,
                session_id,
            ):
                del pending[user_id]
        self.armed.pop((user_id, session_id), None)

    def _drop(self, user_id: int, pending: PendingReason) -> None:
        """Remove this pending tap only. A newer tap stays."""
        for key, target in list(self.prompts.items()):
            if key[0] == user_id and target is pending:
                del self.prompts[key]
        if self.pending.get(user_id) is pending:
            del self.pending[user_id]
