"""Fixed bot texts and message splitting. Texts never show another member's data."""

TELEGRAM_MESSAGE_LIMIT = 4096

# PRD §34 "User not found". The text gives no reason and no other member's data.
NOT_MATCHED = (
    "Your Telegram account could not be matched to the attendance namelist. "
    "Please contact an admin."
)
ALREADY_LINKED = "Your Telegram account is already linked to the attendance namelist."
LINKED = "Thank you. Your Telegram account is now linked to the attendance namelist."
PROPOSAL_EXPIRED = "This question expired. Send /start again."
YES = "Yes"
NO = "No"

UPLOAD_DENIED = "Only an admin of this organization can upload a namelist."
UPLOAD_WRONG_TYPE = "Send the namelist as a .csv or .xlsx file."
UPLOAD_TOO_LARGE = "The file is larger than {megabytes} MB. Send a smaller file."
UPLOAD_UNREADABLE = "The namelist could not be read: {error}"
PREVIEW_REJECTED = "Nothing can be applied. Fix the rejected rows and upload the file again."
PREVIEW_CONFIRM = "Apply this import?"
PREVIEW_EXPIRED = "This preview expired. Upload the file again."
APPLY = "Apply"
CANCEL = "Cancel"
APPLIED = "Applied. Created {created}, updated {updated}, unchanged {unchanged}."
CANCELLED = "Cancelled. Nothing changed."
APPLY_CONFLICT = (
    "Nothing applied. The member list changed after the preview. Upload the file again."
)
APPLY_REJECTED = (
    "Nothing applied. The preview has rejected rows. Fix them and upload the file again."
)


def confirm_name(name: str) -> str:
    return f"Are you {name}?"


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
