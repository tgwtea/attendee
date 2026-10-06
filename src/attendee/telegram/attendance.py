"""Private admin attendance conversation. All attendance rules stay in services."""

import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from attendee.application.attendance import (
    AttendanceService,
    DuplicateSeries,
    RosterChanged,
    SessionInput,
    SessionPreview,
)
from attendee.application.errors import AccessDenied, ApplicationError
from attendee.application.groups import GroupAccess
from attendee.domain.attendance import check_deadline, clean_name, parse_date, parse_deadline
from attendee.telegram import messages

CALLBACK_PATTERN = r"^a:"


class Step(IntEnum):
    SERIES = 0
    NAME = 1
    DATE = 2
    LABEL = 3
    DEADLINE = 4
    CONFIRM = 5
    GROUP = 6


@dataclass
class PendingSession:
    creation_key: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    step: Step = Step.SERIES
    token: str | None = None
    message_id: int | None = None
    group_id: int = 0
    series_id: int | None = None
    new_series_name: str | None = None
    session_date: date | None = None
    label: str | None = None
    preview: SessionPreview | None = None
    offered_series: set[int] = field(default_factory=set[int])
    offered_pages: set[int] = field(default_factory=set[int])
    offered_groups: set[int] = field(default_factory=set[int])


def callback(token: str, action: str, value: int | None = None) -> str:
    data = f"a:{token}:{action}" + ("" if value is None else f":{value}")
    if len(data.encode()) > 64:
        raise ValueError("Callback exceeds Telegram's limit.")
    return data


def parse_callback(data: str | None) -> tuple[str, str, int | None] | None:
    match = re.fullmatch(r"a:([A-Za-z0-9_-]{16}):([gsnplyc])(?::([0-9]{1,19}))?", data or "")
    if match is None:
        return None
    action = match[2]
    value = None if match[3] is None else int(match[3])
    if (action in ("g", "s", "p")) != (value is not None):
        return None
    return match[1], action, value


class AttendanceHandlers:
    def __init__(self, access: GroupAccess, attendance: AttendanceService, timezone: str) -> None:
        self.access = access
        self.attendance = attendance
        self.timezone = timezone
        self.pending: dict[tuple[int, int], PendingSession] = {}

    def conversation(self) -> ConversationHandler[ContextTypes.DEFAULT_TYPE]:
        return ConversationHandler(
            entry_points=[
                CommandHandler("attendance", self.start, filters=filters.ChatType.PRIVATE)
            ],
            states={
                int(step): [
                    CallbackQueryHandler(self.button, pattern=CALLBACK_PATTERN),
                    MessageHandler(
                        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, self.text
                    ),
                ]
                for step in Step
            },
            fallbacks=[CommandHandler("cancel", self.cancel, filters=filters.ChatType.PRIVATE)],
            allow_reentry=True,
            per_chat=True,
            per_user=True,
            per_message=False,
            persistent=False,
        )

    def _key(self, update: Update) -> tuple[int, int] | None:
        chat, user = update.effective_chat, update.effective_user
        if chat is None or user is None or chat.type != "private":
            return None
        return chat.id, user.id

    async def _actor(self, pending: PendingSession, user_id: int) -> int:
        """Ask Telegram again at each step. A demoted admin stops at once (decision T83)."""
        await self.access.require_admin(pending.group_id, user_id)
        return user_id

    async def _prompt(
        self,
        update: Update,
        pending: PendingSession,
        step: Step,
        text: str,
        buttons: list[tuple[str, str, int | None]] | None = None,
    ) -> int:
        message = update.effective_message
        assert message is not None
        pending.step = step
        pending.token = secrets.token_urlsafe(12)
        choices = list(buttons or []) + [(messages.CANCEL, "c", None)]
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(label, callback_data=callback(pending.token, action, value))]
                for label, action, value in choices
            ]
        )
        sent = await message.reply_text(text, reply_markup=keyboard)
        pending.message_id = sent.message_id
        return int(step)

    async def _series(
        self, update: Update, pending: PendingSession, actor: int, page: int = 0, notice: str = ""
    ) -> int:
        series = await self.attendance.list_series(pending.group_id, actor, page * 10, 11)
        pending.offered_series = {row.id for row in series[:10]}
        buttons: list[tuple[str, str, int | None]] = [
            (row.name, "s", row.id) for row in series[:10]
        ]
        pending.offered_pages = set()
        if page:
            buttons.append((messages.PREVIOUS, "p", page - 1))
            pending.offered_pages.add(page - 1)
        if len(series) > 10:
            buttons.append((messages.NEXT, "p", page + 1))
            pending.offered_pages.add(page + 1)
        buttons.append((messages.SESSION_NEW_SERIES_BUTTON, "n", None))
        return await self._prompt(
            update, pending, Step.SERIES, notice + messages.SESSION_SELECT_SERIES, buttons
        )

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> int:
        key = self._key(update)
        if key is None or update.effective_message is None:
            return ConversationHandler.END
        self.pending.pop(key, None)
        try:
            groups = await self.access.admin_groups(key[1])
            if not groups:
                raise AccessDenied(messages.SESSION_DENIED)
            pending = PendingSession()
            self.pending[key] = pending
            if len(groups) > 1:
                pending.offered_groups = {group.id for group in groups}
                buttons: list[tuple[str, str, int | None]] = [
                    (group.title, "g", group.id) for group in groups
                ]
                return await self._prompt(
                    update, pending, Step.GROUP, messages.SELECT_GROUP, buttons
                )
            pending.group_id = groups[0].id
            return await self._series(update, pending, await self._actor(pending, key[1]))
        except AccessDenied:
            self.pending.pop(key, None)
            await update.effective_message.reply_text(messages.SESSION_DENIED)
            return ConversationHandler.END
        except ApplicationError as exc:
            self.pending.pop(key, None)
            await update.effective_message.reply_text(str(exc))
            return ConversationHandler.END
        except SQLAlchemyError:
            return await self._database_failure(update, key)

    async def _database_failure(self, update: Update, key: tuple[int, int]) -> int:
        self.pending.pop(key, None)
        logging.getLogger(__name__).error("Attendance database operation failed")
        if update.effective_message is not None:
            await update.effective_message.reply_text(messages.SESSION_FAILED)
        return ConversationHandler.END

    async def cancel(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> int:
        key = self._key(update)
        if key is not None:
            self.pending.pop(key, None)
            if update.effective_message is not None:
                await update.effective_message.reply_text(messages.SESSION_CANCELLED)
        return ConversationHandler.END

    async def expired(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if update.callback_query is not None:
            await update.callback_query.answer(messages.SESSION_BUTTON_EXPIRED, show_alert=True)

    async def text(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> int | None:
        key = self._key(update)
        message = update.effective_message
        if key is None or message is None or message.text is None:
            return None
        pending = self.pending.get(key)
        if pending is None:
            return ConversationHandler.END
        actor: int | None = None
        try:
            if pending.step is Step.GROUP:
                await message.reply_text(messages.SESSION_USE_BUTTON)
                return None
            actor = await self._actor(pending, key[1])
            value = message.text
            if pending.step is Step.NAME:
                pending.new_series_name = clean_name(value)
                return await self._prompt(update, pending, Step.DATE, messages.SESSION_ASK_DATE)
            if pending.step is Step.DATE:
                pending.session_date = parse_date(value)
                return await self._prompt(
                    update,
                    pending,
                    Step.LABEL,
                    messages.SESSION_ASK_LABEL,
                    [(messages.SKIP, "l", None)],
                )
            if pending.step is Step.LABEL:
                pending.label = clean_name(value)
                return await self._deadline_prompt(update, pending)
            if pending.step is Step.DEADLINE:
                deadline = parse_deadline(value, self.timezone)
                assert pending.session_date is not None
                check_deadline(deadline, pending.session_date, self.timezone)
                request = SessionInput(
                    series_id=pending.series_id,
                    new_series_name=pending.new_series_name,
                    session_date=pending.session_date,
                    label=pending.label,
                    deadline=deadline,
                    creation_key=pending.creation_key,
                )
                return await self._summary(update, pending, actor, request)
            await message.reply_text(messages.SESSION_USE_BUTTON)
        except AccessDenied:
            self.pending.pop(key, None)
            await message.reply_text(messages.SESSION_DENIED)
            return ConversationHandler.END
        except DuplicateSeries as exc:
            assert actor is not None
            pending.series_id = None
            pending.new_series_name = None
            return await self._series(update, pending, actor, notice=f"{exc}\n")
        except (ValueError, ApplicationError) as exc:
            await message.reply_text(str(exc))
        except SQLAlchemyError:
            return await self._database_failure(update, key)
        return None

    async def _deadline_prompt(self, update: Update, pending: PendingSession) -> int:
        return await self._prompt(
            update,
            pending,
            Step.DEADLINE,
            messages.SESSION_ASK_DEADLINE.format(timezone=self.timezone),
        )

    async def _summary(
        self,
        update: Update,
        pending: PendingSession,
        actor: int,
        request: SessionInput,
        notice: str = "",
    ) -> int:
        preview = await self.attendance.preview_session(pending.group_id, actor, request)
        pending.preview = preview
        local = request.deadline.astimezone(ZoneInfo(self.timezone))
        text = notice + messages.SESSION_SUMMARY.format(
            series=preview.series_name,
            date=request.session_date.isoformat(),
            label=request.label or request.session_date.isoformat(),
            deadline=f"{local:%Y-%m-%d %H:%M %z}",
            timezone=self.timezone,
            members=len(preview.person_ids),
        )
        return await self._prompt(
            update, pending, Step.CONFIRM, text, [(messages.CONFIRM, "y", None)]
        )

    async def button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
        query = update.callback_query
        if query is None:
            return None
        key = self._key(update)
        parsed = parse_callback(query.data)
        pending = None if key is None else self.pending.get(key)
        if (
            pending is None
            or parsed is None
            or pending.token != parsed[0]
            or query.message is None
            or query.message.message_id != pending.message_id
        ):
            await self.expired(update, context)
            return None
        _, action, value = parsed
        valid = (
            action == "c"
            or (pending.step is Step.GROUP and action == "g" and value in pending.offered_groups)
            or (
                pending.step is Step.SERIES
                and (
                    (action == "s" and value in pending.offered_series)
                    or (action == "p" and value in pending.offered_pages)
                    or action == "n"
                )
            )
            or (pending.step is Step.LABEL and action == "l")
            or (pending.step is Step.CONFIRM and action == "y")
        )
        if not valid:
            await self.expired(update, context)
            return None
        # Consume before the first await. Concurrent repeats cannot enter this action.
        pending.token = None
        await query.answer()
        assert key is not None
        actor: int | None = None
        try:
            if action == "c":
                return await self.cancel(update, context)
            if action == "g":
                assert value is not None
                pending.group_id = value
            actor = await self._actor(pending, key[1])
            if action == "g":
                return await self._series(update, pending, actor)
            if action == "p":
                assert value is not None
                return await self._series(update, pending, actor, value)
            if action == "n":
                pending.series_id = None
                return await self._prompt(
                    update, pending, Step.NAME, messages.SESSION_ASK_SERIES_NAME
                )
            if action == "s":
                pending.series_id = value
                pending.new_series_name = None
                return await self._prompt(update, pending, Step.DATE, messages.SESSION_ASK_DATE)
            if action == "l":
                pending.label = None
                return await self._deadline_prompt(update, pending)
            assert pending.preview is not None
            try:
                result = await self.attendance.create_session(
                    pending.group_id, actor, pending.preview
                )
            except RosterChanged:
                return await self._summary(
                    update,
                    pending,
                    actor,
                    pending.preview.request,
                    messages.SESSION_ROSTER_CHANGED + "\n",
                )
            self.pending.pop(key, None)
            assert update.effective_message is not None
            await update.effective_message.reply_text(
                messages.SESSION_SAVED.format(
                    id=result.id,
                    series=result.series_name,
                    date=result.session_date.isoformat(),
                    label=result.label or result.session_date.isoformat(),
                    members=len(result.person_ids),
                )
            )
            return ConversationHandler.END
        except DuplicateSeries as exc:
            assert actor is not None
            pending.series_id = None
            pending.new_series_name = None
            return await self._series(update, pending, actor, notice=f"{exc}\n")
        except AccessDenied:
            text = messages.SESSION_DENIED
        except ApplicationError as exc:
            text = str(exc)
        except SQLAlchemyError:
            return await self._database_failure(update, key)
        self.pending.pop(key, None)
        if update.effective_message is not None:
            await update.effective_message.reply_text(text)
        return ConversationHandler.END
