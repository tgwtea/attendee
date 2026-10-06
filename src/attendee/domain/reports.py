"""Attendance report rules: cell values, completed sessions, and names, without storage."""

from datetime import date, datetime

from attendee.domain.attendance import SessionStatus, is_archived
from attendee.domain.responses import ResponseStatus

# Spreadsheet cell values (PRD §7, §9). Live formulas count these values (decision T72).
NO_RESPONSE = "NR"
NOT_REQUIRED = "NA"

type Cell = int | str


def cell(on_roster: bool, status: ResponseStatus | None) -> Cell:
    """1 or 0 for a response, NR for no response, NA for a member who is not on the roster."""
    if not on_roster:
        return NOT_REQUIRED
    if status is None:
        return NO_RESPONSE
    return status.value_for_attendance


def is_complete(status: SessionStatus, deadline: datetime, now: datetime) -> bool:
    """A Closed session, or an archived Open session, counts in the totals (decision T73).

    An archived session takes no more responses, so it is complete in practice.
    A Draft session has no poll and never appears in a report.
    """
    if status is SessionStatus.CLOSED:
        return True
    return status is SessionStatus.OPEN and is_archived(deadline, now)


def session_heading(session_date: date, label: str | None) -> str:
    """'13 Oct', or '13 Oct (Week 3)' with a label. PRD §10 uses the same form."""
    day = f"{session_date.day} {session_date:%b}"
    return day if label is None else f"{day} ({label})"


def member_name(person_id: int, display_name: str | None, handle: str | None) -> str:
    """A person needs a name or a Telegram ID (T22), so fall back to the handle, then the ID."""
    if display_name:
        return display_name
    if handle:
        return f"@{handle}"
    return f"Member {person_id}"
