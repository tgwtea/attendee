"""Attendance names, explicit local dates, and read-time session status."""

import re
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from attendee import copy


class SessionStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


def clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value or len(value) > 200:
        raise ValueError(copy.NAME_LENGTH)
    return value


def normalize_series_name(value: str) -> str:
    return clean_name(value).casefold()


def parse_date(value: str) -> date:
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value, re.ASCII):
            return date.fromisoformat(value)
        match = re.fullmatch(r"(\d{1,2}) ([A-Za-z]{3}) (\d{4})", value, re.ASCII)
        if match:
            months: tuple[str, ...] = (
                "jan",
                "feb",
                "mar",
                "apr",
                "may",
                "jun",
                "jul",
                "aug",
                "sep",
                "oct",
                "nov",
                "dec",
            )
            return date(int(match[3]), months.index(match[2].lower()) + 1, int(match[1]))
    except ValueError:
        pass
    raise ValueError(copy.DATE_FORMAT)


def parse_deadline(value: str, timezone: str) -> datetime:
    match = re.fullmatch(
        r"(.+?)(?:,)?\s+(\d{1,2}):(\d{2})(?:\s+([AaPp][Mm]))?", value.strip(), re.ASCII
    )
    if not match:
        raise ValueError(copy.DEADLINE_FORMAT)
    day = parse_date(match[1])
    hour, minute = int(match[2]), int(match[3])
    if match[4]:
        if not 1 <= hour <= 12:
            raise ValueError(copy.DEADLINE_HOUR)
        hour = hour % 12 + (12 if match[4].lower() == "pm" else 0)
    try:
        local = datetime(day.year, day.month, day.day, hour, minute)
    except ValueError as exc:
        raise ValueError(copy.DEADLINE_TIME) from exc
    zone = ZoneInfo(timezone)
    candidates = {
        local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        for fold in (0, 1)
        if local.replace(tzinfo=zone, fold=fold)
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == local
    }
    if len(candidates) != 1:
        raise ValueError(copy.DEADLINE_AMBIGUOUS)
    return candidates.pop()


def check_deadline(deadline: datetime, session_date: date, timezone: str) -> None:
    """The deadline may fall at any time on the session date, but not later (decision T70)."""
    if deadline.astimezone(ZoneInfo(timezone)).date() > session_date:
        raise ValueError(copy.DEADLINE_AFTER_SESSION.format(session_date=session_date.isoformat()))


# A session is archived this long after its deadline (decision T69).
ARCHIVE_AFTER = timedelta(days=7)


def archive_cutoff(now: datetime) -> datetime:
    """A session whose deadline is earlier than this time is archived."""
    return now - ARCHIVE_AFTER


def is_archived(deadline: datetime, now: datetime) -> bool:
    """Archived is derived at read time, like Deadline Passed. Nothing is stored or deleted."""
    return deadline < archive_cutoff(now)


def display_status(status: SessionStatus, deadline: datetime, now: datetime) -> str:
    if is_archived(deadline, now):
        return "Archived"
    if status is SessionStatus.OPEN and now > deadline:
        return "Deadline Passed"
    return status.value.title()
