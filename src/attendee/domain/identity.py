"""Organization identity rules without transport or storage dependencies."""

import re
from enum import StrEnum


class MembershipRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


_RANK = {MembershipRole.MEMBER: 0, MembershipRole.ADMIN: 1}
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def role_satisfies(actual: MembershipRole, required: MembershipRole) -> bool:
    """An admin satisfies a member requirement. A member never satisfies an admin one."""
    return _RANK[actual] >= _RANK[required]


def validate_slug(slug: str) -> str:
    if len(slug) > 64 or not _SLUG.fullmatch(slug):
        raise ValueError("Use lowercase letters, digits, and single hyphens, at most 64 characters")
    return slug


_HANDLE = re.compile(r"[a-z][a-z0-9_]{3,31}")


def normalize_handle(handle: str) -> str:
    """Return the canonical handle: no whitespace, no leading "@", lowercase.

    Telegram handles are case-insensitive. Raise ValueError for a handle that Telegram rejects.
    """
    canonical = handle.strip().removeprefix("@").lower()
    if not _HANDLE.fullmatch(canonical):
        raise ValueError(
            "A Telegram handle has 4 to 32 letters, digits, or underscores and starts with a letter"
        )
    return canonical
