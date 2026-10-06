"""Admin namelist upload in a private chat: document, preview, then Apply or Cancel.

The bot downloads the file into memory and never writes it to disk (decision T36).
A preview waits in memory until Apply or Cancel; a restart cancels it (decision T37).
"""

import asyncio
import secrets
from dataclasses import dataclass
from pathlib import PurePath

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from attendee.application.authorization import AuthorizationService
from attendee.application.errors import AccessDenied, ImportConflict, ImportRejected
from attendee.application.identity import IdentityService
from attendee.application.import_files import MAX_FILE_BYTES, SUFFIXES, parse_file
from attendee.application.imports import ImportPreview, ImportService
from attendee.application.matching import AccountMatchingService
from attendee.domain.identity import MembershipRole
from attendee.domain.imports import ImportFileError
from attendee.reporting.imports import format_preview
from attendee.telegram import messages

CALLBACK_PATTERN = r"^i:"


@dataclass(frozen=True)
class PendingImport:
    admin_user_id: int
    preview: ImportPreview


class PendingImports:
    """One pending preview per admin, keyed by a random token. Memory only."""

    def __init__(self) -> None:
        self._by_token: dict[str, PendingImport] = {}
        self._token_by_admin: dict[int, str] = {}

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


class UploadHandlers:
    def __init__(
        self,
        organization_id: int,
        identity: IdentityService,
        authorization: AuthorizationService,
        imports: ImportService,
        matching: AccountMatchingService,
        pending: PendingImports | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.identity = identity
        self.authorization = authorization
        self.imports = imports
        self.matching = matching
        self.pending = pending or PendingImports()

    async def _is_admin(self, telegram_user_id: int) -> bool:
        person = await self.identity.find_by_telegram_user_id(telegram_user_id)
        if person is None:
            return False
        try:
            await self.authorization.require_role(
                self.organization_id, person.id, MembershipRole.ADMIN
            )
        except AccessDenied:
            return False
        return True

    async def document(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or message.document is None:
            return
        if not await self._is_admin(user.id):
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
        preview = await self.imports.preview(self.organization_id, parsed)
        unresolved = await self.matching.list_unresolved(self.organization_id)
        unresolved_line = messages.PREVIEW_UNRESOLVED.format(count=len(unresolved))
        text = f"{format_preview(preview)}\n{unresolved_line}"
        if preview.rejected:
            self.pending.discard(user.id)
            text = f"{text}\n\n{messages.PREVIEW_REJECTED}"
            keyboard = None
        else:
            token = self.pending.put(user.id, preview)
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
            await message.reply_text(chunk)
        await message.reply_text(chunks[-1], reply_markup=keyboard)

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
        if not await self._is_admin(user.id):
            await context.bot.send_message(user.id, messages.UPLOAD_DENIED)
            return
        try:
            result = await self.imports.apply(preview)
        except ImportConflict:
            text = messages.APPLY_CONFLICT
        except ImportRejected:
            text = messages.APPLY_REJECTED
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
