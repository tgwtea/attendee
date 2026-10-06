"""Response statuses, poll button codes, and reason rules, without Telegram or storage."""

import re
from enum import StrEnum


class ResponseStatus(StrEnum):
    COMING = "coming"
    NOT_COMING = "not_coming"
    LATE = "late"
    LEAVING_EARLY = "leaving_early"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def value_for_attendance(self) -> int:
        """PRD §7: only Coming counts as attendance."""
        return 1 if self is ResponseStatus.COMING else 0

    @property
    def needs_reason(self) -> bool:
        return self is not ResponseStatus.COMING


_LABELS = {
    ResponseStatus.COMING: "Coming",
    ResponseStatus.NOT_COMING: "Not Coming",
    ResponseStatus.LATE: "Late",
    ResponseStatus.LEAVING_EARLY: "Leaving Early",
}

# Poll buttons carry v:<session_id>:<code> (decision T61).
CODES = {
    "c": ResponseStatus.COMING,
    "n": ResponseStatus.NOT_COMING,
    "l": ResponseStatus.LATE,
    "e": ResponseStatus.LEAVING_EARLY,
}

REASON_LIMIT = 1000


class ReasonMissing(ValueError):
    pass


class ReasonTooLong(ValueError):
    pass


def parse_vote(data: str | None) -> tuple[int, ResponseStatus] | None:
    match = re.fullmatch(r"v:([0-9]{1,19}):([cnle])", data or "")
    if match is None:
        return None
    return int(match[1]), CODES[match[2]]


def clean_reason(status: ResponseStatus, reason: str | None) -> str | None:
    """Coming takes no reason. Other statuses keep the typed text without outer whitespace."""
    if not status.needs_reason:
        return None
    reason = (reason or "").strip()
    if not reason:
        raise ReasonMissing
    if len(reason) > REASON_LIMIT:
        raise ReasonTooLong
    return reason
