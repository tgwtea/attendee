"""Environment configuration shared by the bot and maintenance commands."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from attendee.domain.identity import validate_slug


class ConfigurationError(ValueError):
    """A startup setting is missing or wrong. The message holds no secret value."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    telegram_bot_token: SecretStr | None = None
    database_url: str = "sqlite+aiosqlite:///./data/attendee.db"
    app_timezone: str = "Asia/Singapore"
    bootstrap_admin_ids: Annotated[tuple[int, ...], NoDecode] = ()
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    backup_dir: Path = Path("./data/backups")
    sqlite_busy_timeout_ms: int = Field(default=5000, gt=0)
    # The organization slug that this bot deployment serves (decision T33).
    bot_organization: str | None = None

    @field_validator("bootstrap_admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> tuple[int, ...]:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return ()
            value = json.loads(value) if value.startswith("[") else value.split(",")
        if not isinstance(value, (list, tuple)):
            raise ValueError("Use a comma-separated list or a JSON array of positive IDs")
        result: list[int] = []
        for item in cast(Sequence[object], value):
            if isinstance(item, bool) or not isinstance(item, (int, str)):
                raise ValueError("Each admin ID must be a positive integer")
            if isinstance(item, str) and not item.strip().isascii():
                raise ValueError("Each admin ID must use ASCII digits")
            if isinstance(item, str) and not item.strip().isdigit():
                raise ValueError("Each admin ID must be a positive integer")
            number = int(item)
            if number <= 0:
                raise ValueError("Each admin ID must be a positive integer")
            if number not in result:
                result.append(number)
        return tuple(result)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        try:
            url = make_url(value)
        except ArgumentError as exc:
            raise ValueError("Use a valid sqlite+aiosqlite URL") from exc
        if (
            url.drivername != "sqlite+aiosqlite"
            or not url.database
            or url.database == ":memory:"
            or url.host
            or url.username
            or url.password
            or url.port
            or url.query
        ):
            raise ValueError("Use a file-backed sqlite+aiosqlite URL without query parameters")
        return value

    @field_validator("bot_organization")
    @classmethod
    def validate_bot_organization(cls, value: str | None) -> str | None:
        value = None if value is None else value.strip()
        return validate_slug(value) if value else None

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown application timezone") from exc
        return value

    @property
    def database_path(self) -> Path:
        database = make_url(self.database_url).database
        assert database is not None
        return Path(database).resolve()

    def require_bot_token(self) -> str:
        token = self.telegram_bot_token
        if token is None or not token.get_secret_value().strip():
            raise ValueError("TELEGRAM_BOT_TOKEN is required for bot startup")
        return token.get_secret_value().strip()

    def require_bot_organization(self) -> str:
        if self.bot_organization is None:
            raise ConfigurationError("BOT_ORGANIZATION is required for bot startup")
        return self.bot_organization
