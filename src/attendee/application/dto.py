"""Validated application output. ORM records never leave a service."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from attendee.domain.identity import MembershipRole


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)


class OrganizationDTO(_Record):
    id: int
    slug: str
    name: str
    created_at: datetime


class PersonDTO(_Record):
    id: int
    display_name: str | None
    telegram_user_id: int | None
    telegram_handle: str | None
    created_at: datetime
    updated_at: datetime


class MembershipDTO(_Record):
    id: int
    organization_id: int
    person_id: int
    role: MembershipRole
    created_at: datetime
    updated_at: datetime
