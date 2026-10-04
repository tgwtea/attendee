"""Safe local SQLite backups for host cron."""

import fcntl
import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from attendee.config.settings import Settings
from attendee.logging import configure_logging

LOGGER = logging.getLogger(__name__)
RETENTION = 14


def backup_database(settings: Settings) -> Path:
    source = settings.database_path
    if not source.is_file():
        raise FileNotFoundError("The source database does not exist")
    directory = settings.backup_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".backup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        destination = directory / f"attendee-{stamp}-{uuid4().hex}.sqlite3"
        temporary = destination.with_suffix(".partial")
        try:
            with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as reader:
                writer = sqlite3.connect(temporary)
                try:
                    reader.backup(writer)
                finally:
                    writer.close()
            temporary.replace(destination)
            backups = sorted(directory.glob("attendee-*.sqlite3"), reverse=True)
            for old in backups[RETENTION:]:
                old.unlink()
        finally:
            temporary.unlink(missing_ok=True)
        LOGGER.info("Backup complete: %s", destination)
        return destination


def main() -> None:
    configure_logging("INFO")
    try:
        settings = Settings()
        secrets = (
            (settings.telegram_bot_token.get_secret_value(),) if settings.telegram_bot_token else ()
        )
        configure_logging(settings.log_level, secrets)
        backup_database(settings)
    except Exception:
        LOGGER.error("Backup failed", exc_info=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
