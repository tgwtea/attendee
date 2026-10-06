"""Bot texts and message splitting. Edit the wording in `attendee/copy.py`, not here."""

from attendee.copy import *  # noqa: F403  # Re-export every text for the Telegram layer.
from attendee.copy import CONFIRM_NAME

TELEGRAM_MESSAGE_LIMIT = 4096


def confirm_name(name: str) -> str:
    return CONFIRM_NAME.format(name=name)


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split text into messages within the limit. Split at line ends where possible."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks
