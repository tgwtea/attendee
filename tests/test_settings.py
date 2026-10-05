import pytest
from pydantic import ValidationError

from attendee.config.settings import Settings


def test_defaults():
    settings = Settings()
    assert settings.app_timezone == "Asia/Singapore"
    assert settings.log_level == "INFO"
    assert settings.bootstrap_admin_ids == ()
    assert settings.sqlite_busy_timeout_ms == 5000
    assert settings.database_path.name == "attendee.db"
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        settings.require_bot_token()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", ()),
        ("   ", ()),
        ("123, 456,123", (123, 456)),
        ("[123, 456, 123]", (123, 456)),
        ('["123", "456"]', (123, 456)),
    ],
)
def test_admin_ids(monkeypatch, raw, expected):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_IDS", raw)
    assert Settings().bootstrap_admin_ids == expected


@pytest.mark.parametrize("raw", ["0", "-1", "abc", "1,", "[true]", "[1.5]", "[null]", "[1", "١"])
def test_invalid_admin_ids(monkeypatch, raw):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_IDS", raw)
    with pytest.raises(ValidationError):
        Settings()


def test_environment_overrides_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("LOG_LEVEL=DEBUG\nBOOTSTRAP_ADMIN_IDS=1,2\n")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    settings = Settings()
    assert settings.log_level == "WARNING"
    assert settings.bootstrap_admin_ids == (1, 2)


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
        {"bot_organization": "Not A Slug"},
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


def test_bot_organization(monkeypatch):
    with pytest.raises(ValueError, match="BOT_ORGANIZATION"):
        Settings().require_bot_organization()
    monkeypatch.setenv("BOT_ORGANIZATION", " smu-samba-masala ")
    assert Settings().require_bot_organization() == "smu-samba-masala"
    monkeypatch.setenv("BOT_ORGANIZATION", "")
    assert Settings().bot_organization is None
