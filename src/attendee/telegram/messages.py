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

REGISTER_ANONYMOUS = (
    "The bot cannot see who sent this command. "
    'Turn off "Remain anonymous" in your admin rights, then send /register again.'
)
REGISTER_DENIED = (
    "Only an admin of this organization who is also an admin of this group can register it."
)
REGISTER_CHECK_FAILED = "The bot could not check your role in this group. Try again later."
REGISTER_FAILED = "The registration failed. Send /register to try again."
REGISTERED = "This group is now registered for attendance polls."
REGISTER_REFRESHED = "This group is already registered for attendance polls."
REGISTER_TAKEN = "Another organization already registered this group."


PUBLISH_DENIED = "Only an admin of this organization can publish attendance."
PUBLISH_EXPIRED = "This button expired. Send /publish again."
PUBLISH_NO_DRAFTS = "No Draft session waits for publication. Create one with /attendance."
PUBLISH_NO_GROUPS = "Register a group with /register first."
PUBLISH_SELECT_SESSION = "Select a Draft session to publish."
PUBLISH_SELECT_GROUP = "Select the group for this poll."
PUBLISH_CONFIRM = "Publish this poll?"
PUBLISH_IN_PROGRESS = "This poll is being published. Send /publish again in 2 minutes."
PUBLISH_UNKNOWN = (
    "The bot does not know if the poll reached the group. "
    "Look at the group, then tell the bot what you see."
)
PUBLISH_DONE = "The poll is in the group. The session is now Open."
PUBLISH_DONE_NO_EDIT = (
    "The session is now Open. The bot cannot edit or close the poll message that you see."
)
PUBLISH_FAILED = (
    "Telegram rejected the poll ({failure}). Nothing was posted. Send /publish to retry."
)
PUBLISH_NOT_SEEN = "The attempt is marked failed. Send /publish to retry."
PUBLISH_DB_FAILED = "The publication failed. Send /publish to try again."
PUBLISH_CANCELLED = "Cancelled. Nothing was published."
I_SEE_POLL = "I can see the poll"
I_CANT_SEE_POLL = "I can't see the poll"
PUBLISH = "Publish"
PREVIOUS = "Previous"
NEXT = "Next"

# PRD §12 poll buttons. telegram/responses.py handles them.
POLL_BUTTONS = (("Coming", "c"), ("Not Coming", "n"), ("Late", "l"), ("Leaving Early", "e"))

# Responses. A group tap answers with a pop-up that only the member sees, or opens the
# private chat. No text below goes to the group.
RECORDED = "Attendance recorded: {status}"
RECORDED_REASON = "Attendance recorded: {status}\nReason: {reason}"
REASON_PROMPT = "You selected {status} for {session}.\n\nPlease enter your reason."
NO_PENDING_REASON = "No response is waiting for a reason. Tap a button on the group poll first."
# PRD §34 "Reason missing" and "Poll closed".
REASON_MISSING = "Please provide a reason before your response can be submitted."
REASON_TOO_LONG = "Use 1000 characters or fewer for your reason. Send it again."
POLL_CLOSED = (
    "This attendance poll has already been closed. "
    "Contact an admin if your response needs to be changed."
)
NOT_ON_ROSTER = "You are not on the list for this session."
VOTE_INVALID = "This button is not valid."
TAP_NOT_SAVED = "Not saved. Tap the button again."
REASON_NOT_SAVED = "Not saved. Send your reason again."


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
