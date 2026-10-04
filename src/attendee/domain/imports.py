"""Namelist rows and file-only validation, without transport or storage dependencies."""

import re
from collections import defaultdict
from dataclasses import dataclass, replace

from attendee.domain.identity import normalize_handle

NAME = "Name"
TELEGRAM_HANDLE = "Telegram Handle"
TELEGRAM_ID = "Telegram ID"
REQUIRED_COLUMNS = (NAME, TELEGRAM_HANDLE)
KNOWN_COLUMNS = (NAME, TELEGRAM_HANDLE, TELEGRAM_ID)
NAME_MAX_LENGTH = 200
_TELEGRAM_ID_MAX = 2**63 - 1
_SPACES = re.compile(r"\s+")


class ImportFileError(ValueError):
    """The whole file is unusable, for example a required column is missing."""


@dataclass(frozen=True)
class RawTable:
    """Cell text from a CSV or XLSX sheet. The first row is the header."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ImportRow:
    """One namelist row. `line` is the spreadsheet row number; the header is line 1."""

    line: int
    name: str | None
    telegram_handle: str | None
    telegram_user_id: int | None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedFile:
    rows: tuple[ImportRow, ...]
    ignored_columns: tuple[str, ...]


def _header_key(value: str) -> str:
    return _SPACES.sub(" ", value.strip()).casefold()


def read_table(table: RawTable) -> ParsedFile:
    """Map the header, read every row, and validate what the file alone can show."""
    known = {_header_key(column): column for column in KNOWN_COLUMNS}
    positions: dict[str, int] = {}
    ignored: list[str] = []
    for position, cell in enumerate(table.header):
        column = known.get(_header_key(cell))
        if column is None:
            if cell.strip():
                ignored.append(cell.strip())
        elif column in positions:
            raise ImportFileError(f"The column {column!r} appears more than once")
        else:
            positions[column] = position
    missing = [column for column in REQUIRED_COLUMNS if column not in positions]
    if missing:
        raise ImportFileError(f"Missing required columns: {', '.join(missing)}")

    rows: list[ImportRow] = []
    for line, cells in enumerate(table.rows, start=2):
        if not any(cell.strip() for cell in cells):
            continue
        name, handle, telegram_id = (
            _cell(cells, positions.get(column)) for column in KNOWN_COLUMNS
        )
        rows.append(_read_row(line, name, handle, telegram_id))
    if not rows:
        raise ImportFileError("The file has no member rows")
    return ParsedFile(_reject_duplicates(rows), tuple(ignored))


def _cell(cells: tuple[str, ...], position: int | None) -> str:
    return "" if position is None or position >= len(cells) else cells[position].strip()


def _read_row(line: int, name: str, handle: str, telegram_id: str) -> ImportRow:
    errors: list[str] = []
    if not name:
        errors.append("Missing name")
    elif len(name) > NAME_MAX_LENGTH:
        errors.append(f"Name is longer than {NAME_MAX_LENGTH} characters")
    canonical: str | None = None
    if not handle:
        errors.append("Missing Telegram handle")
    else:
        try:
            canonical = normalize_handle(handle)
        except ValueError as exc:
            errors.append(f"Invalid Telegram handle {handle!r}: {exc}")
    telegram_user_id: int | None = None
    if telegram_id:
        if (
            telegram_id.isascii()
            and telegram_id.isdigit()
            and 0 < int(telegram_id) <= _TELEGRAM_ID_MAX
        ):
            telegram_user_id = int(telegram_id)
        else:
            errors.append(f"Invalid Telegram ID {telegram_id!r}")
    return ImportRow(line, name or None, canonical, telegram_user_id, tuple(errors))


def _reject_duplicates(rows: list[ImportRow]) -> tuple[ImportRow, ...]:
    """Reject every row that shares a handle or a Telegram ID with another row in the file."""
    handles: defaultdict[str, list[int]] = defaultdict(list)
    telegram_ids: defaultdict[int, list[int]] = defaultdict(list)
    for row in rows:
        if row.telegram_handle is not None:
            handles[row.telegram_handle].append(row.line)
        if row.telegram_user_id is not None:
            telegram_ids[row.telegram_user_id].append(row.line)
    result: list[ImportRow] = []
    for row in rows:
        errors = list(row.errors)
        for label, lines in (
            ("handle", handles.get(row.telegram_handle or "", [])),
            ("Telegram ID", telegram_ids.get(row.telegram_user_id or 0, [])),
        ):
            if len(lines) > 1:
                rows_text = ", ".join(str(line) for line in lines)
                errors.append(f"Duplicate {label} in file (rows {rows_text})")
        result.append(replace(row, errors=tuple(errors)))
    return tuple(result)
