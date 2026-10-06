"""Publication attempt states and poll text, without Telegram or storage dependencies."""

from datetime import date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from attendee import copy


class PublicationStatus(StrEnum):
    """One attempt to post a session poll. Session status stays draft, open, or closed."""

    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PUBLISH_UNKNOWN = "publish_unknown"
    FAILED = "failed"


# At most one attempt per session holds one of these states (a partial unique index).
ACTIVE_STATUSES = frozenset(
    {
        PublicationStatus.PUBLISHING,
        PublicationStatus.PUBLISH_UNKNOWN,
        PublicationStatus.PUBLISHED,
    }
)

# A send that takes longer than this is not in progress. Only a crash leaves a row this old.
PUBLISH_LEASE = timedelta(minutes=2)


def lease_expired(lease_expires_at: datetime, now: datetime) -> bool:
    return now >= lease_expires_at


def poll_text(
    series_name: str, session_date: date, label: str | None, deadline: datetime, timezone: str
) -> str:
    """PRD §12 poll text. It never shows a count or another member's response."""
    local = deadline.astimezone(ZoneInfo(timezone))
    hour = local.strftime("%I").lstrip("0")
    day = f"{session_date:%A}, {session_date.day} {session_date:%B %Y}"
    return copy.POLL_TEXT.format(
        series=series_name,
        session=label or day,
        deadline=f"{local:%A}, {local.day} {local:%B %Y} at {hour}:{local:%M %p}",
        timezone=timezone,
    )
