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
