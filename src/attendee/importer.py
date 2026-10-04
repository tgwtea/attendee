"""Server-side namelist import for one organization. Preview by default; --apply to write."""

import argparse
import asyncio
import logging
from pathlib import Path

from attendee.application.import_files import parse_file
from attendee.application.imports import ImportPreview, ImportResult, ImportService
from attendee.application.organizations import OrganizationService
from attendee.config.settings import Settings
from attendee.domain.imports import ImportFileError, ParsedFile
from attendee.logging import configure_logging
from attendee.persistence.database import create_engine, create_session_factory

LOGGER = logging.getLogger(__name__)


async def run_import(
    settings: Settings, slug: str, parsed: ParsedFile, apply: bool
) -> tuple[ImportPreview, ImportResult | None]:
    """Preview the parsed file. Apply it only when asked and when no row is rejected."""
    engine = create_engine(settings)
    try:
        factory = create_session_factory(engine)
        organization = await OrganizationService(factory).find_by_slug(slug)
        if organization is None:
            raise ImportFileError(f"No organization has the slug {slug!r}")
        service = ImportService(factory)
        preview = await service.preview(organization.id, parsed)
        if not apply or preview.rejected:
            return preview, None
        return preview, await service.apply(preview)
    finally:
        await engine.dispose()


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
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="attendee-import",
        description="Preview a CSV or XLSX namelist import. Add --apply to write it.",
    )
    parser.add_argument("--organization", required=True, help="Organization slug, e.g. my-club")
    parser.add_argument("--apply", action="store_true", help="Apply the preview if it is clean")
    parser.add_argument("file", type=Path, help="Namelist with Name and Telegram Handle columns")
    arguments = parser.parse_args(argv)
    configure_logging("INFO")
    try:
        settings = Settings()
        configure_logging(settings.log_level)
        # The command reads the file into memory. It never copies or stores the file.
        parsed = parse_file(arguments.file.name, arguments.file.read_bytes())
        preview, result = asyncio.run(
            run_import(settings, arguments.organization, parsed, arguments.apply)
        )
    except ImportFileError as exc:
        LOGGER.error("Import failed: %s", exc)
        raise SystemExit(1) from None
    except Exception:
        LOGGER.error("Import failed", exc_info=True)
        raise SystemExit(1) from None
    print(format_preview(preview))
    if preview.rejected:
        print("Nothing applied: fix the rejected rows and run the import again.")
        raise SystemExit(2)
    print("Applied." if result is not None else "Preview only. Add --apply to write it.")


if __name__ == "__main__":
    main()
