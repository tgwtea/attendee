"""Admin namelist upload in a private chat: document, group, preview, then Apply or Cancel.

The bot downloads the file into memory and never writes it to disk (decision T36).
A preview waits in memory until Apply or Cancel; a restart cancels it (decision T37).
An admin of several groups picks the group first; the parsed file waits in memory (T85).
"""

import asyncio
import secrets
from dataclasses import dataclass
from pathlib import PurePath
from typing import Protocol

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from attendee.application.errors import (
    AccessDenied,
    ApplicationError,
    ImportConflict,
    ImportRejected,
)
from attendee.application.groups import GroupAccess
from attendee.application.import_files import MAX_FILE_BYTES, SUFFIXES, parse_file
from attendee.application.imports import ImportPreview, ImportService
from attendee.application.matching import AccountMatchingService
from attendee.domain.imports import ImportFileError, ParsedFile
from attendee.reporting.imports import format_preview
from attendee.telegram import messages

CALLBACK_PATTERN = r"^i:[ac]:"
GROUP_PATTERN = r"^i:g:"


class ReplyText(Protocol):
    async def __call__(
        self, text: str, *, reply_markup: InlineKeyboardMarkup | None = None
    ) -> object: ...


@dataclass(frozen=True)
class PendingImport:
    admin_user_id: int
    preview: ImportPreview


class PendingImports:
    """One pending preview and one pending group choice per admin, by random token. Memory only."""

    def __init__(self) -> None:
        self._by_token: dict[str, PendingImport] = {}
        self._token_by_admin: dict[int, str] = {}
        self._files: dict[int, tuple[str, ParsedFile, frozenset[int]]] = {}

    def put_file(self, admin_user_id: int, parsed: ParsedFile, group_ids: frozenset[int]) -> str:
        """Keep a parsed file until the admin picks one of the offered groups."""
        token = secrets.token_urlsafe(9)
        self._files[admin_user_id] = (token, parsed, group_ids)
        return token

    def take_file(self, token: str, admin_user_id: int, group_id: int) -> ParsedFile | None:
        """Remove and return the file for an offered group. A second call returns None."""
        pending = self._files.get(admin_user_id)
        if pending is None or pending[0] != token or group_id not in pending[2]:
            return None
        del self._files[admin_user_id]
        return pending[1]

    def put(self, admin_user_id: int, preview: ImportPreview) -> str:
        """Store the preview. It replaces an earlier preview of the same admin."""
        self.discard(admin_user_id)
        token = secrets.token_urlsafe(9)
        self._by_token[token] = PendingImport(admin_user_id, preview)
        self._token_by_admin[admin_user_id] = token
        return token

    def take(self, token: str, admin_user_id: int) -> ImportPreview | None:
        """Remove and return the preview. A second call for the same token returns None."""
        pending = self._by_token.get(token)
        if pending is None or pending.admin_user_id != admin_user_id:
            return None
        del self._by_token[token]
        del self._token_by_admin[admin_user_id]
        return pending.preview

    def discard(self, admin_user_id: int) -> None:
        token = self._token_by_admin.pop(admin_user_id, None)
        if token is not None:
            del self._by_token[token]


def import_callback(apply: bool, token: str) -> str:
    return f"i:{'a' if apply else 'c'}:{token}"


def parse_import_callback(data: str | None) -> tuple[bool, str] | None:
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != "i" or parts[1] not in ("a", "c") or not parts[2]:
        return None
    return parts[1] == "a", parts[2]


def group_callback(token: str, group_id: int) -> str:
    return f"i:g:{token}:{group_id}"


def parse_group_callback(data: str | None) -> tuple[str, int] | None:
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[:2] != ["i", "g"] or not parts[2]:
        return None
    if not (parts[3].isascii() and parts[3].isdigit()):
        return None
    return parts[2], int(parts[3])


class UploadHandlers:
    def __init__(
        self,
        access: GroupAccess,
        imports: ImportService,
        matching: AccountMatchingService,
        pending: PendingImports | None = None,
    ) -> None:
        self.access = access
        self.imports = imports
        self.matching = matching
        self.pending = pending or PendingImports()

    async def _is_admin(self, group_id: int, telegram_user_id: int) -> bool:
        """Ask Telegram. AdminCheckFailed reaches the caller."""
        try:
            await self.access.require_admin(group_id, telegram_user_id)
        except AccessDenied:
            return False
        return True

    async def document(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or message.document is None:
            return
        try:
            groups = await self.access.admin_groups(user.id)
        except ApplicationError as exc:
            await message.reply_text(str(exc))
            return
        if not groups:
            await message.reply_text(messages.UPLOAD_DENIED)
            return
        document = message.document
        filename = document.file_name or ""
        if PurePath(filename).suffix.lower() not in SUFFIXES:
            await message.reply_text(messages.UPLOAD_WRONG_TYPE)
            return
        if document.file_size is not None and document.file_size > MAX_FILE_BYTES:
            megabytes = MAX_FILE_BYTES // (1024 * 1024)
            await message.reply_text(messages.UPLOAD_TOO_LARGE.format(megabytes=megabytes))
            return
        telegram_file = await document.get_file()
        # Download into memory only. Never write the uploaded file to disk.
        data = bytes(await telegram_file.download_as_bytearray())
        try:
            parsed = await asyncio.to_thread(parse_file, filename, data)
        except ImportFileError as exc:
            await message.reply_text(messages.UPLOAD_UNREADABLE.format(error=exc))
            return
        if len(groups) > 1:
            token = self.pending.put_file(user.id, parsed, frozenset(g.id for g in groups))
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            group.title, callback_data=group_callback(token, group.id)
                        )
                    ]
                    for group in groups
                ]
            )
            await message.reply_text(messages.SELECT_GROUP, reply_markup=keyboard)
            return
        await self._preview(message.reply_text, user.id, groups[0].id, parsed)

    async def _preview(
        self, reply: ReplyText, user_id: int, group_id: int, parsed: ParsedFile
    ) -> None:
        preview = await self.imports.preview(group_id, parsed)
        unresolved = await self.matching.list_unresolved(group_id)
        unresolved_line = messages.PREVIEW_UNRESOLVED.format(count=len(unresolved))
        text = f"{format_preview(preview)}\n{unresolved_line}"
        if preview.rejected:
            self.pending.discard(user_id)
            text = f"{text}\n\n{messages.PREVIEW_REJECTED}"
            keyboard = None
        else:
            token = self.pending.put(user_id, preview)
            text = f"{text}\n\n{messages.PREVIEW_CONFIRM}"
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            messages.APPLY, callback_data=import_callback(True, token)
                        ),
                        InlineKeyboardButton(
                            messages.CANCEL, callback_data=import_callback(False, token)
                        ),
                    ]
                ]
            )
        chunks = messages.split_message(text)
        for chunk in chunks[:-1]:
            await reply(chunk)
        await reply(chunks[-1], reply_markup=keyboard)

    async def pick_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """i:g:<token>:<group_id>. The group ID is a claim: the token and admin check decide."""
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        await _remove_buttons(query)
        user = query.from_user
        parsed = parse_group_callback(query.data)
        file = None if parsed is None else self.pending.take_file(parsed[0], user.id, parsed[1])
        if parsed is None or file is None:
            await context.bot.send_message(user.id, messages.PREVIEW_EXPIRED)
            return

        async def reply(text: str, *, reply_markup: InlineKeyboardMarkup | None = None) -> object:
            return await context.bot.send_message(user.id, text, reply_markup=reply_markup)

        try:
            if not await self._is_admin(parsed[1], user.id):
                await reply(messages.UPLOAD_DENIED)
                return
        except ApplicationError as exc:
            await reply(str(exc))
            return
        await self._preview(reply, user.id, parsed[1], file)

    async def button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        await _remove_buttons(query)
        user = query.from_user
        parsed = parse_import_callback(query.data)
        # Take the preview before any await on the database, so a repeat finds nothing.
        preview = None if parsed is None else self.pending.take(parsed[1], user.id)
        if parsed is None or preview is None:
            await context.bot.send_message(user.id, messages.PREVIEW_EXPIRED)
            return
        if not parsed[0]:
            await context.bot.send_message(user.id, messages.CANCELLED)
            return
        try:
            if not await self._is_admin(preview.group_id, user.id):
                await context.bot.send_message(user.id, messages.UPLOAD_DENIED)
                return
            result = await self.imports.apply(preview)
        except ImportConflict:
            text = messages.APPLY_CONFLICT
        except ImportRejected:
            text = messages.APPLY_REJECTED
        except ApplicationError as exc:
            text = str(exc)
        else:
            text = messages.APPLIED.format(
                created=result.created, updated=result.updated, unchanged=result.unchanged
            )
        await context.bot.send_message(user.id, text)


async def _remove_buttons(query: CallbackQuery) -> None:
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise
