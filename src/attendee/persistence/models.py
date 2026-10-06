"""ORM records for groups, people, unresolved matches, attendance, publication, and responses.

A Telegram group owns all data (decision T80). Every scoped table carries `group_id`.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from attendee.domain.matching import UnresolvedReason
from attendee.persistence.base import Base
from attendee.persistence.types import UTCDateTime, utc_now


def _enum_values(values: type[UnresolvedReason]) -> list[str]:
    return [value.value for value in values]


class Group(Base):
    """A Telegram group that added the bot. The internal ID never changes (decision T81).

    A supergroup upgrade changes `telegram_chat_id` in this row only.
    """

    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint("chat_type IN ('group', 'supergroup')", name="valid_chat_type"),
        CheckConstraint("length(title) BETWEEN 1 AND 200", name="valid_title"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    chat_type: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean(), default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class Person(Base):
    """A namelist member of one group. Each group has its own copy of a person (decision T82).

    Names never identify a person. A Telegram user ID is unique in its group only.
    """

    __tablename__ = "people"
    __table_args__ = (
        UniqueConstraint("group_id", "id", name="uq_people_group_id"),
        UniqueConstraint("group_id", "telegram_user_id", name="uq_people_group_telegram_user_id"),
        CheckConstraint("telegram_user_id > 0", name="telegram_user_id_positive"),
        CheckConstraint(
            "display_name IS NOT NULL OR telegram_user_id IS NOT NULL", name="has_identity"
        ),
        Index("ix_people_group_handle", "group_id", "telegram_handle"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="RESTRICT"))
    display_name: Mapped[str | None] = mapped_column(String(200))
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_handle: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class UnresolvedMatch(Base):
    """A Telegram account that matching could not bind in one group.

    One record exists per group and Telegram user ID. It grants no access.
    """

    __tablename__ = "unresolved_matches"
    __table_args__ = (
        CheckConstraint("telegram_user_id > 0", name="telegram_user_id_positive"),
        UniqueConstraint(
            "group_id", "telegram_user_id", name="uq_unresolved_matches_group_telegram_user_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="RESTRICT"))
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    telegram_handle: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[UnresolvedReason] = mapped_column(
        Enum(
            UnresolvedReason,
            name="unresolved_reason",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=_enum_values,
        )
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AttendanceSeries(Base):
    """`created_by` is the Telegram user ID of a group admin, who may not be on the namelist."""

    __tablename__ = "attendance_series"
    __table_args__ = (
        UniqueConstraint("group_id", "id", name="uq_attendance_series_group_id"),
        UniqueConstraint("group_id", "normalized_name", name="uq_attendance_series_name"),
        CheckConstraint("length(name) BETWEEN 1 AND 200", name="valid_name"),
        CheckConstraint("normalized_name <> ''", name="normalized_name_not_empty"),
        CheckConstraint("created_by > 0", name="created_by_positive"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(600))
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        UniqueConstraint("group_id", "id", name="uq_attendance_sessions_group_id"),
        UniqueConstraint("group_id", "creation_key", name="uq_attendance_sessions_creation"),
        CheckConstraint("status IN ('draft', 'open', 'closed')", name="valid_status"),
        CheckConstraint("label IS NULL OR length(label) BETWEEN 1 AND 200", name="valid_label"),
        CheckConstraint("created_by > 0", name="created_by_positive"),
        ForeignKeyConstraint(
            ["group_id", "series_id"],
            ["attendance_series.group_id", "attendance_series.id"],
            ondelete="RESTRICT",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="RESTRICT"))
    series_id: Mapped[int] = mapped_column(index=True)
    session_date: Mapped[date] = mapped_column(Date())
    label: Mapped[str | None] = mapped_column(String(200))
    deadline: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(10), default="draft")
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    creation_key: Mapped[str] = mapped_column(String(64))
    request_fingerprint: Mapped[str] = mapped_column(String(64))


class SessionRosterEntry(Base):
    __tablename__ = "session_roster_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "session_id"],
            ["attendance_sessions.group_id", "attendance_sessions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["group_id", "person_id"],
            ["people.group_id", "people.id"],
            ondelete="RESTRICT",
        ),
    )
    group_id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(primary_key=True)


class SessionPublication(Base):
    """One attempt to post a session poll to the session's group (decision T55).

    A partial unique index allows one publishing, publish_unknown, or published row per session.
    Failed rows stay as history, so a retry inserts a new row. `requested_by` and
    `resolved_by` are Telegram user IDs of group admins.
    """

    __tablename__ = "session_publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('publishing', 'published', 'publish_unknown', 'failed')",
            name="valid_publication_status",
        ),
        CheckConstraint(
            "telegram_message_id IS NULL OR status = 'published'", name="message_only_published"
        ),
        CheckConstraint("requested_by > 0", name="requested_by_positive"),
        CheckConstraint("resolved_by IS NULL OR resolved_by > 0", name="resolved_by_positive"),
        ForeignKeyConstraint(
            ["group_id", "session_id"],
            ["attendance_sessions.group_id", "attendance_sessions.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "uq_session_publications_active",
            "session_id",
            unique=True,
            sqlite_where=text("status IN ('publishing', 'publish_unknown', 'published')"),
        ),
        Index("ix_session_publications_lease", "status", "lease_expires_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int]
    session_id: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    requested_by: Mapped[int] = mapped_column(BigInteger)
    lease_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    failure: Mapped[str | None] = mapped_column(String(64))
    resolved_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


_RESPONSE_STATUS = "status IN ('coming', 'not_coming', 'late', 'leaving_early')"
_REASON_RULE = (
    "(status = 'coming' AND reason IS NULL) OR "
    "(status <> 'coming' AND length(reason) BETWEEN 1 AND 1000)"
)
_ROSTER_COLUMNS = ["group_id", "session_id", "person_id"]
_ROSTER_TARGET = [
    "session_roster_entries.group_id",
    "session_roster_entries.session_id",
    "session_roster_entries.person_id",
]


class SessionResponse(Base):
    """The current response of one roster member (decision T62). Attendance counts this row."""

    __tablename__ = "session_responses"
    __table_args__ = (
        CheckConstraint(_RESPONSE_STATUS, name="valid_response_status"),
        CheckConstraint(_REASON_RULE, name="reason_matches_status"),
        ForeignKeyConstraint(_ROSTER_COLUMNS, _ROSTER_TARGET, ondelete="RESTRICT"),
    )
    group_id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(1000))
    responded_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class SessionResponseEvent(Base):
    """One append-only audit row per response change (decision T13). No code updates it."""

    __tablename__ = "session_response_events"
    __table_args__ = (
        CheckConstraint(_RESPONSE_STATUS, name="valid_response_status"),
        CheckConstraint(_REASON_RULE, name="reason_matches_status"),
        CheckConstraint("telegram_user_id > 0", name="telegram_user_id_positive"),
        ForeignKeyConstraint(_ROSTER_COLUMNS, _ROSTER_TARGET, ondelete="RESTRICT"),
        Index("ix_session_response_events_member", "session_id", "person_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int]
    session_id: Mapped[int]
    person_id: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(1000))
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
