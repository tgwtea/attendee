"""Member responses: a group tap, then a reason in the private chat for non-Coming statuses.

A tap that changes a saved status asks for a second tap first (decision T68).

A response takes up to three updates: the tap, "/start reason", and the reason text.
The private prompt links the reason reply to its original pending tap (decision T78).
The state lives in process memory, so a restart loses it and the member taps again.
"""

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from telegram import ForceReply, Message, Update
from telegram.ext import ContextTypes, filters

from attendee.application.responses import (
    NotLinked,
    NotOnRoster,
    ResponseService,
    ResponseTarget,
    SessionNotOpen,
)
from attendee.domain.responses import ReasonMissing, ReasonTooLong, ResponseStatus, parse_vote
from attendee.telegram import messages

CALLBACK_PATTERN = r"^v:"
START_PAYLOAD = "reason"
START_PATTERN = rf"^/start {START_PAYLOAD}$"


@dataclass(frozen=True)
class PendingReason:
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


def _session_name(target: ResponseTarget) -> str:
    day = f"{target.session_date.day} {target.session_date:%B %Y}"
    if target.label:
        return f"{target.series_name} ({target.label}) on {day}"
    return f"{target.series_name} on {day}"


class ResponseHandlers:
    def __init__(
        self,
        organization_id: int,
        responses: ResponseService,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.organization_id = organization_id
        self.responses = responses
        self.clock = clock
        self.pending: dict[int, PendingReason] = {}
        self.prompts: dict[tuple[int, int], PendingReason] = {}
        self.has_pending = HasPendingReason(self.prompts)
        self.callbacks: OrderedDict[str, None] = OrderedDict()
        # Memory only, like `pending`. A restart forgets an armed change.
        self.armed: dict[int, ArmedChange] = {}

    def _needs_confirmation(
        self,
        user_id: int,
        session_id: int,
        status: ResponseStatus,
        current: ResponseStatus | None,
        callback_id: str,
    ) -> bool:
        """Arm on the first tap that changes a saved status. A second tap in time disarms."""
        armed = self.armed.pop(user_id, None)
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
        self.armed[user_id] = ArmedChange(session_id, status, now + CONFIRM_SECONDS, callback_id)
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
        try:
            target = await self.responses.check(self.organization_id, user_id, session_id)
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
                # A Coming tap replaces any pending non-Coming tap.
                await self.responses.record(self.organization_id, user_id, session_id, status)
                self.pending.pop(user_id, None)
                self._clear_prompts(user_id)
                await query.answer(messages.RECORDED.format(status=status.label), show_alert=True)
                return
        except (NotLinked, NotOnRoster, SessionNotOpen) as exc:
            await query.answer(_denied_text(exc), show_alert=True)
            return
        except SQLAlchemyError:
            logging.getLogger(__name__).error("Response database operation failed")
            await query.answer(messages.TAP_NOT_SAVED, show_alert=True)
            return
        # A new tap replaces the pending one. Nothing is in the database yet.
        self.pending[user_id] = PendingReason(session_id, status)
        await query.answer(url=f"https://t.me/{context.bot.username}?start={START_PAYLOAD}")

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
            target = await self.responses.check(self.organization_id, user.id, pending.session_id)
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
                self.organization_id, user.id, pending.session_id, pending.status, message.text
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
        self._drop(user.id, pending)
        await message.reply_text(
            messages.RECORDED_REASON.format(status=result.status.label, reason=result.reason)
        )

    async def _prompt(
        self, message: Message, user_id: int, pending: PendingReason, text: str
    ) -> None:
        prompt = await message.reply_text(text, reply_markup=ForceReply(selective=True))
        self.prompts[user_id, prompt.message_id] = pending

    def _clear_prompts(self, user_id: int) -> None:
        for key in list(self.prompts):
            if key[0] == user_id:
                del self.prompts[key]

    def _drop(self, user_id: int, pending: PendingReason) -> None:
        """Remove this pending tap only. A newer tap stays."""
        for key, target in list(self.prompts.items()):
            if key[0] == user_id and target is pending:
                del self.prompts[key]
        if self.pending.get(user_id) is pending:
            del self.pending[user_id]
