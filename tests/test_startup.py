import logging
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from attendee.application.dto import OrganizationDTO
from attendee.config.settings import ConfigurationError, Settings
from attendee.logging import SecretFormatter
from attendee.main import create_handlers, run
from attendee.telegram.bootstrap import build_application

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:abcdefghijklmnopqrstuvwxyzABCDEFGHI"
ORGANIZATION = "club"


def bot_settings(**values):
    return Settings(telegram_bot_token=TOKEN, bot_organization=ORGANIZATION, **values)


@pytest.fixture
def organization_found(monkeypatch):
    async def load(_factory, slug):
        return OrganizationDTO(id=1, slug=slug, name="Club", created_at="2026-10-04T00:00:00Z")

    async def recover(_factory, _organization_id):
        return 0

    monkeypatch.setattr("attendee.main.load_organization", load)
    monkeypatch.setattr("attendee.main.recover_publications", recover)


def test_registered_handlers():
    application = build_application(TOKEN, create_handlers(Mock(), 1))
    names = [type(handler).__name__ for handler in application.handlers[0]]
    assert names == [
        "MessageHandler",
        "ConversationHandler",
        "CallbackQueryHandler",
        "MessageHandler",
        "CommandHandler",
        "CallbackQueryHandler",
        "MessageHandler",
        "CallbackQueryHandler",
        "CommandHandler",
        "MessageHandler",
        "CommandHandler",
        "CallbackQueryHandler",
        "CallbackQueryHandler",
    ]


def test_empty_application():
    application = build_application(TOKEN)
    assert application.handlers == {}
    assert application.concurrent_updates == 1
    with pytest.warns(UserWarning, match="No `JobQueue`"):
        assert application.job_queue is None


def test_shutdown_disposes_engine(monkeypatch, organization_found):
    engine = Mock()
    engine.dispose = AsyncMock()
    application = Mock()
    monkeypatch.setattr("attendee.main.create_engine", lambda _: engine)
    monkeypatch.setattr("attendee.main.create_session_factory", lambda _: Mock())
    monkeypatch.setattr("attendee.main.build_application", lambda *_: application)
    run(bot_settings())
    engine.dispose.assert_awaited_once()
    application.run_polling.assert_called_once_with(close_loop=False, bootstrap_retries=0)


def test_recovery_runs_before_polling(monkeypatch, organization_found):
    order = []

    async def recover(_factory, organization_id):
        order.append(("recover", organization_id))
        return 1

    application = Mock()
    application.run_polling.side_effect = lambda **_: order.append(("poll", None))
    engine = Mock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr("attendee.main.recover_publications", recover)
    monkeypatch.setattr("attendee.main.create_engine", lambda _: engine)
    monkeypatch.setattr("attendee.main.create_session_factory", lambda _: Mock())
    monkeypatch.setattr("attendee.main.build_application", lambda *_: application)
    run(bot_settings())
    assert order == [("recover", 1), ("poll", None)]


def test_startup_failure_disposes_engine(monkeypatch, organization_found):
    engine = Mock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr("attendee.main.create_engine", lambda _: engine)
    monkeypatch.setattr("attendee.main.create_session_factory", lambda _: Mock())

    def fail(*_):
        raise RuntimeError("startup failed")

    monkeypatch.setattr("attendee.main.build_application", fail)
    with pytest.raises(RuntimeError):
        run(bot_settings())
    engine.dispose.assert_awaited_once()


def test_unknown_organization_stops_startup(migrated_settings, monkeypatch):
    build = Mock()
    monkeypatch.setattr("attendee.main.build_application", build)
    settings = bot_settings(database_url=migrated_settings.database_url)
    with pytest.raises(ConfigurationError, match="attendee-setup"):
        run(settings)
    build.assert_not_called()


def test_missing_organization_exits():
    result = subprocess.run(
        [str(ROOT / ".venv/bin/attendee")],
        env={**os.environ, "TELEGRAM_BOT_TOKEN": TOKEN},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "BOT_ORGANIZATION is required" in result.stderr


def test_missing_token_exits():
    result = subprocess.run([str(ROOT / ".venv/bin/attendee")], capture_output=True, text=True)
    assert result.returncode == 1
    assert "TELEGRAM_BOT_TOKEN" in result.stderr


def test_logs_redact_secrets():
    formatter = SecretFormatter((TOKEN,))
    record = logging.LogRecord("test", logging.ERROR, "", 0, "URL /bot%s", (TOKEN,), None)
    assert TOKEN not in formatter.format(record)
    assert "[REDACTED]" in formatter.format(record)


def test_entrypoint_does_not_start_bot_after_migration_failure(tmp_path):
    commands = tmp_path / "bin"
    commands.mkdir()
    marker = tmp_path / "started"
    (commands / "alembic").write_text("#!/bin/sh\nexit 7\n")
    (commands / "attendee").write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    for command in commands.iterdir():
        command.chmod(0o755)
    result = subprocess.run(
        ["/bin/sh", str(ROOT / "scripts/entrypoint.sh")],
        env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}"},
        capture_output=True,
    )
    assert result.returncode == 7
    assert not marker.exists()


def test_real_polling_lifecycle_with_fake_transport(monkeypatch, migrated_settings):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(migrated_settings.database_path)) as connection:
        connection.execute(
            "INSERT INTO organizations (slug, name, created_at) "
            "VALUES ('club', 'Club', '2026-10-04 00:00:00')"
        )
        connection.commit()
    import asyncio
    import json

    from telegram.ext import Application
    from telegram.request import BaseRequest

    requests = []
    transports = []
    stopped = False

    class FakeRequest(BaseRequest):
        def __init__(self):
            self.closed = False
            transports.append(self)

        @property
        def read_timeout(self):
            return 1

        async def initialize(self):
            pass

        async def shutdown(self):
            self.closed = True

        async def do_request(self, url, method, request_data=None, **kwargs):
            nonlocal stopped
            endpoint = url.rsplit("/", 1)[-1]
            requests.append(endpoint)
            if endpoint == "getMe":
                result = {"id": 123456789, "is_bot": True, "first_name": "Foundation"}
            elif endpoint == "deleteWebhook":
                result = True
            elif endpoint == "getUpdates":
                await asyncio.sleep(0.01)
                if application.running and not stopped:
                    stopped = True
                    application.stop_running()
                result = []
            else:
                raise AssertionError(f"Unexpected Telegram endpoint: {endpoint}")
            return 200, json.dumps({"ok": True, "result": result}).encode()

    application = (
        Application.builder()
        .token(TOKEN)
        .request(FakeRequest())
        .get_updates_request(FakeRequest())
        .concurrent_updates(False)
        .job_queue(None)
        .build()
    )
    monkeypatch.setattr("attendee.main.build_application", lambda *_: application)
    settings = bot_settings(database_url=migrated_settings.database_url)
    run(settings)
    assert {"getMe", "deleteWebhook", "getUpdates"} <= set(requests)
    assert all(transport.closed for transport in transports)
    assert not application.running
    assert settings.database_path.exists()
