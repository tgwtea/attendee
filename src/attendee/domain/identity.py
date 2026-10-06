"""Member identity rules without transport or storage dependencies."""

import re

from attendee import copy

_HANDLE = re.compile(r"[a-z][a-z0-9_]{3,31}")


def normalize_handle(handle: str) -> str:
    """Return the canonical handle: no whitespace, no leading "@", lowercase.

    Telegram handles are case-insensitive. Raise ValueError for a handle that Telegram rejects.
    """
    canonical = handle.strip().removeprefix("@").lower()
    if not _HANDLE.fullmatch(canonical):
        raise ValueError(copy.HANDLE_RULE)
    return canonical
