"""Guard the placeholders in attendee/copy.py, so a wording edit cannot break a `.format()` call."""

from string import Formatter

from attendee import copy

# Every text with a placeholder, and the names that code passes to `.format()`.
PLACEHOLDERS = {
    "CONFIRM_NAME": {"name"},
    "LINK_NOT_FOUND": {"handle"},
    "UPLOAD_TOO_LARGE": {"megabytes"},
    "UPLOAD_UNREADABLE": {"error"},
    "PREVIEW_UNRESOLVED": {"count"},
    "APPLIED": {"created", "updated", "unchanged"},
    "PREVIEW_CREATE": {"count"},
    "PREVIEW_UPDATE": {"count"},
    "PREVIEW_UNCHANGED": {"count"},
    "PREVIEW_REJECT": {"count"},
    "PREVIEW_NOT_IN_FILE": {"count"},
    "PREVIEW_IGNORED_COLUMNS": {"columns"},
    "PREVIEW_ROW": {"action", "line", "name", "handle"},
    "PREVIEW_ROW_REJECT": {"line", "reasons"},
    "PREVIEW_ROW_WARNING": {"line", "name"},
    "FILE_WRONG_TYPE": {"suffixes"},
    "FILE_BAD_CSV": {"detail"},
    "FILE_TOO_LARGE": {"megabytes"},
    "FILE_DUPLICATE_COLUMN": {"column"},
    "FILE_MISSING_COLUMNS": {"columns"},
    "ROW_NAME_TOO_LONG": {"limit"},
    "ROW_BAD_HANDLE": {"handle", "detail"},
    "ROW_BAD_TELEGRAM_ID": {"telegram_id"},
    "ROW_DUPLICATE": {"label", "rows"},
    "ROW_SAME_MEMBER": {"rows"},
    "SESSION_ASK_DEADLINE": {"timezone"},
    "SESSION_SUMMARY": {"series", "date", "label", "deadline", "timezone", "members"},
    "SESSION_SAVED": {"id", "series", "date", "label", "members"},
    "DEADLINE_AFTER_SESSION": {"session_date"},
    "PUBLISH_REVIEW": {"group", "poll"},
    "PUBLISH_FAILED": {"failure"},
    "PUBLISH_SESSION_CHECK": {"session"},
    "PUBLISH_SESSION_BUSY": {"session"},
    "POLL_TEXT": {"series", "session", "deadline", "timezone"},
    "RECORDED": {"status"},
    "RECORDED_REASON": {"status", "reason"},
    "CONFIRM_REPLACE": {"current", "new", "seconds"},
    "REASON_PROMPT": {"status", "session"},
    "STATS_SERIES": {"series"},
    "STATS_SERIES_NO_SESSIONS": {"series"},
    "STATS_SESSION_BUTTON": {"session", "status"},
    "STATS_SESSION": {"series", "session", "status", "responded", "required", "missing", "counts"},
    "STATS_COUNT": {"status", "count"},
    "STATS_NO_RESPONSE_TITLE": {"session"},
    "STATS_RESPONSES_TITLE": {"session"},
    "STATS_STATUS_GROUP": {"status", "count"},
    "STATS_MEMBER": {"name"},
    "STATS_REASONS_TITLE": {"session"},
    "STATS_REASON": {"name", "status", "reason"},
    "STATS_OPEN_COLUMN": {"session"},
    "STATS_EXPORT_CAPTION": {"series"},
}


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(text) if name is not None}


def test_placeholders_match_code():
    texts = {
        name: value
        for name, value in vars(copy).items()
        if name.isupper() and isinstance(value, str)
    }
    found = {name: fields(text) for name, text in texts.items() if fields(text)}
    assert found == PLACEHOLDERS
