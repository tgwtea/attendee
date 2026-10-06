"""ORM records for identity, unresolved matches, chats, attendance, publication, and responses."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
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

from attendee.domain.identity import MembershipRole
from attendee.domain.matching import UnresolvedReason
from attendee.persistence.base import Base
from attendee.persistence.types import UTCDateTime, utc_now


def _enum_values(values: type[MembershipRole] | type[UnresolvedReason]) -> list[str]:
    return [value.value for value in values]


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("slug <> ''", name="slug_not_empty"),
        CheckConstraint("name <> ''", name="name_not_empty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Person(Base):
    """A global person. Names never identify a person; only a Telegram user ID is unique."""

    __tablename__ = "people"
    __table_args__ = (
        CheckConstraint("telegram_user_id > 0", name="telegram_user_id_positive"),
        CheckConstraint(
            "display_name IS NOT NULL OR telegram_user_id IS NOT NULL", name="has_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    # Canonical form: lowercase, no leading "@". Unique per organization by application rule.
    telegram_handle: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "person_id", name="uq_memberships_organization_id_person_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"), index=True)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(
            MembershipRole,
            name="role",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=_enum_values,
        )
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class UnresolvedMatch(Base):
    """A Telegram account that matching could not bind in one organization.

    One record exists per organization and Telegram user ID. It grants no access.
    """

    __tablename__ = "unresolved_matches"
    __table_args__ = (
        CheckConstraint("telegram_user_id > 0", name="telegram_user_id_positive"),
        UniqueConstraint(
            "organization_id",
            "telegram_user_id",
            name="uq_unresolved_matches_organization_id_telegram_user_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
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
    __tablename__ = "attendance_series"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_attendance_series_org_id"),
        UniqueConstraint("organization_id", "normalized_name", name="uq_attendance_series_name"),
        CheckConstraint("length(name) BETWEEN 1 AND 200", name="valid_name"),
        CheckConstraint("normalized_name <> ''", name="normalized_name_not_empty"),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(600))
    created_by: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_attendance_sessions_org_id"),
        UniqueConstraint("organization_id", "creation_key", name="uq_attendance_sessions_creation"),
        CheckConstraint("status IN ('draft', 'open', 'closed')", name="valid_status"),
        CheckConstraint("label IS NULL OR length(label) BETWEEN 1 AND 200", name="valid_label"),
        ForeignKeyConstraint(
            ["organization_id", "series_id"],
            ["attendance_series.organization_id", "attendance_series.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int]
    series_id: Mapped[int] = mapped_column(index=True)
    session_date: Mapped[date] = mapped_column(Date())
    label: Mapped[str | None] = mapped_column(String(200))
    deadline: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(10), default="draft")
    created_by: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    creation_key: Mapped[str] = mapped_column(String(64))
    request_fingerprint: Mapped[str] = mapped_column(String(64))


class OrganizationChat(Base):
    """A Telegram group that one organization registered. A group has one owner globally."""

    __tablename__ = "organization_chats"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_organization_chats_org_id"),
        UniqueConstraint("telegram_chat_id", name="uq_organization_chats_telegram_chat_id"),
        CheckConstraint("chat_type IN ('group', 'supergroup')", name="valid_chat_type"),
        CheckConstraint("length(title) BETWEEN 1 AND 200", name="valid_title"),
        ForeignKeyConstraint(
            ["organization_id", "registered_by"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    chat_type: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    registered_by: Mapped[int]
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class SessionRosterEntry(Base):
    __tablename__ = "session_roster_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["attendance_sessions.organization_id", "attendance_sessions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "person_id"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
    )
    organization_id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(primary_key=True)


class SessionPublication(Base):
    """One attempt to post a session poll to a registered group (decision T55).

    A partial unique index allows one publishing, publish_unknown, or published row per session.
    Failed rows stay as history, so a retry inserts a new row.
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
        ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["attendance_sessions.organization_id", "attendance_sessions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "organization_chat_id"],
            ["organization_chats.organization_id", "organization_chats.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "requested_by"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "resolved_by"],
            ["memberships.organization_id", "memberships.person_id"],
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
    organization_id: Mapped[int]
    session_id: Mapped[int]
    organization_chat_id: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    requested_by: Mapped[int]
    lease_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    failure: Mapped[str | None] = mapped_column(String(64))
    resolved_by: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


_RESPONSE_STATUS = "status IN ('coming', 'not_coming', 'late', 'leaving_early')"
_REASON_RULE = (
    "(status = 'coming' AND reason IS NULL) OR "
    "(status <> 'coming' AND length(reason) BETWEEN 1 AND 1000)"
)
_ROSTER_COLUMNS = ["organization_id", "session_id", "person_id"]
_ROSTER_TARGET = [
    "session_roster_entries.organization_id",
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
    organization_id: Mapped[int] = mapped_column(primary_key=True)
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
    organization_id: Mapped[int]
    session_id: Mapped[int]
    person_id: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(1000))
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
