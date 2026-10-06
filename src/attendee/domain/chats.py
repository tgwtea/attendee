"""Telegram group rules without Telegram or storage dependencies."""

from enum import StrEnum


class ChatType(StrEnum):
    """Chat types that the bot serves. A channel post has no sender to check."""

    GROUP = "group"
    SUPERGROUP = "supergroup"


# Telegram member statuses of a group admin. Only these grant admin commands (decision T83).
_GROUP_CONTROL_ROLES = frozenset({"creator", "administrator"})
# Telegram member statuses of a bot that is still in the group.
_PRESENT_STATUSES = frozenset({"creator", "administrator", "member", "restricted"})


def group_chat_type(value: str) -> ChatType | None:
    try:
        return ChatType(value)
    except ValueError:
        return None


def controls_group(telegram_status: str) -> bool:
    """A group creator or administrator controls the group. Other statuses never do."""
    return telegram_status in _GROUP_CONTROL_ROLES


def is_present(telegram_status: str) -> bool:
    """The bot is in the group. "left" and "kicked" mean it is not."""
    return telegram_status in _PRESENT_STATUSES
