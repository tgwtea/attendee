"""Validated application output. ORM records never leave a service."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from attendee.domain.matching import UnresolvedReason


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)


class PersonDTO(_Record):
    id: int
    group_id: int
    display_name: str | None
    telegram_user_id: int | None
    telegram_handle: str | None
    created_at: datetime
    updated_at: datetime


class UnresolvedMatchDTO(_Record):
    id: int
    group_id: int
    telegram_user_id: int
    telegram_handle: str | None
    reason: UnresolvedReason
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
