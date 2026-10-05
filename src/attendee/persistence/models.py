"""ORM records for organization identity, unresolved matches, and attendance."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
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
