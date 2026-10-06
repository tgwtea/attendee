"""Every text that a person sees from the bot. Edit the wording here only.

Rules for editors:
- Keep each `{placeholder}` exactly. Code fills it with `.format()`. A test checks the names.
- A text never shows another member's response, reason, or count. The one exception is the
  "Attendance reports" section: only an admin gets those texts, in a private chat.
- The comment `PRD §34` marks a text whose meaning the PRD fixes. Change its words, not its meaning.
"""

# ---------------------------------------------------------------------------
# Shared buttons
# ---------------------------------------------------------------------------
YES = "Yes"
NO = "No"
APPLY = "Apply"
CANCEL = "Cancel"
CONFIRM = "Confirm"
SKIP = "Skip"
PREVIOUS = "Previous"
NEXT = "Next"

# ---------------------------------------------------------------------------
# Group admins. A Telegram group admin is a bot admin for that group (decision T83).
# ---------------------------------------------------------------------------
ADMIN_DENIED = (
    "Only a group admin can do this. Add me to your Telegram group, "
    "and make sure you are an admin of that group."
)
ADMIN_CHECK_FAILED = "I couldn't check your admin role with Telegram. Please try again."
SELECT_GROUP = "Which group is this for?"

# ---------------------------------------------------------------------------
# Onboarding: a member sends /start and links their Telegram account
# ---------------------------------------------------------------------------
# PRD §34 "User not found". Give no reason and no other member's data.
NOT_MATCHED = "Hmm, I couldn't find you on the attendance list. Please ask an admin to add you."
CONFIRM_NAME = "Hi! Are you {name}?"
ALREADY_LINKED = "You're already set up. Nothing else to do!"
LINKED = "Thanks, you're all set! Your Telegram account is now linked to the attendance list."
PROPOSAL_EXPIRED = "This question has expired. Tap a button on the group poll to try again."
# A private /start does not say which group the member belongs to (decision T80).
START_FROM_GROUP = "To link your account, tap a button on an attendance poll in your group."
# Linking from a poll tap (decisions T88–T90). Show only the member's own username.
LINK_NO_PENDING = "Tap a button on the attendance poll in your group first."
# PRD §34 "User not found". Two matches use this text too, with no names.
LINK_NOT_FOUND = "I couldn't find @{handle} on the attendance list. Please ask an admin to add you."
LINK_NO_USERNAME = (
    "Your Telegram account has no username, so I can't find you on the attendance list. "
    "Please ask an admin to add you."
)
LINK_TAP_AGAIN = "Thanks, you're linked! Please tap the poll button again."

# ---------------------------------------------------------------------------
# Namelist upload (admins)
# ---------------------------------------------------------------------------
UPLOAD_DENIED = ADMIN_DENIED
UPLOAD_WRONG_TYPE = "Please send the namelist as a .csv or .xlsx file."
UPLOAD_TOO_LARGE = "That file is over {megabytes} MB. Please send a smaller one."
UPLOAD_UNREADABLE = "I couldn't read that namelist: {error}"
PREVIEW_UNRESOLVED = "Account matches still waiting for review: {count}"
PREVIEW_REJECTED = (
    "Some rows have problems, so I can't apply this file. Fix them and upload it again."
)
PREVIEW_CONFIRM = "Apply these changes?"
PREVIEW_EXPIRED = "This preview has expired. Please upload the file again."
APPLIED = "Done! Added {created}, updated {updated}, unchanged {unchanged}."
CANCELLED = "Cancelled. Nothing changed."
APPLY_CONFLICT = (
    "Nothing changed. The member list changed after this preview. Please upload the file again."
)
APPLY_REJECTED = "Nothing changed. Some rows have problems. Fix them and upload the file again."

# Preview lines. The command-line importer uses the same text.
PREVIEW_CREATE = "New: {count}"
PREVIEW_UPDATE = "Updated: {count}"
PREVIEW_UNCHANGED = "Unchanged: {count}"
PREVIEW_REJECT = "Problems: {count}"
PREVIEW_NOT_IN_FILE = "Members not in this file (kept as they are): {count}"
PREVIEW_IGNORED_COLUMNS = "Ignored columns: {columns}"
PREVIEW_ROW = "  {action} row {line}: {name} @{handle}"
PREVIEW_ROW_ACTION_CREATE = "new"
PREVIEW_ROW_ACTION_UPDATE = "update"
PREVIEW_ROW_REJECT = "  problem in row {line}: {reasons}"
PREVIEW_ROW_WARNING = (
    "  check row {line}: someone named {name} is already on the list. Is this a new person?"
)

# Whole-file problems. They fill {error} in UPLOAD_UNREADABLE.
FILE_WRONG_TYPE = "use a {suffixes} file"
FILE_NOT_UTF8 = "please save the CSV file as UTF-8"
FILE_BAD_CSV = "the CSV file is not valid ({detail})"
FILE_BAD_XLSX = "the XLSX file is not valid"
FILE_TOO_LARGE = "the file is over {megabytes} MB"
FILE_EMPTY = "the file is empty"
FILE_NO_ROWS = "the file has no member rows"
FILE_DUPLICATE_COLUMN = "the column {column!r} appears more than once"
FILE_MISSING_COLUMNS = "these columns are missing: {columns}"

# Row problems. They fill {reasons} in PREVIEW_ROW_REJECT.
ROW_MISSING_NAME = "the name is missing"
ROW_NAME_TOO_LONG = "the name is over {limit} characters"
ROW_MISSING_HANDLE = "the Telegram handle is missing"
ROW_BAD_HANDLE = "{handle!r} is not a valid Telegram handle ({detail})"
ROW_BAD_TELEGRAM_ID = "{telegram_id!r} is not a valid Telegram ID"
ROW_DUPLICATE = "the same {label} is in rows {rows}"
ROW_DUPLICATE_HANDLE_LABEL = "handle"
ROW_DUPLICATE_ID_LABEL = "Telegram ID"
ROW_HANDLE_TAKEN = "another member already has this handle"
ROW_HANDLE_SHARED = "several members already have this handle"
ROW_HANDLE_ID_MISMATCH = "the member with this handle has a different Telegram ID"
ROW_SAME_MEMBER = "rows {rows} all match the same member"
HANDLE_RULE = "4 to 32 letters, digits, or underscores, starting with a letter"

# ---------------------------------------------------------------------------
# Session setup (/attendance, admins, private chat)
# ---------------------------------------------------------------------------
SESSION_DENIED = ADMIN_DENIED
SESSION_BUTTON_EXPIRED = "This button has expired. Use the latest message or send /attendance."
SESSION_FAILED = "Something went wrong. Send /attendance to try again."
SESSION_CANCELLED = "Cancelled. Nothing was created."
SESSION_USE_BUTTON = "Please use a button on the latest message, or send /cancel."
SESSION_SELECT_SERIES = "Which attendance series is this for?"
SESSION_NEW_SERIES_BUTTON = "Create new series"
SESSION_ASK_SERIES_NAME = "What's the name of the new series? (1 to 200 characters)"
SESSION_ASK_DATE = "What's the date of the session? For example 2026-10-12 or 12 Oct 2026."
SESSION_ASK_LABEL = "Add a short label for this session, or tap Skip."
SESSION_ASK_DEADLINE = (
    "When should members reply by? Times are in {timezone}.\n"
    "For example 2026-10-12 20:00 or 12 Oct 2026, 8:00 PM.\n"
    "The deadline can't be after the session date."
)
SESSION_SUMMARY = (
    "{series}\n"
    "Date: {date}\n"
    "Label: {label}\n"
    "Reply by: {deadline} ({timezone})\n"
    "Members on the list: {members} (everyone on the namelist)\n"
    "Status: Draft\n\n"
    "Save this Draft session?"
)
SESSION_ROSTER_CHANGED = "The member list changed. Please check this new summary."
SESSION_SAVED = (
    "Saved Draft session #{id}.\n{series}\n{date} — {label}\nMembers on the list: {members}"
)
SERIES_EXISTS = "That series already exists. Please pick it from the list."
SERIES_NOT_FOUND = "I couldn't find that series."
SESSION_NOT_FOUND = "I couldn't find that session."
SESSION_KEY_CONFLICT = "This request clashed with another one. Send /attendance to start again."

# Input problems in session setup.
NAME_LENGTH = "Please use 1 to 200 characters."
DATE_FORMAT = "I didn't understand that date. Try 2026-10-12 or 12 Oct 2026."
DEADLINE_FORMAT = "Please give a date and a time, like 2026-10-12 20:00 or 12 Oct 2026, 8:00 PM."
DEADLINE_HOUR = "With AM or PM, use an hour from 1 to 12."
DEADLINE_TIME = "That time doesn't exist. Please check it."
DEADLINE_AMBIGUOUS = "That local time is unclear or skipped by a clock change. Pick another time."
DEADLINE_AFTER_SESSION = (
    "The deadline can't be after the session on {session_date}. Please pick an earlier time."
)

# ---------------------------------------------------------------------------
# Publishing a poll (/publish, admins)
# ---------------------------------------------------------------------------
PUBLISH_DENIED = ADMIN_DENIED
PUBLISH_EXPIRED = "This button has expired. Send /publish again."
PUBLISH_NO_DRAFTS = "There's no Draft session to publish. Create one with /attendance."
PUBLISH_SELECT_SESSION = "Which Draft session do you want to publish?"
PUBLISH_REVIEW = "Group: {group}\n\n{poll}\n\nPublish this poll?"
PUBLISH_IN_PROGRESS = "This poll is still being published. Send /publish again in 2 minutes."
PUBLISH_UNKNOWN = "I'm not sure the poll reached the group. Please check the group and tell me."
PUBLISH_DONE = "The poll is live in the group. The session is now Open."
PUBLISH_DONE_NO_EDIT = (
    "The session is now Open. I can't edit or close the poll message you see in the group."
)
PUBLISH_FAILED = (
    "Telegram didn't accept the poll ({failure}). Nothing was posted. Send /publish to retry."
)
PUBLISH_NOT_SEEN = "OK, I marked it as failed. Send /publish to retry."
PUBLISH_DB_FAILED = "Publishing didn't work. Send /publish to try again."
PUBLISH_CANCELLED = "Cancelled. Nothing was published."
PUBLISH_SESSION_CHECK = "{session} (check)"
PUBLISH_SESSION_BUSY = "{session} (publishing)"
PUBLISH_NOT_DRAFT = "This session is no longer a Draft."
PUBLISH_ARCHIVED = "This session is archived because its deadline was over a week ago."
PUBLISH_GROUP_NOT_FOUND = "I couldn't find that group."
PUBLISH_NOTHING_WAITING = "No publication is waiting for your answer."
I_SEE_POLL = "I can see the poll"
I_CANT_SEE_POLL = "I can't see the poll"
PUBLISH = "Publish"

# PRD §12 poll message in the group. It shows no counts.
POLL_TEXT = (
    "Attendance — {series}\n\n"
    "{session}\n"
    "Please reply by {deadline} ({timezone}).\n\n"
    "Your answer is private. Only admins see it."
)
# PRD §12 poll buttons: (label, code). The code must not change.
POLL_BUTTONS = (("Coming", "c"), ("Not Coming", "n"), ("Late", "l"), ("Leaving Early", "e"))

# ---------------------------------------------------------------------------
# Member responses. A group tap answers with a pop-up that only the member sees,
# or opens the private chat. No text below goes to the group.
# ---------------------------------------------------------------------------
RECORDED = "Got it! You're marked as {status}."
RECORDED_REASON = "Got it! You're marked as {status}.\nReason: {reason}"
CONFIRM_REPLACE = (
    "You already said {current}. Tap {new} again within {seconds} seconds to change your answer."
)
REASON_PROMPT = (
    "You picked {status} for {session}.\n\n"
    "Reply to this message with the reason. Only admins will see it."
)
NO_PENDING_REASON = "There's nothing waiting for a reason. Tap a button on the group poll first."
# PRD §34 "Reason missing".
REASON_MISSING = "Please add a reason so I can save your answer."
REASON_TOO_LONG = "That reason is a bit long. Please keep it to 1000 characters or fewer."
# PRD §34 "Poll closed".
POLL_CLOSED = "This poll is closed. Please contact an admin if you need to change your answer."
NOT_ON_ROSTER = "You're not on the list for this session."
VOTE_INVALID = "This button doesn't work anymore."
TAP_NOT_SAVED = "Sorry, that didn't save. Please tap the button again."
REASON_NOT_SAVED = "Sorry, that didn't save. Please send your reason again."

# ---------------------------------------------------------------------------
# Attendance reports (/stats, admins only, private chat). These texts show other
# members' responses, reasons, and counts, so they never go to a group or a member.
# ---------------------------------------------------------------------------
STATS_DENIED = ADMIN_DENIED
STATS_EXPIRED = "This button doesn't work anymore. Send /stats again."
STATS_DB_FAILED = "I couldn't load the report. Send /stats to try again."
STATS_EXPORT_FAILED = "I couldn't make the file. Send /stats to try again."
STATS_NO_SERIES = "There's no published poll yet. Publish one with /publish."
STATS_SERIES_NOT_FOUND = "I couldn't find that series."
STATS_SELECT_SERIES = "Which series do you want to see?"
STATS_SERIES = "{series}\n\nPick a session to see its responses, or export the whole series."
STATS_SERIES_NO_SESSIONS = (
    "{series}\n\nNo current sessions. Archived sessions are still in the export."
)
STATS_SESSION_BUTTON = "{session} · {status}"
STATS_EXPORT = "Export Excel"
# PRD §19 admin attendance view.
STATS_SESSION = (
    "{series} — {session}\nStatus: {status}\n\n"
    "Responded: {responded} / {required}\nNo response: {missing}\n\n{counts}"
)
STATS_COUNT = "{status}: {count}"
STATS_VIEW_NO_RESPONSE = "View No Response"
STATS_VIEW_RESPONSES = "View Responses"
STATS_VIEW_REASONS = "View Reasons"
STATS_NO_RESPONSE_TITLE = "No response — {session}"
STATS_EVERYONE_RESPONDED = "Everyone responded."
STATS_RESPONSES_TITLE = "Responses — {session}"
STATS_NO_RESPONSES = "No responses yet."
STATS_STATUS_GROUP = "{status} ({count})"
STATS_MEMBER = "- {name}"
STATS_REASONS_TITLE = "Reasons — {session}\nOnly admins can see this."
STATS_REASON = "- {name} · {status}: {reason}"
STATS_NO_REASONS = "No reasons yet."
# XLSX export. Open sessions sit after the totals and do not count yet (decision T73).
STATS_OPEN_COLUMN = "{session} (Open)"
STATS_EXPORT_CAPTION = "{series}. Columns marked (Open) don't count in the totals yet."

VOTE_REPEAT = "This tap already reached the bot. Tap the button again to confirm a change."
