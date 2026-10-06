import logging
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import OperationalError

from attendee.config.settings import Settings
from attendee.logging import SecretFormatter
from attendee.main import create_handlers, run
from attendee.telegram.bootstrap import build_application

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:abcdefghijklmnopqrstuvwxyzABCDEFGHI"


def bot_settings(**values):
    return Settings(telegram_bot_token=TOKEN, **values)


@pytest.fixture
def database_ready(monkeypatch):
    async def check(_factory):
        return None

    async def recover(_factory):
        return 0

    monkeypatch.setattr("attendee.main.check_database", check)
    monkeypatch.setattr("attendee.main.recover_publications", recover)


def test_registered_handlers():
    application = build_application(TOKEN, create_handlers(Mock(), Mock()))
    names = [type(handler).__name__ for handler in application.handlers[0]]
    assert names == [
        "MessageHandler",
        "ConversationHandler",
        "CallbackQueryHandler",
        "MessageHandler",
        "MessageHandler",
        "CommandHandler",
        "CallbackQueryHandler",
        "MessageHandler",
        "CallbackQueryHandler",
        "CallbackQueryHandler",
        "ChatMemberHandler",
        "MessageHandler",
        "CommandHandler",
        "CallbackQueryHandler",
        "CallbackQueryHandler",
        "CommandHandler",
        "CallbackQueryHandler",
    ]


def test_empty_application():
    application = build_application(TOKEN)
    assert application.handlers == {}
    assert application.concurrent_updates == 1
    with pytest.warns(UserWarning, match="No `JobQueue`"):
        assert application.job_queue is None


def test_shutdown_disposes_engine(monkeypatch, database_ready):
    engine = Mock()
    engine.dispose = AsyncMock()
    application = Mock()
    monkeypatch.setattr("attendee.main.create_engine", lambda _: engine)
    monkeypatch.setattr("attendee.main.create_session_factory", lambda _: Mock())
    monkeypatch.setattr("attendee.main.build_application", lambda *_: application)
    run(bot_settings())
    engine.dispose.assert_awaited_once()
    application.add_handlers.assert_called_once()
    application.run_polling.assert_called_once_with(close_loop=False, bootstrap_retries=0)


def test_recovery_runs_before_polling(monkeypatch, database_ready):
    order = []

    async def recover(_factory):
        order.append(("recover", None))
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
    assert order == [("recover", None), ("poll", None)]


def test_startup_failure_disposes_engine(monkeypatch, database_ready):
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


def test_unmigrated_database_stops_startup(tmp_path, monkeypatch):
    build = Mock()
    monkeypatch.setattr("attendee.main.build_application", build)
    settings = bot_settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    with pytest.raises(OperationalError):
        run(settings)
    build.assert_not_called()


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
