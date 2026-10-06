"""Member responses: a group tap, then a reason in the private chat for non-Coming statuses.

A tap that changes a saved status asks for a second tap first (decision T68).

A response takes up to three updates: the tap, "/start reason", and the reason text.
Only the pending tap links them. It lives in process memory, keyed by Telegram user ID
(decision T64), so a restart loses it and the member taps again.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from telegram import Message, Update
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


class HasPendingReason(filters.MessageFilter):
    """Match a message only from a user with a pending tap. Other text reaches /attendance."""

    def __init__(self, pending: dict[int, PendingReason]) -> None:
        super().__init__(name="HasPendingReason")
        self.pending = pending

    def filter(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in self.pending


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
        self.has_pending = HasPendingReason(self.pending)
        # Memory only, like `pending`. A restart forgets an armed change.
        self.armed: dict[int, ArmedChange] = {}

    def _needs_confirmation(
        self, user_id: int, session_id: int, status: ResponseStatus, current: ResponseStatus | None
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
            and now < armed.expires_at
        ):
            return False
        self.armed[user_id] = ArmedChange(session_id, status, now + CONFIRM_SECONDS)
        return True

    async def tap(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """A poll button in the group. Every answer is visible to the tapping member only."""
        query = update.callback_query
        if query is None:
            return
        vote = parse_vote(query.data)
        if vote is None:
            await query.answer(messages.VOTE_INVALID, show_alert=True)
            return
        session_id, status = vote
        user_id = query.from_user.id
        try:
            target = await self.responses.check(self.organization_id, user_id, session_id)
            if self._needs_confirmation(user_id, session_id, status, target.current_status):
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
                self.pending.pop(user_id, None)
                await self.responses.record(self.organization_id, user_id, session_id, status)
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
        await message.reply_text(
            messages.REASON_PROMPT.format(
                status=pending.status.label, session=_session_name(target)
            )
        )

    async def reason(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Private text from a user with a pending tap. Never log the reason text."""
        message, user = update.effective_message, update.effective_user
        if message is None or user is None:
            return
        pending = self.pending.get(user.id)
        if pending is None:
            return
        try:
            result = await self.responses.record(
                self.organization_id, user.id, pending.session_id, pending.status, message.text
            )
        except ReasonMissing:
            await message.reply_text(messages.REASON_MISSING)
            return
        except ReasonTooLong:
            await message.reply_text(messages.REASON_TOO_LONG)
            return
        except (NotLinked, NotOnRoster, SessionNotOpen) as exc:
            self._drop(user.id, pending)
            await message.reply_text(_denied_text(exc))
            return
        except SQLAlchemyError:
            # Keep the pending tap. PRD §36: confirm only after the save.
            logging.getLogger(__name__).error("Response database operation failed")
            await message.reply_text(messages.REASON_NOT_SAVED)
            return
        self._drop(user.id, pending)
        await message.reply_text(
            messages.RECORDED_REASON.format(status=result.status.label, reason=result.reason)
        )

    def _drop(self, user_id: int, pending: PendingReason) -> None:
        """Remove this pending tap only. A newer tap stays."""
        if self.pending.get(user_id) is pending:
            del self.pending[user_id]
