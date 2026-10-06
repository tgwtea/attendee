"""Group chat registration rules without Telegram or storage dependencies."""

from enum import StrEnum


class ChatType(StrEnum):
    """Chat types that accept registration. A channel post has no sender to check."""

    GROUP = "group"
    SUPERGROUP = "supergroup"


# Telegram group roles that control a group. These roles are separate from membership roles.
_GROUP_CONTROL_ROLES = frozenset({"creator", "administrator"})


def registrable_chat_type(value: str) -> ChatType | None:
    try:
        return ChatType(value)
    except ValueError:
        return None


def controls_group(telegram_role: str) -> bool:
    """A group creator or administrator controls the group. Other roles never do."""
    return telegram_role in _GROUP_CONTROL_ROLES
