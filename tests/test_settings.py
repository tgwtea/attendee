import pytest
from pydantic import ValidationError

from attendee.config.settings import Settings


def test_defaults():
    settings = Settings()
    assert settings.app_timezone == "Asia/Singapore"
    assert settings.log_level == "INFO"
    assert settings.sqlite_busy_timeout_ms == 5000
    assert settings.database_path.name == "attendee.db"
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        settings.require_bot_token()


def test_environment_overrides_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("LOG_LEVEL=DEBUG\nAPP_TIMEZONE=UTC\n")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    settings = Settings()
    assert settings.log_level == "WARNING"
    assert settings.app_timezone == "UTC"


@pytest.mark.parametrize(
    "values",
    [
        {"app_timezone": "Invalid/Place"},
        {"log_level": "TRACE"},
        {"database_url": "postgresql://localhost/db"},
        {"database_url": "not a URL"},
        {"database_url": "sqlite+aiosqlite:///:memory:"},
        {"database_url": "sqlite+aiosqlite:///a.db?mode=ro"},
        {"sqlite_busy_timeout_ms": 0},
    ],
)
def test_invalid_settings(values):
    with pytest.raises(ValidationError):
        Settings(**values)


def test_secret_hidden():
    settings = Settings(telegram_bot_token="123:secret")
    assert "123:secret" not in repr(settings)
    assert settings.require_bot_token() == "123:secret"
    with pytest.raises(ValidationError) as exc:
        Settings(log_level="secret-invalid-value")
    assert "secret-invalid-value" not in str(exc.value)


def test_removed_settings_are_ignored(monkeypatch):
    """Old deployments may still set these. Admins now come from Telegram (decision T83)."""
    monkeypatch.setenv("BOOTSTRAP_ADMIN_IDS", "1,2")
    monkeypatch.setenv("BOT_ORGANIZATION", "smu-samba-masala")
    settings = Settings()
    assert not hasattr(settings, "bootstrap_admin_ids")
    assert not hasattr(settings, "bot_organization")
