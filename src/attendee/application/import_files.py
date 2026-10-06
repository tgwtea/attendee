"""Read an uploaded namelist from memory. The caller never stores the file."""

import csv
import io
import zipfile
from datetime import date, datetime, time
from pathlib import PurePath

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from attendee import copy
from attendee.domain.imports import ImportFileError, ParsedFile, RawTable, read_table

MAX_FILE_BYTES = 5 * 1024 * 1024
SUFFIXES = (".csv", ".xlsx")


def parse_file(filename: str, data: bytes) -> ParsedFile:
    """Choose the parser from the file name suffix."""
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".csv":
        return parse_csv(data)
    if suffix == ".xlsx":
        return parse_xlsx(data)
    raise ImportFileError(copy.FILE_WRONG_TYPE.format(suffixes=" or ".join(SUFFIXES)))


def parse_csv(data: bytes) -> ParsedFile:
    _check_size(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFileError(copy.FILE_NOT_UTF8) from exc
    try:
        lines = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise ImportFileError(copy.FILE_BAD_CSV.format(detail=exc)) from exc
    return read_table(_table(lines))


def parse_xlsx(data: bytes) -> ParsedFile:
    """Read the first worksheet. Formulas give their last saved value."""
    _check_size(data)
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ImportFileError(copy.FILE_BAD_XLSX) from exc
    try:
        sheet = workbook.worksheets[0]
        lines = [[_cell_text(value) for value in row] for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()
    return read_table(_table(lines))


def _check_size(data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError(copy.FILE_TOO_LARGE.format(megabytes=MAX_FILE_BYTES // (1024 * 1024)))


def _table(lines: list[list[str]]) -> RawTable:
    if not lines:
        raise ImportFileError(copy.FILE_EMPTY)
    return RawTable(tuple(lines[0]), tuple(tuple(line) for line in lines[1:]))


def _cell_text(value: object) -> str:
    """Give XLSX cells the text a CSV export would hold. A whole float loses its ".0"."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).upper()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    return str(value)
