"""Attendance names, explicit local dates, and read-time session status."""

import re
from datetime import UTC, date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


class SessionStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


def clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value or len(value) > 200:
        raise ValueError("Use 1 to 200 characters.")
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
    raise ValueError("Use YYYY-MM-DD or 12 Oct 2026 with a valid date.")


def parse_deadline(value: str, timezone: str) -> datetime:
    match = re.fullmatch(
        r"(.+?)(?:,)?\s+(\d{1,2}):(\d{2})(?:\s+([AaPp][Mm]))?", value.strip(), re.ASCII
    )
    if not match:
        raise ValueError("Use a date followed by HH:MM or 8:00 PM.")
    day = parse_date(match[1])
    hour, minute = int(match[2]), int(match[3])
    if match[4]:
        if not 1 <= hour <= 12:
            raise ValueError("Use an hour from 1 to 12 with AM or PM.")
        hour = hour % 12 + (12 if match[4].lower() == "pm" else 0)
    try:
        local = datetime(day.year, day.month, day.day, hour, minute)
    except ValueError as exc:
        raise ValueError("Use a valid time.") from exc
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
        raise ValueError("This local time is ambiguous or does not exist. Choose another time.")
    return candidates.pop()


def display_status(status: SessionStatus, deadline: datetime, now: datetime) -> str:
    if status is SessionStatus.OPEN and now > deadline:
        return "Deadline Passed"
    return status.value.title()
