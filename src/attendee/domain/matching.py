"""Telegram account matching outcomes without transport or storage dependencies."""

from enum import StrEnum


class MatchOutcome(StrEnum):
    BY_TELEGRAM_ID = "by_telegram_id"
    BOUND_BY_HANDLE = "bound_by_handle"
    UNRESOLVED = "unresolved"


class UnresolvedReason(StrEnum):
    """Why the matching service bound no person. An admin resolves the match later."""

    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"
    TELEGRAM_ID_TAKEN = "telegram_id_taken"
