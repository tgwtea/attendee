"""Plain-text namelist import previews for admins. The CLI and the bot share this text."""

from attendee.application.imports import ImportPreview


def format_preview(preview: ImportPreview) -> str:
    lines = [
        f"Create: {len(preview.to_create)}",
        f"Update: {len(preview.to_update)}",
        f"Unchanged: {len(preview.unchanged)}",
        f"Rejected: {len(preview.rejected)}",
        f"Members not in file (left unchanged): {len(preview.not_in_file)}",
    ]
    if preview.ignored_columns:
        lines.append(f"Ignored columns: {', '.join(preview.ignored_columns)}")
    for label, plans in (("create", preview.to_create), ("update", preview.to_update)):
        lines.extend(
            f"  {label} row {plan.row.line}: {plan.row.name} @{plan.row.telegram_handle}"
            for plan in plans
        )
    lines.extend(
        f"  reject row {plan.row.line}: {'; '.join(plan.reasons)}" for plan in preview.rejected
    )
    lines.extend(
        f"  warning row {warning.line}: an existing member is also named {warning.name}. "
        "Check that this row is a new person."
        for warning in preview.duplicate_name_warnings
    )
    return "\n".join(lines)
