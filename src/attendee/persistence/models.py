"""ORM records for organizations, global people, and organization memberships."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from attendee.domain.identity import MembershipRole
from attendee.persistence.base import Base
from attendee.persistence.types import UTCDateTime, utc_now


def _role_values(roles: type[MembershipRole]) -> list[str]:
    return [role.value for role in roles]


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
    telegram_handle: Mapped[str | None] = mapped_column(String(64))
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
            values_callable=_role_values,
        )
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
