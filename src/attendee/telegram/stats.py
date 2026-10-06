"""Private admin /stats flow: series, sessions, the PRD §19 view, and the XLSX export.

Report rules stay in ReportService. The flow only reads, so its buttons keep no state:
st:<action>:<id>. Each tap checks the private chat and the admin role again (decision T74).
"""

import asyncio
import logging
import re

from sqlalchemy.exc import SQLAlchemyError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from attendee.application.authorization import AuthorizationService
from attendee.application.errors import AccessDenied, ApplicationError
from attendee.application.identity import IdentityService
from attendee.application.reports import ReportService, SessionReport
from attendee.domain.identity import MembershipRole
from attendee.domain.reports import session_heading
from attendee.domain.responses import ResponseStatus
from attendee.reporting.workbook import build_workbook, filename
from attendee.telegram import messages

CALLBACK_PATTERN = r"^st:"
PAGE_SIZE = 10


def callback(action: str, value: int) -> str:
    return f"st:{action}:{value}"


def parse_callback(data: str | None) -> tuple[str, int] | None:
    """p: series page, r: series, x: export, s: session, n/a/w: no response, responses, reasons."""
    match = re.fullmatch(r"st:([prxsnaw]):([0-9]{1,19})", data or "")
    return None if match is None else (match[1], int(match[2]))


def _keyboard(rows: list[tuple[str, str, int]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=callback(action, value))]
            for label, action, value in rows
        ]
    )


def _title(report: SessionReport) -> str:
    return session_heading(report.session_date, report.label)


def session_text(report: SessionReport) -> str:
    required = len(report.members)
    counts = "\n".join(
        messages.STATS_COUNT.format(status=status.label, count=report.count(status))
        for status in ResponseStatus
    )
    return messages.STATS_SESSION.format(
        series=report.series_name,
        session=_title(report),
        status=report.status,
        responded=report.responded,
        required=required,
        missing=required - report.responded,
        counts=counts,
    )


def no_response_text(report: SessionReport) -> str:
    names = [
        messages.STATS_MEMBER.format(name=member.name)
        for member in report.members
        if member.status is None
    ]
    body = "\n".join(names) or messages.STATS_EVERYONE_RESPONDED
    return f"{messages.STATS_NO_RESPONSE_TITLE.format(session=_title(report))}\n\n{body}"


def responses_text(report: SessionReport) -> str:
    groups: list[str] = []
    for status in ResponseStatus:
        names = [member.name for member in report.members if member.status is status]
        if names:
            lines = [messages.STATS_STATUS_GROUP.format(status=status.label, count=len(names))]
            lines.extend(messages.STATS_MEMBER.format(name=name) for name in names)
            groups.append("\n".join(lines))
    body = "\n\n".join(groups) or messages.STATS_NO_RESPONSES
    return f"{messages.STATS_RESPONSES_TITLE.format(session=_title(report))}\n\n{body}"


def reasons_text(report: SessionReport) -> str:
    lines = [
        messages.STATS_REASON.format(
            name=member.name, status=member.status.label, reason=member.reason
        )
        for member in report.members
        if member.status is not None and member.reason is not None
    ]
    body = "\n".join(lines) or messages.STATS_NO_REASONS
    return f"{messages.STATS_REASONS_TITLE.format(session=_title(report))}\n\n{body}"


class StatsHandlers:
    def __init__(
        self,
        organization_id: int,
        identity: IdentityService,
        authorization: AuthorizationService,
        reports: ReportService,
    ) -> None:
        self.organization_id = organization_id
        self.identity = identity
        self.authorization = authorization
        self.reports = reports

    async def _actor(self, user_id: int) -> int:
        person = await self.identity.find_by_telegram_user_id(user_id)
        if person is None:
            raise AccessDenied(messages.STATS_DENIED)
        await self.authorization.require_role(self.organization_id, person.id, MembershipRole.ADMIN)
        return person.id

    async def _reply(
        self, update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None
    ) -> None:
        message = update.effective_message
        if message is None:
            return
        chunks = messages.split_message(text)
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            await message.reply_text(chunk, reply_markup=keyboard if last else None)

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        chat, user = update.effective_chat, update.effective_user
        if chat is None or user is None or chat.type != "private":
            return
        await self._run(update, user.id, "p", 0)

    async def button(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        chat, user = update.effective_chat, update.effective_user
        parsed = parse_callback(query.data)
        if parsed is None or chat is None or user is None or chat.type != "private":
            await query.answer(messages.STATS_EXPIRED, show_alert=True)
            return
        await query.answer()
        await self._run(update, user.id, *parsed)

    async def _run(self, update: Update, user_id: int, action: str, value: int) -> None:
        try:
            actor = await self._actor(user_id)
            if action == "p":
                await self._series(update, actor, value)
            elif action == "r":
                await self._sessions(update, actor, value)
            elif action == "x":
                await self._export(update, actor, value)
            else:
                await self._session(update, actor, action, value)
        except AccessDenied:
            await self._reply(update, messages.STATS_DENIED)
        except ApplicationError as exc:
            await self._reply(update, str(exc))
        except SQLAlchemyError:
            logging.getLogger(__name__).error("Report database operation failed")
            await self._reply(update, messages.STATS_DB_FAILED)

    async def _series(self, update: Update, actor: int, page: int) -> None:
        found = await self.reports.list_series(
            self.organization_id, actor, page * PAGE_SIZE, PAGE_SIZE + 1
        )
        if not found and page == 0:
            await self._reply(update, messages.STATS_NO_SERIES)
            return
        rows = [(series.name, "r", series.id) for series in found[:PAGE_SIZE]]
        if page:
            rows.append((messages.PREVIOUS, "p", page - 1))
        if len(found) > PAGE_SIZE:
            rows.append((messages.NEXT, "p", page + 1))
        await self._reply(update, messages.STATS_SELECT_SERIES, _keyboard(rows))

    async def _sessions(self, update: Update, actor: int, series_id: int) -> None:
        series, sessions = await self.reports.list_sessions(self.organization_id, actor, series_id)
        rows = [
            (
                messages.STATS_SESSION_BUTTON.format(
                    session=session_heading(session.session_date, session.label),
                    status=session.status,
                ),
                "s",
                session.id,
            )
            for session in sessions
        ]
        rows.append((messages.STATS_EXPORT, "x", series_id))
        text = messages.STATS_SERIES if sessions else messages.STATS_SERIES_NO_SESSIONS
        await self._reply(update, text.format(series=series), _keyboard(rows))

    async def _session(self, update: Update, actor: int, action: str, session_id: int) -> None:
        report = await self.reports.session_report(self.organization_id, actor, session_id)
        if action == "n":
            await self._reply(update, no_response_text(report))
        elif action == "a":
            await self._reply(update, responses_text(report))
        elif action == "w":
            await self._reply(update, reasons_text(report))
        else:
            keyboard = _keyboard(
                [
                    (messages.STATS_VIEW_NO_RESPONSE, "n", session_id),
                    (messages.STATS_VIEW_RESPONSES, "a", session_id),
                    (messages.STATS_VIEW_REASONS, "w", session_id),
                ]
            )
            await self._reply(update, session_text(report), keyboard)

    async def _export(self, update: Update, actor: int, series_id: int) -> None:
        report = await self.reports.series_report(self.organization_id, actor, series_id)
        message = update.effective_message
        assert message is not None
        try:
            data = await asyncio.to_thread(build_workbook, report)
        except Exception as exc:  # Log the type only: an error text could hold member data.
            logging.getLogger(__name__).error("Workbook export failed: %s", type(exc).__name__)
            await self._reply(update, messages.STATS_EXPORT_FAILED)
            return
        await message.reply_document(
            document=data,
            filename=filename(report.series_name),
            caption=messages.STATS_EXPORT_CAPTION.format(series=report.series_name),
        )
