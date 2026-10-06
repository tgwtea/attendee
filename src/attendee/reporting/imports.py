"""Plain-text namelist import previews for admins. The CLI and the bot share this text."""

from attendee import copy
from attendee.application.imports import ImportPreview


def format_preview(preview: ImportPreview) -> str:
    lines = [
        copy.PREVIEW_CREATE.format(count=len(preview.to_create)),
        copy.PREVIEW_UPDATE.format(count=len(preview.to_update)),
        copy.PREVIEW_UNCHANGED.format(count=len(preview.unchanged)),
        copy.PREVIEW_REJECT.format(count=len(preview.rejected)),
        copy.PREVIEW_NOT_IN_FILE.format(count=len(preview.not_in_file)),
    ]
    if preview.ignored_columns:
        lines.append(
            copy.PREVIEW_IGNORED_COLUMNS.format(columns=", ".join(preview.ignored_columns))
        )
    for action, plans in (
        (copy.PREVIEW_ROW_ACTION_CREATE, preview.to_create),
        (copy.PREVIEW_ROW_ACTION_UPDATE, preview.to_update),
    ):
        lines.extend(
            copy.PREVIEW_ROW.format(
                action=action,
                line=plan.row.line,
                name=plan.row.name,
                handle=plan.row.telegram_handle,
            )
            for plan in plans
        )
    lines.extend(
        copy.PREVIEW_ROW_REJECT.format(line=plan.row.line, reasons="; ".join(plan.reasons))
        for plan in preview.rejected
    )
    lines.extend(
        copy.PREVIEW_ROW_WARNING.format(line=warning.line, name=warning.name)
        for warning in preview.duplicate_name_warnings
    )
    return "\n".join(lines)
