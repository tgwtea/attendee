"""Keep foundation tests independent of local environment settings."""

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "DATABASE_URL",
        "APP_TIMEZONE",
        "BOOTSTRAP_ADMIN_IDS",
        "LOG_LEVEL",
        "BACKUP_DIR",
        "SQLITE_BUSY_TIMEOUT_MS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
